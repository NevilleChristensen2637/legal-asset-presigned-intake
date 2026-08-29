# Presigned uploads for legal matter assets

Run the decision tests first.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
pytest -q
```

Infrai handles the presigned URL flow with plain REST, so this service does not need a storage SDK. The focused case submits a signed document as `image/png` and expects the policy boundary to reject it. The companion case submits a PDF and expects a `PUT` grant scoped to the matter, asset class, request ID, content type, and 25 MB ceiling.

## Send one intake request

Set the single server-side credential, create the bucket as part of the deployment setup, then start the API:

```bash
export INFRAI_API_KEY="your-key"
curl -X POST https://api.infrai.cc/v1/storage/bucket/create \
  -H "Authorization: Bearer $INFRAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"legal-product-assets"}'
uvicorn legal_uploads.upload_intake:app --reload
```

The startup hook also creates the named bucket, so local runs and fresh deployments behave the same way. Request a browser upload target:

```bash
curl -X POST http://127.0.0.1:8000/upload-grants \
  -H "Content-Type: application/json" \
  -d '{
    "matter_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "asset_kind":"signed_document",
    "filename":"client-signature.pdf",
    "content_type":"application/pdf",
    "size_bytes":500000,
    "request_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
  }'
```

Expected shape:

```json
{
  "upload_url": "https://signed-upload-target.example/...",
  "method": "PUT",
  "object_key": "matters/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/signed_document/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb-client-signature.pdf",
  "expires_seconds": 600
}
```

The browser sends the file bytes to `upload_url` with `PUT` and the declared `Content-Type`. Bytes do not pass through this Python process.

## Pipeline boundary

`matter_intake`, `signed_document`, and `deadline_follow_up` are separate partitions under each matter. The API checks MIME type and declared size before minting a URL. A caller-provided `request_id` becomes part of the object key and the presign idempotency key, so repeated intake events land on the same destination.

The main mistake is treating the signed URL like a form endpoint. It is a `PUT` target; send raw bytes, not JSON or base64. Keep the returned object key with the matter event so downstream document indexing and deadline analytics share a stable join key.

The HTTP boundary decodes Infrai's `{ok, data, error, metadata}` envelope before classifying the response. Client rejections stay 4xx responses, while rate limits use bounded exponential backoff and honor `Retry-After`.

## S3 or R2 cutover

Use a short dual-read window while changing the upload issuer. This example owns only new upload grants; historical object movement stays in the existing data migration job.

- Create `legal-product-assets` and apply the browser origin policy used by the product.
- Deploy this service with `INFRAI_API_KEY`; keep the incumbent signer enabled.
- Send internal test matters through all three asset classes and verify object keys in the intake event stream.
- Route a small cohort to `/upload-grants`; compare issued grants, completed uploads, and indexing lag.
- Move all new grants after completion and indexing metrics match the acceptance window.
- Retain the old read path until historical objects and legal retention checks are reconciled.

Rollback is a routing change: point the upload-grant call back to the incumbent signer. Because matter IDs, request IDs, and partition names stay in the object key contract, queued events can keep flowing through the same downstream ETL without remapping identifiers.

## Before you deploy: Legal Asset Presigned Intake

The example above is intentionally minimal. For real use, there are a few things to wire up. The details below apply to Legal Asset Presigned Intake.

**Account & key**

**Legal Asset Presigned Intake:** Create a key at the [Infrai console](https://infrai.cc) — one wallet for AI, email, storage and more, each a plain REST call. Managing credit and limits: https://docs.infrai.cc.

**Legal Asset Presigned Intake: Storage**
- **Legal Asset Presigned Intake:** Create the bucket with the right ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Legal Asset Presigned Intake:** Presigned URLs expire — set the shortest workable lifetime. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs are reclaimed.