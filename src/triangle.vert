#version 330 core

layout (location = 0) in vec3 Position;
layout (location = 1) in vec3 Colour;

out VS_OUTPUT {
    vec3 Colour;
} OUT;

void main()
{
    gl_Position = vec4(Position, 1.0);
    OUT.Colour = Colour;
}