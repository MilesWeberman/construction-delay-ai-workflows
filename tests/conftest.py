from pathlib import Path

import pytest


@pytest.fixture
def sample_dir() -> Path:
    return Path(__file__).parent.parent / "data" / "sample"
