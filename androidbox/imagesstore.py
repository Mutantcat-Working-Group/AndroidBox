"""Carry the bundled Android image disk on the tail of a Windows installer.

makensis cannot mmap a datablock that grew past its 16 MiB threshold, so the
guest image disk never enters the NSIS database. The installer itself stays
byte-for-byte the payload makensis was proven to compile, and the disk rides
behind it: an LZMA-compressed copy followed by a small trailer. NSIS locates
its own data by scanning forward from the start of the file and stops at its
CRC, so anything appended after that is invisible to it - the client
materializes the disk on first boot instead.
"""

import lzma
import os
from pathlib import Path
import struct


MAGIC = b"ANDBOX01"
TRAILER = struct.Struct("<8sQQ")
CHUNK = 1 << 20


def append(installer, raw):
    """Attach a compressed copy of the guest image disk to a finished installer."""
    installer, raw = Path(installer), Path(raw)
    if not installer.is_file():
        raise ValueError(f"Installer does not exist: {installer}")
    raw_size = raw.stat().st_size
    if raw_size <= 0:
        raise ValueError(f"Android image disk is empty: {raw}")
    compressor = lzma.LZMACompressor(format=lzma.FORMAT_XZ)
    written = 0
    with installer.open("ab") as sink, raw.open("rb") as source:
        while True:
            chunk = source.read(CHUNK)
            if not chunk:
                break
            block = compressor.compress(chunk)
            if block:
                sink.write(block)
                written += len(block)
        block = compressor.flush()
        sink.write(block)
        written += len(block)
        sink.write(TRAILER.pack(MAGIC, written, raw_size))
    return installer


def locate(installer):
    """Return (offset, compressed length, raw length) of an attached disk, if any."""
    installer = Path(installer)
    size = installer.stat().st_size
    if size < TRAILER.size:
        return None
    with installer.open("rb") as stream:
        stream.seek(size - TRAILER.size)
        magic, length, raw_size = TRAILER.unpack(stream.read(TRAILER.size))
    if magic != MAGIC or length <= 0 or raw_size <= 0 or TRAILER.size + length > size:
        return None
    return size - TRAILER.size - length, length, raw_size


def extract(installer, target, progress=None):
    """Expand an attached image disk, replacing the target only when it is whole."""
    located = locate(installer)
    if located is None:
        raise ValueError(f"{installer} carries no bundled Android image disk")
    start, length, raw_size = located
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    decompressor = lzma.LZMADecompressor(format=lzma.FORMAT_AUTO)
    received = 0
    try:
        with Path(installer).open("rb") as source, partial.open("wb") as sink:
            source.seek(start)
            remaining = length
            while remaining > 0:
                chunk = source.read(min(CHUNK, remaining))
                if not chunk:
                    raise ValueError(f"Truncated image disk in {installer}")
                remaining -= len(chunk)
                block = decompressor.decompress(chunk)
                if block:
                    sink.write(block)
                    received += len(block)
                    if progress is not None:
                        progress(received, raw_size)
        if not decompressor.eof or received != raw_size:
            raise ValueError(f"Corrupt image disk in {installer}")
        os.replace(partial, target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return target
