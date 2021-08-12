use glm::{TVec3, Mat4};

pub static UP: TVec3<f32> = TVec3::new(0.0, 1.0, 0.0);
pub static DOWN: TVec3<f32> = TVec3::new(0.0, -1.0, 0.0);
pub static FRONT: TVec3<f32> = TVec3::new(0.0, 0.0, -1.0);
pub static BACK: TVec3<f32> = TVec3::new(0.0, 0.0, 1.0);
pub static RIGHT: TVec3<f32> = TVec3::new(1.0, 0.0, 0.0);
pub static LEFT: TVec3<f32> = TVec3::new(-1.0, 0.0, 0.0);

pub struct Camera {
    position: TVec3<f32>,
    direction: TVec3<f32>
}

impl Camera {
    pub fn new(position: &TVec3<f32>) -> Self {
        return Self {
          position: position.clone(),
          direction: FRONT.clone()
        };
    }

    pub fn translate(&mut self, translation: &TVec3<f32>) {
        self.position += translation;
    }

    pub fn view_matrix(&self) -> Mat4 {
        return glm::look_at(
            &self.position,
            &(&self.position + &self.direction),
            &UP,
        );
    }
}

