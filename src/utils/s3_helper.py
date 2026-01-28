import os
import logging
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

def get_s3_client():
    """Create a Boto3 S3 client using environment variables."""
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("AWS_ENDPOINT_URL"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        region_name=os.environ.get("AWS_REGION", "us-east-1")
    )

def check_s3_prefix_exists(client, bucket, prefix):
    """
    Check if any objects exist under the given prefix (efficiently).
    Result is based on 'ListObjectsV2' with MaxKeys=1.
    """
    try:
        # 1. Normalize Bucket Name (Strip s3://)
        bucket_name = bucket.replace("s3://", "")
        
        # 2. Normalize Prefix
        # The prefix might be full S3 URI: s3://bucket/key/path...
        # Or just /key/path...
        # We need just 'key/path...'
        
        prefix_clean = prefix
        if prefix_clean.startswith("s3://"):
             # Remove s3://
             prefix_clean = prefix_clean[5:]
             
        # Start with bucket name? verification
        if prefix_clean.startswith(bucket_name):
             prefix_clean = prefix_clean[len(bucket_name):]
             
        # Remove leading slashes
        prefix_clean = prefix_clean.lstrip("/")
        
        response = client.list_objects_v2(Bucket=bucket_name, Prefix=prefix_clean, MaxKeys=1)
        return 'Contents' in response
    except ClientError as e:
        logger.warning(f"S3 ClientError checking prefix {prefix} in {bucket}: {e}")
        return False
    except Exception as e:
        logger.warning(f"Unexpected error checking prefix {prefix} in {bucket}: {e}")
        return False
