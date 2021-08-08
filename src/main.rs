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
        gl::ClearColor(1.0, 1.0, 1.0, 1.0);
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

    let vertices: Vec<f32> = vec![
        // positions       // colours
        -0.5, -0.5, 0.0,   1.0, 0.0, 0.0,
        0.5, -0.5, 0.0,    0.0, 1.0, 0.0,
        0.0, 0.5, 0.0,     0.0, 0.0, 1.0,
    ];

    // creating buffer object to that stores vertex data
    let mut vbo: gl::types::GLuint = 0;
    unsafe {
        gl::GenBuffers(1, &mut vbo);
        gl::BindBuffer(gl::ARRAY_BUFFER, vbo);
        gl::BufferData(
            gl::ARRAY_BUFFER, // what type of buffer
            (vertices.len() * std::mem::size_of::<f32>()) as gl::types::GLsizeiptr, // size of data in bytes
            vertices.as_ptr() as *const gl::types::GLvoid, // pointer to data
            gl::STATIC_DRAW, // usage
        );

        // unbind as it is no longer be changed
        gl::BindBuffer(gl::ARRAY_BUFFER, 0);
    }

    // creating vertex array that uses buffered data
    let mut vao: gl::types::GLuint = 0;
    unsafe {
        gl::GenVertexArrays(1, &mut vao);
        gl::BindVertexArray(vao);

        // link buffer data to this vertex array
        gl::BindBuffer(gl::ARRAY_BUFFER, vbo);
        gl::EnableVertexAttribArray(0);
        gl::VertexAttribPointer(
            0, // index of the generic vertex attribute
            3, // the number of components per vertex
            gl::FLOAT, // data type
            gl::FALSE, // normalized (int-to-float conversion)
            (6 * std::mem::size_of::<f32>()) as gl::types::GLint, // stride (byte offset between attributes)
            std::ptr::null()); // offset of the first component

        gl::EnableVertexAttribArray(1);
        gl::VertexAttribPointer(
            1, // index of the generic vertex attribute
            3, // the number of components per vertex
            gl::FLOAT, // data type
            gl::FALSE, // normalized (int-to-float conversion)
            (6 * std::mem::size_of::<f32>()) as gl::types::GLint, // stride (byte offset between attributes)
            (3 * std::mem::size_of::<f32>()) as *const gl::types::GLvoid); // offset of the first component

        // unbind everything as they are no longer be changed
        gl::BindBuffer(gl::ARRAY_BUFFER, 0);
        gl::BindVertexArray(0);
    }

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

        shader_program.set_used();
        unsafe {
            gl::BindVertexArray(vao);
            gl::DrawArrays(
                gl::TRIANGLES, // mode
                0, // starting index in the enabled arrays
                3 // number of indices to be rendered
            );
        }

        window.gl_swap_window();
    }
}
