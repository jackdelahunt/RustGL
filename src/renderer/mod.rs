pub mod vertex_buffer;
pub mod vertex_array;
pub mod program;
pub mod shader;

use std::ffi::CString;
use std;

fn create_whitespace_c_string(length: usize) -> CString {
    let mut buffer: Vec<u8> = Vec::with_capacity(length + 1); // +1 is for 0 terminating string
    // fill with spaces
    buffer.extend([b' '].iter().cycle().take(length));
    // convert buffer to CString
    unsafe { return CString::from_vec_unchecked(buffer); };
}