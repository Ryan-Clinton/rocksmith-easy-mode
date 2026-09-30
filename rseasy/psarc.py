"""Read and write Rocksmith 2014 .psarc archives.

A psarc is an AES-256-CFB encrypted table of contents followed by zlib
blocks. Entry 0 is a newline-separated manifest naming entries 1..n.

Only what the patcher needs is implemented: read every entry, swap one of
them, write the archive back. Rebuilds are verified by reading the result
and comparing every payload before anything touches the live file.
"""
import hashlib
import struct
import zlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ARC_KEY = bytes.fromhex(
    "C53DB23870A1A2F71CAE64061FDD0E1157309DC85204D4C5BFDF25090DF2572C")
BLOCK = 65536


def cfb(key, data, encrypt=False):
    """AES-256-CFB with full 16-byte block feedback and a zero IV."""
    c = Cipher(algorithms.AES(key), modes.CFB(b"\x00" * 16))
    op = c.encryptor() if encrypt else c.decryptor()
    pad = (-len(data)) % 16
    out = op.update(data + b"\x00" * pad) + op.finalize()
    return out[:len(data)]


def read(path):
    """Return (raw_bytes, header_dict) for the archive at *path*."""
    with open(path, "rb") as fh:
        raw = fh.read()
    magic, ver, comp, toc_size, tes, n, block_alloc, flags = struct.unpack(
        ">4sI4sIIIII", raw[:32])
    if magic != b"PSAR":
        raise ValueError("%s is not a psarc (magic %r)" % (path, magic))
    toc = raw[32:toc_size]
    if flags & 4:
        toc = cfb(ARC_KEY, toc)
    entries = []
    for i in range(n):
        e = toc[i * tes:(i + 1) * tes]
        entries.append({
            "md5": e[0:16],
            "zbegin": struct.unpack(">I", e[16:20])[0],
            "len": int.from_bytes(e[20:25], "big"),
            "ofs": int.from_bytes(e[25:30], "big"),
        })
    bs_bytes = {0x100: 1, 0x10000: 2, 0x1000000: 3, 0x100000000: 4}[block_alloc]
    rest = toc[n * tes:]
    blocks = [int.from_bytes(rest[i * bs_bytes:(i + 1) * bs_bytes], "big")
              for i in range(len(rest) // bs_bytes)]
    return raw, {"ver": ver, "comp": comp, "toc_size": toc_size, "tes": tes,
                 "n": n, "block_alloc": block_alloc, "flags": flags,
                 "entries": entries, "blocks": blocks, "bs_bytes": bs_bytes}


def extract(raw, h, idx):
    """Return the decompressed bytes of entry *idx* (0 is the manifest)."""
    e = h["entries"][idx]
    out = bytearray()
    ofs, bi = e["ofs"], e["zbegin"]
    while len(out) < e["len"]:
        bsz = h["blocks"][bi]
        if bsz == 0:
            out += raw[ofs:ofs + h["block_alloc"]]
            ofs += h["block_alloc"]
        else:
            chunk = raw[ofs:ofs + bsz]
            if chunk[:1] == b"\x78":
                try:
                    out += zlib.decompress(chunk)
                except zlib.error:
                    out += chunk
            else:
                out += chunk
            ofs += bsz
        bi += 1
    return bytes(out[:e["len"]])


def read_all(path):
    """Return (names, payloads, manifest_md5) with payloads aligned to names."""
    raw, h = read(path)
    manifest = extract(raw, h, 0)
    names = manifest.decode().split("\n")
    payloads = [extract(raw, h, i + 1) for i in range(len(names))]
    return names, payloads, h["entries"][0]["md5"]


def build(names, payloads, manifest_md5):
    """Serialise a complete archive. Inverse of read_all()."""
    manifest = "\n".join(names).encode()
    everything = [manifest] + list(payloads)
    md5s = [manifest_md5] + [hashlib.md5(n.encode()).digest() for n in names]

    blocks, chunks, entries, cur = [], [], [], 0
    for p in everything:
        zbegin, start = len(blocks), cur
        for i in range(0, max(len(p), 1), BLOCK):
            part = p[i:i + BLOCK]
            if not part and len(p):
                break
            c = zlib.compress(part, 9)
            if len(c) < len(part):
                chunks.append(c)
                blocks.append(len(c))
                cur += len(c)
            else:
                chunks.append(part)
                blocks.append(0 if len(part) == BLOCK else len(part))
                cur += len(part)
        entries.append([zbegin, len(p), start])

    n = len(entries)
    toc_size = 32 + n * 30 + len(blocks) * 2
    toc = b"".join(
        md5 + struct.pack(">I", zbegin) + length.to_bytes(5, "big") +
        (start + toc_size).to_bytes(5, "big")
        for md5, (zbegin, length, start) in zip(md5s, entries))
    toc += b"".join(b.to_bytes(2, "big") for b in blocks)
    hdr = struct.pack(">4sI4sIIIII", b"PSAR", 0x00010004, b"zlib",
                      toc_size, 30, n, BLOCK, 4)
    return hdr + cfb(ARC_KEY, toc, encrypt=True) + b"".join(chunks)


def write_verified(path, names, payloads, manifest_md5):
    """Build, read the result back, compare every payload, then move into place.

    Writes to *path*.new first so a failed verify never leaves a broken
    archive where the game will find it.
    """
    import os
    tmp = str(path) + ".new"
    with open(tmp, "wb") as fh:
        fh.write(build(names, payloads, manifest_md5))
    try:
        raw, h = read(tmp)
        if extract(raw, h, 0).decode().split("\n") != names:
            raise ValueError("manifest mismatch in rebuilt archive")
        for i, want in enumerate(payloads):
            if extract(raw, h, i + 1) != want:
                raise ValueError("payload mismatch: %s" % names[i])
        # Windows refuses this while the game has the archive open.
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise
