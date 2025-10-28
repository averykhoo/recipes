# TODO

## todo: use collapsible markdown

<details>
<summary>CLICK ME</summary>

```python
print("hello world!")
```

<blockquote>
    <details>
    <summary>test nested section</summary>
    :smile:

</details>
</blockquote>

</details>

## Schema

* how to display comments (e.g. chocolate chip cookies)
* how to format weights alongside measures
* basic conversions chart (1 cup = 16 Tbsp = 48 tsp = 240ml)
* common ingredient density chart (fine / granulated sugar: 1 cup = 200g)
* how to break a recipe down into sections / submodules
* standardized recipe format?
    * good way to specify of ingredient weights and measures - table?
    * needs to accommodate fuzzy measures - e.g. 1-2 Tbsp, a handful of something, knob of butter, ...
    * should the title be titlecase? how about the ingredients and instructions?
    * how many portions output
* should be possible to generate a shopping list from recipes and optional scaling
* highlight or link to relevant recipes or techniques
* comments / footnotes for notes and tips

### look into these schemas

* https://github.com/cnstoll/Grocery-Recipe-Format
* https://briansunter.com/blog/cooklang
* https://cooklang.org
* https://www.reddit.com/r/Pizza/comments/3rvxdf/basic_recipe_writing_tables_and_formatting_with/
* https://recipemd.org
* https://microsoft.github.io/DevCookbook/contribute/
* https://cooklang.org/docs/
* https://flutterawesome.com/recipe-flavored-markdown-make-recipes-easy-to-create-and-maintain/
* https://github.com/cnstoll/Grocery-Recipe-Format
* https://github.com/fictivekin/openrecipes
* http://www.cookingforengineers.com
* https://arisgarden.theiceshelf.com/recipe/sweet-potato-gnocci
* https://wiki.gnome.org/Apps/Recipes
* https://github.com/schemaorg/schemaorg/issues/882
* http://diyhpl.us/~bryan/papers2/CompCook.html
* https://mtlynch.io/resurrecting-1/
* https://archive.nytimes.com/open.blogs.nytimes.com/2015/04/09/extracting-structured-data-from-recipes-using-conditional-random-fields/
* https://zestfuldata.com/demo/
* http://microformats.org/wiki/hrecipe
* https://fathub.org
* https://www.reciped.io
* https://www.cinc.kitchen/info/features
* https://github.com/dansinker/tacofancy
* https://github.com/cooklang/recipes
* http://www.formatdata.com/recipeml/
* https://schema.org/Recipe
* https://based.cooking
* https://slate.com/human-interest/2012/05/how-to-cook-onions-why-recipe-writers-lie-and-lie-about-how-long-they-take-to-caramelize.html
* http://www.grouprecipes.com/133488/mexican-hash.html

## other todo

* pwa / serviceworker
* JSON-LD injection - inject via `json-ld` key into yaml frontmatter and use an _include template
* recipe parsing - requires some schema first
* dark mode toggle
* better link cleaning via markdown-soup, which will probably a concrete syntax tree wrapper around markdown-it-py
* consider not using the github jekyll action since it's very outdated
* change logo to cookie book / 🍪📖 / :cookie: :book: (does :cookie::book: work)