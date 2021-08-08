#version 330 core

in vec3 vertexColour;
out vec4 colour;

uniform vec4 ourColour;

void main()
{
    colour = ourColour;
}