"""Document extraction: turns raw file bytes into (text, location) segments.

Defensive like the CSV/XLSX parser -- extraction failure is reported
honestly (an ExtractionError with a human message), never silently
swallowed or replaced with empty content.
"""

import io
import re
from dataclasses import dataclass

from app.documents.models import ChunkLocation, DocumentType

HEADING_STYLE_RE = re.compile(r"^Heading\s*\d*$", re.IGNORECASE)
MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
# Top-level (unindented) function/class definitions -- used as the
# "heading"/section boundary for .py files, same role MD_HEADING_RE plays
# for Markdown.
PY_DEF_RE = re.compile(r"^(def|class)\s+(\w+)")


class ExtractionError(Exception):
    """Raised when a document cannot be extracted. Carries a human message."""


@dataclass
class Segment:
    text: str
    location: ChunkLocation


def extract_pdf(content: bytes, filename: str) -> tuple[list[Segment], list[str]]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    warnings: list[str] = []
    try:
        reader = PdfReader(io.BytesIO(content))
    except (PdfReadError, ValueError) as exc:
        raise ExtractionError(f"{filename}: could not open PDF -- {exc}") from exc

    segments: list[Segment] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 -- a single bad page must not fail the whole doc
            warnings.append(f"Page {i}: text extraction failed -- {exc}")
            continue
        text = text.strip()
        if text:
            segments.append(Segment(text=text, location=ChunkLocation(page=i)))

    if not segments:
        raise ExtractionError(f"{filename}: no extractable text found (the PDF may be scanned/image-only).")
    return segments, warnings


def extract_docx(content: bytes, filename: str) -> tuple[list[Segment], list[str]]:
    import zipfile

    import docx
    from docx.opc.exceptions import PackageNotFoundError
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = docx.Document(io.BytesIO(content))
    except (PackageNotFoundError, ValueError, zipfile.BadZipFile, KeyError) as exc:
        raise ExtractionError(f"{filename}: could not open DOCX -- {exc}") from exc

    segments: list[Segment] = []
    current_heading: str | None = None

    def iter_block_items(doc):
        parent_elm = doc.element.body
        for child in parent_elm.iterchildren():
            if child.tag.endswith("}p"):
                yield Paragraph(child, doc)
            elif child.tag.endswith("}tbl"):
                yield Table(child, doc)

    for block in iter_block_items(document):
        if isinstance(block, Paragraph):
            style_name = block.style.name if block.style else ""
            text = block.text.strip()
            if not text:
                continue
            if HEADING_STYLE_RE.match(style_name or ""):
                current_heading = text
                continue
            segments.append(Segment(text=text, location=ChunkLocation(heading=current_heading)))
        else:  # Table -- preserve as a simple pipe-delimited text block
            rows = ["  |  ".join(cell.text.strip() for cell in row.cells) for row in block.rows]
            table_text = "\n".join(r for r in rows if r.strip())
            if table_text:
                segments.append(Segment(text=table_text, location=ChunkLocation(heading=current_heading)))

    if not segments:
        raise ExtractionError(f"{filename}: no extractable text found in the document.")
    return segments, []


def extract_pptx(content: bytes, filename: str) -> tuple[list[Segment], list[str]]:
    import zipfile

    from pptx import Presentation
    from pptx.exc import PackageNotFoundError

    try:
        presentation = Presentation(io.BytesIO(content))
    except (PackageNotFoundError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise ExtractionError(f"{filename}: could not open PPTX -- {exc}") from exc

    segments: list[Segment] = []
    for i, slide in enumerate(presentation.slides, start=1):
        title = None
        if slide.shapes.title is not None and slide.shapes.title.has_text_frame:
            title = slide.shapes.title.text.strip() or None

        parts: list[str] = []
        for shape in slide.shapes:
            if shape == slide.shapes.title:
                continue
            if shape.has_text_frame and shape.text_frame.text.strip():
                parts.append(shape.text_frame.text.strip())
            elif shape.has_table:
                rows = ["  |  ".join(cell.text.strip() for cell in row.cells) for row in shape.table.rows]
                parts.append("\n".join(r for r in rows if r.strip()))

        body_text = "\n".join(p for p in parts if p)
        combined = "\n".join(p for p in [title, body_text] if p)
        if combined.strip():
            segments.append(Segment(text=combined.strip(), location=ChunkLocation(slide=i, slide_title=title)))

    if not segments:
        raise ExtractionError(f"{filename}: no extractable text found in the presentation.")
    return segments, []


def extract_html(content: bytes, filename: str) -> tuple[list[Segment], list[str]]:
    """Unstructured-document extraction, not structured-data parsing --
    HTML never becomes a dataset. Safe by construction: BeautifulSoup's
    .get_text() strips every tag and returns text content only, so nothing
    from an uploaded HTML file is ever executed, on the server or later in
    a browser -- <script>/<style>/<noscript>/<template> elements and HTML
    comments are dropped entirely before any text is read, so their
    contents can never leak into a chunk even as literal text.
    """
    from bs4 import BeautifulSoup, Comment

    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ExtractionError(f"{filename}: could not decode file as text.")

    if not text.strip():
        raise ExtractionError(f"{filename}: file is empty.")

    soup = BeautifulSoup(text, "html.parser")

    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    for node in soup.find_all(string=lambda s: isinstance(s, Comment)):
        node.extract()

    segments: list[Segment] = []
    current_heading: str | None = None
    heading_tags = {"h1", "h2", "h3", "h4", "h5", "h6"}

    for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table"]):
        if element.name in heading_tags:
            heading_text = element.get_text(" ", strip=True)
            if heading_text:
                current_heading = heading_text
            continue

        if element.name == "table":
            rows = []
            for row in element.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
                if any(cells):
                    rows.append("  |  ".join(cells))
            table_text = "\n".join(rows)
            if table_text.strip():
                segments.append(Segment(text=table_text, location=ChunkLocation(heading=current_heading)))
            continue

        para_text = element.get_text(" ", strip=True)
        if para_text:
            segments.append(Segment(text=para_text, location=ChunkLocation(heading=current_heading)))

    if not segments:
        raise ExtractionError(f"{filename}: no extractable text found in the HTML.")
    return segments, []


def extract_text_like(content: bytes, filename: str, document_type: DocumentType) -> tuple[list[Segment], list[str]]:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ExtractionError(f"{filename}: could not decode file as text.")

    if not text.strip():
        raise ExtractionError(f"{filename}: file is empty.")

    lines = text.splitlines()
    segments: list[Segment] = []
    current_heading: str | None = None
    block_lines: list[str] = []
    block_start = 1

    def flush(end_line: int):
        block_text = "\n".join(block_lines).strip()
        if block_text:
            segments.append(
                Segment(
                    text=block_text,
                    location=ChunkLocation(heading=current_heading, line_start=block_start, line_end=end_line),
                )
            )

    for line_no, line in enumerate(lines, start=1):
        heading_text: str | None = None
        include_heading_line_in_body = False
        if document_type == DocumentType.MD:
            md_match = MD_HEADING_RE.match(line)
            if md_match:
                heading_text = md_match.group(2).strip()
        elif document_type == DocumentType.PY:
            py_match = PY_DEF_RE.match(line)
            if py_match:
                heading_text = f"{py_match.group(1)} {py_match.group(2)}"
                include_heading_line_in_body = True  # keep the def/class signature as real code content

        if heading_text is not None:
            flush(line_no - 1)
            block_lines = [line] if include_heading_line_in_body else []
            current_heading = heading_text
            block_start = line_no if include_heading_line_in_body else line_no + 1
            continue
        if line.strip() == "" and block_lines:
            flush(line_no - 1)
            block_lines = []
            block_start = line_no + 1
            continue
        if line.strip():
            block_lines.append(line)

    flush(len(lines))

    if not segments:
        raise ExtractionError(f"{filename}: no extractable text found.")
    return segments, []
