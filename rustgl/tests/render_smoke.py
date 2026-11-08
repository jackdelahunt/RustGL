#!/usr/bin/env python3
"""Headless GLES rendering through the actual RustGL cdylib (not a mock).

Run after cargo build -p gl-compat on Linux with Mesa EGL/GLES installed:
  EGL_PLATFORM=surfaceless LIBGL_ALWAYS_SOFTWARE=1 python3 tests/render_smoke.py
A separate invocation with MESA_EXTENSION_OVERRIDE=-GL_EXT_buffer_storage exercises
ordinary ES buffer-storage fallback. These are regression probes, not a full game test.
"""
import ctypes as C
import os
from pathlib import Path
import re
import sys

os.environ.setdefault('EGL_PLATFORM', 'surfaceless')
os.environ.setdefault('LIBGL_ALWAYS_SOFTWARE', '1')
root = Path(__file__).resolve().parents[1]
lib = C.CDLL(str(root / 'target/debug/librust_gl.so'), mode=C.RTLD_LOCAL)
P, U, I, F, Z = C.c_void_p, C.c_uint, C.c_int, C.c_float, C.c_ssize_t

def direct(name, result, *args):
    f = getattr(lib, name)
    f.restype, f.argtypes = result, args
    return f

resolve = direct('eglGetProcAddress', P, C.c_char_p)

def gl(name, result, *args):
    address = resolve(name.encode())
    assert address, name
    return C.CFUNCTYPE(result, *args)(address)

def ints(*values):
    return (I * len(values))(*values)

# Use the exported EGL bridge exactly as the launcher does, with a small pbuffer.
dpy = direct('eglGetDisplay', P, P)(None)
assert dpy
assert direct('eglInitialize', U, P, P, P)(dpy, None, None)
assert direct('eglBindAPI', U, U)(0x30A0)
config, count = P(), I()
attrs = ints(0x3033, 1, 0x3040, 0x40, 0x3024, 8, 0x3023, 8, 0x3022, 8, 0x3021, 8, 0x3038)
assert direct('eglChooseConfig', U, P, P, P, I, P)(dpy, attrs, C.byref(config), 1, C.byref(count))
assert count.value
surface = direct('eglCreatePbufferSurface', P, P, P, P)(dpy, config, ints(0x3057, 16, 0x3056, 16, 0x3038))
ctx = direct('eglCreateContext', P, P, P, P, P)(dpy, config, None, ints(0x3098, 3, 0x3038))
assert ctx and surface
assert direct('eglMakeCurrent', U, P, P, P, P)(dpy, surface, surface, ctx)
get_error = gl('glGetError', U)

def no_error(label):
    error = get_error()
    assert error == 0, f'{label}: GL error 0x{error:04x}'

# RTLD_LOCAL must not cause display lists/legacy state/query exports to resolve to
# system EGL's unsupported function stubs. Check identity, not merely non-nullness.
for name in ['glGenLists', 'glNewList', 'glCallList', 'glGetFloatv', 'glTexEnvi', 'glLinkProgram']:
    assert resolve(name.encode()) == C.cast(getattr(lib, name), P).value, name
print('PASS: exported compatibility functions win under RTLD_LOCAL', flush=True)

# Extension pointers must refer to renderer-owned stable memory, not freed clones.
get_i = gl('glGetIntegerv', None, U, P)
get_si = gl('glGetStringi', P, U, U)
n = I()
get_i(0x821D, C.byref(n))
assert n.value > 0
for index in range(n.value):
    a = get_si(0x1F03, index)
    name = C.string_at(a)
    assert name.startswith(b'GL_'), (index, name)
    # Exercise queries/allocations between uses of the original pointer.
    get_i(0x821D, C.byref(n))
    b = get_si(0x1F03, index)
    assert a == b and C.string_at(a) == name, (index, name)
no_error('extension queries')
print('PASS: stable extension pointers', flush=True)

create_shader = gl('glCreateShader', U, U)
source = gl('glShaderSource', None, U, I, P, P)
compile_shader = gl('glCompileShader', None, U)
shader_iv = gl('glGetShaderiv', None, U, U, P)
shader_log = gl('glGetShaderInfoLog', None, U, I, P, P)
delete_shader = gl('glDeleteShader', None, U)

def compile_src(text, stage, label, expect_success=True):
    shader = create_shader(stage)
    strings = (C.c_char_p * 1)(text.encode())
    source(shader, 1, strings, None)
    compile_shader(shader)
    ok, size = I(), I()
    shader_iv(shader, 0x8B81, C.byref(ok))
    shader_iv(shader, 0x8B84, C.byref(size))
    log = C.create_string_buffer(max(size.value, 1))
    shader_log(shader, len(log), None, log)
    assert bool(ok.value) == expect_success, f'{label}: {log.value.decode(errors="replace")}'
    return shader

fixtures = (root / 'crates/shader-translate/tests/mc_shader_fixtures.rs').read_text()
fixture_count = 0
for match in re.finditer(r'const (\w+): &str = r(#?)"(.*?)"\2;', fixtures, re.S):
    fixture_count += 1
    name, _, text = match.groups()
    # A fixture whose name carries _VSH is a vertex shader; everything else is a fragment
    # shader. (The suffix is part of the contract with the fixture file.)
    stage = 0x8B31 if '_VSH' in name else 0x8B30
    shader = compile_src(text, stage, name)
    delete_shader(shader)
    print(f'PASS: GLES compile {name}', flush=True)
assert fixture_count == 20, f'Expected all twenty shader fixtures, found {fixture_count}'
shader = compile_src('#version 330\nvoid main(){ EmitVertex(); }', 0x8B31,
                     'unsupported stage must fail instead of becoming a blank shader', False)
delete_shader(shader)
no_error('fixture compiles')

viewport = gl('glViewport', None, I, I, I, I)
clear_color = gl('glClearColor', None, F, F, F, F)
clear = gl('glClear', None, U)
read_pixels = gl('glReadPixels', None, I, I, I, I, U, U, P)
viewport(0, 0, 16, 16)

def background():
    clear_color(0, 0, 0, 1)
    clear(0x4000)

def pixel(expected, label):
    data = (C.c_ubyte * 4)()
    read_pixels(8, 8, 1, 1, 0x1908, 0x1401, data)
    no_error(label)
    assert all(abs(a-b) <= 2 for a, b in zip(data, expected)), f'{label}: {list(data)} != {expected}'
    print(f'PASS: {label}: {list(data)}', flush=True)

# Old Minecraft: client arrays + quads + matrix stack + texture enable/disable.
positions = (F * 12)(-1,-1,0, 1,-1,0, 1,1,0, -1,1,0)
uvs = (F * 8)(0,0, 1,0, 1,1, 0,1)
mat_mode = gl('glMatrixMode', None, U)
identity = gl('glLoadIdentity', None)
for mode in (0x1700, 0x1701):
    mat_mode(mode)
    identity()
matrix = (F * 16)()
gl('glGetFloatv', None, U, P)(0x0BA7, matrix)
assert list(matrix) == [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
gl('glEnableClientState', None, U)(0x8074)
gl('glEnableClientState', None, U)(0x8078)
gl('glVertexPointer', None, I, U, I, P)(3, 0x1406, 0, positions)
gl('glTexCoordPointer', None, I, U, I, P)(2, 0x1406, 0, uvs)
gl('glColor4f', None, F,F,F,F)(1,1,1,1)
texture = U()
gl('glGenTextures', None, I, P)(1, C.byref(texture))
gl('glBindTexture', None, U,U)(0x0DE1, texture.value)
texel = (C.c_ubyte * 4)(0,255,0,255)
gl('glTexImage2D', None, U,I,I,I,I,I,U,U,P)(0x0DE1,0,0x8058,1,1,0,0x1908,0x1401,texel)
param = gl('glTexParameteri', None, U,U,I)
param(0x0DE1,0x2801,0x2600)
param(0x0DE1,0x2800,0x2600)
enable, disable = gl('glEnable', None, U), gl('glDisable', None, U)
active = gl('glActiveTexture', None, U)
draw = gl('glDrawArrays', None, U,I,I)
enable(0x0DE1)
# Active server unit 1 must not affect sampling/enabling of unit 0.
active(0x84C1)
disable(0x0DE1)
background()
draw(7,0,4)
pixel((0,255,0,255), 'legacy textured quad with active unit 1')
active(0x84C0)
disable(0x0DE1)
background()
draw(7,0,4)
pixel((255,255,255,255), 'legacy disabled texture remains untextured despite bound atlas')

# Java-8-era entity lighting: current multitexture coordinate, no lightmap array.
light = U()
active(0x84C1)
gl('glGenTextures', None, I, P)(1, C.byref(light))
gl('glBindTexture', None, U,U)(0x0DE1, light.value)
light_pixels = (C.c_ubyte * 8)(255,0,0,255, 0,255,0,255)
gl('glTexImage2D', None, U,I,I,I,I,I,U,U,P)(0x0DE1,0,0x8058,2,1,0,0x1908,0x1401,light_pixels)
param(0x0DE1,0x2801,0x2600)
param(0x0DE1,0x2800,0x2600)
enable(0x0DE1)
client_active = gl('glClientActiveTexture', None,U)
client_active(0x84C1)
gl('glDisableClientState', None,U)(0x8078)
multi_uv = gl('glMultiTexCoord2f', None,U,F,F)
for u, expected in [(0.25,(255,0,0,255)), (0.75,(0,255,0,255))]:
    multi_uv(0x84C1,u,0.5)
    background()
    draw(7,0,4)
    pixel(expected, f'legacy constant lightmap coordinate {u}')
disable(0x0DE1)
active(0x84C0)
client_active(0x84C0)

# Modern Minecraft: translated #version 330 shader with a std140 UBO. Use a
# fullscreen triangle generated from gl_VertexID to isolate UBO updates from vertex setup.
vs = compile_src('''#version 330
layout(std140) uniform DynamicTransforms { mat4 ModelViewMat; vec4 ColorModulator; };
out vec4 vertexColor;
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    gl_Position = ModelViewMat * vec4(p * 2.0 - 1.0, 0.0, 1.0);
    vertexColor = ColorModulator;
}
''', 0x8B31, 'UBO VS')
fs = compile_src('''#version 330
in vec4 vertexColor;
out vec4 fragColor;
void main(){ fragColor = vertexColor; }
''', 0x8B30, 'UBO FS')
program = gl('glCreateProgram', U)()
attach = gl('glAttachShader', None, U,U)
attach(program,vs)
attach(program,fs)
gl('glLinkProgram', None,U)(program)
status = I()
gl('glGetProgramiv', None,U,U,P)(program,0x8B82,C.byref(status))
assert status.value, 'UBO shader link failed'
gl('glUseProgram', None,U)(program)
vao = U()
gl('glGenVertexArrays', None,I,P)(1,C.byref(vao))
gl('glBindVertexArray', None,U)(vao.value)
block = gl('glGetUniformBlockIndex',U,U,C.c_char_p)(program,b'DynamicTransforms')
assert block != 0xffffffff
gl('glUniformBlockBinding',None,U,U,U)(program,block,0)
bind_buffer = gl('glBindBuffer',None,U,U)
bind_base = gl('glBindBufferBase',None,U,U,U)
subdata = gl('glBufferSubData',None,U,Z,Z,P)
values = (F * 20)(1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1, 1,0,0,1)
for allocation in ("mutable", "immutable", "named immutable"):
    immutable = allocation != "mutable"
    ubo = U()
    gl('glGenBuffers',None,I,P)(1,C.byref(ubo))
    bind_buffer(0x8A11,ubo.value)
    if allocation == "named immutable":
        before = I()
        get_i(0x8894, C.byref(before))
        gl('glNamedBufferStorage',None,U,Z,P,U)(ubo.value,C.sizeof(values),values,0x0100)
        after = I()
        get_i(0x8894, C.byref(after))
        assert before.value == after.value, 'named storage changed ARRAY_BUFFER binding'
    elif immutable:
        gl('glBufferStorage',None,U,Z,P,U)(0x8A11,C.sizeof(values),values,0x0100)
    else:
        gl('glBufferData',None,U,Z,P,U)(0x8A11,C.sizeof(values),values,0x88E8)
    bind_base(0x8A11,0,ubo.value)
    background()
    draw(4,0,3)
    pixel((255,0,0,255), f'UBO initial draw ({allocation})')
    green = (F * 4)(0,1,0,1)
    if allocation == "named immutable":
        gl('glNamedBufferSubData',None,U,Z,Z,P)(ubo.value,64,16,green)
        get_i(0x8894, C.byref(after))
        assert before.value == after.value, 'named subdata changed ARRAY_BUFFER binding'
    else:
        subdata(0x8A11,64,16,green)
    background()
    draw(4,0,3)
    pixel((0,255,0,255), f'UBO subdata update ({allocation})')
    if immutable:
        gl('glBufferData',None,U,Z,P,U)(0x8A11,C.sizeof(values),values,0x88E8)
        assert get_error() == 0x0502, 'immutable storage must reject reallocation'
    gl('glDeleteBuffers',None,I,P)(1,C.byref(ubo))

# Modern cloud/texture-buffer path: translate, DSA attach, sample, update, ranged attach.
vs_buffer = compile_src('''#version 330
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
''', 0x8B31, 'buffer texture VS')
fs_buffer = compile_src('''#version 330
uniform isamplerBuffer Colors;
out vec4 fragColor;
void main() { fragColor = vec4(texelFetch(Colors, 0)) / 255.0; }
''', 0x8B30, 'integer buffer texture FS')
buffer_program = gl('glCreateProgram', U)()
attach(buffer_program, vs_buffer)
attach(buffer_program, fs_buffer)
gl('glLinkProgram', None,U)(buffer_program)
gl('glGetProgramiv', None,U,U,P)(buffer_program,0x8B82,C.byref(status))
assert status.value, 'buffer texture shader link failed'
gl('glUseProgram', None,U)(buffer_program)
location = gl('glGetUniformLocation', I,U,C.c_char_p)(buffer_program,b'Colors')
gl('glUniform1i', None,I,I)(location,0)
colors = U()
gl('glGenBuffers',None,I,P)(1,C.byref(colors))
bind_buffer(0x8892,colors.value)
red = (I * 4)(255,0,0,255)
gl('glBufferData',None,U,Z,P,U)(0x8892,C.sizeof(red),red,0x88E8)
# A sentinel binding catches accidental state changes by glCreateTextures and DSA.
sentinel, buffer_texture = U(), U()
gl('glGenTextures',None,I,P)(1,C.byref(sentinel))
gl('glBindTexture',None,U,U)(0x8C2A,sentinel.value)
gl('glCreateTextures',None,U,I,P)(0x8C2A,1,C.byref(buffer_texture))
previous = I()
get_i(0x8C2C,C.byref(previous))
assert previous.value == sentinel.value, 'glCreateTextures changed texture-buffer binding'
gl('glTextureBuffer',None,U,U,U)(buffer_texture.value,0x8D82,colors.value)
get_i(0x8C2C,C.byref(previous))
assert previous.value == sentinel.value, 'glTextureBuffer changed texture-buffer binding'
active(0x84C1)
gl('glBindTextureUnit',None,U,U)(0,buffer_texture.value)
get_i(0x84E0,C.byref(previous))
assert previous.value == 0x84C1, 'glBindTextureUnit changed active texture unit'
background()
draw(4,0,3)
pixel((255,0,0,255), 'integer buffer texture initial sample')
green = (I * 4)(0,255,0,255)
subdata(0x8892,0,C.sizeof(green),green)
background()
draw(4,0,3)
pixel((0,255,0,255), 'integer buffer texture reflects buffer updates')
gl('glTextureBufferRange',None,U,U,U,Z,Z)(buffer_texture.value,0x8D82,colors.value,0,16)
background()
draw(4,0,3)
pixel((0,255,0,255), 'DSA buffer texture range')
gl('glBindTextureUnit',None,U,U)(0,0)
active(0x84C0)
get_i(0x8C2C,C.byref(previous))
assert previous.value == 0, 'glBindTextureUnit(unit, 0) did not unbind buffer texture'
no_error('buffer texture DSA state restoration')

# Everything above runs in one process/context, matching the renderer's global state model.
print('PASS: all RustGL rendering probes', flush=True)
