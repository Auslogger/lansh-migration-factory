"""
Seal and verify the held-out jobs (plan §7.4).

The held-out jobs are written by an isolated agent outside the repo. Sealing packs that
folder into a deterministic archive, ``estate/holdout/holdout.tar.gz`` (sorted entries, zero
timestamps and owners, fixed gzip header), and records its SHA-256 in ``SEAL.json``. The
archive is not opened until the factory freeze (step 3.11); ``verify_seal`` proves it hasn't
changed since. Factory code must never call ``unseal`` or read ``estate/holdout/``.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

from lansh.config import HOLDOUT_DIR

ARCHIVE = "holdout.tar.gz"
SEAL = "SEAL.json"


def pack(folder: Path) -> bytes:
    """
    Pack every regular file in a folder into a byte-reproducible .tar.gz.

    Entries are sorted, with mode 0644, zero mtime and owner ids and empty owner names, and
    the gzip header has no timestamp or file name, so the same files always give the same
    bytes.

    Args:
        folder: Folder to pack; entry names are relative to it.

    Returns:
        The archive's bytes.
    """
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for path in sorted(p for p in folder.rglob("*") if p.is_file()):
            data = path.read_bytes()
            info = tarfile.TarInfo(name=path.relative_to(folder).as_posix())
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0, filename="") as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def seal(folder: Path, out_dir: Path = HOLDOUT_DIR, note: str = "") -> dict:
    """
    Seal a folder into ``out_dir`` and record the archive's SHA-256.

    Args:
        folder: Folder holding the held-out jobs.
        out_dir: Where ``holdout.tar.gz`` and ``SEAL.json`` are written.
        note: Free text kept in the seal record.

    Returns:
        The seal record also written to ``SEAL.json``: archive name, SHA-256, file list,
        sealing time and note.

    Raises:
        FileExistsError: ``out_dir`` already holds a seal, which is never overwritten.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if (out_dir / SEAL).exists():
        raise FileExistsError(f"{out_dir / SEAL} exists: the held-out jobs are already sealed")
    blob = pack(folder)
    (out_dir / ARCHIVE).write_bytes(blob)
    record = {
        "archive": ARCHIVE,
        "sha256": hashlib.sha256(blob).hexdigest(),
        "files": sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()),
        "sealed_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "note": note,
    }
    (out_dir / SEAL).write_text(json.dumps(record, indent=2) + "\n")
    return record


def verify_seal(out_dir: Path = HOLDOUT_DIR) -> bool:
    """
    Check that the archive still has the SHA-256 recorded when it was sealed.

    Args:
        out_dir: Folder holding ``SEAL.json`` and the archive.

    Returns:
        True when the archive is unchanged.
    """
    record = json.loads((out_dir / SEAL).read_text())
    digest = hashlib.sha256((out_dir / record["archive"]).read_bytes()).hexdigest()
    return digest == record["sha256"]


def unseal(dest: Path, out_dir: Path = HOLDOUT_DIR) -> list[str]:
    """
    Extract the held-out jobs, once the seal checks out.

    Only at the factory freeze (step 3.11). Factory code must never call it.

    Args:
        dest: Folder to extract into.
        out_dir: Folder holding ``SEAL.json`` and the archive.

    Returns:
        The names of the extracted entries.

    Raises:
        RuntimeError: The archive no longer matches its seal.
    """
    if not verify_seal(out_dir):
        raise RuntimeError("the held-out archive does not match its seal")
    with tarfile.open(out_dir / ARCHIVE, mode="r:gz") as tar:
        tar.extractall(dest, filter="data")
        return tar.getnames()
