use crate::renderer::vertex_buffer::*;

pub struct VertexArray {
    pub id: gl::types::GLuint
}

impl VertexArray {
    pub fn new(vertex_buffer: &VertexBuffer) -> Result<Self, String> {
        let mut id: gl::types::GLuint = 0;
        unsafe {
            gl::GenVertexArrays(1, &mut id);
        }

        let vertex_array = Self {id};
        vertex_array.bind();
        unsafe {
            gl::BindVertexArray(id);
            gl::BindBuffer(gl::ARRAY_BUFFER, vertex_buffer.id);
            gl::BindVertexArray(0);
        }
        vertex_array.unbind();
        return Ok(vertex_array)
    }

    pub fn attribute(&self, index: u32, components: i32, stride: usize, offset: usize) -> () {
        self.bind();
        unsafe {
            let mut offset_ptr = std::ptr::null();
            if offset != 0 {
                offset_ptr = (offset * std::mem::size_of::<f32>()) as *const gl::types::GLvoid;
            }

            gl::EnableVertexAttribArray(index);
            gl::VertexAttribPointer(
                index,
                components,
                gl::FLOAT,
                gl::FALSE, // normalized (int-to-float conversion)
                (stride * std::mem::size_of::<f32>()) as gl::types::GLint, // stride (byte offset between attributes)
                offset_ptr); // offset of the first component
        }
        self.unbind();
    }

    pub fn bind(&self) {
        unsafe {
            gl::BindVertexArray(self.id);
        }
    }

    pub fn unbind(&self) {
        unsafe {
            gl::BindVertexArray(0);
        }
    }
}