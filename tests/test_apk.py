"""Contract tests for the universal RustGL plugin APK.

These run with plain Python 3 (no Android SDK, no Rust toolchain): they check
the committed manifest, the v2 renderer config and the packaging helpers that
must not silently produce an APK a launcher would refuse. Everything that needs
aapt2/apksigner lives in tools/verify_apk.py and runs in CI after the build.
"""

import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import package_apk  # noqa: E402
import verify_apk  # noqa: E402
import check_sync  # noqa: E402
from check_sync import tree_hash  # noqa: E402

ANDROID = "{http://schemas.android.com/apk/res/android}"
MANIFEST = ROOT / "android-plugin" / "AndroidManifest.xml"
CONFIG = ROOT / "android-plugin" / "renderer-config.json"
RECORD = ROOT / "renderer-source.json"
ABIS = ["arm64-v8a", "armeabi-v7a", "x86", "x86_64"]


def meta_data():
    """The <meta-data> entries of the plugin manifest, Android namespace stripped."""
    application = ET.parse(MANIFEST).getroot().find("application")
    entries = {}
    for node in application.findall("meta-data"):
        key = node.get(ANDROID + "name")
        value = node.get(ANDROID + "value")
        resource = node.get(ANDROID + "resource")
        entries[key] = value if value is not None else resource
    return entries


class ManifestTests(unittest.TestCase):
    def test_package_and_version(self):
        root = ET.parse(MANIFEST).getroot()
        self.assertEqual(root.get("package"), "np.com.gurkha.rustgl.plugin")
        self.assertTrue(root.get(ANDROID + "versionCode").isdigit())
        self.assertRegex(root.get(ANDROID + "versionName"), r"^\d+\.\d+\.\d+")

    def test_sdk_range_matches_the_launcher(self):
        uses_sdk = ET.parse(MANIFEST).getroot().find("uses-sdk")
        self.assertEqual(uses_sdk.get(ANDROID + "minSdkVersion"), "26")
        self.assertEqual(uses_sdk.get(ANDROID + "targetSdkVersion"), "34")

    def test_application_flags(self):
        application = ET.parse(MANIFEST).getroot().find("application")
        self.assertEqual(application.get(ANDROID + "extractNativeLibs"), "true",
                         "the launcher dlopens the library from the plugin's nativeLibraryDir")
        self.assertEqual(application.get(ANDROID + "hasCode"), "true",
                         "FCL and Zalith 2 find plugins through an exported MAIN activity")
        self.assertEqual(ET.parse(MANIFEST).getroot().findall("uses-permission"), [])

    def test_discovery_activity(self):
        """FCL and Zalith Launcher 2 use queryIntentActivities(Intent.ACTION_MAIN)."""
        application = ET.parse(MANIFEST).getroot().find("application")
        activities = application.findall("activity")
        self.assertEqual(len(activities), 1)
        activity = activities[0]
        self.assertEqual(activity.get(ANDROID + "exported"), "true")
        self.assertTrue(activity.get(ANDROID + "name").startswith("."))
        actions = [node.get(ANDROID + "name")
                   for node in activity.find("intent-filter").findall("action")]
        self.assertIn("android.intent.action.MAIN", actions)
        source = ROOT / "android-plugin" / "java" / "np" / "com" / "gurkha" / "rustgl" / "plugin"
        self.assertTrue((source / "MainActivity.java").is_file())

    def test_both_plugin_contracts_are_declared(self):
        values = meta_data()
        # v2 (Zalith Launcher 2, FCL): a string resource holding the JSON config.
        self.assertTrue(values["fclPlugin_V2"].startswith("@string/"))
        # v1 markers: one per family of launchers that reads this contract.
        for marker in ("fclPlugin", "zalithRendererPlugin", "pgwRendererPlugin",
                       "h2co3LauncherPlugin"):
            self.assertEqual(values[marker], "true", marker)
            self.assertTrue(marker in verify_apk.REQUIRED_META, marker)
        # Some readers require the version-range keys even when they are empty.
        for key in verify_apk.OPTIONAL_META:
            self.assertIn(key, values)
            self.assertEqual(values[key], "")

    def test_every_v1_launcher_marker_is_verified_in_the_built_apk(self):
        """tools/verify_apk.py is what gates a release: it must not drift."""
        values = meta_data()
        for key in verify_apk.REQUIRED_META:
            self.assertIn(key, values, f"verify_apk requires {key} but the manifest lacks it")

    def test_v1_renderer_triple(self):
        renderer_id, gl_name, egl_name = meta_data()["renderer"].split(":")
        # "opengles3" is the id every launcher understands; MobileGL uses it too.
        self.assertEqual(renderer_id, "opengles3")
        self.assertEqual(gl_name, "librust_gl.so")
        # A leading "/" is what makes every documented v1 launcher prepend the
        # plugin's nativeLibraryDir; a bare name only resolves by luck.
        self.assertTrue(egl_name.startswith("/"))
        self.assertEqual(egl_name.lstrip("/"), "librust_gl.so")

    def test_16kb_page_alignment_is_detected_either_way(self):
        """A synthetic ELF: one PT_LOAD, 64-bit then 32-bit, aligned and misaligned."""

        def elf(elf_class, page_align, offset):
            header_size = 0x40 if elf_class == 2 else 0x34
            phentsize = 0x38 if elf_class == 2 else 0x20
            blob = bytearray(header_size + phentsize)
            blob[0:4] = b"\x7fELF"
            blob[4] = elf_class
            if elf_class == 2:
                blob[0x20:0x28] = header_size.to_bytes(8, "little")
                blob[0x36:0x38] = phentsize.to_bytes(2, "little")
                blob[0x38:0x3A] = (1).to_bytes(2, "little")
                ph = header_size
                blob[ph:ph + 4] = (1).to_bytes(4, "little")            # PT_LOAD
                blob[ph + 8:ph + 16] = offset.to_bytes(8, "little")    # p_offset
                blob[ph + 48:ph + 56] = page_align.to_bytes(8, "little")  # p_align
            else:
                blob[0x1C:0x20] = header_size.to_bytes(4, "little")
                blob[0x2A:0x2C] = phentsize.to_bytes(2, "little")
                blob[0x2C:0x2E] = (1).to_bytes(2, "little")
                ph = header_size
                blob[ph:ph + 4] = (1).to_bytes(4, "little")
                blob[ph + 4:ph + 8] = offset.to_bytes(4, "little")
                blob[ph + 28:ph + 32] = page_align.to_bytes(4, "little")
            return bytes(blob)

        for elf_class in (2, 1):
            good = elf(elf_class, 16384, 16384)
            self.assertEqual(verify_apk.load_segment_alignments(good), [(16384, 16384)])
            verify_apk.check_page_alignment("good.so", good)
            with self.assertRaises(SystemExit):
                verify_apk.check_page_alignment("small.so", elf(elf_class, 4096, 4096))
            with self.assertRaises(SystemExit):
                verify_apk.check_page_alignment("shifted.so", elf(elf_class, 16384, 4096))
        self.assertEqual(verify_apk.load_segment_alignments(b"not an elf"), [])

    def test_every_abi_ships_the_library_under_both_names(self):
        # Some launchers ask for librustgl.so - the name without the underscore - and
        # crash with "librustgl.so missing" when only librust_gl.so is there.
        self.assertIn("librust_gl.so", package_apk.LIBRARY_ALIASES)
        self.assertIn("librustgl.so", package_apk.LIBRARY_ALIASES)
        doc = (ROOT / "docs" / "UNIVERSAL_APK.md").read_text(encoding="utf-8")
        self.assertIn("librustgl.so", doc,
                      "the second library name is documented, or nobody will know why it ships")

    def test_v1_environment_is_parseable(self):
        for key in ("pojavEnv", "boatEnv", "h2co3Env"):
            entries = meta_data()[key].split(":")
            self.assertTrue(entries)
            for entry in entries:
                name, _, value = entry.partition("=")
                self.assertTrue(name)
                self.assertNotIn("=", value,
                                 f"{key}: Zalith's v1 parser truncates at the second '='")
                self.assertNotIn(":", value, f"{key}: values are split on ':'")
            self.assertIn("POJAV_RENDERER=opengles3", entries, key)
            self.assertIn("LIBGL_ES=3", entries, key)

    def test_env_titles_of_the_v2_config_have_manifest_entries(self):
        values = meta_data()
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        for entry in config["env"]:
            title = entry.get("title")
            if title:
                self.assertIn(title["key"], values,
                              f"{entry['key']}: the launcher resolves this title to a resource id")


class RendererConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_required_fields(self):
        for key in ("displayName", "rendererId", "rendererGLPath", "rendererEGLPath",
                    "dlopenLibPaths", "env", "minMCVer", "maxMCVer"):
            self.assertIn(key, self.config)
        self.assertEqual(self.config["rendererId"], "opengles3")

    def test_library_paths(self):
        # "**|" is replaced with the plugin's nativeLibraryDir by both launchers.
        self.assertTrue(self.config["rendererGLPath"].startswith("**|"))
        self.assertEqual(self.config["rendererGLPath"], "**|librust_gl.so")
        # The EGL library must be resolved the same way: a bare name only loads
        # if the game process happens to have the plugin's library dir on its path.
        self.assertEqual(self.config["rendererEGLPath"], "**|librust_gl.so")
        self.assertEqual(self.config["dlopenLibPaths"], [])

    def test_environment(self):
        env = {entry["key"]: entry for entry in self.config["env"]}
        self.assertEqual(env["LIBGL_ES"]["type"], "NormalEnv")
        self.assertEqual(env["LIBGL_ES"]["value"], "3")
        self.assertEqual(env["RENDERER_BACKEND"]["value"], "gles")
        self.assertEqual(env["RENDERER_SPOOF_GL"]["type"], "SelectableEnv")
        self.assertEqual(env["RENDERER_SPOOF_GL"]["items"]["defaultValue"], "1")
        for entry in self.config["env"]:
            self.assertIn(entry["type"], ("NormalEnv", "SelectableEnv",
                                          "CustomizableEnv", "ToggleableEnv"))
            if entry["type"] == "SelectableEnv":
                self.assertIn(entry["items"]["defaultValue"], entry["items"]["values"])
        # POJAV_RENDERER comes from rendererId, it must not be duplicated in env.
        self.assertNotIn("POJAV_RENDERER", env)

    def test_serialised_shape_matches_the_dsl(self):
        """The official DSL emits one line, escaped quotes, "type" discriminant."""
        serialised = json.dumps(self.config, separators=(",", ":"))
        escaped = package_apk.escape_resource_text(serialised)
        self.assertNotIn('"', escaped.replace('\\"', ""))
        for entry in self.config["env"]:
            self.assertIn(f'\\"type\\":\\"{entry["type"]}\\"', escaped)


class IconTests(unittest.TestCase):
    """Launchers call PackageManager.loadIcon(): a plugin without one looks broken."""

    def test_adaptive_icon_resources_exist(self):
        res = ROOT / "android-plugin" / "res"
        self.assertTrue((res / "mipmap-anydpi-v26" / "ic_launcher.xml").is_file())
        for density in ("mdpi", "hdpi", "xhdpi", "xxhdpi", "xxxhdpi"):
            icon = res / f"mipmap-{density}" / "ic_launcher_foreground.png"
            self.assertTrue(icon.is_file(), icon)
            self.assertTrue(icon.read_bytes().startswith(b"\x89PNG"))
        self.assertIn("ic_launcher_background", (res / "values" / "colors.xml").read_text())

    def test_the_application_references_the_icon(self):
        application = ET.parse(MANIFEST).getroot().find("application")
        self.assertEqual(application.get(ANDROID + "icon"), "@mipmap/ic_launcher")
        self.assertEqual(application.get(ANDROID + "roundIcon"), "@mipmap/ic_launcher")


class PackagingTests(unittest.TestCase):
    def make_elf(self, path: Path, elf_class: int, machine: int) -> None:
        data = bytearray(64)
        data[:6] = b"\x7fELF" + bytes([elf_class, 1])
        data[16:18] = (3).to_bytes(2, "little")
        data[18:20] = machine.to_bytes(2, "little")
        path.write_bytes(data)

    def test_elf_verification_accepts_and_rejects(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            good = tmp / "good.so"
            self.make_elf(good, 2, 183)
            package_apk.verify_elf(good, "arm64-v8a")
            with self.assertRaises(SystemExit):
                package_apk.verify_elf(good, "armeabi-v7a")
            bad = tmp / "bad.so"
            bad.write_bytes(b"not an elf")
            with self.assertRaises(SystemExit):
                package_apk.verify_elf(bad, "x86_64")

    def test_resource_escaping(self):
        self.assertEqual(package_apk.escape_resource_text('say "hi" & <b>'),
                         'say \\"hi\\" &amp; &lt;b&gt;')
        self.assertEqual(package_apk.escape_resource_text("it's"), "it\\'s")

    def test_local_import_config_is_written_for_java(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            native = tmp / "native"
            build_info = {"versionName": "0.0.0-test", "libraries": {}}
            for abi, (elf_class, machine) in package_apk.ABIS.items():
                (native / abi).mkdir(parents=True)
                library = native / abi / "librust_gl.so"
                self.make_elf(library, elf_class, machine)
                build_info["libraries"][abi] = {
                    "path": library, "sha256": "0" * 64, "size": 64}
            target = tmp / "local.zip"
            package_apk.write_local_import(target, build_info)
            with zipfile.ZipFile(target) as archive:
                names = archive.namelist()
                blob = archive.read("config")
                length = int.from_bytes(blob[:2], "big")
                self.assertEqual(length, len(blob) - 2)
                config = json.loads(blob[2:].decode("utf-8"))
            self.assertEqual(config["rendererId"], "opengles3_rust")
            self.assertEqual(config["glName"], "librust_gl.so")
            self.assertTrue(config["eglName"].startswith("/"))
            self.assertIn("JAVA_TOOL_OPTIONS", config["pojavEnv"])
            for abi in ABIS:
                self.assertIn(f"libs/{abi}/librust_gl.so", names)


class SourceSyncTests(unittest.TestCase):
    def test_renderer_source_matches_the_recorded_source(self):
        """rustgl/ is the recorded Gurkha Launcher source plus its documented local changes.

        check_sync.verify() substitutes the recorded upstream blobs back into the tree and
        compares the result with the recorded tree hash, so an undocumented edit - or a
        documented entry that no longer describes a change - fails here.
        """
        record = json.loads(RECORD.read_text(encoding="utf-8"))
        ok, report = check_sync.verify(record)
        self.assertTrue(ok, "\n".join(report))

    def test_documented_local_changes_are_complete(self):
        record = json.loads(RECORD.read_text(encoding="utf-8"))
        for entry in record.get("localChanges", []):
            self.assertIn("path", entry)
            self.assertIn("summary", entry, f"{entry['path']} needs a reason")
            self.assertIn("upstreamBlob", entry)
            self.assertRegex(entry["upstreamBlob"], r"^[0-9a-f]{40}$",
                             f"{entry['path']} needs the upstream blob id")
            self.assertTrue((ROOT / "rustgl" / entry["path"]).is_file(),
                            f"{entry['path']} is not a file in rustgl/")
            self.assertFalse(entry["path"].startswith("/"), "paths are relative to rustgl/")
            self.assertNotIn("..", Path(entry["path"]).parts, "no escapes above rustgl/")

    def test_tree_hash_helper_still_hashes_the_directory(self):
        """The helper the sync check is built on: a stable hash of rustgl/."""
        self.assertRegex(tree_hash(ROOT / "rustgl"), r"^[0-9a-f]{40}$")

    def test_renderer_workspace_builds_the_expected_library(self):
        cargo = (ROOT / "rustgl" / "crates" / "gl-compat" / "Cargo.toml").read_text()
        self.assertIn('name = "rust_gl"', cargo)
        self.assertIn('crate-type = ["cdylib"]', cargo)
        workspace = (ROOT / "rustgl" / "Cargo.toml").read_text()
        for member in ("renderer-core", "backend", "shader-translate",
                       "format-translate", "gl-compat", "shader-manager"):
            self.assertIn(member, workspace)


if __name__ == "__main__":
    unittest.main(verbosity=2)
