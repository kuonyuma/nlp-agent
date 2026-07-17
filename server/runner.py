"""Composition boundary for embedding the single-owner Backend Gateway."""

from gateway.core import BackendGateway


def create_backend_gateway() -> BackendGateway:
    """Create an unstarted Gateway; the host must call start/close in its lifespan."""
    return BackendGateway()
