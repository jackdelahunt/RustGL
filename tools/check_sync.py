#!/usr/bin/env python3
"""Check rustgl/ against the renderer source it was copied from.

The renderer in this repository is synced from the Gurkha Launcher repository
(directory rustgl/ there). renderer-source.json records the exact Git tree hash
of that directory, so `python3 tools/check_sync.py` proves the local copy has
not been modified - without needing network access.

This repository carries a small number of local changes on top of that source
(performance work on the GL shim). Those are listed in renderer-source.json as
`localChanges`, each with the upstream blob id of the file it replaces, and the
check still proves the rest: substituting the recorded upstream blobs back into
the tree must reproduce the recorded hash exactly. That is, every file other
than the documented ones is byte-identical to upstream, and no file was added
or removed.

The hash is a Git tree object id computed the way Git computes it: recursively,
from the mode, name and blob id of every file (only text files are synced, all
of them mode 100644).
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Dict, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "rustgl"
RECORD = ROOT / "renderer-source.json"

SKIP = {".git", "target", ".cargo-ok"}


def blob_hash(data: bytes) -> bytes:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\x00" + data).digest()


def tree_hash(directory: Path, overrides: Optional[Mapping[str, str]] = None,
              prefix: str = "") -> str:
    """Hash `directory` the way Git would, substituting recorded blobs for `overrides`.

    `overrides` maps a path relative to the hashed root to the blob id that should be
    used for it, which is how a documented local change is undone for the comparison.
    """
    overrides = overrides or {}
    entries = []
    for child in directory.iterdir():
        if child.name in SKIP:
            continue
        key = f"{prefix}{child.name}"
        if child.is_dir():
            entries.append((b"40000", child.name, tree_hash(child, overrides, f"{key}/")))
        else:
            mode = b"100755" if child.stat().st_mode & 0o111 else b"100644"
            digest = overrides.get(key) or blob_hash(child.read_bytes()).hex()
            entries.append((mode, child.name, digest))
    # Git sorts tree entries by name, comparing directories as if they ended in "/".
    entries.sort(key=lambda item: (item[1] + "/" if item[0] == b"40000" else item[1]).encode())
    payload = b"".join(mode + b" " + name.encode() + b"\x00" + bytes.fromhex(digest)
                       for mode, name, digest in entries)
    header = b"tree " + str(len(payload)).encode() + b"\x00"
    return hashlib.sha1(header + payload).hexdigest()


def local_changes(record: Mapping[str, object]) -> Dict[str, dict]:
    """The documented local changes, keyed by path relative to rustgl/."""
    changes = record.get("localChanges") or []
    return {str(entry["path"]): entry for entry in changes}


def verify(record: Mapping[str, object]) -> tuple[bool, list[str]]:
    """Check rustgl/ against the recorded upstream source. Returns (ok, report)."""
    lines = []
    actual = tree_hash(SOURCE_DIR)
    expected = record["treeHash"]
    lines.append(f"rustgl/ tree:   {actual}")
    lines.append(f"recorded tree:  {expected}  ({record['repository']} {record['commit']})")
    if actual == expected:
        lines.append("OK: rustgl/ is byte-identical to the recorded renderer source")
        changes = local_changes(record)
        if changes:
            lines.append("ERROR: renderer-source.json lists local changes but the tree is "
                         "unchanged - the entries are stale")
            return False, lines
        return True, lines

    changes = local_changes(record)
    if not changes:
        lines.append("ERROR: rustgl/ differs from the recorded source and no local changes "
                     "are documented in renderer-source.json.")
        lines.append(f"Re-sync it from {record['repository']} ({record['branch']}), or "
                     "document the change.")
        return False, lines

    # Undo every documented change (put the recorded upstream blobs back) and compare.
    restored = tree_hash(SOURCE_DIR, {path: entry["upstreamBlob"]
                                      for path, entry in changes.items()})
    if restored != expected:
        lines.append("tree with the documented changes reverted:")
        lines.append(f"  {restored}")
        lines.append("ERROR: rustgl/ differs from the recorded source in ways that are not "
                     "documented in renderer-source.json.")
        return False, lines

    for path, entry in changes.items():
        target = SOURCE_DIR / path
        if not target.is_file():
            lines.append(f"ERROR: documented change {path} does not exist in rustgl/")
            return False, lines
        if blob_hash(target.read_bytes()).hex() == entry["upstreamBlob"]:
            lines.append(f"ERROR: {path} is listed as a local change but matches upstream - "
                         "remove the stale entry")
            return False, lines
        lines.append(f"  {path}: {entry.get('summary', 'local change')}")
    lines.append(f"OK: rustgl/ = the recorded renderer source + {len(changes)} documented "
                 "local change(s); every other file is byte-identical")
    return True, lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true",
                        help="print the current tree hash instead of checking it")
    args = parser.parse_args()

    if args.record:
        print(tree_hash(SOURCE_DIR))
        return 0

    record = json.loads(RECORD.read_text(encoding="utf-8"))
    ok, report = verify(record)
    print("\n".join(report))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
