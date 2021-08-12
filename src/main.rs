extern crate sdl2;
extern crate gl;
extern crate  nalgebra_glm as glm;

mod renderer;
mod data;
mod time;
mod camera;

use sdl2::event::{Event, WindowEvent};
use std::ffi::CString;
use renderer::Renderer;
use renderer::vertex_buffer::VertexBuffer;
use renderer::vertex_array::VertexArray;
use renderer::index_array::IndexArray;
use renderer::texture::Texture;
use renderer::shader::Shader;
use renderer::program::Program;
use glm::{TVec3, Mat4};
use sdl2::keyboard::Keycode;
use camera::Camera;

fn main() {
    let sdl = sdl2::init().unwrap();
    let video_subsystem = sdl.video().unwrap();

    let mut delta_timer = time::DeltaTimer::new();

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
    vertex_array.attribute(0, 3, 8, 0);
    vertex_array.attribute(1, 2, 8, 3);
    vertex_array.attribute(2, 3, 8, 5);


    let renderer = Renderer::new();

    let face_1_texture = Texture::new("res/face.png").unwrap();
    face_1_texture.bind_to_slot(0);

    shader_program.set_uniform_1i("texture_sample_1", 0);

    let mut model: Mat4 = glm::identity();

    let mut camera = Camera::new(&TVec3::new(0.0, 0.0, 2.0));

    let mut projection: Mat4 = glm::perspective(800.5 / 600.0, f32::to_radians(90.0), 0.1, 100.0);
    projection = glm::translate(&projection, &TVec3::new(0.0, 0.0, -3.0));

    let movement_speed: f32 = 50.0;

    let mut event_pump = sdl.event_pump().unwrap();
    'main_loop: loop {
        delta_timer.tick();
        for event in event_pump.poll_iter() {
            match event {
                Event::Window {win_event, ..} => {
                    if let WindowEvent::Resized(width, height) = win_event {
                        unsafe {
                            gl::Viewport(0, 0, width, height)
                        }
                    }
                },
                Event::KeyDown {keycode, ..} => {
                    match keycode {
                        None => {}
                        Some(code) => {
                            match code {
                                Keycode::A => camera.translate(&(camera::LEFT * movement_speed * delta_timer.delta_time())),
                                Keycode::W => camera.translate(&(camera::FRONT * movement_speed * delta_timer.delta_time())),
                                Keycode::S => camera.translate(&(camera::BACK * movement_speed * delta_timer.delta_time())),
                                Keycode::D => camera.translate(&(camera::RIGHT * movement_speed * delta_timer.delta_time())),
                                Keycode::LShift => camera.translate(&(camera::DOWN * movement_speed * delta_timer.delta_time())),
                                Keycode::Space => camera.translate(&(camera::UP * movement_speed * delta_timer.delta_time())),
                                _ => {}
                            }
                        }
                    }
                }
                Event::Quit{..} => break 'main_loop,
                _ => {}
            }
        }

        model = glm::rotate(&model, f32::to_radians(1.5), &TVec3::new(1.0, 1.0, 1.0));

        shader_program.set_uniform_matrix_4f("model", &model);
        shader_program.set_uniform_matrix_4f("view", &camera.view_matrix());
        shader_program.set_uniform_matrix_4f("projection", &projection);

        renderer.clear();
        renderer.draw(&vertex_array, &shader_program);
        window.gl_swap_window();
    }
}
