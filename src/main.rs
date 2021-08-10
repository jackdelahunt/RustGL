extern crate sdl2;
extern crate gl;
extern crate  nalgebra_glm as glm;

mod renderer;
mod data;

use sdl2::event::{Event, WindowEvent};
use std::ffi::CString;
use renderer::Renderer;
use renderer::vertex_buffer::VertexBuffer;
use renderer::vertex_array::VertexArray;
use renderer::index_array::IndexArray;
use renderer::texture::Texture;
use renderer::shader::Shader;
use renderer::program::Program;

fn main() {
    let sdl = sdl2::init().unwrap();
    let video_subsystem = sdl.video().unwrap();

    // specify gl versions
    let gl_attribute = video_subsystem.gl_attr();
    gl_attribute.set_context_profile(sdl2::video::GLProfile::Core);
    gl_attribute.set_context_version(4, 5);

    // create window
    let window = video_subsystem.window("Game", 700, 700)
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
        gl::Viewport(0, 0, 700, 700);
        gl::ClearColor(0.2, 0.2, 0.7, 1.0);
    }

    // create vertex shader form source
    let vertex_shader = Shader::from_vert_source(
        &CString::new(include_str!("triangle.vert")).unwrap()
    ).unwrap();

    // create fragment shader form source
    let fragment_shader = Shader::from_frag_source(
        &CString::new(include_str!("triangle.frag")).unwrap()
    ).unwrap();

    // make program and use it
    let shader_program = Program::from_shaders(
        &[vertex_shader, fragment_shader]
    ).unwrap();

    let vertex_buffer = VertexBuffer::new(data::gen_cube_vertices()).unwrap();

    let vertex_array = VertexArray::new(&vertex_buffer).unwrap();
    vertex_array.attribute(0, 3, 5, 0);
    vertex_array.attribute(1, 2, 5, 3);

    let renderer = Renderer::new();

    let face_1_texture = Texture::new("res/face.png").unwrap();
    face_1_texture.bind_to_slot(0);

    shader_program.set_uniform_1i("texture_sample_1", 0);

    let mut model: glm::Mat4 = glm::identity();
    //model = glm::rotate(&model, f32::to_radians(90.0), &glm::make_vec3(&[1.0, 0.0, 0.0])); // local coords to world coords

    let mut view: glm::Mat4 = glm::identity();
    view  = glm::translate(&view, &glm::make_vec3(&[0.0, 0.0, -3.0])); // world coords to view coords, moving increase of camera

    let mut projection: glm::Mat4 = glm::perspective(f32::to_radians(45.0), 800.5 / 600.0, 0.1, 100.0);


    let mut event_pump = sdl.event_pump().unwrap();
    'main_loop: loop {
        for event in event_pump.poll_iter() {
            match event {
                Event::Quit{..} => break 'main_loop,
                Event::Window {win_event, ..} => {
                    if let WindowEvent::Resized(width, height) = win_event {
                        unsafe {
                            gl::Viewport(0, 0, width, height)
                        }
                    }
                }
                _ => {}
            }
        }

        model = glm::rotate(&model, f32::to_radians(1.0), &glm::make_vec3(&[1.0, 1.0, 0.0])); // local coords to world coords


        shader_program.set_uniform_matrix_4f("model", &model);
        shader_program.set_uniform_matrix_4f("view", &view);
        shader_program.set_uniform_matrix_4f("projection", &projection);

        renderer.clear();
        renderer.draw(&vertex_array, &shader_program);
        window.gl_swap_window();
    }
}
