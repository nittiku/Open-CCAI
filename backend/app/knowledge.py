import hashlib
import io
import math
from sqlalchemy import select, delete, literal
from pgvector.sqlalchemy import Vector
from . import providers
from .db import Session
from .models import Collection, Document, Chunk, Provider
from .storage import storage


class KnowledgeError(Exception):
    pass


def profile(provider):
    # Credential rotation doesn't change the embedding space; base URL/model changes do.
    return hashlib.sha256(
        f"{provider.kind}:{provider.model}:{provider.base_url or ''}".encode()
    ).hexdigest()


def ingest(document_id):
    with Session() as db:
        doc = db.get(Document, document_id)
        if not doc:
            return
        col = db.get(Collection, doc.collection_id)
        generation, key, name = col.generation, doc.storage_key, doc.name
        doc.status, doc.error = "processing", None
        db.commit()
        try:
            content = storage.read(key)
            if name.lower().endswith(".pdf"):
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(content))
                if len(reader.pages) > 500:
                    raise KnowledgeError("too_many_pages")
                text = "\n".join(page.extract_text() or "" for page in reader.pages)
            else:
                text = content.decode("utf-8")
            if not text.strip():
                raise KnowledgeError("no_extractable_text")
            if len(text) > 2_000_000:
                raise KnowledgeError("document_text_too_large")
            pieces = [text[i : i + 1800] for i in range(0, len(text), 1500)]
            provider = db.get(Provider, col.provider_id)
            fingerprint = profile(provider)
            vectors = []
            for i in range(0, len(pieces), 32):
                vectors.extend(
                    providers.adapter.embed(db, provider, pieces[i : i + 32])
                )
            if len(vectors) != len(pieces) or not vectors or not vectors[0]:
                raise KnowledgeError("invalid_embeddings")
            dimension = len(vectors[0])
            if dimension > 8192 or any(
                len(v) != dimension or any(not math.isfinite(x) for x in v)
                for v in vectors
            ):
                raise KnowledgeError("invalid_embeddings")
            # Lock and recheck after the external embedding call; deletion/reindex wins.
            db.expire_all()
            col = db.scalar(
                select(Collection).where(Collection.id == col.id).with_for_update()
            )
            doc = db.scalar(
                select(Document).where(Document.id == document_id).with_for_update()
            )
            if (
                not doc
                or not col
                or col.generation != generation
                or profile(db.get(Provider, col.provider_id)) != fingerprint
            ):
                return
            db.execute(delete(Chunk).where(Chunk.document_id == document_id))
            for i, (piece, vector) in enumerate(zip(pieces, vectors)):
                db.add(
                    Chunk(
                        document_id=document_id,
                        text=piece,
                        position=i,
                        embedding=vector,
                        profile=fingerprint,
                    )
                )
            doc.status, doc.generation, doc.error = "ready", generation, None
            db.commit()
        except Exception as exc:
            db.rollback()
            doc = db.get(Document, document_id)
            if doc and doc.generation == generation:
                doc.status = "error"
                doc.error = (
                    str(exc) if isinstance(exc, KnowledgeError) else "ingestion_failed"
                )
                db.commit()
            else:
                raise


def retrieve(db, bot_id, collection_ids, query, limit=5, allowed_bot_ids=None):
    if not collection_ids:
        return []
    results = []
    for cid in collection_ids:
        col = db.get(Collection, cid)
        if not col or col.bot_id not in (
            allowed_bot_ids if allowed_bot_ids is not None else [bot_id]
        ):
            raise KnowledgeError("foreign_collection")
        provider = db.get(Provider, col.provider_id)
        vector = providers.adapter.embed(db, provider, [query])[0]
        fingerprint = profile(provider)
        statement = (
            select(Chunk, Document)
            .join(Document, Chunk.document_id == Document.id)
            .where(
                Document.collection_id == cid,
                Document.status == "ready",
                Document.generation == col.generation,
                Chunk.profile == fingerprint,
            )
        )
        if db.bind.dialect.name == "postgresql":
            distance = Chunk.embedding.op("<=>")(literal(vector, type_=Vector()))
            rows = db.execute(statement.order_by(distance).limit(limit)).all()
        else:
            rows = db.execute(
                statement
            ).all()  # SQLite only for deterministic local tests.
        for chunk, doc in rows:
            v = list(chunk.embedding)
            if len(v) != len(vector):
                raise KnowledgeError("embedding_dimension_changed_reindex_required")
            denominator = math.sqrt(sum(x * x for x in v) * sum(x * x for x in vector))
            score = (
                sum(a * b for a, b in zip(v, vector)) / denominator
                if denominator
                else 0
            )
            results.append(
                {
                    "document_id": doc.id,
                    "name": doc.name,
                    "chunk": chunk.position,
                    "text": chunk.text,
                    "score": score,
                }
            )
    return sorted(results, key=lambda x: x["score"], reverse=True)[:limit]
