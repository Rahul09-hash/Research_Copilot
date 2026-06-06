from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_stream(stream: BinaryIO) -> str:
    position = stream.tell() if stream.seekable() else None
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    if position is not None:
        stream.seek(position)
    return digest.hexdigest()
