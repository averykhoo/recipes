# recipe_parser/__init__.py
"""
Recipe Parser Package
A layer-based Markdown recipe parser and validator with complete support for
fractions, GFM tables, flat-sibling block DOM ASTs, and metric unit tolerance checks.
"""

from recipe_parser.core.orchestrator import process_recipe_document

__all__ = ["process_recipe_document"]
