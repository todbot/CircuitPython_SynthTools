# SPDX-FileCopyrightText: Copyright (c) 2026 Tod Kurt
# SPDX-License-Identifier: MIT
#
# wavhdr.py -- 44-byte canonical PCM WAV read/write, stdlib `struct` only, so
# the same code runs under the CircuitPython unix build (render side, no `wave`
# module) and desktop CPython (analysis side).

import struct


def write_wav(path, pcm, sample_rate, channel_count, bits=16):
    """pcm: bytes/bytearray of interleaved little-endian signed samples."""
    byte_rate = sample_rate * channel_count * (bits // 8)
    block_align = channel_count * (bits // 8)
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + len(pcm)))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, channel_count, sample_rate,
                            byte_rate, block_align, bits))
        f.write(b"data")
        f.write(struct.pack("<I", len(pcm)))
        f.write(pcm)


def read_wav(path):
    """-> (pcm_bytes, sample_rate, channel_count, bits). Skips unknown chunks."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a WAV: %s" % path)
    pos = 12
    sample_rate = channel_count = bits = None
    pcm = b""
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            _, channel_count, sample_rate, _, _, bits = struct.unpack_from(
                "<HHIIHH", body, 0)
        elif cid == b"data":
            pcm = body
        pos += 8 + size + (size & 1)
    if sample_rate is None or not pcm:
        raise ValueError("missing fmt/data chunk: %s" % path)
    return pcm, sample_rate, channel_count, bits
