import chromadb

from app.services.chunking import TextChunk
from app.services.retrieval import (
    delete_document_chunks,
    query_supplier_chunks,
    replace_document_chunks,
)


def test_query_is_strictly_filtered_to_supplier() -> None:
    collection = chromadb.EphemeralClient().get_or_create_collection(
        "retrieval_isolation",
        metadata={"hnsw:space": "cosine"},
    )
    chunk = TextChunk(index=0, page_number=1, text="shared evidence", token_count=2)
    replace_document_chunks(
        collection,
        supplier_id="supplier-a",
        document_id="document-a",
        filename="a.pdf",
        chunks=[chunk],
        embeddings=[[1.0, 0.0, 0.0]],
    )
    replace_document_chunks(
        collection,
        supplier_id="supplier-b",
        document_id="document-b",
        filename="b.pdf",
        chunks=[chunk],
        embeddings=[[1.0, 0.0, 0.0]],
    )

    results = query_supplier_chunks(
        collection,
        supplier_id="supplier-a",
        query_embedding=[1.0, 0.0, 0.0],
        limit=4,
        max_distance=1.0,
    )

    assert len(results) == 1
    assert results[0].document_id == "document-a"
    assert results[0].filename == "a.pdf"


def test_deleting_one_document_keeps_other_supplier_chunks() -> None:
    collection = chromadb.EphemeralClient().get_or_create_collection(
        "document_delete_isolation"
    )
    chunk = TextChunk(index=0, page_number=1, text="evidence", token_count=1)
    for document_id in ("document-a", "document-b"):
        replace_document_chunks(
            collection,
            supplier_id="supplier-a",
            document_id=document_id,
            filename=f"{document_id}.pdf",
            chunks=[chunk],
            embeddings=[[1.0, 0.0]],
        )

    delete_document_chunks(collection, "supplier-a", "document-a")

    remaining = collection.get(where={"supplier_id": "supplier-a"})
    assert remaining["ids"] == ["supplier-a:document-b:0"]
