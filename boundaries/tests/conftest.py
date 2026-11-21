import pytest
import structlog


@pytest.fixture(autouse=True)
def reset_structlog():
    """The CLI configures structlog globally; undo it after each test."""
    yield
    structlog.reset_defaults()
