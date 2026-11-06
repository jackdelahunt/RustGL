# SDL3, Minecraft 26.3+, and what a launcher has to provide

This is written for launcher developers (and for users who want to know why 26.3
does or does not start). It states what this renderer plugin does, what it cannot
do, and exactly what has to happen on the launcher side.

## What changed in the game

Minecraft Java Edition 26.3 replaced GLFW with SDL3 for window management, input
and platform integration ([26.3 Snapshot 4](https://www.minecraft.net/en-us/article/minecraft-26-3-snapshot-4)).
26.1 and 26.2 still use GLFW.

This plugin is a **GL and EGL** layer. It has never provided windowing, input,
the Android surface, the IME or the clipboard — those were the launcher's GLFW
stub then, and they are the launcher's SDL3 now. **No renderer plugin can supply
them from the outside**: LWJGL loads SDL3 by name out of its own natives
directory, and the game calls SDL3 directly from Java.

So the work splits like this:

| Layer | Who provides it |
|---|---|
| SDL3 library for Android, JNI/surface/IME wiring, event loop | **the launcher** |
| EGL display, config, context, surfaces | the launcher normally, but this plugin is the EGL library it calls |
| GL entry points and GLSL translation | **this plugin** |

## Two ways a launcher can supply SDL3

1. **Ship real SDL3 for Android.** SDL3 has an Android backend. This is the
   route the [FlameLauncher-SDL3](https://github.com/FlameLaunchers/FlameLauncher-SDL3)
   and [GappleClub android-natives](https://github.com/GappleClub/android-natives)
   projects took: build scripts plus prebuilt `libSDL3.so` and LWJGL 3.4.3
   natives for `arm64-v8a`. Those projects also build shaderc and SPIRV-Cross,
   which they report Minecraft 26.3 needs for its shader compiler.
2. **Hook or stub SDL3.** [ZalithLauncher2's PR #1721](https://github.com/ZalithLauncher/ZalithLauncher2/pull/1721)
   (and the [port of it to TurtleLauncher](https://github.com/Endiq-jar/TurtleLauncher/pull/32))
   takes this route: a self-contained `libsdlhook.so` with SDL hooks plus
   dlsym-layer proxies — LWJGL resolves SDL functions with `dlsym`, so a hook at
   that layer catches them — together with JNI isolation, ES-profile forcing and
   EGL normalisation on the Java side.

Either way the context has to end up as **ES 3.x**, because there is no desktop
OpenGL on Android.

## Getting this renderer into the SDL3 path

SDL3 loads EGL and OpenGL by library name, and both are overridable with hints
that must be set before the first window or context is created
([`SDL_HINT_EGL_LIBRARY`](https://wiki.libsdl.org/SDL3/SDL_HINT_EGL_LIBRARY),
`SDL_HINT_OPENGL_LIBRARY`, both since SDL 3.2.0):

```
SDL_EGL_LIBRARY     = <nativeLibraryDir>/librust_gl.so
SDL_OPENGL_LIBRARY  = <nativeLibraryDir>/librust_gl.so
```

This plugin already re-exports EGL and is already installed as the EGL library by
the v1 plugin contract (its `renderer` meta-data carries `/librust_gl.so` for
exactly that reason — a leading `/` makes every documented v1 launcher prepend
the plugin's native library directory). The same absolute path is what the SDL3
hints need. If SDL3 loads the system EGL instead, **this plugin is bypassed
entirely** and the game gets an untranslated ES context: desktop GL calls will
fail and no amount of work in this repository will show up.

## What this plugin now does for an SDL3 launcher

* **Answers the entry points SDL3 tries first.** SDL3's EGL backend
  ([src/video/SDL_egl.c](https://github.com/spurious/SDL-mirror/blob/master/src/video/SDL_egl.c))
  prefers `eglGetPlatformDisplay` over `eglGetDisplay` and
  `eglCreatePlatformWindowSurface` over `eglCreateWindowSurface` whenever the
  driver is EGL 1.5 or advertises `EGL_EXT_platform_base`. Those are now served,
  each forwarding to the system EGL and falling back to the EGL 1.4 spelling
  when the driver does not have it, so nothing that works today changes.
  `eglSwapBuffersWithDamageKHR/EXT` are served the same way, falling back to the
  ordinary swap so the overlay and the frame-time logging still run.
* **Normalises a desktop-GL context request into ES 3.** Minecraft asks for what
  it asks on a PC — GL 3.3 core, forward compatible — and SDL3 passes those
  attributes straight through to EGL. No Android driver accepts them. When the
  caller has bound `EGL_OPENGL_API`, this layer rewrites the list: the version
  token is pinned to 3, and the GL minor version, profile mask and context flags
  (which carry the forward-compatible and debug bits) are dropped. Note that
  `EGL_CONTEXT_CLIENT_VERSION` and `EGL_CONTEXT_MAJOR_VERSION` are the *same*
  token, `0x3098`, in Khronos' `egl.h`, so which one a list means is decided by
  the bound API — and an ES request is left strictly untouched, because every
  launcher today makes one and changing it could only break working setups.
  If the rewritten list is refused, the original is retried before giving up.
* **Keeps the API lie consistent.** `eglBindAPI(EGL_OPENGL_API)` binds ES and
  logs that it did; `eglQueryAPI` then reports `EGL_OPENGL_API` back, because a
  game that recognises its own request is a game that accepts the context.
* **Says what is missing.** Unresolved GL entry points are logged as
  `[GLBridge] Missing entry point: <name>`, so a failed 26.x launch produces a
  list of what to add instead of a silent crash.

## What it cannot do

* Windowing, input, scancode/keycode mapping, IME, controller, clipboard,
  lifecycle, and the Android surface itself.
* Force a launcher to use it. If SDL3 is pointed at the system EGL, we are not
  in the call path.
* Serve the **Vulkan** renderer that Minecraft 26.2+ ships as an experimental
  option. That path needs Vulkan 1.2 with dynamic rendering and push
  descriptors; where it is missing — every PowerVR GE8300 — the game falls back
  to OpenGL by itself, and `preferredGraphicsBackend:"opengl"` in the instance's
  `options.txt` forces it. This plugin is the OpenGL path.

## Status in the launchers this APK targets

| Launcher | SDL3 for 26.3+ |
|---|---|
| Zalith Launcher 2 | SDL3 support merged ([PR #1721](https://github.com/ZalithLauncher/ZalithLauncher2/pull/1721)); users still report 26.3 failures on 2.5.3 ([#1879](https://github.com/ZalithLauncher/ZalithLauncher2/issues/1879), [#1903](https://github.com/ZalithLauncher/ZalithLauncher2/issues/1903)) |
| Pojav Glow·Worm | states 26.3+ is supported through a bundled SDL3 compatibility layer (`libSDL3.so`) |
| FCL (Fold Craft Launcher) | reported crashing on 26.3 Snapshot 4+ for lack of `libSDL3.so` ([#1744](https://github.com/FCL-Team/FoldCraftLauncher/issues/1744)) |
| FlameLauncher / GappleClient | purpose-built SDL3 + LWJGL 3.4.3 natives for `arm64-v8a` |

Treat this table as a snapshot, not a promise: it is compiled from public
issues and pull requests, not from testing each launcher.

## Checklist for a launcher developer bringing up 26.3+ with this renderer

1. Provide SDL3 for Android (real SDL3 or a hook), wired to your surface and
   input, with JNI/VM isolation as needed.
2. Set `SDL_EGL_LIBRARY` and `SDL_OPENGL_LIBRARY` to the absolute path of
   `librust_gl.so` **before** the first window or context.
3. Ask for an ES context (`SDL_GL_CONTEXT_PROFILE_MASK` = ES, version 3.x).
   If you cannot, this layer will normalise a desktop-GL request for you — but
   asking correctly is better, and it is what your existing GLFW stub already
   does.
4. Launch with `RENDERER_DEBUG=1` and read the log:
   `[GLBridge] eglGetPlatformDisplay(0x…)` tells you SDL3 came through here,
   `eglCreateContext: desktop-GL attributes rewritten to ES 3` tells you the
   normalisation fired, and `Missing entry point:` lines name what is left.
5. Send that log with the launcher name, the device and the MC version. Without
   it, the answer to "why does 26.3 not start" is guesswork.
