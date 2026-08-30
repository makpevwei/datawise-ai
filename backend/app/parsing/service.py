"""File Parsing Layer -- turns uploaded bytes into pandas DataFrames.

Deliberately defensive: a malformed file must never crash the app. Every
failure mode is turned into a ParsingError with a human-readable message,
or into a warning attached to the successfully parsed table.
"""

import csv
import io
from dataclasses import dataclass, field

import pandas as pd

from app.parsing.errors import ParsingError

ENCODINGS_TO_TRY = ("utf-8-sig", "utf-8", "latin-1")
CSV_DELIMITER_CANDIDATES = [",", ";", "\t", "|"]


@dataclass
class ParsedTable:
    sheet_name: str | None
    dataframe: pd.DataFrame
    warnings: list[str] = field(default_factory=list)
    duplicate_columns: list[str] = field(default_factory=list)


def _decode_bytes(content: bytes, filename: str) -> tuple[str, str]:
    for encoding in ENCODINGS_TO_TRY:
        try:
            return content.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ParsingError(
        f"{filename}: could not decode file as text (tried {', '.join(ENCODINGS_TO_TRY)}). "
        "The file may be corrupted or not a text CSV."
    )


def _sniff_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="".join(CSV_DELIMITER_CANDIDATES))
        return dialect.delimiter
    except csv.Error:
        pass
    first_line = sample.splitlines()[0] if sample.splitlines() else ""
    counts = {d: first_line.count(d) for d in CSV_DELIMITER_CANDIDATES}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def _find_duplicate_headers(text: str, delimiter: str) -> list[str]:
    first_line = text.splitlines()[0] if text.splitlines() else ""
    reader = csv.reader([first_line], delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        return []
    header = [h.strip() for h in header]
    seen: dict[str, int] = {}
    duplicates: list[str] = []
    for h in header:
        seen[h] = seen.get(h, 0) + 1
        if seen[h] == 2:
            duplicates.append(h)
    return duplicates


def parse_csv_bytes(content: bytes, filename: str) -> ParsedTable:
    if len(content) == 0:
        raise ParsingError(f"{filename}: file is empty.")

    text, encoding = _decode_bytes(content, filename)
    if not text.strip():
        raise ParsingError(f"{filename}: file contains no data.")

    warnings: list[str] = []
    if encoding != "utf-8-sig" and encoding != "utf-8":
        warnings.append(f"File was not valid UTF-8; decoded using {encoding} as a fallback.")

    delimiter = _sniff_delimiter(text[:8192])
    duplicate_headers = _find_duplicate_headers(text, delimiter)
    if duplicate_headers:
        warnings.append(
            "Duplicate column names detected in header and auto-renamed: "
            + ", ".join(sorted(set(duplicate_headers)))
        )

    try:
        df = pd.read_csv(io.StringIO(text), sep=delimiter, engine="python")
    except pd.errors.EmptyDataError as exc:
        raise ParsingError(f"{filename}: no columns could be parsed from the file.") from exc
    except pd.errors.ParserError as exc:
        raise ParsingError(f"{filename}: malformed CSV -- {exc}") from exc

    df.columns = [str(c).strip().strip('"') for c in df.columns]

    if df.shape[1] == 0:
        raise ParsingError(f"{filename}: no columns could be parsed from the file.")
    if df.shape[0] == 0:
        warnings.append("File contains a header row but no data rows.")

    return ParsedTable(
        sheet_name=None,
        dataframe=df,
        warnings=warnings,
        duplicate_columns=sorted(set(duplicate_headers)),
    )


def parse_xlsx_bytes(content: bytes, filename: str) -> tuple[list[ParsedTable], list[str]]:
    if len(content) == 0:
        raise ParsingError(f"{filename}: file is empty.")
    if content[:2] != b"PK":
        raise ParsingError(
            f"{filename}: not a valid .xlsx file (legacy .xls is not supported -- "
            "please re-save as .xlsx)."
        )

    try:
        sheets = pd.read_excel(
            io.BytesIO(content),
            sheet_name=None,
            engine="openpyxl",
            engine_kwargs={"read_only": True},
        )
    except Exception as exc:
        raise ParsingError(f"{filename}: could not read workbook -- {exc}") from exc

    tables: list[ParsedTable] = []
    skipped_warnings: list[str] = []

    for sheet_name, df in sheets.items():
        if df.shape[1] == 0:
            skipped_warnings.append(f"Worksheet '{sheet_name}' has no columns and was skipped.")
            continue
        if df.shape[0] == 0:
            skipped_warnings.append(
                f"Worksheet '{sheet_name}' has a header row but no data rows and was skipped."
            )
            continue

        warnings: list[str] = []
        raw_columns = [str(c).strip() for c in df.columns]
        seen: dict[str, int] = {}
        duplicates: list[str] = []
        for c in raw_columns:
            seen[c] = seen.get(c, 0) + 1
            if seen[c] == 2:
                duplicates.append(c)
        if duplicates:
            warnings.append(
                "Duplicate column names detected and auto-renamed: " + ", ".join(sorted(set(duplicates)))
            )
        df.columns = raw_columns

        tables.append(
            ParsedTable(
                sheet_name=str(sheet_name),
                dataframe=df,
                warnings=warnings,
                duplicate_columns=sorted(set(duplicates)),
            )
        )

    if not tables:
        raise ParsingError(f"{filename}: workbook has no worksheets with data.")

    return tables, skipped_warnings
