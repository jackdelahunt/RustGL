use crate::renderer::vertex_buffer::*;

pub struct VertexArray {
    pub id: gl::types::GLuint
}

impl VertexArray {
    pub fn new(vertex_buffer: &VertexBuffer) -> Result<Self, String> {
        let mut id: gl::types::GLuint = 0;
        unsafe {
            gl::GenVertexArrays(1, &mut id);
            gl::BindVertexArray(id);
            gl::BindBuffer(gl::ARRAY_BUFFER, vertex_buffer.id);
            gl::BindVertexArray(0);
        }

        return Ok(Self {id})
    }

    pub fn bind_element_array(&self, indices: &Vec<i32>) {
        let mut ebo: gl::types::GLuint = 0;
        unsafe {
            gl::BindVertexArray(self.id);

            gl::GenBuffers(1, &mut ebo);
            gl::BindBuffer(gl::ELEMENT_ARRAY_BUFFER, ebo);
            gl::BufferData(
                gl::ELEMENT_ARRAY_BUFFER, // what type of buffer
                (indices.len() * std::mem::size_of::<f32>()) as gl::types::GLsizeiptr, // size of data in bytes
                indices.as_ptr() as *const gl::types::GLvoid, // pointer to data
                gl::STATIC_DRAW, // usage
            );

            // unbind as it is no longer be changed
            gl::BindBuffer(gl::ELEMENT_ARRAY_BUFFER, 0);
            gl::BindVertexArray(0);
        }
    }

    pub fn attribute(&self, index: u32, components: i32, stride: usize, offset: usize) -> () {
        unsafe {
            gl::BindVertexArray(self.id);

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

            gl::BindVertexArray(0);
        }
    }
}