"""
utils.py - Helper utilities for Ray Document Processing Pipeline

Author: Prudhvi | Thoughtworks
"""

import boto3
import logging
import os
import shutil
from pathlib import Path
from datetime import datetime


logger = logging.getLogger(__name__)


class S3Helper:
    """S3 upload/download operations."""

    def __init__(self, bucket: str, region: str = 'us-east-1'):
        self.bucket = bucket
        self.s3 = boto3.client('s3', region_name=region)

    def download_file(self, s3_key: str, local_path: str) -> bool:
        try:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            self.s3.download_file(self.bucket, s3_key, local_path)
            logger.info(f"Downloaded s3://{self.bucket}/{s3_key} → {local_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to download {s3_key}: {e}")
            return False

    def upload_file(self, local_path: str, s3_key: str) -> bool:
        try:
            self.s3.upload_file(local_path, self.bucket, s3_key)
            logger.info(f"Uploaded {local_path} → s3://{self.bucket}/{s3_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to upload {local_path}: {e}")
            return False

    def upload_directory(self, local_dir: str, s3_prefix: str) -> bool:
        try:
            for root, _, files in os.walk(local_dir):
                for file in files:
                    local_path = os.path.join(root, file)
                    relative_path = os.path.relpath(local_path, local_dir)
                    self.upload_file(local_path, f"{s3_prefix}/{relative_path}")
            logger.info(f"Uploaded {local_dir} → s3://{self.bucket}/{s3_prefix}")
            return True
        except Exception as e:
            logger.error(f"Failed to upload directory {local_dir}: {e}")
            return False

    def download_directory(self, s3_prefix: str, local_dir: str) -> bool:
        try:
            Path(local_dir).mkdir(parents=True, exist_ok=True)
            paginator = self.s3.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=self.bucket, Prefix=s3_prefix):
                for obj in page.get('Contents', []):
                    s3_key = obj['Key']
                    if s3_key.endswith('/'):
                        continue
                    relative_path = s3_key[len(s3_prefix):].lstrip('/')
                    self.download_file(s3_key, os.path.join(local_dir, relative_path))
            logger.info(f"Downloaded s3://{self.bucket}/{s3_prefix} → {local_dir}")
            return True
        except Exception as e:
            logger.error(f"Failed to download directory {s3_prefix}: {e}")
            return False


class LocalFileManager:
    """Manages temporary local workspaces during processing."""

    def __init__(self, base_dir: str = '/tmp/ray_pipeline'):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_document_workspace(self, document_id: str) -> Path:
        workspace = self.base_dir / document_id
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def cleanup_document_workspace(self, document_id: str):
        workspace = self.base_dir / document_id
        if workspace.exists():
            shutil.rmtree(workspace)
            logger.info(f"Cleaned up workspace for {document_id}")


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds / 60:.1f}m"
    else:
        return f"{seconds / 3600:.2f}h"


def get_timestamp() -> str:
    return datetime.utcnow().isoformat() + 'Z'


def setup_logging(level: str = 'INFO'):
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logging.getLogger('boto3').setLevel(logging.WARNING)
    logging.getLogger('botocore').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
