#version 330 core

in vec3 colour;
in vec2 texture_data_frag;

out vec4 final_colour;

uniform sampler2D texture_sample_1;
uniform sampler2D texture_sample_2;

void main()
{
    final_colour = mix(texture(texture_sample_1, texture_data_frag), texture(texture_sample_2, texture_data_frag), 0.5) * vec4(colour, 1.0);
    //final_colour = texture(texture_sample_1, texture_data_frag) * vec4(colour, 1.0);
}