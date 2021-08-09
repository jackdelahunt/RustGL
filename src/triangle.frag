#version 330 core

in vec3 colour;
in vec2 text_coord;

out vec4 final_colour;

uniform sampler2D texture_sample_1;
uniform sampler2D texture_sample_2;

void main()
{
    final_colour = mix(texture(texture_sample_1, text_coord), texture(texture_sample_2, text_coord), 0.2) * vec4(colour, 1.0);
}