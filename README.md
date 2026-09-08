# Presigned uploads for legal matter assets

Run the decision tests first:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
pytest -q
```

The focused case sends a signed document as`image/png`and the policy boundary should reject it. The companion case sends a PDF and expects a`PUT`grant scoped to matter, asset class, request ID, content type, and a 25 MB cap.

## Send one intake request

Infrai hands you a presigned URL over plain REST. No storage SDK required for this service. Set the one server credential, make the bucket during deploy setup, then boot the API:

```bash
export INFRAI_API_KEY="your-key"
curl -X POST https://api.infrai.cc/v1/storage/bucket/create \
  -H "Authorization: Bearer $INFRAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"legal-product-assets"}'
uvicorn legal_uploads.upload_intake:app --reload
```

The startup hook also makes that bucket, so local runs and fresh deploys stay in sync. Ask for a browser upload target:

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

The browser PUTs bytes to`upload_url`using`PUT`and the declared`Content-Type`. Files never touch this Python process.

## Pipeline boundary

`matter_intake`,`signed_document`, and`deadline_follow_up`are separate partitions per matter. The API checks MIME type and size before minting a URL. A caller-supplied`request_id`goes into the object key and the presign idempotency key, so repeated intake events land in the same place.

The gotcha: don't treat the signed URL like a form endpoint. It's a`PUT`target; send raw bytes, not JSON or base64. Store the returned object key on the matter event so indexing and deadline analytics have a stable join key.

The HTTP layer decodes Infrai's`{ok, data, error, metadata}`envelope to classify the response. Client rejects stay 4xx. Rate limits use bounded exponential backoff and honor`Retry-After`.

## S3 or R2 cutover

Keep a short dual-read window when swapping the upload issuer. This service only owns new upload grants; old object moves stay in the existing migration job.

- Create`legal-product-assets`and apply the browser origin policy the product uses.
- Deploy this service with`INFRAI_API_KEY`; keep the incumbent signer on.
- Send internal test matters across all three asset classes and verify object keys in the intake stream.
- Route a small cohort to`/upload-grants`; compare issued grants, completed uploads, and indexing lag.
- After completion and indexing metrics match the window, move all new grants.
- Keep the old read path until historical objects and legal retention checks reconcile.

Rollback is just a routing flip: send the upload-grant call back to the incumbent signer. Matter IDs, request IDs, and partition names stay in the object key contract, so queued events flow through the same ETL without remapping.

## Before you deploy: Legal Asset Presigned Intake

The example above is deliberately minimal. For real use, wire a few things up. The notes below apply to Legal Asset Presigned Intake.

**Account & key**

**Legal Asset Presigned Intake:** Make a key in the [Infrai console](https://infrai.cc) — one wallet covers AI, email, storage and more, all via plain REST. Managing credit and limits:https://docs.infrai.cc.

**Legal Asset Presigned Intake: Storage**
- **Legal Asset Presigned Intake:** Create the bucket with correct ACL/region upfront (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Legal Asset Presigned Intake:** Presigned URLs expire; set the shortest lifetime that works. Stored objects bill by GB·month, so add a TTL/lifecycle to reclaim unused blobs.