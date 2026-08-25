"""DataWise's PostgreSQL persistence layer.

Its own engine, session factory, declarative Base, and Alembic history
(backend/alembic/), reading DATABASE_URL only from DataWise's own
settings (app/config.py).

Ownership/versioning metadata (users, datasets, documents, reports,
analysis sessions/messages) lives here in Postgres; the underlying
dataframes and document chunks themselves stay on the existing
file-backed stores (parquet + JSON under the configured upload
directories) rather than being duplicated into the database.
"""
