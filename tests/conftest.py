import pytest
from fastapi.testclient import TestClient

from helpdesk_agent.api import create_app
from helpdesk_agent.provider import OfflineProvider


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path / "test.sqlite", OfflineProvider())


@pytest.fixture
def client(app):
    with TestClient(app, headers={"X-Helpdesk": "1"}) as c:
        c.get("/api/bootstrap")
        yield c


@pytest.fixture
def session(client):
    return client.post("/api/sessions", json={"employee_id": "EMP-001"}).json()
