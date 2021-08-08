#version 330 core

in vec3 vertexColour;
out vec4 colour;

void main()
{
    colour = vec4(vertexColour, 1.0);
}