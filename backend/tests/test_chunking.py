from app.services.chunking import chunk_document


def test_chunks_by_page_and_respects_token_limit() -> None:
    text = "[Page 1]\n" + "alpha " * 40 + "\n\n[Page 2]\n" + "beta " * 12

    chunks = chunk_document(
        text,
        model="text-embedding-3-small",
        chunk_size=10,
        overlap=2,
    )

    assert len(chunks) > 2
    assert {chunk.page_number for chunk in chunks} == {1, 2}
    assert all(chunk.token_count <= 10 for chunk in chunks)
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))


def test_rejects_invalid_overlap() -> None:
    try:
        chunk_document("text", "text-embedding-3-small", chunk_size=10, overlap=10)
    except ValueError as exc:
        assert "overlap" in str(exc)
    else:
        raise AssertionError("Expected invalid overlap to fail")
