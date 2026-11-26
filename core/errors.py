"""Errors shared across layers."""


class CapabilityUnavailable(Exception):
    """A required external capability (model, vision, travel provider) is not configured or not enabled."""
