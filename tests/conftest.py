import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(scope="session", autouse=True)
def _mock_db_engine():
    """Prevent MySQL connection in CI — mock the SQLAlchemy engine."""
    with patch("sqlalchemy.create_engine", return_value=MagicMock()):
        yield
