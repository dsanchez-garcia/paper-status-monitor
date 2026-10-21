"""Sphinx configuration for the paper-status-monitor documentation."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper_status_monitor import __version__  # noqa: E402

project = "paper-status-monitor"
author = "Daniel Sánchez-García"
copyright = f"2025-{date.today().year}, {author}"
release = __version__
version = ".".join(release.split(".")[:2])

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
]

source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
root_doc = "index"
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

myst_enable_extensions = ["colon_fence", "deflist", "fieldlist"]
myst_heading_anchors = 3

autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_default_options = {"members": True, "show-inheritance": True}
napoleon_google_docstring = True
napoleon_numpy_docstring = False

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "requests": ("https://requests.readthedocs.io/en/latest", None),
}

html_theme = "sphinx_rtd_theme"
html_title = f"paper-status-monitor {release}"
html_theme_options = {"navigation_depth": 3}
html_context = {
    "display_github": True,
    "github_user": "dsanchez-garcia",
    "github_repo": "paper-status-monitor",
    "github_version": "main",
    "conf_py_path": "/docs/",
}
