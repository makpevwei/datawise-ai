"""Read-only ad-hoc SQL over uploaded datasets, via DuckDB.

Exists for the case the deterministic single-table tools
(calculate_metric/group_and_aggregate, see app/agent/tools.py) don't cover
well: a question that genuinely needs a real JOIN across multiple
datasets. DuckDB runs directly against the same in-memory pandas
dataframes the rest of the app already has profiled -- no separate
database, no persistence, a fresh connection per call. The deterministic
tools stay exactly as they are for the common single-table case; this is
an addition, not a replacement.

Security is enforced at two independent layers, both verified live (see
tests/test_sql_query.py), not just assumed from reading the query text:

  1. `enable_external_access=false` on the connection -- DuckDB itself
     then refuses any file, network, or extension-install access no
     matter what SQL is sent (confirmed directly: read_csv_auto, ATTACH,
     COPY TO, and INSTALL all raise PermissionException with this set).
     This is the layer that actually matters.
  2. A statement-shape check (SELECT/WITH only, one statement) as defense
     in depth -- clearer to reason about and test than relying solely on
     (1) staying true across every future DuckDB version.

Every dataset is registered as a DuckDB view over its pandas dataframe,
not a writable base table -- confirmed live: INSERT/UPDATE/DELETE against
a registered dataframe all fail with a DuckDB error, not a silent no-op,
so even a query that somehow slipped past (2) still can't mutate anything.
"""

import re
import threading
from dataclasses import dataclass

import duckdb

from app.semantic.store import DatasetRecord

MAX_SQL_QUERY_ROWS = 500
SQL_QUERY_TIMEOUT_SECONDS = 20.0

_STRING_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")
_IDENT_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_]+")
_ALLOWED_LEADING_KEYWORDS = ("select", "with")


class SqlQueryError(Exception):
    pass


@dataclass
class SqlQueryResult:
    # sql-safe name -> the dataset's real display name, so the caller can
    # tell the LLM (or a human reading the trace) what each table actually
    # is.
    table_names: dict[str, str]
    # sql-safe name -> its column names, handed back up front so the LLM
    # rarely needs a separate inspect_schema round trip before writing SQL.
    tables_schema: dict[str, list[str]]
    columns: list[str]
    rows: list[dict]
    row_count: int
    truncated: bool


def _sql_safe_table_name(record: DatasetRecord, used: set[str]) -> str:
    """A dataset's display name is usually not a valid unquoted SQL
    identifier (spaces, "--", a file extension, ...) -- derive a clean one
    instead, preferring the short sheet name when there is one (matches
    the same short, human-recognizable label already used for chart/KPI
    source labels elsewhere in the app -- see dashboard_charts.py)."""
    base = record.profile.sheet_name or record.profile.name
    base = _IDENT_UNSAFE_RE.sub("_", base).strip("_") or "dataset"
    if base[0].isdigit():
        base = f"t_{base}"
    candidate = base
    n = 2
    while candidate.lower() in used:
        candidate = f"{base}_{n}"
        n += 1
    used.add(candidate.lower())
    return candidate


def _validate_readonly_query(query: str) -> str:
    q = query.strip()
    if q.endswith(";"):
        q = q[:-1].strip()
    if not q:
        raise SqlQueryError("Query is empty.")
    # Checked against the query with string literals blanked out, so a
    # filter value that happens to contain a semicolon or a keyword-shaped
    # word (e.g. WHERE notes LIKE '%order; cancelled%') can't trip this.
    stripped = _STRING_LITERAL_RE.sub("''", q)
    if ";" in stripped:
        raise SqlQueryError("Only a single SQL statement is allowed -- no ';'-separated multiple statements.")
    lead_match = re.match(r"[A-Za-z]+", stripped)
    lead = lead_match.group(0).lower() if lead_match else ""
    if lead not in _ALLOWED_LEADING_KEYWORDS:
        raise SqlQueryError(
            f"Only read-only SELECT/WITH queries are allowed. This query starts with "
            f"'{lead or q[:20]}', which isn't permitted -- rewrite it as a SELECT."
        )
    return q


def run_sql_query(
    records: list[DatasetRecord],
    query: str,
    max_rows: int = MAX_SQL_QUERY_ROWS,
    timeout_seconds: float = SQL_QUERY_TIMEOUT_SECONDS,
) -> SqlQueryResult:
    if not records:
        raise SqlQueryError("No datasets were provided to query against.")
    safe_query = _validate_readonly_query(query)

    con = duckdb.connect(":memory:")
    try:
        con.execute("SET enable_external_access=false")

        used_names: set[str] = set()
        table_names: dict[str, str] = {}
        tables_schema: dict[str, list[str]] = {}
        for record in records:
            sql_name = _sql_safe_table_name(record, used_names)
            con.register(sql_name, record.dataframe)
            table_names[sql_name] = record.profile.name
            tables_schema[sql_name] = list(record.dataframe.columns)

        # Wrapping in an outer LIMIT caps the result regardless of what the
        # caller's own query did or didn't specify -- fetch one extra row
        # so `truncated` can be reported honestly rather than guessed at.
        capped_query = f"SELECT * FROM ({safe_query}) AS _capped_result LIMIT {max_rows + 1}"

        result_holder: dict[str, object] = {}

        def _run() -> None:
            try:
                cursor = con.execute(capped_query)
                result_holder["rows"] = cursor.fetchall()
                result_holder["columns"] = [d[0] for d in cursor.description]
            except Exception as exc:  # noqa: BLE001 -- re-raised as SqlQueryError on the calling thread below
                result_holder["error"] = exc

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout_seconds)
        if thread.is_alive():
            con.interrupt()
            thread.join(5.0)
            raise SqlQueryError(
                f"Query took longer than {timeout_seconds:.0f}s and was cancelled -- "
                "simplify it, add filters, or aggregate before joining."
            )

        if "error" in result_holder:
            available = ", ".join(f"{name} ({', '.join(cols)})" for name, cols in tables_schema.items())
            raise SqlQueryError(f"SQL error: {result_holder['error']} Available tables: {available}.")

        raw_rows: list[tuple] = result_holder["rows"]  # type: ignore[assignment]
        columns: list[str] = result_holder["columns"]  # type: ignore[assignment]
        truncated = len(raw_rows) > max_rows
        raw_rows = raw_rows[:max_rows]
        rows = [dict(zip(columns, row, strict=True)) for row in raw_rows]

        return SqlQueryResult(
            table_names=table_names,
            tables_schema=tables_schema,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
        )
    finally:
        con.close()
