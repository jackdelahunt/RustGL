use std::ffi::{CStr, CString};
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

                let error = create_whitespace_c_string(len as usize);

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

    pub fn set_used(&self) {
        unsafe {
            gl::UseProgram(self.id);
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

                let error = create_whitespace_c_string(error_length as usize);

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

pub struct VertexBuffer {
    pub id: gl::types::GLuint,
}

impl VertexBuffer {
    pub fn new(vertex_data: Vec<f32>) -> Result<Self, String> {
        let mut id: gl::types::GLuint = 0;
        unsafe {
            gl::GenBuffers(1, &mut id);
            gl::BindBuffer(gl::ARRAY_BUFFER, id);
            gl::BufferData(
                gl::ARRAY_BUFFER, // what type of buffer
                (vertex_data.len() * std::mem::size_of::<f32>()) as gl::types::GLsizeiptr, // size of data in bytes
                vertex_data.as_ptr() as *const gl::types::GLvoid, // pointer to data
                gl::STATIC_DRAW, // usage
            );

            // unbind as it is no longer be changed
            gl::BindBuffer(gl::ARRAY_BUFFER, 0);
        }
        return Ok(Self {
            id
        });
    }
}

fn create_whitespace_c_string(length: usize) -> CString {
    let mut buffer: Vec<u8> = Vec::with_capacity(length + 1); // +1 is for 0 terminating string
    // fill with spaces
    buffer.extend([b' '].iter().cycle().take(length));
    // convert buffer to CString
    unsafe { return CString::from_vec_unchecked(buffer); };
}