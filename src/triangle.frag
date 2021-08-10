#version 330 core

in vec2 texture_data_frag;

out vec4 final_colour;

uniform sampler2D texture_sample_1;

void main()
{
    final_colour = texture(texture_sample_1, texture_data_frag);
}