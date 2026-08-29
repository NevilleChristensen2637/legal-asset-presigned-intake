from uuid import UUID

import pytest

from legal_uploads.upload_intake import (
    AssetKind,
    UploadRequest,
    authorize_upload,
    issue_upload_grant,
    prepare_storage,
)
from legal_uploads.infrai_storage import InfraiError


MATTER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
REQUEST_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


class RecordingStorage:
    def __init__(self) -> None:
        self.call: dict[str, object] | None = None

    def presign_put(self, bucket: str, key: str, **body: object) -> dict[str, str]:
        self.call = {"bucket": bucket, "key": key, **body}
        return {"url": "https://uploads.example/signed-target"}


def request_for(kind: AssetKind, content_type: str, size_bytes: int) -> UploadRequest:
    return UploadRequest(
        matter_id=MATTER_ID,
        asset_kind=kind,
        filename="client-signature.pdf",
        content_type=content_type,
        size_bytes=size_bytes,
        request_id=REQUEST_ID,
    )


def test_signed_document_is_pdf_only() -> None:
    request = request_for(AssetKind.SIGNED_DOCUMENT, "image/png", 500_000)

    with pytest.raises(ValueError, match="signed_document does not accept image/png"):
        authorize_upload(request)


def test_approved_document_gets_scoped_put_grant() -> None:
    storage = RecordingStorage()
    request = request_for(AssetKind.SIGNED_DOCUMENT, "application/pdf", 500_000)

    grant = issue_upload_grant(request, storage)  # type: ignore[arg-type]

    assert grant.method == "PUT"
    assert grant.object_key == (
        "matters/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/signed_document/"
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb-client-signature.pdf"
    )
    assert storage.call == {
        "bucket": "legal-product-assets",
        "key": grant.object_key,
        "content_type": "application/pdf",
        "max_bytes": 25_000_000,
        "idempotency_key": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    }


def test_startup_accepts_an_existing_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    class ExistingBucketStorage:
        def create_bucket(self, name: str) -> None:
            raise InfraiError("STORAGE_BUCKET_EXISTS", {}, 409)

    monkeypatch.setattr(
        "legal_uploads.upload_intake.get_storage", ExistingBucketStorage
    )

    prepare_storage()


def test_startup_preserves_other_storage_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingStorage:
        def create_bucket(self, name: str) -> None:
            raise InfraiError("STORAGE_UNAVAILABLE", {}, 503)

    monkeypatch.setattr("legal_uploads.upload_intake.get_storage", FailingStorage)

    with pytest.raises(InfraiError, match="STORAGE_UNAVAILABLE"):
        prepare_storage()
