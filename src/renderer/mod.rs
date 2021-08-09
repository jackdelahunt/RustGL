pub mod vertex_buffer;
pub mod vertex_array;
pub mod program;
pub mod shader;
pub mod index_array;
pub mod texture;

use std::ffi::CString;
use std;
use crate::renderer::vertex_array::VertexArray;
use crate::renderer::index_array::IndexArray;
use crate::renderer::program::Program;

pub struct Renderer {}

impl Renderer {
    pub fn new() -> Self {
        return Self {};
    }
    pub fn draw(&self, vertex_array: &VertexArray, index_array: &IndexArray, shader_program: &Program) {
        shader_program.bind();
        vertex_array.bind();
        unsafe {
            gl::DrawElements(gl::TRIANGLES, index_array.count() as i32, gl::UNSIGNED_INT, index_array.indices.as_ptr() as *const gl::types::GLvoid);
        }
        vertex_array.unbind();
    }

    pub fn clear(&self) {
        unsafe {
            gl::Clear(gl::COLOR_BUFFER_BIT);
        }
    }
}

fn create_whitespace_c_string(length: usize) -> CString {
    let mut buffer: Vec<u8> = Vec::with_capacity(length + 1); // +1 is for 0 terminating string
    // fill with spaces
    buffer.extend([b' '].iter().cycle().take(length));
    // convert buffer to CString
    unsafe { return CString::from_vec_unchecked(buffer); };
}