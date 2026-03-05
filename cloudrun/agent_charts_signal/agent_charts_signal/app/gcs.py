from __future__ import annotations

from datetime import timedelta

from google.cloud import storage


def get_storage_client() -> storage.Client:
    return storage.Client()


def sign_put_url(
    *,
    client: storage.Client,
    bucket: str,
    blob_name: str,
    ttl_seconds: int,
    content_type: str,
) -> str:
    b = client.bucket(bucket)
    blob = b.blob(blob_name)
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(seconds=ttl_seconds),
        method="PUT",
        content_type=content_type,
    )


def sign_get_url(
    *,
    client: storage.Client,
    bucket: str,
    blob_name: str,
    ttl_seconds: int,
) -> str:
    b = client.bucket(bucket)
    blob = b.blob(blob_name)
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(seconds=ttl_seconds),
        method="GET",
    )


def download_bytes(*, client: storage.Client, bucket: str, blob_name: str) -> bytes:
    b = client.bucket(bucket)
    blob = b.blob(blob_name)
    return blob.download_as_bytes()


def blob_exists(*, client: storage.Client, bucket: str, blob_name: str) -> bool:
    b = client.bucket(bucket)
    blob = b.blob(blob_name)
    return blob.exists(client)


def list_blob_names(*, client: storage.Client, bucket: str, prefix: str) -> list[str]:
    b = client.bucket(bucket)
    return [blob.name for blob in client.list_blobs(b, prefix=prefix)]


def delete_blob_prefix(*, client: storage.Client, bucket: str, prefix: str) -> int:
    b = client.bucket(bucket)
    deleted = 0
    for blob in client.list_blobs(b, prefix=prefix):
        blob.delete(client=client)
        deleted += 1
    return deleted


def upload_json_bytes(*, client: storage.Client, bucket: str, blob_name: str, data: bytes) -> None:
    b = client.bucket(bucket)
    blob = b.blob(blob_name)
    blob.upload_from_string(data, content_type="application/json")
