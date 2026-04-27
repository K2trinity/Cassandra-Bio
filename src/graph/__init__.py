"""Knowledge graph integration package.

The disease report workflow no longer lives in src.graph.
"""

try:
    from .manager import GraphManager
except Exception:
    GraphManager = None

__all__ = ["GraphManager"]
