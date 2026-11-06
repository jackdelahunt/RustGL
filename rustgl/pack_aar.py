#!/usr/bin/env python3
"""Pack the cross-built librust_gl.so files into ZalithLauncher/libs/rustgl-release.aar.

Run this from anywhere after:
    cd rustgl && cargo ndk -t arm64-v8a -t armeabi-v7a -t x86 -t x86_64 build --release -p gl-compat

The AAR layout is the same minimal shape as ng_gl4es-release.aar: a manifest, an empty
classes.jar, an empty R.txt, AGP aar metadata, and jni/<abi>/librust_gl.so for every ABI.
"""

import io
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT)
OUT = os.path.join(REPO, "ZalithLauncher", "libs", "rustgl-release.aar")

TARGETS = {
    "arm64-v8a": "aarch64-linux-android",
    "armeabi-v7a": "armv7-linux-androideabi",
    "x86": "i686-linux-android",
    "x86_64": "x86_64-linux-android",
}

MANIFEST = (
    b'<?xml version="1.0" encoding="utf-8"?>\n'
    b'<manifest xmlns:android="http://schemas.android.com/apk/res/android"\n'
    b'    package="com.gurkha.rustgl" />\n'
)
AAR_METADATA = (
    b"aarFormatVersion=1.0\n"
    b"aarMetadataVersion=1.0\n"
    b"minCompileSdk=1\n"
    b"minCompileSdkExtension=0\n"
    b"minAndroidGradlePluginVersion=1.0.0\n"
)


def classes_jar() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as jar:
        jar.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
    return buf.getvalue()


def main() -> int:
    libs = {}
    for abi, triple in TARGETS.items():
        path = os.path.join(ROOT, "target", triple, "release", "librust_gl.so")
        if not os.path.isfile(path):
            print(f"::error title=RustGL build missing::{path} not found; run the cargo-ndk build first")
            return 1
        libs[abi] = path

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as out:
        out.writestr("AndroidManifest.xml", MANIFEST)
        out.writestr("classes.jar", classes_jar())
        out.writestr("R.txt", b"")
        out.writestr("META-INF/com/android/build/gradle/aar-metadata.properties", AAR_METADATA)
        for abi, path in libs.items():
            out.write(path, f"jni/{abi}/librust_gl.so")

    size = os.path.getsize(OUT)
    print(f"wrote {OUT} ({size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
