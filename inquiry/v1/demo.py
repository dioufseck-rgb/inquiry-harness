"""Compatibility import for the explicitly selected hardship benchmark worker.

New application code should import ``inquiry.v1.adapters.hardship_demo``.
This fixture is not a general inquiry worker and is never selected by core.
"""

from .adapters.hardship_demo import DemoWorker

__all__ = ["DemoWorker"]
