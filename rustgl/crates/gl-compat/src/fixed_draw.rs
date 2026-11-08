//! Fixed-function draw emulation for GLES 3.
//!
//! When the game draws with no shader program bound (Minecraft 1.16 and older), we render
//! the tracked client arrays with a small built-in program: MVP transform, per-vertex or
//! constant color, optional texture on unit 0, and the alpha test. `GL_QUADS` is expanded
//! to triangles. NOT emulated yet: lighting, fog, texture matrices, texture environment
//! modes. Fog, the lightmap (texture unit 1 on 1.12-1.14, unit 2 on 1.15/1.16) and texture
//! matrices are handled by the extended program; if that program fails to compile the base
//! program (no fog, lightmap or texture matrices) is used instead, so a typo in the extended
//! shader costs those features rather than the whole fixed-function path.
//!
//! Draws made while a program is bound (1.17+) are never touched.

use crate::fixed_func::{self, ArraySnapshot};
use renderer_core::{Backend, BufferId, ProgramId, VertexArrayId};
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;

const GL_ARRAY_BUFFER: u32 = 0x8892;
const GL_ELEMENT_ARRAY_BUFFER: u32 = 0x8893;
const GL_STREAM_DRAW: u32 = 0x88E0;
const GL_STATIC_DRAW: u32 = 0x88E4;
const GL_UNSIGNED_SHORT: u32 = 0x1403;
const GL_VERTEX_ARRAY_BINDING: u32 = 0x85B5;
const GL_ARRAY_BUFFER_BINDING: u32 = 0x8894;
const GL_VERTEX_SHADER: u32 = 0x8B31;
const GL_FRAGMENT_SHADER: u32 = 0x8B30;
const GL_QUADS: u32 = 0x0007;
const GL_TRIANGLES: u32 = 0x0004;
const GL_UNSIGNED_INT: u32 = 0x1405;
const GL_ALPHA_TEST: u32 = 0x0BC0;

const VS_BASE: &str = "#version 300 es
layout(location = 0) in vec4 aPos;
layout(location = 1) in vec4 aColor;
layout(location = 2) in vec2 aUV;
uniform mat4 uMvp;
out vec4 vColor;
out vec2 vUV;
void main() {
    gl_Position = uMvp * aPos;
    vColor = aColor;
    vUV = aUV;
}
";

const FS_BASE: &str = "#version 300 es
precision highp float;
in vec4 vColor;
in vec2 vUV;
uniform sampler2D uTex;
uniform int uUseTex;
uniform int uAlphaFunc;
uniform float uAlphaRef;
out vec4 oColor;
void main() {
    vec4 c = vColor;
    if (uUseTex != 0) c *= texture(uTex, vUV);
    if (uAlphaFunc != 0) {
        int f = uAlphaFunc - 1;
        bool ok = true;
        if (f == 0) ok = false;
        else if (f == 1) ok = c.a < uAlphaRef;
        else if (f == 2) ok = c.a == uAlphaRef;
        else if (f == 3) ok = c.a <= uAlphaRef;
        else if (f == 4) ok = c.a > uAlphaRef;
        else if (f == 5) ok = c.a != uAlphaRef;
        else if (f == 6) ok = c.a >= uAlphaRef;
        if (!ok) discard;
    }
    oColor = c;
}
";

const VS_EXT: &str = "#version 300 es
layout(location = 0) in vec4 aPos;
layout(location = 1) in vec4 aColor;
layout(location = 2) in vec2 aUV;
layout(location = 3) in vec2 aLightUV;
uniform mat4 uMvp;
uniform mat4 uMv;
uniform mat4 uTexMat0;
uniform mat4 uTexMatLight;
out vec4 vColor;
out vec2 vUV;
out vec2 vLightUV;
out float vFogDist;
void main() {
    gl_Position = uMvp * aPos;
    vColor = aColor;
    vUV = (uTexMat0 * vec4(aUV, 0.0, 1.0)).xy;
    vLightUV = (uTexMatLight * vec4(aLightUV, 0.0, 1.0)).xy;
    vFogDist = abs((uMv * aPos).z);
}
";

const FS_EXT: &str = "#version 300 es
precision highp float;
in vec4 vColor;
in vec2 vUV;
in vec2 vLightUV;
in float vFogDist;
uniform sampler2D uTex;
uniform sampler2D uTexLight;
uniform int uUseTex;
uniform int uUseLight;
uniform int uAlphaFunc;
uniform float uAlphaRef;
uniform int uFogMode;
uniform vec4 uFogColor;
uniform vec4 uFogParams;
out vec4 oColor;
void main() {
    vec4 c = vColor;
    if (uUseTex != 0) c *= texture(uTex, vUV);
    if (uUseLight != 0) c.rgb *= texture(uTexLight, vLightUV).rgb;
    if (uAlphaFunc != 0) {
        int f = uAlphaFunc - 1;
        bool ok = true;
        if (f == 0) ok = false;
        else if (f == 1) ok = c.a < uAlphaRef;
        else if (f == 2) ok = c.a == uAlphaRef;
        else if (f == 3) ok = c.a <= uAlphaRef;
        else if (f == 4) ok = c.a > uAlphaRef;
        else if (f == 5) ok = c.a != uAlphaRef;
        else if (f == 6) ok = c.a >= uAlphaRef;
        if (!ok) discard;
    }
    if (uFogMode != 0) {
        float k = 1.0;
        if (uFogMode == 1) {
            k = (uFogParams.y - vFogDist) / max(uFogParams.y - uFogParams.x, 0.0001);
        } else if (uFogMode == 2) {
            k = exp(-uFogParams.z * vFogDist);
        } else {
            float d = uFogParams.z * vFogDist;
            k = exp(-d * d);
        }
        c.rgb = mix(uFogColor.rgb, c.rgb, clamp(k, 0.0, 1.0));
    }
    oColor = c;
}
";

struct Gpu {
    prog: ProgramId,
    vao: VertexArrayId,
    vbo: [BufferId; 4],
    ebo: BufferId,
    /// True for the extended program (fog, lightmap, texture matrices).
    extended: bool,
    loc_mv: i32,
    loc_tm0: i32,
    loc_tm_light: i32,
    loc_tex_light: i32,
    loc_use_light: i32,
    loc_fog_mode: i32,
    loc_fog_color: i32,
    loc_fog_params: i32,
    loc_mvp: i32,
    loc_tex: i32,
    loc_use_tex: i32,
    loc_afunc: i32,
    loc_aref: i32,
}

static GPU: Mutex<Option<Gpu>> = Mutex::new(None);
static DRAWS: AtomicU64 = AtomicU64::new(0);
static DIAG: AtomicU64 = AtomicU64::new(0);
static SUSPECT: AtomicU64 = AtomicU64::new(0);
static ERRS: AtomicU64 = AtomicU64::new(0);

/// Compiles and links one fixed-function program, logging (not panicking) on failure.
fn make_program(be: &dyn Backend, vs_src: &str, fs_src: &str, tag: &str) -> Option<ProgramId> {
    let vs = be
        .compile_shader(GL_VERTEX_SHADER, vs_src)
        .map_err(|e| crate::log(&format!("[FFDraw] {tag} vertex shader: {e}")))
        .ok()?;
    let fs = match be.compile_shader(GL_FRAGMENT_SHADER, fs_src) {
        Ok(f) => f,
        Err(e) => {
            crate::log(&format!("[FFDraw] {tag} fragment shader: {e}"));
            be.delete_shader(vs);
            return None;
        }
    };
    let prog = match be.link_program(&[vs, fs]) {
        Ok(p) => p,
        Err(e) => {
            crate::log(&format!("[FFDraw] {tag} link: {e}"));
            be.delete_shader(vs);
            be.delete_shader(fs);
            return None;
        }
    };
    be.delete_shader(vs);
    be.delete_shader(fs);
    Some(prog)
}

fn build(be: &dyn Backend) -> Option<Gpu> {
    let (prog, extended) = match make_program(be, VS_EXT, FS_EXT, "extended") {
        Some(p) => (p, true),
        None => {
            crate::log("[FFDraw] extended program failed; falling back to the base program (no fog, lightmap or texture matrices)");
            (make_program(be, VS_BASE, FS_BASE, "base")?, false)
        }
    };
    let vao = be.create_vertex_array().ok()?;
    let vbo = [
        be.create_buffer().ok()?,
        be.create_buffer().ok()?,
        be.create_buffer().ok()?,
        be.create_buffer().ok()?,
    ];
    let ebo = be.create_buffer().ok()?;
    let loc = |n: &str| be.uniform_location(prog, n).unwrap_or(-1);
    crate::log(&format!(
        "[FFDraw] fixed-function emulation program ready ({})",
        if extended { "extended: fog, lightmap, texture matrices" } else { "base" }
    ));
    Some(Gpu {
        prog,
        vao,
        vbo,
        ebo,
        extended,
        loc_mv: loc("uMv"),
        loc_tm0: loc("uTexMat0"),
        loc_tm_light: loc("uTexMatLight"),
        loc_tex_light: loc("uTexLight"),
        loc_use_light: loc("uUseLight"),
        loc_fog_mode: loc("uFogMode"),
        loc_fog_color: loc("uFogColor"),
        loc_fog_params: loc("uFogParams"),
        loc_mvp: loc("uMvp"),
        loc_tex: loc("uTex"),
        loc_use_tex: loc("uUseTex"),
        loc_afunc: loc("uAlphaFunc"),
        loc_aref: loc("uAlphaRef"),
    })
}

/// Enabled lightmap unit, including entity draws that use a constant coordinate
/// rather than a UV array. Unit 2 is preferred for 1.15/1.16; older games use 1.
fn lightmap_unit(enabled: impl Fn(usize) -> bool) -> Option<usize> {
    [2usize, 1usize].into_iter().find(|&u| enabled(u))
}

fn type_size(ty: u32) -> usize {
    match ty {
        0x1400 | 0x1401 => 1, // BYTE, UNSIGNED_BYTE
        0x1402 | 0x1403 => 2, // SHORT, UNSIGNED_SHORT
        _ => 4,               // INT, UNSIGNED_INT, FLOAT
    }
}

/// Points attribute `idx` at array `a`, rebased so vertex `first` becomes vertex 0.
/// Returns false if the array is unusable (caller then uses a constant value).
fn setup_attrib(be: &dyn Backend, idx: u32, a: &ArraySnapshot, vbo: BufferId, first: i32, count: i32, normalized: bool) -> bool {
    if !a.enabled || a.size <= 0 || a.size > 4 {
        return false;
    }
    let elem = a.size as usize * type_size(a.ty);
    let stride = if a.stride > 0 { a.stride as usize } else { elem };
    let skip = first as usize * stride;
    if a.buffer != 0 {
        be.bind_buffer(GL_ARRAY_BUFFER, Some(BufferId(a.buffer)));
        be.vertex_attrib_pointer(idx, a.size, a.ty, normalized, a.stride, a.ptr + skip);
    } else {
        if a.ptr == 0 {
            return false;
        }
        let len = (count as usize - 1) * stride + elem;
        // SAFETY: client-array memory is owned by the game and must stay valid until the
        // draw call returns (GL contract); we copy exactly the bytes the draw will read.
        let src = unsafe { std::slice::from_raw_parts((a.ptr + skip) as *const u8, len) };
        be.bind_buffer(GL_ARRAY_BUFFER, Some(vbo));
        if be.buffer_data(GL_ARRAY_BUFFER, src, GL_STREAM_DRAW).is_err() {
            return false;
        }
        be.vertex_attrib_pointer(idx, a.size, a.ty, normalized, a.stride, 0);
    }
    be.set_vertex_attrib_enabled(idx, true);
    true
}

fn restore(be: &dyn Backend, prev_vao: i32, prev_abuf: i32) {
    be.use_program(None);
    be.bind_vertex_array(if prev_vao > 0 { Some(VertexArrayId(prev_vao as u32)) } else { None });
    be.bind_buffer(GL_ARRAY_BUFFER, if prev_abuf > 0 { Some(BufferId(prev_abuf as u32)) } else { None });
}

/// Returns true if the draw was handled here.
///
/// # Safety
/// Reads raw client-array memory recorded by `glVertexPointer` and friends.
pub unsafe fn try_draw_arrays(mode: u32, first: i32, count: i32) -> bool {
    if count <= 0 || first < 0 {
        return false;
    }
    let be = match crate::backend() {
        Some(b) => b,
        None => return false,
    };
    type GetInt = unsafe extern "C" fn(u32, *mut i32);
    let get_int = match crate::driver_fn_cached::<GetInt>("glGetIntegerv") {
        Some(f) => f,
        None => return false,
    };
    // Tracked by glUseProgram instead of queried: this runs on every glDrawArrays, and a
    // driver query per draw is exactly the overhead the weakest devices cannot absorb.
    let cur = crate::current_program();
    if cur != 0 {
        // The game runs its own shader. Legacy shader packs (OptiFine) draw with the
        // fixed-function arrays and read gl_Vertex / gl_ModelViewProjectionMatrix, so the
        // arrays and matrices still have to be fed - see draw_arrays_with_program.
        return draw_arrays_with_program(be, mode, first, count, cur);
    }
    let (pos, col, uv) = fixed_func::arrays();
    if !pos.enabled {
        return false;
    }

    let mut guard = GPU.lock().unwrap_or_else(|e| e.into_inner());
    if guard.is_none() {
        *guard = build(be);
    }
    let gpu = match guard.as_ref() {
        Some(g) => g,
        None => return false,
    };

    let n = DRAWS.fetch_add(1, Ordering::Relaxed);
    if (n == 0 || n % 10000 == 0) && std::env::var("RENDERER_DEBUG").map(|v| v == "1").unwrap_or(false) {
        crate::log(&format!(
            "[FFDraw] draw #{n}: mode=0x{mode:04X} first={first} count={count} pos(size={} ty=0x{:04X} stride={} vbo={}) color={} uv={}",
            pos.size, pos.ty, pos.stride, pos.buffer, col.enabled, uv.enabled
        ));
    }

    let mut prev_vao = 0i32;
    let mut prev_abuf = 0i32;
    get_int(GL_VERTEX_ARRAY_BINDING, &mut prev_vao);
    get_int(GL_ARRAY_BUFFER_BINDING, &mut prev_abuf);

    be.bind_vertex_array(Some(gpu.vao));
    if !setup_attrib(be, 0, &pos, gpu.vbo[0], first, count, false) {
        restore(be, prev_vao, prev_abuf);
        return false;
    }
    type Attrib4f = unsafe extern "C" fn(u32, f32, f32, f32, f32);
    let attrib4f = crate::driver_fn_cached::<Attrib4f>("glVertexAttrib4f");

    let has_color = setup_attrib(be, 1, &col, gpu.vbo[1], first, count, true);
    if !has_color {
        be.set_vertex_attrib_enabled(1, false);
        if let Some(f) = attrib4f {
            let c = fixed_func::current_color();
            f(1, c[0], c[1], c[2], c[3]);
        }
    }
    let has_uv = setup_attrib(be, 2, &uv, gpu.vbo[2], first, count, false);
    if !has_uv {
        be.set_vertex_attrib_enabled(2, false);
        if let Some(f) = attrib4f {
            let uv = fixed_func::current_texcoord(0);
            f(2, uv[0], uv[1], 0.0, 1.0);
        }
    }

    // Lightmap: UV array or current coordinate on an enabled unit 1/2.
    let mut light_unit: Option<usize> = None;
    if gpu.extended {
        light_unit = lightmap_unit(fixed_func::unit_texture_enabled);
        if let Some(u) = light_unit {
            let a = fixed_func::texcoord_unit(u);
            if !setup_attrib(be, 3, &a, gpu.vbo[3], first, count, false) {
                be.set_vertex_attrib_enabled(3, false);
                if let Some(f) = attrib4f {
                    let uv = fixed_func::current_texcoord(u);
                    f(3, uv[0], uv[1], 0.0, 1.0);
                }
            }
        }
        if light_unit.is_none() {
            be.set_vertex_attrib_enabled(3, false);
            if let Some(f) = attrib4f {
                f(3, 0.0, 0.0, 0.0, 1.0);
            }
        }
    }

    // The sampler always reads unit 0, regardless of the last active server unit.
    // A bound texture is not an enable bit: legacy GUI passes disable texturing
    // while leaving the atlas bound. Sampling it then paints the wrong fullscreen quad.
    let use_tex = fixed_func::unit_texture_enabled(0);
    let (afunc, aref) = fixed_func::alpha();
    let alpha_mode = if fixed_func::legacy_cap_enabled(GL_ALPHA_TEST) && (0x200..=0x207).contains(&afunc) {
        (afunc - 0x200 + 1) as i32
    } else {
        0
    };

    let d = DIAG.fetch_add(1, Ordering::Relaxed);
    let suspect = !use_tex && !has_color;
    if std::env::var("RENDERER_DEBUG").map(|v| v == "1").unwrap_or(false)
        && (d < 20 || (suspect && SUSPECT.fetch_add(1, Ordering::Relaxed) < 10))
    {
        let c = fixed_func::current_color();
        crate::log(&format!(
            "[FFDraw] diag #{d}: mode=0x{mode:04X} count={count} tex={use_tex} color_array={has_color} uv_array={has_uv} alpha_mode={alpha_mode} cur_color=({:.2},{:.2},{:.2},{:.2})",
            c[0], c[1], c[2], c[3]
        ));
    }

    be.use_program(Some(gpu.prog));
    be.uniform_matrix_4(gpu.loc_mvp, &fixed_func::mvp_matrix(), false);
    be.uniform_1i(gpu.loc_tex, 0);
    be.uniform_1i(gpu.loc_use_tex, use_tex as i32);
    be.uniform_1i(gpu.loc_afunc, alpha_mode);
    be.uniform_1f(gpu.loc_aref, aref);
    if gpu.extended {
        be.uniform_matrix_4(gpu.loc_mv, &fixed_func::modelview_matrix(), false);
        be.uniform_matrix_4(gpu.loc_tm0, &fixed_func::texture_matrix(0), false);
        match light_unit {
            Some(u) => {
                be.uniform_matrix_4(gpu.loc_tm_light, &fixed_func::texture_matrix(u), false);
                be.uniform_1i(gpu.loc_tex_light, u as i32);
                be.uniform_1i(gpu.loc_use_light, 1);
            }
            None => {
                be.uniform_matrix_4(gpu.loc_tm_light, &fixed_func::texture_matrix(0), false);
                be.uniform_1i(gpu.loc_tex_light, 1);
                be.uniform_1i(gpu.loc_use_light, 0);
            }
        }
        match fixed_func::fog() {
            Some(f) => {
                be.uniform_1i(gpu.loc_fog_mode, f.mode);
                be.uniform_4f(gpu.loc_fog_color, f.color[0], f.color[1], f.color[2], f.color[3]);
                be.uniform_4f(gpu.loc_fog_params, f.start, f.end, f.density, 0.0);
            }
            None => be.uniform_1i(gpu.loc_fog_mode, 0),
        }
    }

    if mode == GL_QUADS {
        let quads = (count / 4) as usize;
        if let Some((buf, ty, need)) = quad_indices(be, quads) {
            be.bind_buffer(GL_ELEMENT_ARRAY_BUFFER, Some(buf));
            be.draw_elements(GL_TRIANGLES, need, ty, 0);
        }
    } else {
        be.draw_arrays(mode, 0, count);
    }

    sample_draw_error(be, "legacy", mode, count);

    restore(be, prev_vao, prev_abuf);
    // Restore the game's program (0 = fixed-function / none).
    if cur != 0 {
        be.use_program(Some(ProgramId(cur)));
    } else {
        be.use_program(None);
    }
    true
}

/// Index buffers for the `GL_QUADS` expansion: a 16-bit and a 32-bit one, each created on
/// first use and only ever grown.
///
/// 16-bit indices wherever the vertex count allows: half the index bandwidth of a 32-bit
/// index on every quad draw, and a GE8300-class part is bandwidth bound long before it is
/// ALU bound. Minecraft 1.12.2 and older draw chunks, the GUI and the debug overlay as
/// quads, so this is the common case on exactly the version range the weakest devices run.
/// The buffer is uploaded once and read many times, hence `GL_STATIC_DRAW` and not the
/// `GL_STREAM_DRAW` a per-draw upload would want.
static QUAD_INDICES_16: Mutex<Option<(BufferId, usize)>> = Mutex::new(None);
static QUAD_INDICES_32: Mutex<Option<(BufferId, usize)>> = Mutex::new(None);

/// Returns the buffer, the index type and the index count for `quads` quads.
unsafe fn quad_indices(be: &dyn Backend, quads: usize) -> Option<(BufferId, u32, i32)> {
    let need = quads * 6;
    if quads * 4 <= u16::MAX as usize {
        let mut slot = QUAD_INDICES_16.lock().unwrap_or_else(|e| e.into_inner());
        let (buf, have) = match *slot {
            Some(cached) => cached,
            None => (be.create_buffer().ok()?, 0usize),
        };
        if have < need {
            let mut idx: Vec<u16> = Vec::with_capacity(need);
            for q in 0..quads {
                let b = (q * 4) as u16;
                idx.extend_from_slice(&[b, b + 1, b + 2, b, b + 2, b + 3]);
            }
            // SAFETY: reinterpreting a live Vec<u16> as bytes (same allocation, len * 2).
            let bytes = std::slice::from_raw_parts(idx.as_ptr() as *const u8, idx.len() * 2);
            be.bind_buffer(GL_ELEMENT_ARRAY_BUFFER, Some(buf));
            be.buffer_data(GL_ELEMENT_ARRAY_BUFFER, bytes, GL_STATIC_DRAW).ok()?;
            *slot = Some((buf, need));
        }
        Some((buf, GL_UNSIGNED_SHORT, need as i32))
    } else {
        let mut slot = QUAD_INDICES_32.lock().unwrap_or_else(|e| e.into_inner());
        let (buf, have) = match *slot {
            Some(cached) => cached,
            None => (be.create_buffer().ok()?, 0usize),
        };
        if have < need {
            let mut idx: Vec<u32> = Vec::with_capacity(need);
            for q in 0..quads {
                let b = (q * 4) as u32;
                idx.extend_from_slice(&[b, b + 1, b + 2, b, b + 2, b + 3]);
            }
            // SAFETY: reinterpreting a live Vec<u32> as bytes (same allocation, len * 4).
            let bytes = std::slice::from_raw_parts(idx.as_ptr() as *const u8, idx.len() * 4);
            be.bind_buffer(GL_ELEMENT_ARRAY_BUFFER, Some(buf));
            be.buffer_data(GL_ELEMENT_ARRAY_BUFFER, bytes, GL_STATIC_DRAW).ok()?;
            *slot = Some((buf, need));
        }
        Some((buf, GL_UNSIGNED_INT, need as i32))
    }
}

/// Draws are only error-checked every 256th call.
///
/// `glGetError` has to flush the driver's pending work to collect errors, which on a
/// tile-based GPU means draining tile memory - once per draw that is a stall per draw.
/// Sampling costs a 256th of that and still reports a persistent error within a frame or
/// two; the trade is that the error reported by a sample may have been raised by an earlier
/// draw, which is acceptable for a diagnostic that exists to point at the failing path.
static ERROR_SAMPLES: AtomicU64 = AtomicU64::new(0);

#[cold]
#[inline(never)]
fn report_draw_error(be: &dyn Backend, tag: &str, mode: u32, count: i32) {
    let err = be.get_error();
    if err != 0 && ERRS.fetch_add(1, Ordering::Relaxed) < 20 {
        crate::log(&format!(
            "[FFDraw] GL error 0x{err:04X} after a {tag} draw mode=0x{mode:04X} count={count}"
        ));
    }
}

fn sample_draw_error(be: &dyn Backend, tag: &str, mode: u32, count: i32) {
    let n = ERROR_SAMPLES.fetch_add(1, Ordering::Relaxed);
    if n == 0 || n % 256 == 0 {
        report_draw_error(be, tag, mode, count);
    }
}

/// Attribute and uniform locations of the legacy fixed-function builtins in a linked program.
///
/// Cached per program: `glGetAttribLocation` / `glGetUniformLocation` are cheap once, but
/// running a dozen of them on every draw is not, and the weakest devices this renderer
/// targets cannot spare a driver round trip per draw call.
#[derive(Clone, Copy)]
struct LegacyLocations {
    position: i32,
    normal: i32,
    color: i32,
    texcoord: [i32; 4],
    mvp: i32,
    modelview: i32,
    projection: i32,
    normal_matrix: i32,
    texture_matrix: [i32; 4],
}

impl LegacyLocations {
    fn feeds_anything(&self) -> bool {
        self.position >= 0
            || self.normal >= 0
            || self.color >= 0
            || self.mvp >= 0
            || self.modelview >= 0
            || self.projection >= 0
            || self.normal_matrix >= 0
            || self.texcoord.iter().any(|l| *l >= 0)
            || self.texture_matrix.iter().any(|l| *l >= 0)
    }
}

static LEGACY_LOCS: Mutex<Option<HashMap<u32, LegacyLocations>>> = Mutex::new(None);

/// Forgets the cached builtin locations of `program`. Called when it is relinked or deleted:
/// a re-linked program does not keep its old locations.
pub fn forget_legacy_locations(program: u32) {
    let mut guard = LEGACY_LOCS.lock().unwrap_or_else(|e| e.into_inner());
    if let Some(map) = guard.as_mut() {
        map.remove(&program);
    }
}

/// Resolves the builtin locations of `program` once, then caches them.
fn legacy_locations(program: u32) -> Option<LegacyLocations> {
    {
        let guard = LEGACY_LOCS.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(map) = guard.as_ref() {
            if let Some(locs) = map.get(&program) {
                return Some(*locs);
            }
        }
    }
    let be = crate::backend()?;
    type AttribLoc = unsafe extern "C" fn(u32, *const std::ffi::c_char) -> i32;
    let attrib = crate::driver_fn_cached::<AttribLoc>("glGetAttribLocation")?;
    let attrib_of = |name: &str| -> i32 {
        match std::ffi::CString::new(name) {
            // glGetAttribLocation: the pointer is valid for the call and the name is NUL
            // terminated by CString. -1 is the "not present" answer, not an error to log.
            Ok(c) => unsafe { attrib(program, c.as_ptr()) },
            Err(_) => -1,
        }
    };
    let uniform_of = |name: &str| -> i32 {
        be.uniform_location(ProgramId(program), name).unwrap_or(-1)
    };
    let mut texcoord = [-1i32; 4];
    for (i, entry) in shader_translate::LEGACY_TEXCOORD_ATTRIBS.iter().enumerate() {
        texcoord[i] = attrib_of(entry.0);
    }
    let mut texture_matrix = [-1i32; 4];
    for (i, name) in shader_translate::LEGACY_TEXTURE_MATRIX_UNIFORMS.iter().enumerate() {
        texture_matrix[i] = uniform_of(name);
    }
    let locs = LegacyLocations {
        position: attrib_of(shader_translate::LEGACY_POSITION_ATTRIB.0),
        normal: attrib_of(shader_translate::LEGACY_NORMAL_ATTRIB.0),
        color: attrib_of(shader_translate::LEGACY_COLOR_ATTRIB.0),
        texcoord,
        mvp: uniform_of(shader_translate::LEGACY_MVP_UNIFORM),
        modelview: uniform_of(shader_translate::LEGACY_MODELVIEW_UNIFORM),
        projection: uniform_of(shader_translate::LEGACY_PROJECTION_UNIFORM),
        normal_matrix: uniform_of(shader_translate::LEGACY_NORMAL_MATRIX_UNIFORM),
        texture_matrix,
    };
    let mut guard = LEGACY_LOCS.lock().unwrap_or_else(|e| e.into_inner());
    guard.get_or_insert_with(HashMap::new).insert(program, locs);
    Some(locs)
}

/// Buffers for the arrays the legacy-shader path uploads, created once.
static LEGACY_BUFFERS: Mutex<Option<([BufferId; 4], BufferId)>> = Mutex::new(None);

fn legacy_buffers(be: &dyn Backend) -> Option<([BufferId; 4], BufferId)> {
    let mut guard = LEGACY_BUFFERS.lock().unwrap_or_else(|e| e.into_inner());
    if let Some(buffers) = *guard {
        return Some(buffers);
    }
    let vbo = [
        be.create_buffer().ok()?,
        be.create_buffer().ok()?,
        be.create_buffer().ok()?,
        be.create_buffer().ok()?,
    ];
    let ebo = be.create_buffer().ok()?;
    *guard = Some((vbo, ebo));
    Some((vbo, ebo))
}

/// Draws the tracked fixed-function arrays with the game's own program.
///
/// OptiFine (and any other shader that runs while the game still draws with `glVertexPointer`
/// / `glColorPointer`) reads `gl_Vertex`, `gl_MultiTexCoord0` and
/// `gl_ModelViewProjectionMatrix`. GLSL ES has none of them, so shader-translate renamed them
/// onto `rust_gl_*` attributes and uniforms; this looks those up and feeds the client arrays
/// and the current matrix stacks, which is what a desktop compatibility profile does.
///
/// Returns false when the program declares none of them - that is a modern shader drawing its
/// own buffers, which this path must not touch.
unsafe fn draw_arrays_with_program(
    be: &dyn Backend,
    mode: u32,
    first: i32,
    count: i32,
    program: u32,
) -> bool {
    let locs = match legacy_locations(program) {
        Some(locs) if locs.feeds_anything() => locs,
        _ => return false,
    };
    let (vbo, _ebo) = match legacy_buffers(be) {
        Some(buffers) => buffers,
        None => return false,
    };
    let (pos, col, _uv) = fixed_func::arrays();
    let normal = fixed_func::normal_array();
    if !pos.enabled && !col.enabled && !normal.enabled && !fixed_func::texcoord_unit(0).enabled {
        return false;
    }

    type GetInt = unsafe extern "C" fn(u32, *mut i32);
    let get_int = match crate::driver_fn_cached::<GetInt>("glGetIntegerv") {
        Some(f) => f,
        None => return false,
    };
    let mut prev_abuf = 0i32;
    get_int(GL_ARRAY_BUFFER_BINDING, &mut prev_abuf);

    type Attrib4f = unsafe extern "C" fn(u32, f32, f32, f32, f32);
    let attrib4f = crate::driver_fn_cached::<Attrib4f>("glVertexAttrib4f");

    if locs.position >= 0 && pos.enabled {
        setup_attrib(be, locs.position as u32, &pos, vbo[0], first, count, false);
    }
    if locs.color >= 0 {
        if col.enabled {
            setup_attrib(be, locs.color as u32, &col, vbo[1], first, count, true);
        } else {
            be.set_vertex_attrib_enabled(locs.color as u32, false);
            if let Some(f) = attrib4f {
                let c = fixed_func::current_color();
                f(locs.color as u32, c[0], c[1], c[2], c[3]);
            }
        }
    }
    if locs.normal >= 0 && normal.enabled {
        setup_attrib(be, locs.normal as u32, &normal, vbo[2], first, count, false);
    }
    for (unit, loc) in locs.texcoord.iter().enumerate() {
        if *loc < 0 || unit > 2 {
            continue;
        }
        let array = fixed_func::texcoord_unit(unit);
        if array.enabled {
            setup_attrib(be, *loc as u32, &array, vbo[3], first, count, false);
        } else {
            be.set_vertex_attrib_enabled(*loc as u32, false);
            if let Some(f) = attrib4f {
                let t = fixed_func::current_texcoord(unit);
                f(*loc as u32, t[0], t[1], 0.0, 1.0);
            }
        }
    }

    // Matrices: gl-compat tracks the stacks the game loaded, so feed them the same way a
    // compatibility profile would. gl_NormalMatrix gets the upper left 3x3 of the modelview:
    // exact for the rotations and uniform scales Minecraft uses, and an inverse transpose
    // per draw is not worth it on the hardware at the bottom of the range.
    if locs.mvp >= 0 {
        be.uniform_matrix_4(locs.mvp, &fixed_func::mvp_matrix(), false);
    }
    if locs.modelview >= 0 {
        be.uniform_matrix_4(locs.modelview, &fixed_func::modelview_matrix(), false);
    }
    if locs.projection >= 0 {
        if let Some(p) = fixed_func::matrix_for_pname(0x0BA7) {
            be.uniform_matrix_4(locs.projection, &p, false);
        }
    }
    if locs.normal_matrix >= 0 {
        let mv = fixed_func::modelview_matrix();
        let m3 = [mv[0], mv[1], mv[2], mv[4], mv[5], mv[6], mv[8], mv[9], mv[10]];
        type Uniform3 = unsafe extern "C" fn(i32, i32, u8, *const f32);
        if let Some(f) = crate::driver_fn_cached::<Uniform3>("glUniformMatrix3fv") {
            f(locs.normal_matrix, 1, 0, m3.as_ptr());
        }
    }
    for (unit, loc) in locs.texture_matrix.iter().enumerate() {
        if *loc >= 0 {
            be.uniform_matrix_4(*loc, &fixed_func::texture_matrix(unit), false);
        }
    }

    if mode == GL_QUADS {
        let quads = (count / 4) as usize;
        if let Some((buf, ty, need)) = quad_indices(be, quads) {
            be.bind_buffer(GL_ELEMENT_ARRAY_BUFFER, Some(buf));
            be.draw_elements(GL_TRIANGLES, need, ty, 0);
        }
    } else {
        be.draw_arrays(mode, 0, count);
    }

    sample_draw_error(be, "legacy-shader", mode, count);
    be.bind_buffer(
        GL_ARRAY_BUFFER,
        if prev_abuf > 0 { Some(BufferId(prev_abuf as u32)) } else { None },
    );
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lightmap_prefers_unit_two_then_one() {
        // 1.16: overlay on unit 1, lightmap on unit 2.
        assert_eq!(lightmap_unit(|_| true), Some(2));
        // 1.12-1.14: lightmap on unit 1 only.
        assert_eq!(lightmap_unit(|u| u == 1), Some(1));
        // A UV array without an enabled texture is not a lightmap.
        assert_eq!(lightmap_unit(|_| false), None);
        assert_eq!(lightmap_unit(|_| true), Some(2));
    }

    #[test]
    fn extended_shaders_declare_every_uniform_the_draw_sets() {
        for u in ["uMvp", "uMv", "uTexMat0", "uTexMatLight"] {
            assert!(VS_EXT.contains(u), "{u}");
        }
        for u in ["uTex", "uTexLight", "uUseTex", "uUseLight", "uAlphaFunc", "uAlphaRef",
                  "uFogMode", "uFogColor", "uFogParams"] {
            assert!(FS_EXT.contains(u), "{u}");
        }
        // The attribute locations the draw path binds.
        assert!(VS_EXT.contains("location = 3) in vec2 aLightUV"));
    }
}
