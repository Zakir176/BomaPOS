import os
import sys

# Ensure backend directory is on sys.path and TEST_DATABASE_URL is active before importing database/main
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from dotenv import load_dotenv

load_dotenv()

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://bomapos_app:bomapos_app@localhost:5432/bomapos_test",
)
TEST_ADMIN_DATABASE_URL = os.environ.get(
    "TEST_ADMIN_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/bomapos_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ADMIN_DATABASE_URL"] = TEST_ADMIN_DATABASE_URL
os.environ.setdefault(
    "JWT_SECRET", "bomapos-test-jwt-secret-key-minimum-32-bytes-long!"
)
os.environ.setdefault(
    "ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
)
os.environ["LENCO_MODE"] = "mock"
os.environ.setdefault(
    "LENCO_API_TOKEN", "test-lenco-secret-api-token-for-hmac-verification"
)

import pytest
from sqlalchemy import text
from alembic import command
from alembic.config import Config
from database import admin_engine
from seed import seed


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Apply Alembic migrations as schema owner and run tests as non-superuser `bomapos_app`."""
    with admin_engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))

    alembic_cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    alembic_cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", TEST_ADMIN_DATABASE_URL)
    command.upgrade(alembic_cfg, "head")
    seed()
    yield
