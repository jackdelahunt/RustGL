# RustGL universal renderer plugin APK

One installable APK (`rustgl-universal-<version>.apk`) carries `librustgl.so`
for **arm64-v8a, armeabi-v7a, x86 and x86_64** and speaks every renderer-plugin
contract in use, so the same file is picked up by the different launchers
instead of only one of them.

| Contract | Meta-data | Launchers that read it |
|---|---|---|
| RendererPlugin **v2** | `fclPlugin_V2` -> string resource with a JSON config | Zalith Launcher 2 (`ZalithLauncher/ZalithLauncher2`) and its forks (TurboCraft, Cubiq, Hyper Launcher v3, …), FCL (Fold Craft Launcher), NuxLauncher |
| RendererPlugin **v1** - FCL/Zalith marker | `fclPlugin` | FCL, Zalith Launcher 1 and forks (Gurkha Launcher, …), NuxLauncher, H2CO3's Pojav backend |
| RendererPlugin **v1** - Zalith marker | `zalithRendererPlugin` | Zalith/Gurkha forks, Pojav builds that merged movtery's plugin code |
| RendererPlugin **v1** - Pojav Glow·Worm marker | `pgwRendererPlugin` | Pojav Glow·Worm lineage: PojavLauncher-Beta-Zink, NRC for Android |
| RendererPlugin **v1** - H2CO3/Boat marker | `h2co3LauncherPlugin` + `h2co3Env` | H2CO3 Launcher (and the Boat family it continues) |
| Boat/MCinaBox env | `boatEnv` | Boat-style readers that ask for their own env list |
| Local import / bare library | `lib/<abi>/librustgl.so` | Launchers with no plugin loader at all: use the per-ABI ZIP or `rustgl-local-import.zip` from the release |

All of these readers find the package the same way -
`PackageManager.queryIntentActivities(Intent.ACTION_MAIN)` - which is why the APK
ships a small exported information Activity instead of being a pure native
package. The renderer id is `opengles3`, the value every one of them already
knows (the id that MobileGL, the most widely installed third-party renderer
plugin, also uses): launchers derive GL context hints and EGL handling from it,
and a private id makes that code fall through to its defaults.

Both FCL and Zalith Launcher 2 find plugins with
`PackageManager.queryIntentActivities(Intent.ACTION_MAIN)`, so the APK ships a
small exported information `Activity`. The launcher selection is still made
inside the launcher: the activity only explains the plugin and holds no settings.

## Install

1. Download `rustgl-universal-<version>.apk` from
   <https://github.com/kushaladhikari982648-lgtm/RustGL-for-Gurkha-launcher/releases/latest>
   and check it against `SHA256SUMS` of the same release.
2. Allow installation from your browser or file manager if Android asks.
3. Install it, then **fully close and reopen the launcher** (plugin lists are
   cached per process).
4. In the Minecraft version settings, pick **RustGL (Gurkha build)** as the
   renderer. Launchers that read the older v1 metadata show it under the `des`
   text *"RustGL (Gurkha build) - OpenGL 4.5 surface on OpenGL ES 3 [v1 plugin
   API]"* - the same renderer, through the older plugin API.
5. Start the game. If it crashes or renders nothing, switch the version back to
   your previous renderer; nothing else is lost.

Some launchers list both the v2 and the v1 entry of this same package. Either
one loads the same `librustgl.so`; the v2 entry additionally lets you turn
`RENDERER_DEBUG`, `RENDERER_TRACE_GL` and `RENDERER_SPOOF_GL` on and off from
the launcher.

Requirements: **Android 8.0 (API 26) or newer** and real **OpenGL ES 3**
support. Android picks the ABI of the *launcher process*, not of the CPU: a
32-bit launcher on a 64-bit phone uses the armeabi-v7a build.

## If it does not work on a Mali GPU

**The version this layer claims used to be a constant, and that is the first thing to
check.** Until 0.3.0-gurkha.10 the renderer told the game, unconditionally, that it was
OpenGL 4.5 with GLSL 4.50 - whatever the driver underneath really was. On an OpenGL ES 3.2
part that is roughly true. On an ES 3.0 or ES 3.1 part - which is what most older Mali
GPUs are, where an Adreno of the same vintage is 3.2 - it is not, and the game then asks
for compute shaders, image load/store and indirect draws the driver cannot do. What comes
back is a program that will not build or an entry point that is not there, and from the
launcher that looks like "the renderer does not work on Mali".

From 0.3.0-gurkha.10 the claim follows the driver:

| the driver really is | what the game is told |
|---|---|
| OpenGL ES 3.2 | GL 4.5 / GLSL 4.50 |
| OpenGL ES 3.1 | GL 4.3 / GLSL 4.30 |
| OpenGL ES 3.0 | GL 3.3 / GLSL 3.30 |
| older | GL 2.1 / GLSL 1.20 |

The advertised extension list was already gated the same way - `GL_ARB_compute_shader`,
`GL_ARB_shader_image_load_store` and `GL_ARB_multi_draw_indirect` only appear when the
driver has the ES feature behind them - so the claim and the extension list now agree.

**What to send if it still fails.** The renderer logs this once, at startup:

```
[GLCompat] driver is OpenGL ES 3.0 (OpenGL ES 3.0 build 1.9@1234567); claiming GL 3.3 / GLSL 3.30
```

That single line says which tier your GPU landed in. Follow it with any
`[GLCompat] compile failed shader=…` lines, which carry the driver's own GLSL error and
the translated source around the line it names - that is the difference between "Mali
cannot do this" and "the translation emitted something wrong".

Honest limit: this change was reasoned from the code and from what each ES version can
back. No Mali device was available here, so while it removes a claim that was false on
those parts, it has not been run on one.

## If LWJGL says "There is no OpenGL context management API available"

That is a library-name problem, not a GPU one, and it is answered in
[`docs/POJAV_EGL_LWJGL.md`](POJAV_EGL_LWJGL.md) - including the EGL sequence, the value each
call has to return, and the debug flags. From 0.3.0-gurkha.11 the library is linked with
`-Wl,-soname,libGL.so`, which is what lets LWJGL find it without configuration.

## If it crashes on a 64-bit phone but works on a 32-bit one

**Check the page size first.** Android 15 introduced 16 KB memory pages, and a shared
library whose loadable segments are only aligned to 4 KB simply does not load on those
devices: `dlopen` fails with "has bad ELF alignment", and from the launcher that looks
like the renderer crashing. 64-bit phones are the newer ones, so this failure maps almost
exactly onto "works on my old 32-bit device, crashes on a friend's newer one".

Two separate alignments are needed, and this repository now does both and checks both:

| What | Where it comes from | Status here |
|---|---|---|
| the entry inside the APK | `zipalign -P 16 4` | already done |
| the ELF segments inside the `.so` | the linker: `-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384` | added in 0.3.0-gurkha.9, **checked on every build** by `tools/verify_apk.py`, which parses the program headers of every shipped library |

`tools/verify_apk.py` requires two things of every `PT_LOAD` segment:

* `p_align` must be at least 16 KB (0x4000). A segment aligned to 4 KB cannot satisfy a
  16 KB mapping, whatever its offset.
* `p_offset` and `p_vaddr` must be **congruent modulo 16 KB** - the linker maps the page
  that contains the segment's file offset onto the page that contains its address, so any
  difference that is not a whole number of 16 KB pages lands the bytes in the wrong place.

The file offset does *not* have to be a multiple of 16 KB. It usually is not: the linker
packs the segments one after another, and what it guarantees is the congruence above. The
segments in the shipped arm64 build, for example, are

```
[align 0x4000 offset 0x0      vaddr 0x0]
[align 0x4000 offset 0x6304c  vaddr 0x6704c]
[align 0x4000 offset 0x181530 vaddr 0x189530]
[align 0x4000 offset 0x188950 vaddr 0x194950]
```

every one 16 KB aligned, every pair 16 KB congruent, and none of the offsets a round
multiple of 16 KB - which is correct, and is what the check now enforces.

If the crash survives 0.3.0-gurkha.9, it is not this. What is needed then is the log:
`adb logcat` filtered on the launcher, or the launcher's own log export. The useful
lines name either `librustgl.so` / `librustgl.so` (a loading problem) or a GL entry
point (`[GLBridge] Missing entry point: …`, a coverage problem).

Honest limit: the arm64 and x86_64 builds are compiled in CI and pass the same unit tests
as the host build, but the on-device smoke test (`rustgl/tests/render_smoke.py`) runs
against Mesa on the CI machine only. Nothing here has been run on a 64-bit phone.

## Library names

The renderer ships as **`librustgl.so`**, and that is the only name it is under.

It is not the name the crate is built as. Cargo builds `librust_gl.so`, and packaging
renames it, because the name that matters is the one the launcher derives: launchers take
the plugin's display name - "RustGL" - and look for `librustgl.so`, with no underscore.
A library shipped under the crate's own name is one those launchers never find.

This is why 0.3.0-gurkha.9 shipped both names and 0.3.0-gurkha.10 does not. Two copies
solved "missing", but they left the launcher free to load either, including the one whose
name nothing asked for - and that name is what 0.3.0-gurkha.10 removes. The APK is back to
one copy of the library per ABI, so it is roughly half the size of .9.

`tools/verify_apk.py` checks every ABI for `lib/<abi>/librustgl.so` and refuses the build
if it is not there. The per-ABI ZIPs and `rustgl-local-import.zip` carry the same name, and
the plugin's `rendererGLPath` / `rendererEGLPath` and the v1 `renderer` meta-data all point
at it, so a launcher reading the configuration and a launcher guessing the name agree.

## What the renderer is

RustGL is a compatibility layer, not a driver. Minecraft talks desktop OpenGL to
`librustgl.so`, which rewrites the shaders to GLSL ES, emulates desktop-only
entry points (fixed-function drawing, display lists, base-vertex draws, buffer
textures, UBO updates, legacy lightmaps) and forwards to the device's OpenGL ES
3 driver. With `RENDERER_SPOOF_GL=1` it reports an OpenGL 4.5 core profile to
the game and mods.

Environment the plugin sets (`pojavEnv` / v2 `env`):

| Variable | Value | Meaning |
|---|---|---|
| `POJAV_RENDERER` | `opengles3` | renderer id (from `rendererId` in v2): the id every launcher understands |
| `LIBGL_ES` | `3` | create an OpenGL ES 3 context |
| `RENDERER_BACKEND` | `gles` | GLES passthrough backend (the only one that draws) |
| `RENDERER_SPOOF_GL` | `1` | report OpenGL 4.5 core to the game and mods |
| `JAVA_TOOL_OPTIONS` | `-Dorg.lwjgl.util.NoChecks=true` | LWJGL pointer checks off (1.16 fog workaround) |
| `RENDERER_DEBUG` | `0` | set to `1` for draw diagnostics (slow) |
| `RENDERER_TRACE_GL` | `0` | set to `1` to log every GL call (very slow) |

`JAVA_TOOL_OPTIONS` is only in the v2 config: the v1 `pojavEnv` parser in
Zalith truncates values at the second `=`. If you use the v1 entry on Minecraft
1.16 or older, add it to the version's custom environment by hand.

## Limitations (read before reporting a bug)

- **Compatibility is not universal.** No renderer is: Minecraft versions differ
  in GL profile, shader dialect and mod requirements, and GPU drivers differ in
  what they implement. This plugin was built and unit-tested in CI (unit tests,
  shader fixtures, and GLES pixel read-backs against Mesa on the host); it has
  **not** been validated on every launcher, GPU or Minecraft version. Test a
  clean instance without mods or shader packs first.
- **Launchers without a plugin loader** (stock PojavLauncher, Amethyst, and any
  fork that predates the FCL plugin API) cannot use the APK at all. Use
  `rustgl-gurkha-<abi>.zip` (bare `librustgl.so`) and the launcher's own
  "custom"/library mechanism, or `rustgl-local-import.zip` for launchers that
  import renderer folders (Zalith, Gurkha: *renderer plugins -> import local*).
- The **v1 entry** is fixed-environment: its `pojavEnv` cannot contain `=` in a
  value, so `JAVA_TOOL_OPTIONS` is omitted there.
- Minecraft versions that create their GL context through SDL3 (26.3+) or that
  need Vulkan are outside what RustGL provides.
- If a device reports OpenGL ES 3 but the driver is incomplete, expect missing
  geometry or a black screen; that is a driver limitation, not a launcher bug.
- **Shader packs** work through two routes. OptiFine-style packs for
  1.7.10-1.12.2 (GLSL 120, `gl_FragData` MRT, `texture2DLod`) have their
  fixed-function builtins translated onto attributes and uniforms this renderer
  feeds from the arrays and matrix stacks it tracks; Iris and Sodium packs
  (GLSL 330) are passed through untouched. Packs that need geometry,
  tessellation, compute, image load/store or SSBOs are rejected with a logged
  reason - ES 3.x has no equivalent, so they cannot work here. No pack has been
  run end to end on a device: what CI proves is that twenty shader dialects,
  six of them pack dialects, compile on a real GLES driver.

## Minecraft 26.x

Three different things happened to Minecraft: Java Edition in 2026, and they matter
differently for this plugin.

| Version | What changed | What that means here |
|---|---|---|
| **26.1, 26.2** | Still GLFW for the window and OpenGL for rendering | The same path as 1.21.x. Nothing 26-specific is known to be missing; if it fails, the log says which entry point was missing. |
| **26.2+** | An **experimental Vulkan renderer**, chosen in *Options -> Video Settings -> Graphics API* | It needs Vulkan 1.2 with dynamic rendering and push descriptors, and falls back to OpenGL where that is missing [1](https://www.minecraft.net/en-us/article/minecraft-26-2-snapshot-1). A GE8300 has no usable Vulkan 1.2, so the game picks OpenGL by itself. To force it on a device whose Vulkan driver is present but bad, set `preferredGraphicsBackend:"opengl"` in the instance's `options.txt` - the same fix Mojang documented for 26.2 Pre-Release 1 [2](https://endgametools.com/en/minecraft/news/minecraft-vulkan). This plugin is the OpenGL path; it cannot serve the Vulkan one. |
| **26.3+** | Window, input and platform integration moved from **GLFW to SDL3** [3](https://www.minecraft.net/en-us/article/minecraft-26-3-snapshot-4) | This plugin provides GL and EGL, not a windowing backend. The **launcher** has to supply SDL3 (as it supplies a GLFW stub today) and point it at this library: SDL3 reads `SDL_EGL_LIBRARY` and `SDL_OPENGL_LIBRARY` hints for that [4](https://wiki.libsdl.org/SDL3/SDL_HINT_EGL_LIBRARY). Prepared for it: our EGL now also answers the platform entry points SDL3 tries first - `eglGetPlatformDisplay`, `eglGetPlatformDisplayEXT` and `eglCreatePlatformWindowSurface(EXT)` - each forwarding to the system EGL and falling back to the EGL 1.4 spelling when the driver does not have it [5](https://github.com/spurious/SDL-mirror/blob/master/src/video/SDL_egl.c). |

**For 26.3+, see [`docs/SDL3_LAUNCHERS.md`](SDL3_LAUNCHERS.md)**: what the launcher has to
supply, the `SDL_EGL_LIBRARY` hint that points SDL3 at this renderer, and the state of
SDL3 support in the launchers this APK targets.

**WebGPU is not the answer to any of this**, and it is worth saying why rather than
nodding along:

* WebGPU has no fixed-function pipeline, no `glMapBuffer`, no VAOs, no `glGetError` - to
  serve Minecraft's OpenGL calls through it, this project would have to become a complete
  OpenGL implementation with a GLSL-to-WGSL compiler, which is ANGLE/zink-scale work.
* On Android, WebGPU is not a system library. `wgpu` and Dawn both run on **Vulkan**
  underneath [6](https://docs.rs/wgpu/latest/wgpu/struct.Backends.html), so on a
  PowerVR GE8300 - exactly the device you are targeting - it would sit on the weakest
  driver in the device instead of the well-trodden GLES one.
* Every shader pack is GLSL. Translating arbitrary pack GLSL to WGSL is unsolved, so it
  would throw away the shader-pack work.

What would actually help 26.x is: (1) a log from a real 26.1/26.2 launch on your device,
which tells us which OpenGL entry point or capability is missing, and (2) your launcher
adding SDL3 support, which no renderer plugin can do from the outside.

## Signing and updates

The APK is signed with the repository's release key when the
`APK_KEYSTORE_BASE64` secret is configured, and with a freshly generated
one-build key otherwise (the workflow prints a warning in that case). A
differently signed build cannot update an installed plugin: uninstall the
plugin first. Uninstalling the plugin never touches the launcher or Minecraft
data - it only removes the renderer entry. Verify any download against
`SHA256SUMS` in the release.

## Source, licences, rebuild

- Renderer source: `rustgl/` in this repository, synced from
  [`Gurkha Launcher`](https://github.com/kushaladhikari982648-lgtm/Gurkha-launcher)
  (`rustgl/`, branch `arena/a8e9723f-gurkha-launcher`, commit `1726782a`) plus the
  local changes documented in `renderer-source.json` (see
  [`docs/PERFORMANCE.md`](PERFORMANCE.md)). `python3 tools/check_sync.py`
  proves every other file is byte-identical.
- Upstream of that code: <https://github.com/whaltermc/rust-renderer>
  (revision `eb22559`). Upstream publishes **no licence file**; until it does,
  treat the renderer code as "used with the author's permission" and keep the
  notices in `NOTICE` with any redistribution. The packaging tooling in
  `tools/`, `android-plugin/` and `tests/` is MIT licensed.
- Rebuild: `.github/workflows/android.yml` (Rust + `cargo-ndk`, NDK
  25.2.9519653, then `python3 tools/package_apk.py`). Locally:
  `cd rustgl && cargo ndk -t arm64-v8a -t armeabi-v7a -t x86 -t x86_64 build
  --release -p gl-compat`, then copy the libraries to
  `artifacts/rustgl/<abi>/` and run `python3 tools/package_apk.py --sdk
  $ANDROID_HOME`, followed by `python3 tools/verify_apk.py` on the result.
