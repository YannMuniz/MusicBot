import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

TOKEN = "test-token"
H = {"X-Internal-Token": TOKEN}


@pytest.fixture()
def settings(tmp_path):
    return Settings(storage_root=tmp_path / "songs", internal_token=TOKEN, max_upload_bytes=20 * 1024 * 1024,
                    max_duration_s=300, min_duration_s=5, allowed_extensions=("mp3", "wav"))


@pytest.fixture()
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c
