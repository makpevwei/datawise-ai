"""Declarative base for DataWise's SQLAlchemy models.

Models live in app/db/models.py: User, Dataset, Document, AnalysisSession,
Message, Report (added for the productization/auth phase -- see that
module's docstrings for what each owns and why).

Still deliberately NOT in Postgres, and still owned by the existing
file-backed engines instead:

- dataset_columns, relationships, document_chunks, embeddings -- these
  remain DatasetStore/DocumentStore's job (parquet + JSON + in-memory
  embeddings, app/semantic/store.py and app/documents/store.py). The new
  Dataset/Document rows only add per-user ownership and processing-state
  metadata on top, via `storage_reference` pointing back into those
  stores -- they do not duplicate the dataframes/chunks themselves.
- raw chain-of-thought / tool-call traces -- Message stores only
  user-visible content (questions, summaries, evidence references), never
  the agent's internal reasoning.

Add a model here, generate a migration, and update this note when one of
these becomes an actual requirement.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
