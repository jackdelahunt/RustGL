extern crate sdl2;
extern crate gl;
pub mod render_gl;

use sdl2::event::Event;
use std::ffi::CString;

fn main() {
    let sdl = sdl2::init().unwrap();
    let video_subsystem = sdl.video().unwrap();

    // specify gl versions
    let gl_attribute = video_subsystem.gl_attr();
    gl_attribute.set_context_profile(sdl2::video::GLProfile::Core);
    gl_attribute.set_context_version(4, 5);

    // create window
    let window = video_subsystem.window("Game", 810, 540)
        .opengl()
        .resizable()
        .build()
        .unwrap();

    // init gl in window
    let _gl_context = window.gl_create_context().unwrap();

    // load gl function pointers by string :^]
    let _gl = gl::load_with(|s| video_subsystem.gl_get_proc_address(s) as *const std::os::raw::c_void);

    // set the gl clear colour to something new
    unsafe {
        gl::Viewport(0, 0, 810, 540);
        gl::ClearColor(0.3, 0.3, 0.5, 1.0);
    }

    // create vertex shader form source
    let vertex_shader = render_gl::Shader::from_vert_source(
        &CString::new(include_str!("triangle.vert")).unwrap()
    ).unwrap();

    // create fragment shader form source
    let fragment_shader = render_gl::Shader::from_frag_source(
        &CString::new(include_str!("triangle.frag")).unwrap()
    ).unwrap();

    // make program and use it
    let shader_program = render_gl::Program::from_shaders(
        &[vertex_shader, fragment_shader]
    ).unwrap();
    shader_program.set_used();

    let mut event_pump = sdl.event_pump().unwrap();
    'main_loop: loop {
        for event in event_pump.poll_iter() {
            match event {
                Event::Quit{timestamp} => {
                    println!("{}", timestamp);
                    break 'main_loop;
                },
                _ => {}
            }
        }

        unsafe {
            // set pixels on screen to the colour set with ClearColor as
            // indicated with the COLOR_BUFFER_BIT, could be depth or bit
            gl::Clear(gl::COLOR_BUFFER_BIT);
        }

        window.gl_swap_window();
    }
}
