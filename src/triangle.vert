#version 330 core
layout (location = 0) in vec3 position_data;
layout (location = 1) in vec3 colour_data;
layout (location = 2) in vec2 texture_data;

out vec3 colour;
out vec2 text_coord;

void main()
{
    gl_Position = vec4(position_data, 1.0);
    colour = colour_data;
    text_coord = texture_data;
}