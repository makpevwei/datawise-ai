"""Document extraction: turns raw file bytes into (text, location) segments.

PDF pipeline uses three stages:
  1. PyMuPDF (fast, high-quality native text extraction)
  2. Per-page OCR fallback via pytesseract + pdf2image for image/scanned pages
  3. Raises ExtractionError only when ALL pages fail BOTH methods

Users are never asked to install dependencies -- the application manages them.
"""

import io
import re
import shutil
from dataclasses import dataclass

from app.documents.models import ChunkLocation, DocumentType

HEADING_STYLE_RE = re.compile(r"^Heading\s*\d*$", re.IGNORECASE)
MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
PY_DEF_RE = re.compile(r"^(def|class)\s+(\w+)")

# Minimum useful characters on a page to consider native extraction successful.
_MIN_PAGE_CHARS = 30


class ExtractionError(Exception):
    """Raised when a document cannot be extracted. Carries a human-readable message."""


@dataclass
class Segment:
    text: str
    location: ChunkLocation


# ---------------------------------------------------------------------------
# PDF capability detection (lazy, cached per process)
# ---------------------------------------------------------------------------

def _ocr_available() -> bool:
    """Return True when both pytesseract and a tesseract binary are available."""
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:  # noqa: BLE001
        return False


def _pdf2image_available() -> bool:
    """True only when the pdf2image package AND poppler's own command-line
    tools are genuinely usable.

    pdf2image being importable does NOT mean OCR page-rendering will work --
    it's a thin wrapper that shells out to poppler's pdftoppm/pdfinfo
    binaries, a separate system-level dependency. Checking only the Python
    import (as this used to) reports OCR as "available" even when poppler
    itself is missing, so every page then fails OCR silently (caught and
    turned into a warning) instead of the caller ever finding out OCR
    couldn't actually run.
    """
    try:
        from pdf2image import convert_from_bytes  # noqa: F401
    except ImportError:
        return False
    return shutil.which("pdftoppm") is not None


def _pymupdf_available() -> bool:
    try:
        import pymupdf  # noqa: F401
        return True
    except ImportError:
        try:
            import fitz  # noqa: F401
            return True
        except ImportError:
            return False


# ---------------------------------------------------------------------------
# PDF extraction helpers
# ---------------------------------------------------------------------------

def _extract_page_text_pymupdf(pdf_bytes: bytes) -> list[tuple[int, str]]:
    """Extract text from every page using PyMuPDF.

    Returns a list of (page_number_1_based, text) pairs.
    Pages with no usable text have an empty string.
    """
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz  # type: ignore[no-redef]

    pages: list[tuple[int, str]] = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise ExtractionError(f"Could not open PDF: {exc}") from exc

    for i, page in enumerate(doc, start=1):
        try:
            text = page.get_text("text").strip()
        except Exception:  # noqa: BLE001
            text = ""
        pages.append((i, text))
    doc.close()
    return pages


def _ocr_page_image(image) -> str:  # type: ignore[return]
    """Run Tesseract OCR on a PIL image and return the extracted text."""
    import pytesseract
    return pytesseract.image_to_string(image, lang="eng")


def _render_pdf_pages(pdf_bytes: bytes) -> list[tuple[int, object]]:
    """Render every PDF page to a PIL image for OCR.

    Returns a list of (page_number_1_based, PIL.Image) pairs.
    """
    from pdf2image import convert_from_bytes
    images = convert_from_bytes(pdf_bytes, dpi=200)
    return [(i + 1, img) for i, img in enumerate(images)]


# ---------------------------------------------------------------------------
# Public PDF extractor (multi-stage)
# ---------------------------------------------------------------------------

def extract_pdf(content: bytes, filename: str) -> tuple[list[Segment], list[str]]:
    """Multi-stage PDF extractor.

    Stage 1: PyMuPDF native text extraction (fast, accurate for digital PDFs).
    Stage 2: Per-page OCR via pytesseract + pdf2image for image/scanned pages.
    Stage 3: pypdf fallback when PyMuPDF is not available.

    Mixed PDFs (some text pages, some scanned) are handled correctly -- each
    page uses the best available method. The user is never asked to install
    anything; the application manages its own dependencies.
    """
    warnings: list[str] = []

    # --- Stage 1: PyMuPDF (preferred) ---
    if _pymupdf_available():
        try:
            native_pages = _extract_page_text_pymupdf(content)
        except ExtractionError as exc:
            raise ExtractionError(f"{filename}: {exc}") from exc

        segments: list[Segment] = []
        ocr_needed: list[int] = []   # 1-based page numbers needing OCR

        for page_no, text in native_pages:
            if len(text) >= _MIN_PAGE_CHARS:
                segments.append(Segment(text=text, location=ChunkLocation(page=page_no)))
            else:
                ocr_needed.append(page_no)

        # --- Stage 2: OCR for pages that had no native text ---
        if ocr_needed and _ocr_available() and _pdf2image_available():
            try:
                rendered = _render_pdf_pages(content)
                rendered_map = {pn: img for pn, img in rendered}
                for page_no in ocr_needed:
                    img = rendered_map.get(page_no)
                    if img is None:
                        continue
                    try:
                        ocr_text = _ocr_page_image(img).strip()
                    except Exception as exc:  # noqa: BLE001
                        warnings.append(f"Page {page_no}: OCR failed — {exc}")
                        continue
                    if len(ocr_text) >= _MIN_PAGE_CHARS:
                        segments.append(Segment(text=ocr_text, location=ChunkLocation(page=page_no)))
                    else:
                        warnings.append(f"Page {page_no}: no usable text after OCR.")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"OCR batch failed: {exc}")

        elif ocr_needed and not (_ocr_available() and _pdf2image_available()):
            # Name the actual missing piece rather than a generic "OCR
            # unavailable" -- tesseract and poppler are independent system
            # dependencies and either can be present without the other.
            missing = []
            if not _ocr_available():
                missing.append("the OCR engine (tesseract)")
            if not _pdf2image_available():
                missing.append("the PDF page renderer (poppler)")
            warnings.append(
                f"{len(ocr_needed)} page(s) appear to be scanned/image-based and could not be processed "
                f"because {' and '.join(missing)} is not installed on this server."
            )

        # Sort segments by page number
        segments.sort(key=lambda s: s.location.page or 0)

        if not segments:
            raise ExtractionError(
                f"{filename}: no readable content could be extracted from this document. "
                f"The file may contain only images without detectable text, or the content may be in "
                f"an unsupported format."
            )

        return segments, warnings

    # --- Stage 3: pypdf fallback (when PyMuPDF is not installed) ---
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(content))
    except (PdfReadError, ValueError) as exc:
        raise ExtractionError(f"{filename}: could not open PDF — {exc}") from exc

    segments = []
    empty_pages: list[int] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:  # noqa: BLE001
            text = ""
        if len(text) >= _MIN_PAGE_CHARS:
            segments.append(Segment(text=text, location=ChunkLocation(page=i)))
        else:
            empty_pages.append(i)

    # OCR fallback even in pypdf path
    if empty_pages and _ocr_available() and _pdf2image_available():
        try:
            rendered = _render_pdf_pages(content)
            rendered_map = {pn: img for pn, img in rendered}
            for page_no in empty_pages:
                img = rendered_map.get(page_no)
                if img is None:
                    continue
                try:
                    ocr_text = _ocr_page_image(img).strip()
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"Page {page_no}: OCR failed — {exc}")
                    continue
                if len(ocr_text) >= _MIN_PAGE_CHARS:
                    segments.append(Segment(text=ocr_text, location=ChunkLocation(page=page_no)))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"OCR batch failed: {exc}")

    segments.sort(key=lambda s: s.location.page or 0)

    if not segments:
        raise ExtractionError(
            f"{filename}: no readable content could be extracted. "
            f"The document appears to contain only scanned/image content that could not be processed."
        )

    if empty_pages:
        warnings.append(
            f"{len(empty_pages)} page(s) had no extractable text and were skipped."
        )

    return segments, warnings


# ---------------------------------------------------------------------------
# DOCX / PPTX / HTML / text-like extractors (unchanged)
# ---------------------------------------------------------------------------

def extract_docx(content: bytes, filename: str) -> tuple[list[Segment], list[str]]:
    import zipfile

    import docx
    from docx.opc.exceptions import PackageNotFoundError
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = docx.Document(io.BytesIO(content))
    except (PackageNotFoundError, ValueError, zipfile.BadZipFile, KeyError) as exc:
        raise ExtractionError(f"{filename}: could not open DOCX — {exc}") from exc

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
        else:
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
        raise ExtractionError(f"{filename}: could not open PPTX — {exc}") from exc

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

    def flush(end_line: int) -> None:
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
                include_heading_line_in_body = True

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
