# "There is no OpenGL context management API available" on Pojav

The crash that looks like this:

```
java.lang.IllegalStateException: There is no OpenGL context management API available.
    at org.lwjgl.opengl.GL.create(GL.java:116)
```

with a launcher log that says the renderer loaded fine:

```
Renderer native setup finished loaded=true
EGL context/gameplay not yet verified
```

This page explains what that exception actually means, why it is not about your GPU, what
EGL has to return for this renderer to work, and how to make LWJGL use EGL deliberately.

## 1. Why LWJGL cannot detect a context management API

**It fires before any GL call, and before your GPU is involved.** `org.lwjgl.opengl.GL`
resolves its function provider from a static initializer:

```java
static {
    Library.loadSystem(System::load, System::loadLibrary, GL.class, "org.lwjgl.opengl",
                       Platform.mapLibraryNameBundled("lwjgl_opengl"));
    MAX_VERSION = apiParseVersion(Configuration.OPENGL_MAXVERSION);
    if (!Configuration.OPENGL_EXPLICIT_INIT.get(false)) {
        create();          // <-- the crash is in here
    }
}
```

`create()` then tries, in order:

| attempt | library names it dlopens | on Android |
|---|---|---|
| native OpenGL platform API | `libGLX.so.0`, `libGL.so.1`, `libGL.so` | none of them exist |
| EGL | `libEGL.so.1` (only!) | Android ships `libEGL.so`, **no `.1`** |
| OSMesa | `libOSMesa.so.8`, `libOSMesa.so.6`, `libOSMesa.so` | none exist |

All three return null, so:

```java
if (GL == null) {
    throw new IllegalStateException("There is no OpenGL context management API available.");
}
```

That is upstream LWJGL 3.3.x on the `LINUX` platform — which is what it reports on Android,
because it has no Android case. **The failure is a library-name mismatch, not a missing
capability, not a Mali problem, and not a context problem.** Nothing in this renderer can
prevent it, because it happens the moment Java touches `org.lwjgl.opengl.GL`.

### Why a launcher normally avoids it

PojavLauncher adds the property itself — `app_pojavlauncher/.../utils/JREUtils.java`:

```java
purgeArg(userArgs, "-Dorg.lwjgl.opengl.libname");      // strips any user-supplied copy
...
if (LOCAL_RENDERER != null) {
    userArgs.add("-Dorg.lwjgl.opengl.libname=" + graphicsLib);
}
```

Two things follow:

* `LOCAL_RENDERER` is Pojav's **own built-in** renderer preference. With a renderer
  **plugin** selected it is usually null, so the property is never added.
* Any copy of that property you put in the instance's Java arguments is **stripped**.

So a plugin renderer leaves LWJGL unconfigured, and unconfigured LWJGL cannot start on
Android. That is the whole bug.

### What this repository does about it

The library is linked with `-Wl,-soname,libGL.so`. Bionic's `dlopen` returns an
already-loaded library whose SONAME matches the requested name, so once the launcher has
loaded this renderer, LWJGL's third attempt — `dlopen("libGL.so")` — resolves to it
without any configuration. The SONAME is asserted per ABI in CI with `llvm-readelf -d`,
because a flag silently dropped by the linker would bring the crash straight back.

The library is ready for that path: it exports `glXGetProcAddress`,
`glXGetProcAddressARB` and `eglGetProcAddress`, and all three return *this* renderer's GL
entry points — the symbol LWJGL resolves first is exactly the one that decides whether the
game talks to this layer or straight to the driver.

## 2. The EGL sequence, and what each call must return

This renderer forwards every one of these to the system EGL, so the values below are what
the **driver** must return; the two it intercepts are marked.

| call | must return | if it does not |
|---|---|---|
| `eglGetDisplay(EGL_DEFAULT_DISPLAY)` | non-null `EGLDisplay` | returns `EGL_NO_DISPLAY`; `eglGetError()` = `EGL_BAD_PARAMETER` (0x300C) |
| `eglInitialize(dpy, &major, &minor)` | `EGL_TRUE` (1), and `major.minor >= 1.4` (Android 12+ reports 1.5) | `EGL_FALSE` + `EGL_NOT_INITIALIZED` (0x3001) |
| `eglBindAPI(EGL_OPENGL_ES_API)` | `EGL_TRUE` | `EGL_FALSE` + `EGL_BAD_PARAMETER`; the API then stays `EGL_OPENGL_API`, and creating an ES context later fails with `EGL_BAD_MATCH` |
| `eglChooseConfig(dpy, attribs, &cfg, 1, &n)` | `EGL_TRUE` **and** `n >= 1` | `EGL_FALSE` + `EGL_BAD_ATTRIBUTE`, or `n == 0` — usually a config attribute the driver cannot satisfy |
| `eglCreateContext(dpy, cfg, EGL_NO_CONTEXT, {EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE})` | non-null `EGLContext` — **intercepted**: a desktop-GL request is rewritten here to an ES 3 request, the client-version token is pinned to 3, and `EGL_CONTEXT_MINOR_VERSION` / flags / profile-mask are dropped, because Mali refuses a context built from them | `EGL_NO_CONTEXT` + `EGL_BAD_CONFIG` / `EGL_BAD_ATTRIBUTE` / `EGL_BAD_MATCH` |
| `eglCreateWindowSurface(...)` or `eglCreatePbufferSurface(...)` | non-null `EGLSurface` | `EGL_NO_SURFACE`; without `EGL_KHR_surfaceless_context` you cannot skip this — `eglMakeCurrent` needs a surface on EGL 1.4 |
| `eglMakeCurrent(dpy, draw, read, ctx)` | `EGL_TRUE`, then `eglGetCurrentContext() == ctx` | `EGL_FALSE` + `EGL_BAD_MATCH` / `EGL_BAD_ACCESS` |
| `eglGetError()` after each step | `EGL_SUCCESS` (0x3000) | anything else is the real error; read it before assuming the next call's result means anything |

Two things worth knowing about this renderer's EGL:

* `eglQueryAPI()` answers `EGL_OPENGL_API` even when you bound ES. That is deliberate: the
  desktop-to-ES rewrite in `eglCreateContext` keys off the bound API, and a launcher that
  bound `EGL_OPENGL_API` is the one that needs rewriting.
* `eglGetProcAddress` is served here first from this renderer's own symbol table, and only
  falls through to the system EGL. Pojav's `egl_loader.c` resolves *every* EGL entry point
  through `eglGetProcAddress`, so all twenty names it asks for
  (`eglGetDisplay`, `eglInitialize`, `eglChooseConfig`, `eglBindAPI`, `eglCreateContext`,
  `eglCreatePbufferSurface`, `eglCreateWindowSurface`, `eglDestroyContext`,
  `eglDestroySurface`, `eglGetConfigAttrib`, `eglGetCurrentContext`, `eglGetError`,
  `eglMakeCurrent`, `eglSwapBuffers`, `eglReleaseThread`, `eglSwapInterval`,
  `eglTerminate`, `eglGetCurrentSurface`, `eglQuerySurface`, `eglGetProcAddress`) are in
  that table.

**The ordering that matters for LWJGL:** the context must be current *on the thread that
then calls* `GL.createCapabilities()`. A context made current on Pojav's native thread and
never on the Java thread produces a different error —
`java.lang.IllegalStateException: There is no OpenGL context current in the current thread`
— and that one is a threading bug, not this one.

## 3. Is requesting GLES 3.1 on a Mali-G57 the problem?

No, and on your device it is not even the version being requested.

* **Mali-G57 MC2 is an OpenGL ES 3.2 part.** It is Bifrost; 3.2, not 3.1. This renderer
  probes the real driver's `GL_VERSION`, finds 3.2, and therefore claims **OpenGL 4.5 /
  GLSL 4.50** to the game. The claim is logged once:
  `[GLCompat] driver is OpenGL ES 3.2 (...); claiming GL 4.5 / GLSL 4.50`.
* **`LIBGL_GL=31` is not read by this renderer.** It is a gl4es variable. This renderer
  reads `LIBGL_ES` (which Pojav sets to `3` for an `opengles3` renderer). If gl4es is also
  in the process, `LIBGL_GL` will shape what *it* reports, not what this layer reports.
* **An ES 3.1 context request would still be fine on a G57** — the part does 3.2, so 3.1 is
  a subset. `EGL_CONTEXT_CLIENT_VERSION 3` gets you an ES 3.x context either way.
* **What would be fatal** is the game being told 3.1 or lower: Minecraft 1.17+ requires
  OpenGL 3.2, so the game would refuse to start before it ever touched the GPU.

If you want to check what the game was actually told, `RENDERER_SPOOF_GL=0` makes
`glGetString(GL_VERSION)` report the driver's real string instead of this layer's claim.

## 4. Forcing LWJGL to use EGL explicitly

Three ways, in increasing order of how early you have to be.

**a) System properties, which is what a launcher can pass:**

```
-Dorg.lwjgl.opengl.explicitInit=true          # stop GL auto-creating in its static init
-Dorg.lwjgl.egl.libname=librustgl.so          # the EGL library LWJGL should dlopen
-Dorg.lwjgl.opengl.libname=/abs/path/librustgl.so
-Dorg.lwjgl.opengl.contextAPI=EGL             # optional: try EGL first, not last
```

Caveats, all of them real:

* `org.lwjgl.opengl.explicitInit` must be set **before** `org.lwjgl.opengl.GL` is loaded —
  i.e. as a JVM argument, not from inside Java after LWJGL is touched.
* Pojav **strips** `-Dorg.lwjgl.opengl.libname` from user arguments (see §1). Use
  `JAVA_TOOL_OPTIONS`, which the JVM reads itself, if you need to set it on Pojav.
* The value is a name *or* a path. A bare name is resolved by `dlopen`, so it only works
  if the library is already loaded (which it is — that is what the SONAME above relies on)
  or on the search path. An absolute path always works and is the safer choice.

**b) In Java, from a launcher or a mod:**

```java
Configuration.OPENGL_EXPLICIT_INIT.set(true);
Configuration.EGL_LIBRARY_NAME.set("librustgl.so");

// after a context is current on this thread:
EGL.create();                       // or: EGL.create("librustgl.so")
GL.create(EGL.getFunctionProvider());
GLCapabilities caps = GL.createCapabilities();
```

`EGL.create()` with no argument has the same problem as `GL.create()` — its default list is
`libEGL.so.1`, which is not on Android — so set `EGL_LIBRARY_NAME` *or* call
`EGL.create(String libName)`, never the bare `EGL.create()`, and then
`EGL.getFunctionProvider()` will not be null.

**c) Let the SONAME do it.** With 0.3.0-gurkha.11+ no property is needed: LWJGL's
`dlopen("libGL.so")` matches this library's SONAME and lands on it. This is the only route
that survives Pojav stripping the property, which is why it is the one this repository
implements.

## Debug flags

**LWJGL** (all `-D`, all read at JVM start):

| flag | what it gives you |
|---|---|
| `-Dorg.lwjgl.util.DebugLoader=true` | **the one you want here** — logs every library load attempt, including `[GL] Failed to initialize context management based on EGL`, i.e. which of the three paths failed and why |
| `-Dorg.lwjgl.util.Debug=true` | logs every GL call |
| `-Dorg.lwjgl.util.DebugFunctions=true` | logs function lookup failures (`apiLogMissing`) |
| `-Dorg.lwjgl.util.DebugAllocator=true` | NIO buffer allocation tracing |
| `org.lwjgl.util.NoChecks` | leave it **off** while debugging: this plugin sets it by default, and it hides exactly the null-pointer mistakes you are hunting |

**This renderer** (environment variables):

| variable | what it gives you |
|---|---|
| `RENDERER_DEBUG=1` | verbose layer logging |
| `RENDERER_TRACE_GL=1` | logs every GL entry point as the game calls it |
| `RENDERER_FRAME_STATS=1` | frame-time percentiles (p50/p95/p99) |
| `RENDERER_DUMP_SHADER_DIR=/sdcard/rustgl` | writes every shader in and out, so a translation bug can be reproduced offline |
| `RENDERER_SPOOF_GL=0` | `glGetString(GL_VERSION)` reports the driver's real string, not this layer's claim |

**The two decisive checks**, in order:

```bash
# 1. Is LWJGL configured at all? If no -Dorg.lwjgl.opengl.libname appears, §1 is your bug.
adb shell 'ps -A -o args | grep -i lwjgl | tr " " "\n" | grep lwjgl'

# 2. What does the layer think the driver is?
adb logcat | grep -i "GLCompat\|GLBridge\|Shader"
```

## Still stuck

Send the `ps` line from check 1 and the `GLCompat` line from check 2. Together they say
whether LWJGL was pointed at this library, and which GL version this layer decided to
claim — which is the difference between a launcher that never configured LWJGL and a driver
that cannot do what the game asked of it.
