use image::io::Reader as ImageReader;
use image::GenericImageView;
use std::ffi::c_void;

pub struct Texture {
    pub id: gl::types::GLuint
}

impl Texture {
    pub fn new(path: &str) -> Result<Self, String> {
        let image = ImageReader::open(path).unwrap().decode().unwrap().flipv();
        let width = image.width() as i32;
        let height = image.height() as i32;
        let byte_data= image.as_bytes();

        let mut id: gl::types::GLuint = 0;
        unsafe {
            gl::GenTextures(1, &mut id);
        }

        let texture = Self {id};
        texture.bind();
        unsafe {
            gl::TexParameteri(gl::TEXTURE_2D, gl::TEXTURE_WRAP_S, gl::REPEAT as i32);
            gl::TexParameteri(gl::TEXTURE_2D, gl::TEXTURE_WRAP_T, gl::REPEAT as i32);
            gl::TexParameteri(gl::TEXTURE_2D, gl::TEXTURE_MIN_FILTER, gl::NEAREST as i32);
            gl::TexParameteri(gl::TEXTURE_2D, gl::TEXTURE_MAG_FILTER, gl::NEAREST as i32);
            gl::TexImage2D(gl::TEXTURE_2D, 0, gl::RGB as i32, width, height, 0, gl::RGB, gl::UNSIGNED_BYTE, byte_data.as_ptr() as *const c_void);
            gl::GenerateMipmap(gl::TEXTURE_2D);
        }
        texture.unbind();
        return Ok(texture);
    }

    pub fn bind(&self) {
        unsafe {
            gl::BindTexture(gl::TEXTURE_2D, self.id);
        }
    }

    pub fn bind_to_slot(&self, slot: u32) {
        unsafe {
            gl::ActiveTexture(gl::TEXTURE0 + slot);
            gl::BindTexture(gl::TEXTURE_2D, self.id);
        }
    }

    pub fn unbind(&self) {
        unsafe {
            gl::BindTexture(gl::TEXTURE_2D, 0);
        }
    }
}

impl Drop for Texture {
    fn drop(&mut self) {
        unsafe {
            gl::DeleteTextures(1, &self.id);
        }
    }
}