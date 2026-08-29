from __future__ import annotations

from enum import Enum
from pathlib import PurePath
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from .infrai_storage import InfraiError, InfraiStorage

BUCKET = "legal-product-assets"


class AssetKind(str, Enum):
    MATTER_INTAKE = "matter_intake"
    SIGNED_DOCUMENT = "signed_document"
    DEADLINE_FOLLOW_UP = "deadline_follow_up"


class UploadRequest(BaseModel):
    matter_id: UUID
    asset_kind: AssetKind
    filename: str = Field(min_length=1, max_length=180)
    content_type: str
    size_bytes: int = Field(gt=0)
    request_id: UUID


class UploadGrant(BaseModel):
    upload_url: str
    method: str
    object_key: str
    expires_seconds: int


POLICY = {
    AssetKind.MATTER_INTAKE: ({"application/pdf", "image/jpeg", "image/png"}, 10_000_000),
    AssetKind.SIGNED_DOCUMENT: ({"application/pdf"}, 25_000_000),
    AssetKind.DEADLINE_FOLLOW_UP: ({"application/pdf", "image/jpeg", "image/png"}, 8_000_000),
}


def object_key_for(request: UploadRequest) -> str:
    clean_name = PurePath(request.filename).name
    if clean_name in {"", ".", ".."}:
        raise ValueError("filename must name a file")
    return f"matters/{request.matter_id}/{request.asset_kind.value}/{request.request_id}-{clean_name}"


def authorize_upload(request: UploadRequest) -> tuple[str, int]:
    allowed_types, max_bytes = POLICY[request.asset_kind]
    if request.content_type not in allowed_types:
        raise ValueError(f"{request.asset_kind.value} does not accept {request.content_type}")
    if request.size_bytes > max_bytes:
        raise ValueError(f"{request.asset_kind.value} exceeds its {max_bytes}-byte limit")
    return object_key_for(request), max_bytes


def get_storage() -> InfraiStorage:
    return InfraiStorage()


app = FastAPI(title="Legal asset upload intake")


@app.on_event("startup")
def prepare_storage() -> None:
    try:
        get_storage().create_bucket(BUCKET)
    except InfraiError as exc:
        if exc.code != "STORAGE_BUCKET_EXISTS":
            raise


@app.post("/upload-grants", response_model=UploadGrant)
def issue_upload_grant(
    request: UploadRequest,
    storage: InfraiStorage = Depends(get_storage),
) -> UploadGrant:
    try:
        object_key, max_bytes = authorize_upload(request)
        signed = storage.presign_put(
            BUCKET,
            object_key,
            content_type=request.content_type,
            max_bytes=max_bytes,
            idempotency_key=str(request.request_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except InfraiError as exc:
        client_status = exc.status_code if 400 <= exc.status_code < 500 else 502
        raise HTTPException(
            status_code=client_status,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc

    return UploadGrant(
        upload_url=str(signed["url"]),
        method="PUT",
        object_key=object_key,
        expires_seconds=600,
    )
