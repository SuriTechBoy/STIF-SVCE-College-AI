from ingestion.run_ingestion import clean_text, split_chunks


def test_clean_text_removes_excess_whitespace():
    assert clean_text(" Hello   world \n\n\n college ") == "Hello world \n\n college"


def test_split_chunks_returns_text():
    text = "SVCE college information. " * 100
    chunks = split_chunks(text, size=250, overlap=30)
    assert len(chunks) > 1
    assert all(chunk.strip() for chunk in chunks)
