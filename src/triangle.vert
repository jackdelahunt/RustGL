#version 330 core
layout (location = 0) in vec3 position_data;
layout (location = 1) in vec2 texture_data;

out vec3 colour;
out vec2 texture_data_frag;

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;

void main()
{
    gl_Position = projection * view * model * vec4(position_data, 1.0);
    texture_data_frag = texture_data;
}