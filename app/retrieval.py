from dataclasses import dataclass
from hashlib import sha256
import re

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import KnowledgeChunk


FTS_TABLE = "knowledge_fts"
TARGET_CHUNK_CHARS = 1000
MAX_CHUNK_CHARS = 1200
OVERLAP_LINES = 2


class SearchCapabilityError(RuntimeError):
    """The configured SQLite runtime cannot provide the required search index."""


class RetrievalUnavailable(RuntimeError):
    """The persistent retrieval index could not serve a query."""


@dataclass(frozen=True)
class ChunkDraft:
    ordinal: int
    start_line: int
    end_line: int
    body: str
    content_fingerprint: str


def _fingerprint(value):
    return sha256(value.encode("utf-8")).hexdigest()


def _segments(body, max_chars):
    normalized = body.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    segments = []
    for line_number, line in enumerate(lines, start=1):
        if len(line) <= max_chars:
            segments.append((line_number, line))
            continue
        for offset in range(0, len(line), max_chars):
            segments.append((line_number, line[offset : offset + max_chars]))
    return segments


def chunk_text(
    body,
    target_chars=TARGET_CHUNK_CHARS,
    max_chars=MAX_CHUNK_CHARS,
    overlap_lines=OVERLAP_LINES,
):
    """Split normalized text deterministically while preserving source line numbers."""
    if target_chars <= 0 or max_chars < target_chars or overlap_lines < 0:
        raise ValueError("invalid chunking limits")

    segments = _segments(body, max_chars)
    drafts = []
    start = 0
    ordinal = 0
    while start < len(segments):
        end = start
        size = 0
        while end < len(segments):
            separator = 1 if end > start else 0
            proposed = size + separator + len(segments[end][1])
            if end > start and proposed > max_chars:
                break
            size = proposed
            end += 1
            if size >= target_chars:
                break

        window = segments[start:end]
        chunk_body = "\n".join(value for _, value in window)
        if chunk_body.strip():
            drafts.append(
                ChunkDraft(
                    ordinal=ordinal,
                    start_line=window[0][0],
                    end_line=window[-1][0],
                    body=chunk_body,
                    content_fingerprint=_fingerprint(chunk_body),
                )
            )
            ordinal += 1

        if end >= len(segments):
            break

        next_start = end
        if overlap_lines:
            earliest_line = max(window[-1][0] - overlap_lines + 1, window[0][0])
            candidate = end - 1
            while candidate > start and segments[candidate - 1][0] >= earliest_line:
                candidate -= 1
            next_start = candidate
        if next_start <= start:
            next_start = end
        start = next_start

    return drafts


def stable_chunk_id(entry_id, draft):
    source = (
        f"{entry_id}:{draft.start_line}:{draft.end_line}:"
        f"{draft.ordinal}:{draft.content_fingerprint}"
    )
    return _fingerprint(source)


def ensure_search_capabilities():
    probe = "__knowledge_trigram_probe"
    try:
        db.session.execute(text(f"DROP TABLE IF EXISTS temp.{probe}"))
        db.session.execute(
            text(
                f"CREATE VIRTUAL TABLE temp.{probe} "
                "USING fts5(body, tokenize='trigram')"
            )
        )
        db.session.execute(text(f"DROP TABLE temp.{probe}"))
    except SQLAlchemyError as exc:
        raise SearchCapabilityError(
            "SQLite FTS5 with the trigram tokenizer is required"
        ) from exc


def initialize_search_index():
    ensure_search_capabilities()
    try:
        # Existing databases predate the composite source constraints used by
        # knowledge_chunks. These indexes validate the parent keys in SQLite
        # without replacing or rewriting user data tables.
        db.session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_material_id_class_lookup "
                "ON materials(id, class_id)"
            )
        )
        db.session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_id_class_lookup "
                "ON users(id, class_id)"
            )
        )
        db.session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_entry_source_lookup "
                "ON knowledge_entries(id, material_id, class_id)"
            )
        )
        db.session.execute(
            text(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5("
                "chunk_id UNINDEXED, class_id UNINDEXED, material_id UNINDEXED, "
                "body, tokenize='trigram')"
            )
        )
    except SQLAlchemyError as exc:
        raise SearchCapabilityError("Unable to create the persistent FTS5 index") from exc


def search_index_exists():
    row = db.session.execute(
        text(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = :table_name"
        ),
        {"table_name": FTS_TABLE},
    ).first()
    return row is not None


def replace_entry_index(entry):
    """Replace relational chunks and FTS rows in the caller's transaction."""
    if entry.id is None or entry.material_id is None or entry.class_id is None:
        raise ValueError("knowledge entry must be persisted before indexing")
    if entry.material is None or entry.material.class_id != entry.class_id:
        raise ValueError("knowledge entry and material must belong to the same class")

    old_chunk_ids = list(
        db.session.scalars(
            db.select(KnowledgeChunk.chunk_id).where(
                KnowledgeChunk.knowledge_entry_id == entry.id
            )
        )
    )
    for chunk_id in old_chunk_ids:
        db.session.execute(
            text(f"DELETE FROM {FTS_TABLE} WHERE chunk_id = :chunk_id"),
            {"chunk_id": chunk_id},
        )
    db.session.execute(
        db.delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_entry_id == entry.id)
    )

    chunks = []
    for draft in chunk_text(entry.body):
        chunk = KnowledgeChunk(
            chunk_id=stable_chunk_id(entry.id, draft),
            knowledge_entry_id=entry.id,
            material_id=entry.material_id,
            class_id=entry.class_id,
            start_line=draft.start_line,
            end_line=draft.end_line,
            body=draft.body,
            content_fingerprint=draft.content_fingerprint,
        )
        db.session.add(chunk)
        chunks.append(chunk)
    db.session.flush()

    for chunk in chunks:
        db.session.execute(
            text(
                f"INSERT INTO {FTS_TABLE} "
                "(chunk_id, class_id, material_id, body) "
                "VALUES (:chunk_id, :class_id, :material_id, :body)"
            ),
            {
                "chunk_id": chunk.chunk_id,
                "class_id": chunk.class_id,
                "material_id": chunk.material_id,
                "body": chunk.body,
            },
        )
    return chunks


def delete_entry_index(entry_id):
    chunk_ids = list(
        db.session.scalars(
            db.select(KnowledgeChunk.chunk_id).where(
                KnowledgeChunk.knowledge_entry_id == entry_id
            )
        )
    )
    for chunk_id in chunk_ids:
        db.session.execute(
            text(f"DELETE FROM {FTS_TABLE} WHERE chunk_id = :chunk_id"),
            {"chunk_id": chunk_id},
        )
    db.session.execute(
        db.delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_entry_id == entry_id)
    )


def build_fts_query(value):
    normalized = re.sub(r"\s+", " ", (value or "").strip())
    if not normalized:
        raise ValueError("query must not be blank")
    return '"' + normalized.replace('"', '""') + '"'


def _merge_overlapping(rows):
    merged = []
    for row in rows:
        candidate = dict(row)
        match = None
        for existing in merged:
            if existing["material_id"] != candidate["material_id"]:
                continue
            overlap = min(existing["end_line"], candidate["end_line"]) - max(
                existing["start_line"], candidate["start_line"]
            ) + 1
            smaller = min(
                existing["end_line"] - existing["start_line"] + 1,
                candidate["end_line"] - candidate["start_line"] + 1,
            )
            if overlap > 0 and overlap / smaller >= 0.5:
                match = existing
                break
        if match is None:
            merged.append(candidate)
            continue
        match["start_line"] = min(match["start_line"], candidate["start_line"])
        match["end_line"] = max(match["end_line"], candidate["end_line"])
        if candidate["passage"] not in match["passage"]:
            match["passage"] = f"{match['passage']} … {candidate['passage']}"
    return merged


def search_knowledge(user, query, limit=20):
    fts_query = build_fts_query(query)
    try:
        rows = db.session.execute(
            text(
                f"SELECT c.chunk_id, c.material_id, c.start_line, c.end_line, "
                "m.title AS material_title, "
                f"snippet({FTS_TABLE}, 3, '', '', '…', 40) AS passage, "
                f"bm25({FTS_TABLE}) AS score "
                f"FROM {FTS_TABLE} "
                f"JOIN knowledge_chunks AS c ON c.chunk_id = {FTS_TABLE}.chunk_id "
                "JOIN materials AS m ON m.id = c.material_id "
                f"WHERE {FTS_TABLE} MATCH :query "
                "AND c.class_id = :class_id "
                "AND m.class_id = :class_id "
                "ORDER BY score ASC, c.chunk_id ASC "
                "LIMIT :limit"
            ),
            {"query": fts_query, "class_id": user.class_id, "limit": limit},
        ).mappings().all()
    except (SQLAlchemyError, RuntimeError) as exc:
        raise RetrievalUnavailable("knowledge retrieval index is unavailable") from exc

    results = []
    for row in _merge_overlapping(rows):
        material_id = row["material_id"]
        results.append(
            {
                "passage": row["passage"] or "",
                "material_title": row["material_title"],
                "material_id": material_id,
                "chunk_id": row["chunk_id"],
                "start_line": row["start_line"],
                "end_line": row["end_line"],
                "detail_url": f"/api/materials/{material_id}",
                "file_url": f"/api/materials/{material_id}/file",
            }
        )
    return results
