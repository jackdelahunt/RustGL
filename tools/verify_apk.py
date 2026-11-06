#!/usr/bin/env python3
"""Verify a built RustGL universal plugin APK against the launcher contracts.

Checks, in order:

 1. the zip layout (dex, manifest, resource table, one library per ABI, assets);
 2. every packaged library is an ELF of the ABI it ships under;
 3. `apksigner verify` passes and `aapt2 dump badging` reports the expected
    package, version, SDK range, label and launchable activity;
 4. the binary AndroidManifest.xml carries both plugin contracts:
      v2: `fclPlugin_V2` -> string resource with the renderer JSON
      v1: `fclPlugin` / `zalithRendererPlugin`, `renderer`, `des`, `pojavEnv`,
          `boatEnv`
    and no permissions;
 5. the v2 renderer JSON that is really inside the resource table parses and has
    the shape Zalith Launcher 2 and FCL expect;
 6. the v1 `renderer` value is "<id>:<gl>:<egl>" with an EGL name that a launcher
    can resolve (bare name or one starting with "/"), and no v1 environment
    value contains "=" (Zalith's v1 parser truncates at the second "=").
"""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
from package_apk import LIBRARY_NAME  # noqa: E402

ABIS = {
    "arm64-v8a": (2, 183),
    "armeabi-v7a": (1, 40),
    "x86": (1, 3),
    "x86_64": (2, 62),
}
# v2 marker, then every v1 marker seen in the launchers that read this contract:
# fclPlugin (FCL, Zalith/Gurkha, NuxLauncher...), zalithRendererPlugin (Zalith
# forks), pgwRendererPlugin (Pojav Glow.Worm lineage), h2co3LauncherPlugin
# (H2CO3/Boat). H2CO3 also needs its own env, and several readers require the
# version-range keys to exist even when they are empty.
REQUIRED_META = ["fclPlugin_V2", "fclPlugin", "zalithRendererPlugin",
                 "pgwRendererPlugin", "h2co3LauncherPlugin",
                 "renderer", "des", "pojavEnv", "boatEnv", "h2co3Env"]
OPTIONAL_META = ["minMCVer", "maxMCVer"]
DISCOVERY_ACTION = "android.intent.action.MAIN"


def run(*command) -> str:
    return subprocess.run([str(part) for part in command], check=True,
                          capture_output=True, text=True).stdout


def tool(sdk: Path, name: str, preferred: str = "35.0.0") -> Path:
    """Prefer a known-good build-tools version, otherwise the newest one."""
    root = sdk / "build-tools"
    versions = sorted((p for p in root.iterdir() if p.is_dir()),
                      key=lambda p: [int(c) if c.isdigit() else c for c in p.name.split(".")],
                      reverse=True)
    order = [p for p in versions if p.name == preferred] + \
            [p for p in versions if p.name != preferred]
    for version in order:
        candidate = version / name
        if candidate.exists():
            return candidate
    raise SystemExit(f"{name} not found under {root}")


def extract_json(text: str, marker: str = '{"displayName"') -> dict:
    start = text.find(marker)
    if start < 0:
        raise LookupError("renderer JSON not found")
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:index + 1])
    raise LookupError("unterminated renderer JSON")


PT_LOAD = 1
PAGE_16K = 16384


def load_segment_alignments(blob: bytes):
    """The `p_align`, `p_offset` and `p_vaddr` of every PT_LOAD segment.

    Android 15+ devices use 16 KB pages. The dynamic linker mmaps each PT_LOAD
    segment, so every one has to be aligned to at least 16 KB, and its file offset
    and virtual address have to be congruent modulo that alignment. The offset
    itself does *not* have to be a multiple of 16 KB - the linker maps the
    containing page and skips the slack. A bad segment surfaces as a crash the first
    time the game touches the renderer, not as an error anyone reads.
    """
    if blob[:4] != b"\x7fELF":
        return []
    elf_class = blob[4]
    if elf_class == 2:  # 64-bit
        e_phoff = int.from_bytes(blob[0x20:0x28], "little")
        e_phentsize = int.from_bytes(blob[0x36:0x38], "little")
        e_phnum = int.from_bytes(blob[0x38:0x3A], "little")
        layout = {"type": (0, 4), "offset": (8, 8), "vaddr": (16, 8), "align": (48, 8)}
    elif elf_class == 1:  # 32-bit
        e_phoff = int.from_bytes(blob[0x1C:0x20], "little")
        e_phentsize = int.from_bytes(blob[0x2A:0x2C], "little")
        e_phnum = int.from_bytes(blob[0x2C:0x2E], "little")
        layout = {"type": (0, 4), "offset": (4, 4), "vaddr": (8, 4), "align": (28, 4)}
    else:
        return []

    def field(header, name):
        start, size = layout[name]
        return int.from_bytes(header[start:start + size], "little")

    segments = []
    for i in range(e_phnum):
        at = e_phoff + i * e_phentsize
        header = blob[at:at + e_phentsize]
        if len(header) < e_phentsize:
            break
        if field(header, "type") != PT_LOAD:
            continue
        segments.append((field(header, "align"), field(header, "offset"), field(header, "vaddr")))
    return segments


def check_page_alignment(entry: str, blob: bytes) -> None:
    segments = load_segment_alignments(blob)
    if not segments:
        raise SystemExit(f"{entry} has no PT_LOAD segments to check")
    table = ", ".join(
        f"[align 0x{align:x} offset 0x{offset:x} vaddr 0x{vaddr:x}]" for align, offset, vaddr in segments
    )
    for align, offset, vaddr in segments:
        if align < PAGE_16K:
            raise SystemExit(
                f"{entry}: a PT_LOAD segment is aligned to 0x{align:x}, not 16 KB - this "
                "library cannot load on an Android 15+ 16 KB-page device. Segments: " + table
            )
        if (vaddr - offset) % PAGE_16K != 0:
            raise SystemExit(
                f"{entry}: a PT_LOAD segment sits at file offset 0x{offset:x} but asks to "
                f"be mapped at 0x{vaddr:x}; the two differ by 0x{(vaddr - offset) % PAGE_16K:x} "
                f"modulo 16 KB, so the linker cannot map the page it reads onto the "
                "address the segment asks for. Segments: " + table
            )


def check_layout(apk: Path) -> None:
    with zipfile.ZipFile(apk) as archive:
        names = set(archive.namelist())
        for required in ["classes.dex", "AndroidManifest.xml", "resources.arsc",
                         "assets/build-info.json", "assets/README.txt"]:
            if required not in names:
                raise SystemExit(f"{apk.name} is missing {required}")
        for abi, (elf_class, machine) in ABIS.items():
            # The library has to be there under the name launchers actually load.
            entry = f"lib/{abi}/{LIBRARY_NAME}"
            if entry not in names:
                raise SystemExit(f"{apk.name} is missing {entry}")
            blob = archive.read(entry)
            header = blob[:20]
            if header[:4] != b"\x7fELF":
                raise SystemExit(f"{entry} is not an ELF file")
            if header[4] != elf_class or header[5] != 1:
                raise SystemExit(f"{entry} is not a little-endian ELF{elf_class * 32}")
            actual = int.from_bytes(header[18:20], "little")
            if actual != machine:
                raise SystemExit(f"{entry} is ELF machine {actual}, expected {machine} ({abi})")
            check_page_alignment(entry, blob)
        print(f"layout OK: {len(names)} entries, four ABIs, "
              f"{LIBRARY_NAME} in each, 16 KB page alignment, assets present")


def check_badging(aapt2: Path, apk: Path, expected_version: str) -> None:
    badging = run(aapt2, "dump", "badging", apk)
    needed = [
        "package: name='np.com.gurkha.rustgl.plugin'",
        f"versionName='{expected_version}'",
        "targetSdkVersion:'34'",
        "launchable-activity: name='np.com.gurkha.rustgl.plugin.MainActivity'",
        "application-label:'RustGL (Gurkha build)'",
    ]
    for needle in needed:
        if needle not in badging:
            raise SystemExit(f"aapt2 badging is missing {needle!r}\n{badging}")
    # aapt2 of build-tools 37 renamed sdkVersion to minSdkVersion in this output.
    if "sdkVersion:'26'" not in badging and "minSdkVersion:'26'" not in badging:
        raise SystemExit(f"aapt2 badging does not report minSdkVersion 26\n{badging}")
    if "uses-permission:" in badging:
        raise SystemExit(f"The plugin must not request permissions:\n{badging}")
    if "application-icon-" not in badging:
        raise SystemExit(f"The plugin has no launcher icon:\n{badging}")
    print("badging OK: package, version, SDK range, label, launchable activity")


ATTRIBUTE = re.compile(r"A: (\S+)\(0x[0-9a-fA-F]+\)=(.*)")


def attribute_name(raw: str) -> str:
    """aapt2 prints either `android:name` or the full `http://.../android:name`."""
    return raw.split("/")[-1]


def attribute_value(raw: str):
    """aapt2 prints ="text" (Raw: "text"), =true/false, =26 and =@0x7f040000."""
    raw = raw.strip()
    if raw.startswith('"'):
        return raw[1:raw.index('"', 1)]
    if raw.startswith("@0x"):
        return "@resource"
    return raw


def parse_meta_data(xml: str) -> dict:
    """Read the <meta-data> entries out of `aapt2 dump xmltree`.

    aapt2 prints one attribute per line right after its element, e.g.

        E: meta-data (line=40)
          A: android:name(0x01010003)="fclPlugin" (Raw: "fclPlugin")
          A: android:value(0x01010024)="true" (Raw: "true")
    """
    lines = xml.splitlines()
    attributes = []
    for line in lines:
        match = ATTRIBUTE.search(line)
        attributes.append((attribute_name(match.group(1)), attribute_value(match.group(2)))
                          if match else None)
    meta = {}
    for index, line in enumerate(lines):
        match = ATTRIBUTE.search(line)
        if not match or attribute_name(match.group(1)) != "android:name":
            continue
        key = attribute_value(match.group(2))
        for offset in (1, 2, -1, -2):
            position = index + offset
            if not 0 <= position < len(attributes) or attributes[position] is None:
                continue
            name, value = attributes[position]
            if name in ("android:value", "android:resource"):
                meta[key] = value
                break
    return meta


def check_manifest(aapt2: Path, apk: Path) -> dict:
    xml = run(aapt2, "dump", "xmltree", apk, "--file", "AndroidManifest.xml")
    meta = parse_meta_data(xml)
    missing = [key for key in REQUIRED_META if key not in meta]
    if missing:
        raise SystemExit(f"manifest is missing meta-data {missing}\n{xml}")
    for marker in ("fclPlugin", "zalithRendererPlugin", "pgwRendererPlugin",
                   "h2co3LauncherPlugin"):
        if meta[marker] != "true":
            raise SystemExit(f"{marker} must be true: {meta}")
    if not meta["fclPlugin_V2"].startswith("@") and not meta["fclPlugin_V2"].isdigit():
        raise SystemExit(f"fclPlugin_V2 must be a resource reference, got {meta['fclPlugin_V2']}")

    parts = meta["renderer"].split(":")
    if len(parts) != 3:
        raise SystemExit(f"renderer must be <id>:<gl>:<egl>, got {meta['renderer']!r}")
    renderer_id, gl_name, egl_name = parts
    if renderer_id != "opengles3":
        raise SystemExit(f"unexpected v1 renderer id {renderer_id!r}: launchers derive "
                         "context hints from it, so it must be the id they know")
    # The name here has to be the one launchers load, which is what ships.
    if gl_name != LIBRARY_NAME:
        raise SystemExit(f"unexpected v1 GL library {gl_name!r}, expected {LIBRARY_NAME}")
    if not egl_name.startswith("/") and egl_name.lstrip("/") != LIBRARY_NAME:
        raise SystemExit(f"v1 EGL library {egl_name!r} cannot be resolved by a launcher")

    for key in ("pojavEnv", "boatEnv", "h2co3Env"):
        for item in meta[key].split(":"):
            if "=" not in item:
                raise SystemExit(f"{key} entry {item!r} has no '='")
            name, value = item.split("=", 1)
            if "=" in value:
                raise SystemExit(f"{key} value {item!r} contains a second '=': "
                                 "Zalith's v1 parser truncates it")
            if ":" in value:
                raise SystemExit(f"{key} value {item!r} contains ':': it would be split")

    if DISCOVERY_ACTION not in xml:
        raise SystemExit("the manifest must declare an ACTION_MAIN activity: FCL and "
                         "Zalith Launcher 2 find plugins with queryIntentActivities")
    if not re.search(r":exported\(0x[0-9a-fA-F]+\)=true", xml):
        raise SystemExit("the discovery activity must be exported")
    if re.search(r"E: uses-permission", xml):
        raise SystemExit("the plugin must not request permissions")
    print("manifest OK: v2 + v1 contracts, no permissions, ACTION_MAIN activity")
    return meta


def shipped_config(apk: Path, aapt2: Path) -> dict:
    """Parse the renderer JSON that is really inside resources.arsc."""
    with zipfile.ZipFile(apk) as archive:
        arsc = archive.read("resources.arsc")
    try:
        return extract_json(arsc.decode("utf-16-le", errors="ignore"))
    except LookupError:
        pass
    try:
        return extract_json(arsc.decode("utf-8", errors="ignore"))
    except LookupError:
        pass
    dumped = run(aapt2, "dump", "strings", apk)
    try:
        return extract_json(dumped.replace('\\"', '"'))
    except LookupError as error:
        raise SystemExit("the v2 renderer JSON is not in the APK resource table") from error


def check_config(config: dict, meta: dict) -> None:
    for key in ("displayName", "rendererId", "rendererGLPath", "rendererEGLPath",
                "dlopenLibPaths", "env", "minMCVer", "maxMCVer"):
        if key not in config:
            raise SystemExit(f"renderer config is missing {key!r}")
    if config["rendererId"] != "opengles3":
        raise SystemExit(f"unexpected rendererId {config['rendererId']!r}: launchers "
                         "derive context hints from it, so it must be the id they know")
    if config["rendererGLPath"] != "**|librust_gl.so":
        raise SystemExit("rendererGLPath must use the **| plugin-path prefix")
    if not config["rendererEGLPath"].endswith("librust_gl.so"):
        raise SystemExit("rendererEGLPath must point at librust_gl.so (it re-exports EGL)")
    # MobileGL, the plugin that runs in the widest set of launchers, resolves both
    # libraries through the **| prefix so the launcher never has to guess a path.
    if not config["rendererEGLPath"].startswith("**|"):
        raise SystemExit("rendererEGLPath must use the **| plugin-path prefix too")

    env_keys = set()
    for entry in config["env"]:
        kind = entry.get("type")
        if kind not in ("NormalEnv", "SelectableEnv", "CustomizableEnv", "ToggleableEnv"):
            raise SystemExit(f"unknown env type {kind!r}")
        env_keys.add(entry.get("key"))
        if kind == "SelectableEnv":
            items = entry["items"]
            if items["defaultValue"] not in items["values"]:
                raise SystemExit(f"{entry['key']}: defaultValue is not one of values")
            title = entry.get("title", {}).get("key")
            if title and title not in meta:
                raise SystemExit(f"env title {title!r} has no meta-data entry")
    for required in ("LIBGL_ES", "RENDERER_BACKEND", "RENDERER_SPOOF_GL"):
        if required not in env_keys:
            raise SystemExit(f"renderer config is missing the {required} environment variable")
    if config["env"][0]["type"] != "NormalEnv" or config["env"][0]["key"] != "LIBGL_ES":
        raise SystemExit("LIBGL_ES=3 must be a fixed (NormalEnv) environment variable")
    print(f"v2 config OK: {len(config['env'])} environment variables, "
          f"rendererId {config['rendererId']}")


def check_signature(apksigner: Path, apk: Path) -> None:
    output = run(apksigner, "verify", "--verbose", "--print-certs", apk)
    if "Verifies" not in output:
        raise SystemExit(f"apksigner did not verify {apk}\n{output}")
    print("signature OK")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("apk", type=Path)
    parser.add_argument("--sdk", type=Path, default=os.environ.get("ANDROID_HOME"))
    parser.add_argument("--expect-version", default=None,
                        help="expected versionName (default: taken from build-info.json in the APK)")
    args = parser.parse_args()
    if not args.sdk:
        parser.error("Android SDK required (--sdk or $ANDROID_HOME)")

    check_layout(args.apk)
    aapt2 = tool(args.sdk, "aapt2")
    apksigner = tool(args.sdk, "apksigner")

    expected = args.expect_version
    if expected is None:
        with zipfile.ZipFile(args.apk) as archive:
            info = json.loads(archive.read("assets/build-info.json"))
        expected = info["versionName"]
    check_badging(aapt2, args.apk, expected)
    meta = check_manifest(aapt2, args.apk)
    check_config(shipped_config(args.apk, aapt2), meta)
    check_signature(apksigner, args.apk)
    print(f"OK: {args.apk}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
