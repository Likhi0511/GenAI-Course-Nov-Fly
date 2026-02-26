"""
dynamodb_manager.py

DynamoDB Manager for Ray Document Processing Pipeline
Handles all DynamoDB operations with error handling and retries

Author: Prudhvi
Organization: Thoughtworks
"""

import boto3
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from decimal import Decimal

from config import config
from utils import get_timestamp


logger = logging.getLogger(__name__)


class DynamoDBManager:
    """Manages all DynamoDB operations with error handling and retries."""
    
    def __init__(self, region: str = None):
        """Initialize DynamoDB manager."""
        self.region = region or config.AWS_REGION
        self.dynamodb = boto3.resource('dynamodb', region_name=self.region)
        
        self.control_table = self.dynamodb.Table(config.DYNAMODB_CONTROL_TABLE)
        self.audit_table = self.dynamodb.Table(config.DYNAMODB_AUDIT_TABLE)
        self.metrics_table = self.dynamodb.Table(config.DYNAMODB_METRICS_TABLE)
        
        logger.info("DynamoDB Manager initialized")
    
    def create_control_record(self, document_id: str, s3_key: str, 
                            file_size: int, bucket: str) -> bool:
        """Create initial control record for new document."""
        try:
            timestamp = get_timestamp()
            
            self.control_table.put_item(
                Item={
                    'document_id': document_id,
                    'processing_version': 'v1',
                    'source_s3_key': s3_key,
                    'source_bucket': bucket,
                    'file_size_bytes': file_size,
                    'upload_timestamp': timestamp,
                    'status': 'PENDING',
                    'current_stage': 'extraction',
                    'created_at': timestamp,
                    'updated_at': timestamp,
                    'stage_status': {
                        'extraction': {'status': 'PENDING'},
                        'chunking': {'status': 'PENDING'},
                        'enrichment': {'status': 'PENDING'},
                        'embedding': {'status': 'PENDING'},
                        'loading': {'status': 'PENDING'}
                    },
                    'retry_count': 0,
                    'max_retries': config.MAX_RETRIES,
                    'ttl': int(time.time()) + (90 * 24 * 3600)  # 90 days
                }
            )
            
            # Log audit event
            self.log_audit_event(
                document_id=document_id,
                event_type='DOCUMENT_RECEIVED',
                stage='ingestion',
                metadata={'source': 's3_event', 'file_size': file_size}
            )
            
            logger.info(f"Created control record for {document_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create control record: {e}")
            return False
    
    def update_stage_status(self, document_id: str, stage: str, 
                          status: str, **kwargs) -> bool:
        """Update status of a specific processing stage."""
        try:
            timestamp = get_timestamp()
            
            # Build stage data
            stage_data = {
                'status': status,
                'updated_at': timestamp
            }
            
            # Add optional fields
            if 'started_at' in kwargs:
                stage_data['started_at'] = kwargs['started_at']
            
            if 'completed_at' in kwargs:
                stage_data['completed_at'] = kwargs['completed_at']
            
            if 'duration_seconds' in kwargs:
                stage_data['duration_seconds'] = kwargs['duration_seconds']
            
            if 'output_s3_key' in kwargs:
                stage_data['output_s3_key'] = kwargs['output_s3_key']
            
            if 'error' in kwargs:
                stage_data['error'] = kwargs['error']
            
            # Add metadata
            if 'metadata' in kwargs:
                stage_data.update(kwargs['metadata'])
            
            # Update DynamoDB
            self.control_table.update_item(
                Key={
                    'document_id': document_id,
                    'processing_version': 'v1'
                },
                UpdateExpression=(
                    "SET stage_status.#stage = :stage_data, "
                    "updated_at = :timestamp, "
                    "current_stage = :current_stage, "
                    "#status = :overall_status"
                ),
                ExpressionAttributeNames={
                    '#stage': stage,
                    '#status': 'status'
                },
                ExpressionAttributeValues={
                    ':stage_data': stage_data,
                    ':timestamp': timestamp,
                    ':current_stage': stage,
                    ':overall_status': status if status == 'FAILED' else 'IN_PROGRESS'
                }
            )
            
            # Log audit event
            event_type = f"STAGE_{status}"
            self.log_audit_event(
                document_id=document_id,
                event_type=event_type,
                stage=stage,
                status=status,
                duration_seconds=kwargs.get('duration_seconds'),
                metadata=kwargs.get('metadata', {})
            )
            
            logger.info(f"Updated {stage} status to {status} for {document_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update stage status: {e}")
            return False
    
    def mark_document_completed(self, document_id: str) -> bool:
        """Mark document as completed."""
        try:
            timestamp = get_timestamp()
            
            self.control_table.update_item(
                Key={
                    'document_id': document_id,
                    'processing_version': 'v1'
                },
                UpdateExpression="SET #status = :status, updated_at = :timestamp, completed_at = :timestamp",
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={
                    ':status': 'COMPLETED',
                    ':timestamp': timestamp
                }
            )
            
            # Log audit event
            self.log_audit_event(
                document_id=document_id,
                event_type='DOCUMENT_COMPLETED',
                stage='pipeline',
                status='COMPLETED'
            )
            
            logger.info(f"Marked document {document_id} as COMPLETED")
            return True
            
        except Exception as e:
            logger.error(f"Failed to mark document as completed: {e}")
            return False
    
    def mark_document_failed(self, document_id: str, stage: str, 
                           error: str) -> bool:
        """Mark document as failed with error details."""
        try:
            timestamp = get_timestamp()
            
            self.control_table.update_item(
                Key={
                    'document_id': document_id,
                    'processing_version': 'v1'
                },
                UpdateExpression=(
                    "SET #status = :status, "
                    "updated_at = :timestamp, "
                    "last_error = :error, "
                    "error_stage = :stage"
                ),
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={
                    ':status': 'FAILED',
                    ':timestamp': timestamp,
                    ':error': error,
                    ':stage': stage
                }
            )
            
            # Log audit event
            self.log_audit_event(
                document_id=document_id,
                event_type='DOCUMENT_FAILED',
                stage=stage,
                status='FAILED',
                error_type='ProcessingError',
                error_message=error
            )
            
            logger.error(f"Marked document {document_id} as FAILED at stage {stage}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to mark document as failed: {e}")
            return False
    
    def log_audit_event(self, document_id: str, event_type: str, 
                       stage: str, **kwargs):
        """Log immutable audit event."""
        try:
            timestamp = get_timestamp()
            
            audit_item = {
                'document_id': document_id,
                'timestamp': timestamp,
                'event_type': event_type,
                'stage': stage,
                'processing_version': 'v1',
                'ttl': int(time.time()) + (180 * 24 * 3600)  # 180 days
            }
            
            # Add optional fields
            for key in ['status', 'worker_id', 'ray_task_id', 'duration_seconds',
                       'output_s3_key', 'error_type', 'error_message']:
                if key in kwargs:
                    audit_item[key] = kwargs[key]
            
            # Add metadata
            if 'metadata' in kwargs:
                audit_item['metadata'] = kwargs['metadata']
            
            self.audit_table.put_item(Item=audit_item)
            
        except Exception as e:
            logger.error(f"Failed to log audit event: {e}")
    
    def get_pending_documents(self, limit: int = 100) -> List[Dict]:
        """Fetch documents ready for processing."""
        try:
            response = self.control_table.query(
                IndexName='status-index',
                KeyConditionExpression='#status = :status',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={':status': 'PENDING'},
                Limit=limit
            )
            
            documents = response.get('Items', [])
            logger.info(f"Found {len(documents)} pending documents")
            return documents
            
        except Exception as e:
            logger.error(f"Failed to fetch pending documents: {e}")
            return []
    
    def get_document(self, document_id: str) -> Optional[Dict]:
        """Get document control record."""
        try:
            response = self.control_table.get_item(
                Key={
                    'document_id': document_id,
                    'processing_version': 'v1'
                }
            )
            return response.get('Item')
            
        except Exception as e:
            logger.error(f"Failed to get document {document_id}: {e}")
            return None
    
    def increment_retry_count(self, document_id: str) -> bool:
        """Increment retry count for a document."""
        try:
            self.control_table.update_item(
                Key={
                    'document_id': document_id,
                    'processing_version': 'v1'
                },
                UpdateExpression="SET retry_count = retry_count + :inc",
                ExpressionAttributeValues={':inc': 1}
            )
            
            logger.info(f"Incremented retry count for {document_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to increment retry count: {e}")
            return False
    
    def get_audit_trail(self, document_id: str) -> List[Dict]:
        """Get complete audit trail for a document."""
        try:
            response = self.audit_table.query(
                KeyConditionExpression='document_id = :doc_id',
                ExpressionAttributeValues={':doc_id': document_id},
                ScanIndexForward=True  # Sort by timestamp ascending
            )
            
            return response.get('Items', [])
            
        except Exception as e:
            logger.error(f"Failed to get audit trail for {document_id}: {e}")
            return []
    
    def update_daily_metrics(self, date: str, metric_type: str, metrics: Dict) -> bool:
        """Update daily metrics table."""
        try:
            timestamp = get_timestamp()
            
            # Convert float values to Decimal for DynamoDB
            decimal_metrics = {}
            for key, value in metrics.items():
                if isinstance(value, float):
                    decimal_metrics[key] = Decimal(str(value))
                else:
                    decimal_metrics[key] = value
            
            decimal_metrics['last_updated'] = timestamp
            
            self.metrics_table.update_item(
                Key={
                    'date': date,
                    'metric_type': metric_type
                },
                UpdateExpression="SET " + ", ".join([f"{k} = :{k}" for k in decimal_metrics.keys()]),
                ExpressionAttributeValues={f":{k}": v for k, v in decimal_metrics.items()}
            )
            
            logger.info(f"Updated daily metrics for {date}/{metric_type}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update daily metrics: {e}")
            return False
