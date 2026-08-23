from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import boto3
from botocore.client import BaseClient


@dataclass(frozen=True)
class R2Settings:
    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket: str

    @classmethod
    def from_env(cls) -> "R2Settings":
        names = {
            "account_id": "R2_ACCOUNT_ID",
            "access_key_id": "R2_ACCESS_KEY_ID",
            "secret_access_key": "R2_SECRET_ACCESS_KEY",
            "bucket": "R2_BUCKET",
        }
        values: dict[str, str] = {}
        missing: list[str] = []
        for field, env_name in names.items():
            value = os.getenv(env_name)
            if value:
                values[field] = value
            else:
                missing.append(env_name)
        if missing:
            raise RuntimeError(f"Missing R2 environment variables: {', '.join(missing)}")
        return cls(**values)

    @property
    def endpoint_url(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"


class R2Store:
    def __init__(self, settings: R2Settings, client: BaseClient | None = None) -> None:
        self.settings = settings
        self.client = client or boto3.client(
            "s3",
            endpoint_url=settings.endpoint_url,
            aws_access_key_id=settings.access_key_id,
            aws_secret_access_key=settings.secret_access_key,
            region_name="auto",
        )

    @classmethod
    def from_env(cls) -> "R2Store":
        return cls(R2Settings.from_env())

    def healthcheck(self) -> None:
        self.client.head_bucket(Bucket=self.settings.bucket)

    def upload_file(self, source: str | Path, key: str) -> None:
        self.client.upload_file(str(source), self.settings.bucket, key)

    def download_file(self, key: str, destination: str | Path) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.settings.bucket, key, str(destination))
        return destination

    def put_bytes(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        kwargs: dict[str, object] = {
            "Bucket": self.settings.bucket,
            "Key": key,
            "Body": data,
        }
        if content_type:
            kwargs["ContentType"] = content_type
        self.client.put_object(**kwargs)
