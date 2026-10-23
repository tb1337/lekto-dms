"""Lekto: self-hosted, headless document management system."""

import importlib.metadata
import os

# The version: the image sets it from the tag of its release (`LEKTO_VERSION`); elsewhere the
# package's own, `0.0.0.dev0` in the repository.
__version__ = os.environ.get("LEKTO_VERSION") or importlib.metadata.version("lekto")
