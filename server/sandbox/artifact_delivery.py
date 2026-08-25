from __future__ import annotations

from pathlib import Path
from typing import Protocol
import os

from fastapi import Response

from .artifacts import ArtifactAccessSigner, artifact_access_url, artifact_security_headers, resolve_artifact_path, validate_artifact_origin

MAX_ARTIFACT_BYTES = 16 * 1024 * 1024


class ArtifactMetadata(Protocol):
    id: str
    owner_user_id: str
    locator: str
    mime_type: str


def build_artifact_response(artifact: ArtifactMetadata, *, ticket: str, signer: ArtifactAccessSigner, store_root: Path) -> Response:
    signer.verify(ticket, artifact_id=artifact.id, owner_user_id=artifact.owner_user_id)
    headers = artifact_security_headers(artifact.mime_type)
    if artifact.mime_type == "image/svg+xml":
        headers["Content-Disposition"] = "attachment"
    path = resolve_artifact_path(store_root, artifact.locator)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            content = stream.read(MAX_ARTIFACT_BYTES + 1)
    except OSError as error:
        raise PermissionError("sandbox artifact could not be opened safely") from error
    if len(content) > MAX_ARTIFACT_BYTES:
        raise PermissionError("sandbox artifact exceeds the delivery size limit")
    return Response(content=content, media_type=artifact.mime_type, headers=headers)


def issue_artifact_access_url(artifact: ArtifactMetadata, *, requester_user_id: str, signer: ArtifactAccessSigner, artifact_origin: str, application_origin: str) -> str:
    if artifact.owner_user_id != requester_user_id:
        raise PermissionError("sandbox artifact does not belong to the current user")
    origin = validate_artifact_origin(artifact_origin, application_origin=application_origin)
    ticket = signer.issue(artifact_id=artifact.id, owner_user_id=artifact.owner_user_id)
    return artifact_access_url(origin, artifact_id=artifact.id, ticket=ticket)
