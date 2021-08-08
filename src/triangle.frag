#version 330 core

in VS_OUTPUT {
    vec3 Colour;
} IN;

out vec4 Colour;

void main()
{
    Colour = vec4(IN.Colour, 1.0f);
}