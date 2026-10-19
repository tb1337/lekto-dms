"""Inbound adapter: the worker service (jobs, event delivery, cleanup)."""

from lekto.adapters.inbound.worker.worker import Worker

__all__ = ["Worker"]
