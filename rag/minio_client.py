import io
import datetime
import os
from pathlib import Path
from typing import Optional, Tuple
from minio import Minio
from minio.error import S3Error

MINIO_CONFIG = {
    'endpoint': os.getenv('MINIO_ENDPOINT', 'localhost:9000'),
    'access_key': os.getenv('MINIO_ACCESS_KEY', 'minioadmin'),
    'secret_key': os.getenv('MINIO_SECRET_KEY', 'minioadmin'),
    'bucket_name': os.getenv('MINIO_BUCKET', 'ros123'),
    'secure': os.getenv('MINIO_SECURE', 'false').lower() in {'1', 'true', 'yes'},
}

_client = None

def get_minio_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            endpoint=MINIO_CONFIG['endpoint'],
            access_key=MINIO_CONFIG['access_key'],
            secret_key=MINIO_CONFIG['secret_key'],
            secure=MINIO_CONFIG['secure'],
        )
        bucket = MINIO_CONFIG['bucket_name']
        if not _client.bucket_exists(bucket):
            _client.make_bucket(bucket)
    return _client

def upload_file_bytes(data: bytes, object_name: str, content_type: str = 'application/octet-stream') -> Tuple[str, str]:
    client = get_minio_client()
    bucket = MINIO_CONFIG['bucket_name']
    client.put_object(bucket, object_name, io.BytesIO(data), len(data), content_type=content_type)
    url = client.presigned_get_object(bucket, object_name, expires=datetime.timedelta(days=7))
    return object_name, url

def upload_local_file(file_path: Path, object_name: Optional[str] = None) -> Tuple[str, str]:
    client = get_minio_client()
    bucket = MINIO_CONFIG['bucket_name']
    if object_name is None:
        object_name = file_path.name
    client.fput_object(bucket, object_name, str(file_path))
    url = client.presigned_get_object(bucket, object_name, expires=datetime.timedelta(days=7))
    return object_name, url

def delete_object(object_name: str) -> bool:
    try:
        client = get_minio_client()
        bucket = MINIO_CONFIG['bucket_name']
        client.remove_object(bucket, object_name)
        return True
    except S3Error:
        return False

def download_object_bytes(object_name: str) -> bytes:
    client = get_minio_client()
    response = client.get_object(MINIO_CONFIG['bucket_name'], object_name)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()

def get_object_url(object_name: str) -> Optional[str]:
    try:
        client = get_minio_client()
        bucket = MINIO_CONFIG['bucket_name']
        return client.presigned_get_object(bucket, object_name, expires=datetime.timedelta(days=7))
    except S3Error:
        return None
