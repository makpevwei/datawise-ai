# DataWise AI — Architecture Notes

## Why layers are separated

The core product risk is a chatbot that invents plausible-looking numbers. To avoid
that, the backend enforces a hard boundary: everything that touches raw data
(parsing, profiling, joins, aggregation, statistics) is deterministic Python/pandas
code with no LLM involvement. The **AI layer** only ever receives already-computed,
structured results — it explains and narrates, it does not calculate. This
boundary is the main thing to preserve as the system grows.

## Layer responsibilities

See the table in the root `README.md` for the full list. In short:

- **Upload → Parsing → Profiling → Relationships → Semantic**: turn raw files into
  a trustworthy, understood dataset model.
- **Analysis Engine**: the only place calculations happen.
- **Visualization Engine**: maps analytical results to an appropriate chart type,
  driven by the shape of the question and the data — never a default chart per
  dataset.
- **Geography**: a static, offline country-centroid lookup for country-level maps
  — no paid geocoding API, and an unmatched value is reported honestly rather than
  guessed.
- **AI layer**: intent routing, tool selection, and narration over
  already-calculated results.
- **Reporting**: assembles findings (finding / evidence / calculation /
  interpretation / recommendation) into exportable executive PDF reports, and
  delivers them by email via SMTP.
- **Auth & persistence**: JWT authentication and a Postgres-backed ownership /
  versioning layer sitting on top of the existing file-backed dataset/document
  stores — Postgres owns *who owns what and which version is active*; the actual
  dataframes and document chunks stay on disk (parquet + JSON), not duplicated
  into the database.

## Routing sits in front of the agent loop, not inside it

`app/agent/graph.py` adds one LangGraph node (`route`) ahead of the core
tool-calling loop (`app/agent/planner.run_agent`): a single bounded LLM call
classifies a question into resource categories (data/documents/web, in
combination, or a general/greeting question with no data dependency) before the
loop runs, scoping which tools are even offered. The loop itself — dataset
inspection, document retrieval, tool selection, calculation, evidence
verification, synthesis — is unchanged; the graph orchestrates it, it does not
reimplement it.

Document RAG prefers embedding-based retrieval (`app/embeddings/provider.py`, a
free local model by default) over a TF-IDF index, but TF-IDF is always still built
as a fallback — RAG availability never depends on the embedding model succeeding.
See `docs/embeddings.md` for the model choice and rationale.

Web research (`app/agent/web_research.py`) is a fully optional tool category — no
provider required — bounded per question by
`MAX_RESEARCH_QUERIES`/`MAX_RESEARCH_TOOL_CALLS`, contributing a
`VERIFIED_FROM_WEB` evidence label verified the same way document-grounded claims
are (lexical overlap against the actual cited source, never trusted from the
LLM's raw claim).

## Relationship & join engine

Relationship discovery (`app/relationships/service.py`) only ever suggests a pair
of columns as a relationship when at least one side is genuinely close to unique
in its own table (a real primary key) — a shared low-cardinality categorical
column (region, segment, status) can never pass this gate, regardless of name
match or value overlap, because neither side of such a column is unique by
definition. Cardinality (`app/relationships/joins.classify_cardinality`) is
computed once and shared between the suggestion engine and the join engine
itself, so "what a relationship claims" and "what a join actually does" can never
drift apart.

The join engine (`app/relationships/joins.py`) supports inner/left/right/full
outer joins, a no-persistence preview endpoint, dataset-name-based column-collision
suffixes (never a silent overwrite), many-to-many fan-out protection (refused by
default, with an estimate, unless explicitly confirmed), and duplicate-join
prevention (repeating an identical join reuses the existing derived dataset rather
than creating a new one). A derived/joined dataset is persisted exactly like an
uploaded one (same file-backed store), with lineage (`JoinLineage`) recording its
parent datasets, join key, and join type — used both for provenance and to
suppress meaningless self-referential relationship suggestions between a derived
dataset and its own direct parents.

## Open items

- Multi-chart cross-filtering across an interactive dashboard (today's
  filter/sort/drill-down in `AnalysisWorkspace.tsx` operates on one analysis
  result at a time).
- State/city-level geocoding (country-level mapping is implemented; state/city
  intentionally is not, since no reliable deterministic lookup exists and adding
  an external geocoding API is out of scope).
- Email delivery is implemented against standard SMTP but has not been exercised
  against real credentials in this environment.
