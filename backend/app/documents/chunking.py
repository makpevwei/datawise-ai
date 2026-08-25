"""Chunking: turns extracted segments into retrieval-sized chunks.

Small adjacent segments sharing the same source location (paragraph,
page, slide) are merged up to a size cap; segments longer than the cap
are split into overlapping windows. Location metadata always travels
with its chunk.
"""

from app.documents.extraction import Segment
from app.documents.models import ChunkLocation, DocumentChunk

MAX_CHUNK_CHARS = 800
OVERLAP_CHARS = 100


def chunk_segments(segments: list[Segment], document_id: str, document_name: str) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    buffer_text = ""
    buffer_location: ChunkLocation | None = None
    chunk_index = 0

    def flush() -> None:
        nonlocal buffer_text, buffer_location, chunk_index
        if buffer_text.strip():
            chunks.append(
                DocumentChunk(
                    id=f"{document_id}_{chunk_index}",
                    document_id=document_id,
                    document_name=document_name,
                    chunk_index=chunk_index,
                    text=buffer_text.strip(),
                    location=buffer_location or ChunkLocation(),
                )
            )
            chunk_index += 1
        buffer_text = ""
        buffer_location = None

    def append_window(text: str, location: ChunkLocation) -> None:
        nonlocal chunk_index
        chunks.append(
            DocumentChunk(
                id=f"{document_id}_{chunk_index}",
                document_id=document_id,
                document_name=document_name,
                chunk_index=chunk_index,
                text=text.strip(),
                location=location,
            )
        )
        chunk_index += 1

    for seg in segments:
        if len(seg.text) > MAX_CHUNK_CHARS:
            flush()
            start = 0
            while start < len(seg.text):
                end = min(start + MAX_CHUNK_CHARS, len(seg.text))
                append_window(seg.text[start:end], seg.location)
                if end == len(seg.text):
                    break
                start = end - OVERLAP_CHARS
            continue

        if not buffer_text:
            buffer_text = seg.text
            buffer_location = seg.location
            continue

        same_location = buffer_location == seg.location
        candidate_len = len(buffer_text) + len(seg.text) + 1
        if same_location and candidate_len <= MAX_CHUNK_CHARS:
            buffer_text += "\n" + seg.text
        else:
            flush()
            buffer_text = seg.text
            buffer_location = seg.location

    flush()
    return chunks
