#version 330 core
out vec4 final_colour;

in vec3 colour;
in vec2 text_coord;

uniform sampler2D texture_sample; // default 0

void main()
{
    final_colour = texture(texture_sample, text_coord) * vec4(colour, 1.0);
}