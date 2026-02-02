"""
utils.py

Helper utilities for Ray Document Processing Pipeline

Author: Prudhvi
Organization: Thoughtworks
"""

import boto3
import logging
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import json


logger = logging.getLogger(__name__)


class S3Helper:
    """Helper class for S3 operations."""
    
    def __init__(self, bucket: str, region: str = 'us-east-1'):
        self.bucket = bucket
        self.s3 = boto3.client('s3', region_name=region)
    
    def download_file(self, s3_key: str, local_path: str) -> bool:
        """Download file from S3 to local path."""
        try:
            # Create directory if doesn't exist
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            
            self.s3.download_file(self.bucket, s3_key, local_path)
            logger.info(f"Downloaded s3://{self.bucket}/{s3_key} to {local_path}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to download {s3_key}: {e}")
            return False
    
    def upload_file(self, local_path: str, s3_key: str) -> bool:
        """Upload file from local path to S3."""
        try:
            self.s3.upload_file(local_path, self.bucket, s3_key)
            logger.info(f"Uploaded {local_path} to s3://{self.bucket}/{s3_key}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to upload {local_path}: {e}")
            return False
    
    def upload_directory(self, local_dir: str, s3_prefix: str) -> bool:
        """Recursively upload directory to S3."""
        try:
            for root, dirs, files in os.walk(local_dir):
                for file in files:
                    local_path = os.path.join(root, file)
                    relative_path = os.path.relpath(local_path, local_dir)
                    s3_key = f"{s3_prefix}/{relative_path}"
                    
                    self.upload_file(local_path, s3_key)
            
            logger.info(f"Uploaded directory {local_dir} to s3://{self.bucket}/{s3_prefix}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to upload directory {local_dir}: {e}")
            return False
    
    def download_directory(self, s3_prefix: str, local_dir: str) -> bool:
        """Download all files with given S3 prefix to local directory."""
        try:
            Path(local_dir).mkdir(parents=True, exist_ok=True)
            
            paginator = self.s3.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=self.bucket, Prefix=s3_prefix):
                for obj in page.get('Contents', []):
                    s3_key = obj['Key']
                    
                    # Skip if it's just the prefix (directory marker)
                    if s3_key.endswith('/'):
                        continue
                    
                    relative_path = s3_key[len(s3_prefix):].lstrip('/')
                    local_file = os.path.join(local_dir, relative_path)
                    
                    self.download_file(s3_key, local_file)
            
            logger.info(f"Downloaded s3://{self.bucket}/{s3_prefix} to {local_dir}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to download directory {s3_prefix}: {e}")
            return False
    
    def list_objects(self, prefix: str) -> List[str]:
        """List all object keys with given prefix."""
        try:
            keys = []
            paginator = self.s3.get_paginator('list_objects_v2')
            
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get('Contents', []):
                    keys.append(obj['Key'])
            
            return keys
        
        except Exception as e:
            logger.error(f"Failed to list objects with prefix {prefix}: {e}")
            return []
    
    def delete_object(self, s3_key: str) -> bool:
        """Delete object from S3."""
        try:
            self.s3.delete_object(Bucket=self.bucket, Key=s3_key)
            logger.info(f"Deleted s3://{self.bucket}/{s3_key}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to delete {s3_key}: {e}")
            return False
    
    def copy_object(self, source_key: str, dest_key: str) -> bool:
        """Copy object within S3 bucket."""
        try:
            copy_source = {'Bucket': self.bucket, 'Key': source_key}
            self.s3.copy_object(
                Bucket=self.bucket,
                CopySource=copy_source,
                Key=dest_key
            )
            logger.info(f"Copied {source_key} to {dest_key}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to copy {source_key} to {dest_key}: {e}")
            return False
    
    def get_file_size(self, s3_key: str) -> Optional[int]:
        """Get file size in bytes."""
        try:
            response = self.s3.head_object(Bucket=self.bucket, Key=s3_key)
            return response['ContentLength']
        
        except Exception as e:
            logger.error(f"Failed to get file size for {s3_key}: {e}")
            return None


class LocalFileManager:
    """Manages local temporary files during processing."""
    
    def __init__(self, base_dir: str = '/tmp/ray_pipeline'):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    def create_document_workspace(self, document_id: str) -> Path:
        """Create workspace directory for a document."""
        workspace = self.base_dir / document_id
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace
    
    def cleanup_document_workspace(self, document_id: str):
        """Clean up workspace for a document."""
        workspace = self.base_dir / document_id
        if workspace.exists():
            shutil.rmtree(workspace)
            logger.info(f"Cleaned up workspace for {document_id}")
    
    def cleanup_all(self):
        """Clean up all temporary files."""
        if self.base_dir.exists():
            shutil.rmtree(self.base_dir)
            self.base_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Cleaned up all temporary files")


class MetricsCollector:
    """Collects and aggregates pipeline metrics."""
    
    def __init__(self):
        self.metrics: Dict[str, float] = {}
    
    def record_metric(self, name: str, value: float):
        """Record a metric value."""
        if name not in self.metrics:
            self.metrics[name] = []
        self.metrics[name].append(value)
    
    def get_average(self, name: str) -> Optional[float]:
        """Get average of a metric."""
        if name not in self.metrics or not self.metrics[name]:
            return None
        return sum(self.metrics[name]) / len(self.metrics[name])
    
    def get_sum(self, name: str) -> Optional[float]:
        """Get sum of a metric."""
        if name not in self.metrics or not self.metrics[name]:
            return None
        return sum(self.metrics[name])
    
    def get_count(self, name: str) -> int:
        """Get count of metric values."""
        if name not in self.metrics:
            return 0
        return len(self.metrics[name])
    
    def get_summary(self) -> Dict:
        """Get summary of all metrics."""
        summary = {}
        for name in self.metrics:
            summary[name] = {
                'count': self.get_count(name),
                'sum': self.get_sum(name),
                'average': self.get_average(name)
            }
        return summary
    
    def reset(self):
        """Reset all metrics."""
        self.metrics = {}


def generate_document_id(prefix: str = 'doc') -> str:
    """Generate unique document ID."""
    import uuid
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    unique_id = uuid.uuid4().hex[:8]
    return f"{prefix}_{timestamp}_{unique_id}"


def format_duration(seconds: float) -> str:
    """Format duration in human-readable format."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    else:
        hours = seconds / 3600
        return f"{hours:.2f}h"


def format_file_size(bytes: int) -> str:
    """Format file size in human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes < 1024.0:
            return f"{bytes:.2f} {unit}"
        bytes /= 1024.0
    return f"{bytes:.2f} PB"


def safe_json_dumps(obj: Dict, **kwargs) -> str:
    """Safely dump JSON with fallback for non-serializable objects."""
    def default_handler(o):
        if isinstance(o, datetime):
            return o.isoformat()
        elif isinstance(o, Path):
            return str(o)
        elif hasattr(o, '__dict__'):
            return o.__dict__
        else:
            return str(o)
    
    return json.dumps(obj, default=default_handler, **kwargs)


def get_timestamp() -> str:
    """Get current UTC timestamp in ISO format."""
    return datetime.utcnow().isoformat() + 'Z'


def parse_s3_uri(s3_uri: str) -> tuple:
    """Parse S3 URI into bucket and key."""
    # s3://bucket/key/path -> (bucket, key/path)
    if not s3_uri.startswith('s3://'):
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    
    parts = s3_uri[5:].split('/', 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ''
    
    return bucket, key


def setup_logging(level: str = 'INFO'):
    """Setup logging configuration."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Reduce noise from boto3 and other libraries
    logging.getLogger('boto3').setLevel(logging.WARNING)
    logging.getLogger('botocore').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
