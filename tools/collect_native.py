#!/usr/bin/env python3
"""Collect the cross-built librust_gl.so files into artifacts/rustgl/<abi>/.

Run after:
    cd rustgl && cargo ndk -t arm64-v8a -t armeabi-v7a -t x86 -t x86_64 build --release -p gl-compat

Every library is checked (ELF class and machine) before it is accepted, so a
mislabelled or stale build cannot end up in the APK.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from package_apk import ABIS, verify_elf  # noqa: E402

TRIPLES = {
    "arm64-v8a": "aarch64-linux-android",
    "armeabi-v7a": "armv7-linux-androideabi",
    "x86": "i686-linux-android",
    "x86_64": "x86_64-linux-android",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", type=Path, default=Path("rustgl") / "target",
                        help="cargo target directory (default: rustgl/target)")
    parser.add_argument("--output", type=Path, default=Path("artifacts") / "rustgl")
    parser.add_argument("--metadata", type=Path, default=Path("artifacts") / "rustgl.json")
    args = parser.parse_args()

    collected = {}
    for abi, triple in TRIPLES.items():
        source = args.target / triple / "release" / "librust_gl.so"
        if not source.is_file():
            raise SystemExit(f"Missing {source}; run the cargo-ndk build first")
        verify_elf(source, abi)
        destination = args.output / abi / "librust_gl.so"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        data = destination.read_bytes()
        collected[abi] = {
            "triple": triple,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
        print(f"{abi}: {destination} ({len(data) / 1024:.0f} KiB)")

    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.write_text(json.dumps({"libraries": collected}, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
