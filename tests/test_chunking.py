from research_copilot.chunking import chunks_from_pages, recursive_split


def test_recursive_split_respects_target_size():
    text = " ".join(f"Sentence {index} explains local research retrieval." for index in range(120))
    chunks = recursive_split(text, chunk_size=160, overlap=30)

    assert len(chunks) > 1
    assert all(len(chunk) <= 160 for chunk in chunks)
    assert all(chunk.strip() == chunk for chunk in chunks)


def test_chunks_from_pages_keeps_page_numbers():
    chunks = chunks_from_pages([(3, "Alpha beta gamma. " * 20)], chunk_size=80, overlap=10)

    assert chunks
    assert {chunk.page_start for chunk in chunks} == {3}
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
