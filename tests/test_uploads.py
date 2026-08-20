"""Uploads module API unit and integration tests."""

from __future__ import annotations

import io
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from core.identity import AuthenticatedPrincipal
from server.uploads.controller import (
    get_current_principal,
    get_write_access,
    router as uploads_router,
)


def _make_test_image_bytes(width: int = 100, height: int = 100, format: str = "PNG") -> bytes:
    img = Image.new("RGB", (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, format=format)
    return buf.getvalue()


@pytest.fixture
def mock_principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="test_user",
        workspace_ids=frozenset({"test_ws"}),
        roles=frozenset({"student"}),
    )


@pytest.fixture
def test_app(mock_principal: AuthenticatedPrincipal) -> FastAPI:
    app = FastAPI()
    app.include_router(uploads_router)
    app.dependency_overrides[get_current_principal] = lambda: mock_principal
    app.dependency_overrides[get_write_access] = lambda: None
    return app


def test_upload_image_success(test_app: FastAPI) -> None:
    client = TestClient(test_app)

    img_data = _make_test_image_bytes(120, 80, "PNG")
    response = client.post(
        "/api/v1/uploads",
        data={"session_id": "sess_123"},
        files={"file": ("my_image.png", img_data, "image/png")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["file_name"].endswith(".png")
    assert payload["url"] == f"/api/v1/uploads/sess_123/{payload['file_name']}"
    assert payload["media_type"] == "image/png"
    assert payload["width"] == 120
    assert payload["height"] == 80
    assert payload["size_bytes"] == len(img_data)
    assert len(payload["sha256"]) == 64

    # Verify GET returns the file with nosniff header
    get_res = client.get(payload["url"])
    assert get_res.status_code == 200
    assert get_res.headers.get("x-content-type-options") == "nosniff"
    assert get_res.content == img_data


def test_upload_corrupt_image_rejected(test_app: FastAPI) -> None:
    client = TestClient(test_app)

    response = client.post(
        "/api/v1/uploads",
        data={"session_id": "sess_123"},
        files={"file": ("bad.png", b"not-a-valid-image-data", "image/png")},
    )

    assert response.status_code == 415


def test_get_upload_rejects_path_traversal(test_app: FastAPI) -> None:
    client = TestClient(test_app)

    response = client.get("/api/v1/uploads/sess_123/..%2f..%2fetc%2fpasswd")
    assert response.status_code == 404
