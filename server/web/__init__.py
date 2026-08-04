"""FastAPI WebUI adapter package.

Importing a small Web submodule such as ``server.web.authorization`` must not
construct the application dependency graph.  The factory remains available at
the package root through a lazy attribute for compatibility.
"""

from typing import Any


def __getattr__(name: str) -> Any:
    if name == "create_app":
        from server.web.app import create_app

        return create_app
    raise AttributeError(name)


__all__ = ["create_app"]
