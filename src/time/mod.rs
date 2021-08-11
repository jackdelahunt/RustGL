use std::time::SystemTime;

pub struct DeltaTimer {
    since_last_tick: SystemTime
}

impl DeltaTimer {
    pub fn new() -> Self {
        return Self {
            since_last_tick: SystemTime::now()
        };
    }
    pub fn tick(&mut self) {
        self.since_last_tick = SystemTime::now();
    }

    pub fn delta_time(&self) -> f32 {
        let delta = SystemTime::now().duration_since(self.since_last_tick).unwrap();
        return delta.as_secs_f32();
    }
}