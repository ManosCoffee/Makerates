import boto3
from botocore.exceptions import ClientError
from typing import Optional, Dict, Any, Tuple, List
from utils.logging_config import root_logger as logger
from utils.helpers import parse_env_vars_config, load_config
import os,sys

# ENV VARS CONFIG FILE
CONFIG_FILE = "settings.yaml"

class DynamoDBClient:
    """Simple wrapper around boto3 DynamoDB Table operations."""

    def __init__(self, table_name: str, endpoint_url: Optional[str] = None, region_name: Optional[str] = "us-east-1"):

        self._load_environment_config()
        dynamodb_kwargs = {}
        try:
            dynamodb_kwargs["endpoint_url"] = endpoint_url if endpoint_url else self.config.get("DYNAMODB_ENDPOINT",None)
            dynamodb_kwargs["region_name"] = region_name if region_name else self.config.get("DYNAMODB_AWS_DEFAULT_REGION",None)                
            dynamodb_kwargs["aws_access_key_id"] = self.config.get("DYNAMODB_AWS_ACCESS_KEY_ID",None)
            dynamodb_kwargs["aws_secret_access_key"] = self.config.get("DYNAMODB_AWS_SECRET_ACCESS_KEY",None)
            self.table = boto3.resource("dynamodb", **dynamodb_kwargs).Table(table_name)
            logger.info(f"DynamoDB table initialized: {table_name}")
        except Exception as e:
            logger.error(f"Failed to initialize DynamoDB table: {e}")
            sys.exit(1)

    
    def _load_environment_config(self)->None:
        try:
            settings = load_config(CONFIG_FILE)
            job_config = settings.get("dynamodb_client", {})
            self.config = parse_env_vars_config(job_config)
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            sys.exit(1)


    def get_item(self, key: Dict[str, Any]) -> Optional[Dict]:
        try:
            resp = self.table.get_item(Key=key)
            return resp.get("Item")
        except ClientError as e:
            logger.error(f"Error fetching item {key}: {e}")
            return None

    def put_item(self, item: Dict[str, Any]) -> bool:
        try:
            self.table.put_item(Item=item)
            logger.debug(f"Inserted item: {item}")
            return True
        except ClientError as e:
            logger.error(f"Error inserting item {item}: {e}")
            return False

    def update_item(
        self, 
        key: dict, 
        update_expression: str, 
        expression_values: dict, 
        expression_names: Optional[dict] = None
    ) -> Optional[dict]:
        try:
            kwargs = {
                "Key": key,
                "UpdateExpression": update_expression,
                "ExpressionAttributeValues": expression_values,
                "ReturnValues": "ALL_NEW"
            }
            if expression_names:
                kwargs["ExpressionAttributeNames"] = expression_names

            resp = self.table.update_item(**kwargs)
            logger.debug(f"Updated item {key}: {resp.get('Attributes')}")
            return resp.get("Attributes")

        except ClientError as e:
            logger.error(f"Error updating item {key}: {e}")
            return None

    def query(
        self, 
        key_condition_expression: str, 
        expression_values: Dict[str, Any], 
        limit: Optional[int] = None, 
        scan_index_forward: bool = True,
        **kwargs
    ) -> Optional[List[Dict[str, Any]]]:
        """Generic query wrapper with argument mapping."""
        try:
            query_kwargs = {
                "KeyConditionExpression": key_condition_expression,
                "ExpressionAttributeValues": expression_values,
                "ScanIndexForward": scan_index_forward
            }
            if limit:
                query_kwargs["Limit"] = limit
            
            # Allow passing other kwargs directly if they match Boto3 names
            query_kwargs.update(kwargs)

            response = self.table.query(**query_kwargs)
            return response.get("Items", [])
        except ClientError as e:
            logger.error(f"Error querying table: {e}")
            return None

