"""Unpack an evidence archive a validator attached, without letting its member paths escape the target folder."""

from __future__ import annotations

import zipfile
from pathlib import Path

from .errors import QaError
from .gitops import safe_name

MAX_UNPACKED_BYTES = 4 * 1024 ** 3


def unpack(archive: Path) -> tuple[Path, int]:
    target = (archive.parent / safe_name(archive.stem)).resolve()
    with zipfile.ZipFile(archive) as bundle:
        members = [m for m in bundle.infolist() if not m.is_dir()]
        if sum(m.file_size for m in members) > MAX_UNPACKED_BYTES:
            raise QaError(f"{archive.name} unpacks to more than 4 GB; open it manually")
        for member in members:
            destination = (target / member.filename).resolve()
            if target not in destination.parents:
                raise QaError(f"{archive.name} contains an unsafe path: {member.filename}")
        bundle.extractall(target)
    return target, len(members)
