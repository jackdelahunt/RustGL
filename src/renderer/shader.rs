use std::ffi::CStr;
use std;
use crate::renderer;

pub struct Shader {
    pub id: gl::types::GLuint
}

impl Shader {
    pub fn new(source: &CStr, kind: gl::types::GLenum) -> Result<Self , String> {
        // create shader and get reference
        let id = unsafe { gl::CreateShader(kind) };

        unsafe {
            // set the source code in the referenced shader with the input source
            gl::ShaderSource(id, 1, &source.as_ptr(), std::ptr::null());
            gl::CompileShader(id);

            // get the compile status of the shader
            let mut success: gl::types::GLint = 1;
            gl::GetShaderiv(id, gl::COMPILE_STATUS, &mut success);

            if success == 0 {
                // if compile failed get length of error in shader
                let mut error_length: gl::types::GLint = 0;
                gl::GetShaderiv(id, gl::INFO_LOG_LENGTH, &mut error_length);

                let error = renderer::create_whitespace_c_string(error_length as usize);

                // fill error with info log in shader
                gl::GetShaderInfoLog(id, error_length, std::ptr::null_mut(), error.as_ptr() as *mut gl::types::GLchar);
                return Err(error.to_string_lossy().into_owned());
            }
        }

        return Ok(Self {
            id
        });
    }

    pub fn from_vert_source(source: &CStr) -> Result<Shader, String> {
        Shader::new(source, gl::VERTEX_SHADER)
    }

    pub fn from_frag_source(source: &CStr) -> Result<Shader, String> {
        Shader::new(source, gl::FRAGMENT_SHADER)
    }
}

impl Drop for Shader {
    fn drop(&mut self) {
        unsafe {
            gl::DeleteShader(self.id);
        }
    }
}