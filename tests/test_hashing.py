from research_copilot.hashing import sha256_bytes, sha256_file


def test_sha256_helpers_match(tmp_path):
    path = tmp_path / "sample.txt"
    data = b"research copilot"
    path.write_bytes(data)

    assert sha256_file(path) == sha256_bytes(data)
