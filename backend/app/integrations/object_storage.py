from typing import Optional

import aioboto3
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.config import (
    MINIO_ACCESS_KEY,
    MINIO_BUCKET,
    MINIO_ENDPOINT,
    MINIO_REGION,
    MINIO_SECRET_KEY,
)


_sync_s3_client = None


def _client_kwargs() -> dict:
    return {
        "endpoint_url": MINIO_ENDPOINT,
        "aws_access_key_id": MINIO_ACCESS_KEY,
        "aws_secret_access_key": MINIO_SECRET_KEY,
        "config": Config(signature_version="s3v4"),
        "region_name": MINIO_REGION,
    }


def get_sync_s3_client():
    global _sync_s3_client

    if _sync_s3_client is None:
        _sync_s3_client = boto3.client("s3", **_client_kwargs())

    return _sync_s3_client


def ensure_bucket_exists_sync() -> None:
    client = get_sync_s3_client()

    try:
        client.head_bucket(Bucket=MINIO_BUCKET)
    except ClientError:
        client.create_bucket(Bucket=MINIO_BUCKET)


def put_bytes_sync(key: str, data: bytes, content_type: str) -> None:
    ensure_bucket_exists_sync()

    get_sync_s3_client().put_object(
        Bucket=MINIO_BUCKET,
        Key=key,
        Body=data,
        ContentType=content_type,
    )


async def get_object_bytes(key: str) -> tuple[bytes, str]:
    session = aioboto3.Session()

    async with session.client("s3", **_client_kwargs()) as client:
        try:
            response = await client.get_object(
                Bucket=MINIO_BUCKET,
                Key=key,
            )
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in {"NoSuchKey", "404", "NotFound"}:
                raise FileNotFoundError(key)
            raise

        async with response["Body"] as stream:
            body = await stream.read()

        content_type = response.get("ContentType") or "application/octet-stream"

        return body, content_type


async def object_exists(key: str) -> bool:
    session = aioboto3.Session()

    async with session.client("s3", **_client_kwargs()) as client:
        try:
            await client.head_object(
                Bucket=MINIO_BUCKET,
                Key=key,
            )
            return True
        except ClientError:
            return False


async def find_cover_key(book_id: int) -> Optional[str]:
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        key = book_cover_key(book_id, ext)

        if await object_exists(key):
            return key

    return None


def book_cover_key(book_id: int, ext: str) -> str:
    ext = ext if ext.startswith(".") else f".{ext}"
    return f"books/{book_id}/cover{ext.lower()}"


def chapter_key(book_id: int, chapter_id: int) -> str:
    return f"books/{book_id}/chapters/{chapter_id}.xml"


def cover_content_type(ext: str) -> str:
    ext = ext.lower()

    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"

    return "application/octet-stream"