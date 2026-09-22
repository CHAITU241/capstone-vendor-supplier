from dataclasses import dataclass

from chromadb.api.models.Collection import Collection

from app.services.chunking import TextChunk
from app.vector_store import get_chroma_client

COLLECTION_NAME = "supplier_chunks_v1"


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    document_id: str
    filename: str
    page_number: int
    text: str
    distance: float


def get_chunk_collection() -> Collection:
    return get_chroma_client().get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def replace_document_chunks(
    collection: Collection,
    supplier_id: str,
    document_id: str,
    filename: str,
    chunks: list[TextChunk],
    embeddings: list[list[float]],
) -> None:
    if len(chunks) != len(embeddings):
        raise ValueError("Every chunk must have one embedding")

    collection.delete(
        where={"$and": [{"supplier_id": supplier_id}, {"document_id": document_id}]}
    )
    if not chunks:
        return

    ids = [f"{supplier_id}:{document_id}:{chunk.index}" for chunk in chunks]
    collection.upsert(
        ids=ids,
        documents=[chunk.text for chunk in chunks],
        embeddings=embeddings,
        metadatas=[
            {
                "supplier_id": supplier_id,
                "document_id": document_id,
                "filename": filename,
                "page_number": chunk.page_number,
                "chunk_index": chunk.index,
                "token_count": chunk.token_count,
            }
            for chunk in chunks
        ],
    )


def delete_supplier_chunks(collection: Collection, supplier_id: str) -> None:
    collection.delete(where={"supplier_id": supplier_id})


def delete_document_chunks(
    collection: Collection,
    supplier_id: str,
    document_id: str,
) -> None:
    collection.delete(
        where={"$and": [
            {"supplier_id": supplier_id},
            {"document_id": document_id},
        ]}
    )


def query_supplier_chunks(
    collection: Collection,
    supplier_id: str,
    query_embedding: list[float],
    limit: int,
    max_distance: float,
) -> list[RetrievedChunk]:
    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=limit,
        where={"supplier_id": supplier_id},
        include=["documents", "metadatas", "distances"],
    )
    ids = result.get("ids", [[]])[0]
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    retrieved: list[RetrievedChunk] = []
    for chunk_id, text, metadata, distance in zip(
        ids, documents, metadatas, distances, strict=True
    ):
        if text is None or metadata is None or distance is None:
            continue
        if float(distance) > max_distance:
            continue
        retrieved.append(
            RetrievedChunk(
                chunk_id=chunk_id,
                document_id=str(metadata["document_id"]),
                filename=str(metadata["filename"]),
                page_number=int(metadata["page_number"]),
                text=text,
                distance=float(distance),
            )
        )
    return retrieved
