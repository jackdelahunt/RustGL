pub struct IndexArray {
    pub id: gl::types::GLuint,
    pub indices: Vec<i32>,
}

impl IndexArray {
    pub fn new(indices: Vec<i32>) -> Result<Self, String> {
        let mut id: gl::types::GLuint = 0;
        unsafe {
            gl::GenBuffers(1, &mut id);
        }

        let index_array = Self {id, indices};
        index_array.bind();
        unsafe {
            gl::BufferData(
                gl::ELEMENT_ARRAY_BUFFER,
                (index_array.count() * std::mem::size_of::<i32>()) as gl::types::GLsizeiptr,
                index_array.indices.as_ptr() as *const gl::types::GLvoid,
                gl::STATIC_DRAW,
            );
        }
        index_array.unbind();

        return Ok(index_array);
    }

    pub fn count(&self) -> usize {
        return self.indices.len();
    }

    pub fn bind(&self) {
        unsafe {
            gl::BindBuffer(gl::ELEMENT_ARRAY_BUFFER, self.id);
        }
    }

    pub fn unbind(&self) {
        unsafe {
            gl::BindBuffer(gl::ELEMENT_ARRAY_BUFFER, 0);
        }
    }
}