import os
import sys

# Ensure Sphinx can import pydebeziumai
sys.path.insert(0, os.path.abspath(".."))

project = "pydebeziumai"
copyright = "2026, The Debezium Authors"
author = "Kodukulla Mohnish Mythreya"
release = "0.1.0"

# Core extensions
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx.ext.autosummary",
    "sphinx_copybutton",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# HTML Output Theme
html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]

# Intersphinx links
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pydantic": ("https://docs.pydantic.dev/latest/", None),
}

# Autodoc configuration
autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_default_options = {
    "members": True,
}

# Disable showing package/module path prefix on all classes/functions
add_module_names = False

# Enable strict reference checking
nitpicky = True

# Napoleon configuration for Google docstrings
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True
napoleon_use_admonition_for_examples = True
napoleon_use_admonition_for_notes = True
napoleon_use_admonition_for_references = True
napoleon_use_ivar = True

# Ignore external type references during strict verification checks
nitpick_ignore = [
    ("py:class", "langchain_core.documents.base.Document"),
    ("py:class", "langchain_core.documents.Document"),
    ("py:class", "langchain_core.retrievers.BaseRetriever"),
    ("py:class", "langchain_core.embeddings.embeddings.Embeddings"),
    ("py:class", "langchain_core.tools.base.BaseTool"),
    ("py:class", "Embeddings"),
    ("py:class", "ConfigDict"),
    ("py:class", "BaseModel"),
]
