pub struct VertexBuffer {
    pub id: gl::types::GLuint,
}

impl VertexBuffer {
    pub fn new(vertex_data: Vec<f32>) -> Result<Self, String> {
        let mut id: gl::types::GLuint = 0;
        unsafe {
            gl::GenBuffers(1, &mut id);
        }

        let buffer = Self {
            id
        };

        unsafe {
            buffer.bind();
            gl::BufferData(
                gl::ARRAY_BUFFER, // what type of buffer
                (vertex_data.len() * std::mem::size_of::<f32>()) as gl::types::GLsizeiptr, // size of data in bytes
                vertex_data.as_ptr() as *const gl::types::GLvoid, // pointer to data
                gl::STATIC_DRAW, // usage
            );
            buffer.unbind();
        }
        return Ok(buffer);
    }

    pub fn bind(&self) {
        unsafe {
            gl::BindBuffer(gl::ARRAY_BUFFER, self.id);
        }
    }

    pub fn unbind(&self) {
        unsafe {
            gl::BindBuffer(gl::ARRAY_BUFFER, 0);
        }
    }
}