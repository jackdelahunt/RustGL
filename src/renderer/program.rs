use crate::renderer;
use crate::renderer::shader::*;
use std::ffi::CString;
use std;

pub struct Program {
    pub id: gl::types::GLuint
}

impl Program {
    pub fn from_shaders(shaders: &[Shader]) -> Result<Program, String> {
        unsafe {
            let program_id = gl::CreateProgram();

            // attach given shaders to new program
            for shader in shaders {
                gl::AttachShader(program_id, shader.id);
            }

            // create executable based on program with given shaders
            gl::LinkProgram(program_id);

            let mut success: gl::types::GLint = 1;
            gl::GetProgramiv(program_id, gl::LINK_STATUS, &mut success);

            // if linking returned a failure then log an error
            if success == 0 {
                let mut len: gl::types::GLint = 0;
                gl::GetProgramiv(program_id, gl::INFO_LOG_LENGTH, &mut len);

                let error = renderer::create_whitespace_c_string(len as usize);

                gl::GetProgramInfoLog(
                    program_id,
                    len,
                    std::ptr::null_mut(),
                    error.as_ptr() as *mut gl::types::GLchar
                );

                return Err(error.to_string_lossy().into_owned());
            }

            // detach linked shaders as they cannot be deleted when drop() is called otherwise
            for shader in shaders {
                gl::DetachShader(program_id, shader.id);
            }

            return Ok(Self {
                id: program_id
            })
        };
    }

    pub fn set_uniform_4f(&self, uniform_name: &str, x: f32, y: f32, z: f32, w: f32) {
        let cstr = CString::new(uniform_name).unwrap();
        let char_ptr = cstr.as_ptr();

        unsafe {
            let location = gl::GetUniformLocation(self.id, char_ptr);
            gl::Uniform4f(location, x, y, z, w);
        }
    }

    pub fn set_uniform_1i(&self, uniform_name: &str, x: i32) {
        self.bind();
        let cstr = CString::new(uniform_name).unwrap();
        let char_ptr = cstr.as_ptr();

        unsafe {
            let location = gl::GetUniformLocation(self.id, char_ptr);
            gl::Uniform1i(location, x);
        }
        self.unbind();
    }

    pub fn set_uniform_matrix_4f(&self, uniform_name: &str, matrix: &glm::Mat4) {
        let cstr = CString::new(uniform_name).unwrap();
        let char_ptr = cstr.as_ptr();

        unsafe {
            let location = gl::GetUniformLocation(self.id, char_ptr);
            gl::UniformMatrix4fv(location, 1, gl::FALSE, glm::value_ptr(matrix).as_ptr());
        }
    }

    pub fn bind(&self) {
        unsafe {
            gl::UseProgram(self.id);
        }
    }

    pub fn unbind(&self) {
        unsafe {
            gl::UseProgram(0);
        }
    }
}

impl Drop for Program {
    fn drop(&mut self) {
        unsafe {
            gl::DeleteProgram(self.id);
        }
    }
}