---
layout: default
title: Home
---
# Contents

An index of all markdown files in the collection.

## Recipes
<ul>
  {% for recipe in site.recipes %}
    <li><a href="{{ recipe.url | relative_url }}">{{ recipe.title | default: recipe.name }}</a></li>
  {% endfor %}
</ul>

## In Progress
<ul>
  {% for recipe in site.in-progress %}
    <li><a href="{{ recipe.url | relative_url }}">{{ recipe.title | default: recipe.name }}</a></li>
  {% endfor %}
</ul>

## Curated & Un-tested
<ul>
  {% for recipe in site.curated-untested %}
    <li><a href="{{ recipe.url | relative_url }}">{{ recipe.title | default: recipe.name }}</a></li>
  {% endfor %}
</ul>