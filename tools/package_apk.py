#!/usr/bin/env python3
"""Build the universal RustGL renderer plugin APK, plus the non-APK distributions.

Inputs (all produced by .github/workflows/android.yml):

    artifacts/rustgl/<abi>/librust_gl.so   cross-built with cargo-ndk, one per ABI

Outputs (written to --output, default artifacts/release):

    rustgl-universal-<version>.apk   one APK, four ABIs, three plugin contracts
    rustgl-gurkha-<abi>.zip          the bare library + build metadata, per ABI
    rustgl-local-import.zip          Zalith/Gurkha "local renderer plugin" import
    SHA256SUMS, build-info.json

The APK is assembled without Gradle: aapt2 links the manifest and the string
resources, javac + d8 build classes.dex from the single information Activity,
the native libraries are zipped in, and zipalign + apksigner finish it. Every
tool comes from the Android SDK passed with --sdk (or $ANDROID_HOME).

Signing: set APK_KEYSTORE_BASE64 (+ APK_KEYSTORE_PASSWORD, APK_KEY_ALIAS) to
sign with a persistent key. Without them an ephemeral key is generated for this
build only; installing a later build signed differently then requires
uninstalling the plugin first. The plugin holds no data of its own, so that
only drops the renderer selection, never a launcher or Minecraft data.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "android-plugin"
PLUGIN_RES = PLUGIN / "res"
MANIFEST = PLUGIN / "AndroidManifest.xml"
CONFIG = PLUGIN / "renderer-config.json"
JAVA_SOURCE = PLUGIN / "java"
DOCS = ROOT / "docs"
TOOLS = ROOT / "tools"

ABIS = {
    "arm64-v8a": (2, 183),   # ELFCLASS64, EM_AARCH64
    "armeabi-v7a": (1, 40),  # ELFCLASS32, EM_ARM
    "x86": (1, 3),           # ELFCLASS32, EM_386
    "x86_64": (2, 62),       # ELFCLASS64, EM_X86_64
}

TITLES = {
    "rustgl_spoof_title": "Report OpenGL 4.5 core to the game (needed by most mods)",
    "rustgl_debug_title": "RustGL draw diagnostics (slow)",
    "rustgl_trace_title": "Trace every GL call (very slow, log only)",
    "rustgl_framestats_title": "Log frame-time percentiles (p50/p95/p99, log only)",
}

# Launchers look for this renderer under two names: the one it is built as, and the
# spelling without the underscore, which some of them derive from the plugin's display
# name and then fail on with "librustgl.so missing". Both are the same library, and an APK
# cannot carry a working symlink, so each ABI ships a copy under each name. That costs the
# size of the library again per ABI; it is cheaper than a renderer that will not load.
LIBRARY_NAME = "librust_gl.so"
LIBRARY_ALIASES = ("librust_gl.so", "librustgl.so")

PACKAGE_NAME = "np.com.gurkha.rustgl.plugin"
APP_LABEL = "RustGL (Gurkha build)"
BUILD_METADATA_NAME = "build-info.json"


def run(*command, **kwargs):
    printable = " ".join(str(part) for part in command)
    print(f"+ {printable}")
    subprocess.run([str(part) for part in command], check=True, **kwargs)


def tool(sdk: Path, name: str) -> Path:
    """Find a build-tools binary; prefer the newest installed build-tools."""
    root = sdk / "build-tools"
    if not root.is_dir():
        raise SystemExit(f"No Android build-tools under {root}")
    versions = sorted((p for p in root.iterdir() if p.is_dir()), key=version_key, reverse=True)
    for version in versions:
        candidate = version / name
        if candidate.exists():
            return candidate
    raise SystemExit(f"{name} not found in any build-tools under {root}")


def version_key(path: Path):
    parts = []
    for chunk in path.name.split("."):
        parts.append((0, int(chunk)) if chunk.isdigit() else (1, chunk))
    return parts


def android_jar(sdk: Path, minimum: int = 34) -> Path:
    platforms = sorted(
        (p for p in (sdk / "platforms").iterdir()
         if p.is_dir() and (p / "android.jar").exists()),
        key=version_key,
        reverse=True,
    )
    for platform in platforms:
        number = "".join(ch for ch in platform.name if ch.isdigit())
        if number and int(number) >= minimum:
            return platform / "android.jar"
    raise SystemExit(f"No android.jar for API {minimum}+ under {sdk / 'platforms'}")


def java_home() -> Path:
    """A JDK (not a JRE): javac for the Activity, keytool for the signing key."""
    candidates = []
    if os.environ.get("JAVA_HOME"):
        candidates.append(Path(os.environ["JAVA_HOME"]))
    which = shutil.which("javac")
    if which:
        candidates.append(Path(which).resolve().parent.parent)
    for candidate in candidates:
        if (candidate / "bin" / "javac").exists() and (candidate / "bin" / "keytool").exists():
            return candidate
    raise SystemExit("No JDK with javac and keytool found (set JAVA_HOME)")


def escape_resource_text(text: str) -> str:
    """Escape a string for an Android <string> resource (aapt2 rules)."""
    out = text.replace("\\", "\\\\").replace("&", "&amp;")
    out = out.replace("<", "&lt;").replace(">", "&gt;")
    return out.replace('"', '\\"').replace("'", "\\'")


def write_strings(target: Path, config_json: str, version_name: str) -> None:
    strings = [f'<string name="app_name">{escape_resource_text(APP_LABEL)}</string>',
               f'<string name="config">{escape_resource_text(config_json)}</string>']
    for key, value in TITLES.items():
        strings.append(f'<string name="{key}">{escape_resource_text(value)}</string>')
    strings.append(f'<string name="plugin_version">{escape_resource_text(version_name)}</string>')
    target.mkdir(parents=True, exist_ok=True)
    (target / "values" / "strings.xml").parent.mkdir(parents=True, exist_ok=True)
    (target / "values" / "strings.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    '
        + "\n    ".join(strings)
        + "\n</resources>\n",
        encoding="utf-8",
    )


def verify_elf(path: Path, abi: str) -> None:
    header = path.read_bytes()[:20]
    if len(header) < 20 or header[:4] != b"\x7fELF":
        raise SystemExit(f"{path} is not an ELF file")
    elf_class, machine = ABIS[abi]
    if header[4] != elf_class or header[5] != 1:
        raise SystemExit(f"{path} is not a little-endian ELF{elf_class * 32} library")
    actual = int.from_bytes(header[18:20], "little")
    if actual != machine:
        raise SystemExit(f"{path} is ELF machine {actual}, expected {machine} ({abi})")


def collect_libraries(native_dir: Path):
    libraries = {}
    for abi in ABIS:
        library = native_dir / abi / "librust_gl.so"
        if not library.is_file():
            raise SystemExit(f"Missing {library}; build the renderer for every ABI first")
        verify_elf(library, abi)
        data = library.read_bytes()
        libraries[abi] = {
            "path": library,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
    return libraries


def manifest_versions():
    text = MANIFEST.read_text(encoding="utf-8")
    code = text.split('android:versionCode="', 1)[1].split('"', 1)[0]
    name = text.split('android:versionName="', 1)[1].split('"', 1)[0]
    return int(code), name


def java_modified_utf8(text: str) -> bytes:
    """Encode text the way java.io.DataOutputStream.writeUTF does."""
    out = bytearray()
    for char in text:
        code = ord(char)
        if code == 0:
            out += b"\xc0\x80"
        elif code < 0x80:
            out.append(code)
        elif code < 0x800:
            out += bytes([0xC0 | (code >> 6), 0x80 | (code & 0x3F)])
        elif 0xD800 <= code <= 0xDFFF:
            raise SystemExit("Surrogate code points are not supported in plugin text")
        else:
            out += bytes([0xE0 | (code >> 12), 0x80 | ((code >> 6) & 0x3F), 0x80 | (code & 0x3F)])
    return bytes(out)


def write_local_import(target: Path, build_info: dict) -> None:
    """Zalith/Gurkha local renderer plugin: a folder with `config` and libs/<arch>/."""
    renderer = {
        "pluginVersion": 1,
        "rendererId": "opengles3_rust",
        "rendererDisplayName": APP_LABEL,
        "glName": "librust_gl.so",
        # A leading "/" makes the launcher prepend libs/<arch> of the imported folder.
        "eglName": "/librust_gl.so",
        "boatEnv": {
            "LIBGL_ES": "3",
            "RENDERER_BACKEND": "gles",
            "RENDERER_SPOOF_GL": "1",
        },
        "pojavEnv": {
            "LIBGL_ES": "3",
            "RENDERER_BACKEND": "gles",
            "RENDERER_SPOOF_GL": "1",
            "JAVA_TOOL_OPTIONS": "-Dorg.lwjgl.util.NoChecks=true",
        },
        "dlopenList": [],
    }
    payload = java_modified_utf8(json.dumps(renderer, separators=(",", ":")))
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("config", (len(payload)).to_bytes(2, "big") + payload)
        for abi, info in build_info["libraries"].items():
            for name in LIBRARY_ALIASES:
                archive.write(info["path"], f"libs/{abi}/{name}")
        archive.writestr("README.txt", (DOCS / "UNIVERSAL_APK.md").read_text(encoding="utf-8"))


def write_abi_zips(output: Path, build_info: dict) -> None:
    for abi, info in build_info["libraries"].items():
        target = output / f"rustgl-gurkha-{abi}.zip"
        metadata = {
            "abi": abi,
            "library": LIBRARY_NAME,
            "aliases": list(LIBRARY_ALIASES),
            "sha256": info["sha256"],
            "size": info["size"],
            "version": build_info["versionName"],
            "source": build_info.get("source"),
        }
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in LIBRARY_ALIASES:
                archive.write(info["path"], name)
            archive.writestr("build.json", json.dumps(metadata, indent=2) + "\n")
            archive.writestr("README.txt", (DOCS / "UNIVERSAL_APK.md").read_text(encoding="utf-8"))
            if (ROOT / "NOTICE").exists():
                archive.write(ROOT / "NOTICE", "NOTICE")


def prepare_assets(staging: Path, build_info: dict, config_json: str) -> None:
    assets = staging / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / BUILD_METADATA_NAME).write_text(json.dumps(build_info, indent=2) + "\n")
    (assets / "renderer-config.json").write_text(config_json + "\n")
    (assets / "README.txt").write_text((DOCS / "UNIVERSAL_APK.md").read_text(encoding="utf-8"))
    if (ROOT / "NOTICE").exists():
        shutil.copy2(ROOT / "NOTICE", assets / "NOTICE")
    for abi in ABIS:
        (staging / "lib" / abi).mkdir(parents=True, exist_ok=True)
        for name in LIBRARY_ALIASES:
            shutil.copy2(build_info["libraries"][abi]["path"], staging / "lib" / abi / name)


def keystore(tmp: Path):
    encoded = os.environ.get("APK_KEYSTORE_BASE64")
    password = os.environ.get("APK_KEYSTORE_PASSWORD")
    alias = os.environ.get("APK_KEY_ALIAS")
    if encoded:
        store = tmp / "signing.keystore"
        store.write_bytes(base64.b64decode(encoded))
        if not password or not alias:
            raise SystemExit("APK_KEYSTORE_BASE64 needs APK_KEYSTORE_PASSWORD and APK_KEY_ALIAS")
        return store, password, alias, False
    store = tmp / "ephemeral.p12"
    password = secrets.token_urlsafe(32)
    alias = "rustgl-plugin"
    environment = dict(os.environ, APK_SIGNING_PASSWORD=password)
    run(java_home() / "bin" / "keytool", "-genkeypair", "-keystore", store,
        "-storetype", "PKCS12", "-storepass:env", "APK_SIGNING_PASSWORD", "-alias", alias,
        "-keyalg", "RSA", "-keysize", "3072", "-validity", "3650",
        "-dname", "CN=RustGL Renderer Plugin (Gurkha build)", "-noprompt", env=environment)
    return store, password, alias, True


def align(zipalign: Path, source: Path, target: Path) -> None:
    """16 KB page alignment (Android 15+) when this build-tools supports it."""
    try:
        run(zipalign, "-f", "-P", "16", "4", source, target)
    except subprocess.CalledProcessError:
        print("-P is unsupported by this build-tools, falling back to 4-byte alignment")
        run(zipalign, "-f", "4", source, target)


def check_alignment(zipalign: Path, apk: Path) -> None:
    for extra in (["-P", "16"], []):
        try:
            run(zipalign, "-c", *extra, "4", apk)
            return
        except subprocess.CalledProcessError:
            continue
    raise SystemExit(f"zipalign -c failed for {apk}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--native", type=Path, default=ROOT / "artifacts" / "rustgl",
                        help="directory with <abi>/librust_gl.so")
    parser.add_argument("--sdk", type=Path, default=os.environ.get("ANDROID_HOME"),
                        help="Android SDK root (default: $ANDROID_HOME)")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "release")
    parser.add_argument("--metadata", type=Path,
                        help="optional JSON with native build metadata to embed")
    args = parser.parse_args()
    if not args.sdk:
        parser.error("Android SDK required (--sdk or $ANDROID_HOME)")

    version_code, version_name = manifest_versions()
    config_json = json.dumps(json.loads(CONFIG.read_text(encoding="utf-8")),
                             separators=(",", ":"), ensure_ascii=False)
    libraries = collect_libraries(args.native)

    source = None
    provenance = ROOT / "renderer-source.json"
    if provenance.exists():
        source = json.loads(provenance.read_text(encoding="utf-8"))
    metadata = json.loads(args.metadata.read_text(encoding="utf-8")) if args.metadata else {}
    build_info = {
        "package": PACKAGE_NAME,
        "versionCode": version_code,
        "versionName": version_name,
        "renderedFrom": "android-plugin/AndroidManifest.xml",
        "libraries": {abi: {"sha256": info["sha256"], "size": info["size"], "path": str(info["path"])}
                      for abi, info in libraries.items()},
        "source": source,
        "build": metadata,
    }

    args.output.mkdir(parents=True, exist_ok=True)
    jar = android_jar(args.sdk)
    aapt2 = tool(args.sdk, "aapt2")
    zipalign = tool(args.sdk, "zipalign")
    apksigner = tool(args.sdk, "apksigner")
    d8 = tool(args.sdk, "lib/d8.jar")
    javac = java_home() / "bin" / "javac"
    java = java_home() / "bin" / "java"

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        res = tmp / "res"
        # Committed resources (launcher icon, adaptive icon XML, colours) first,
        # then the generated strings: the v2 renderer config is a string resource.
        if PLUGIN_RES.is_dir():
            shutil.copytree(PLUGIN_RES, res)
        write_strings(res, config_json, version_name)
        compiled = tmp / "compiled-resources.zip"
        run(aapt2, "compile", "--dir", res, "-o", compiled)

        unsigned = tmp / "unsigned.apk"
        run(aapt2, "link", "-I", jar, "--manifest", MANIFEST, "-o", unsigned,
            "--min-sdk-version", "26", "--target-sdk-version", "34",
            "--auto-add-overlay", compiled)

        classes = tmp / "classes"
        classes.mkdir()
        run(javac, "-source", "11", "-target", "11", "-nowarn", "-classpath", jar,
            "-d", classes, JAVA_SOURCE / "np" / "com" / "gurkha" / "rustgl" / "plugin" / "MainActivity.java")
        dex = tmp / "dex"
        dex.mkdir()
        run(java, "-cp", d8, "com.android.tools.r8.D8", "--min-api", "26", "--lib", jar,
            "--output", dex, *sorted(classes.rglob("*.class")))
        produced_dex = dex / "classes.dex"
        if not produced_dex.is_file():
            raise SystemExit("d8 did not produce classes.dex")

        staging = tmp / "staging"
        prepare_assets(staging, build_info, config_json)

        # Assemble: manifest/resources from aapt2, then the dex and the libraries.
        with zipfile.ZipFile(unsigned, "a") as archive:
            archive.write(produced_dex, "classes.dex", zipfile.ZIP_STORED)
            for path in sorted((staging / "lib").rglob("*.so")):
                archive.write(path, path.relative_to(staging), zipfile.ZIP_DEFLATED)
            for path in sorted((staging / "assets").rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(staging), zipfile.ZIP_DEFLATED)

        aligned = tmp / "aligned.apk"
        align(zipalign, unsigned, aligned)

        store, password, alias, ephemeral = keystore(tmp)
        environment = dict(os.environ, APK_SIGNING_PASSWORD=password)
        apk = args.output / f"rustgl-universal-{version_name}.apk"
        run(apksigner, "sign", "--ks", store, "--ks-key-alias", alias,
            "--ks-pass", "env:APK_SIGNING_PASSWORD", "--key-pass", "env:APK_SIGNING_PASSWORD",
            "--out", apk, aligned, env=environment)
        run(apksigner, "verify", "--verbose", "--print-certs", apk)
        check_alignment(zipalign, apk)
        # apksigner leaves <apk>.idsig next to the output: that file is only used
        # for incremental (streamed) installs over adb, never for a normal one.
        idsig = apk.with_suffix(apk.suffix + ".idsig")
        if idsig.exists():
            idsig.unlink()
        run(aapt2, "dump", "badging", apk)

        if ephemeral:
            print("::warning title=Ephemeral signing key::This APK was signed with a "
                  "key generated for this build only; a later build needs the plugin "
                  "uninstalled before it can be installed over this one.")

    build_info["signedWithPersistentKey"] = not ephemeral
    write_abi_zips(args.output, build_info)
    write_local_import(args.output / "rustgl-local-import.zip", build_info)

    files = sorted(p for p in args.output.iterdir() if p.is_file() and p.name != "SHA256SUMS")
    (args.output / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in files))
    (args.output / BUILD_METADATA_NAME).write_text(json.dumps(build_info, indent=2) + "\n")
    print(f"Built {apk}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
