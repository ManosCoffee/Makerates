"""
Initialize DynamoDB Pipeline Observability Table

Tracks pipeline execution status, health metrics, and rate freshness
for dashboard observability (future scope).

Table Design:
- PK: pipeline_name (e.g., "rates_daily")
- SK: execution_timestamp (ISO format with milliseconds for uniqueness)
- Attributes: status, duration, error_message, data_quality_metrics, etc.
"""

import boto3
import argparse
from datetime import datetime
from decimal import Decimal


def create_observability_table(endpoint_url: str):
    """
    Create pipeline_observability table with composite key.

    Access Patterns:
    1. Get latest execution for a pipeline: Query by PK, limit 1, descending
    2. Get execution history: Query by PK with date range on SK
    3. Get all failed executions: GSI on status
    """

    dynamodb = boto3.client('dynamodb', endpoint_url=endpoint_url, region_name='us-east-1')

    table_name = 'pipeline_observability'

    try:
        # Check if table exists
        existing_tables = dynamodb.list_tables()['TableNames']
        if table_name in existing_tables:
            print(f"✅ Table '{table_name}' already exists")
            return

        # Create table
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {'AttributeName': 'pipeline_name', 'KeyType': 'HASH'},  # Partition key
                {'AttributeName': 'execution_timestamp', 'KeyType': 'RANGE'}  # Sort key
            ],
            AttributeDefinitions=[
                {'AttributeName': 'pipeline_name', 'AttributeType': 'S'},
                {'AttributeName': 'execution_timestamp', 'AttributeType': 'S'},
                {'AttributeName': 'status', 'AttributeType': 'S'},
                {'AttributeName': 'execution_date', 'AttributeType': 'S'}  # For querying by date
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'status-index',
                    'KeySchema': [
                        {'AttributeName': 'status', 'KeyType': 'HASH'},
                        {'AttributeName': 'execution_timestamp', 'KeyType': 'RANGE'}
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {'ReadCapacityUnits': 5, 'WriteCapacityUnits': 5}
                },
                {
                    'IndexName': 'execution-date-index',
                    'KeySchema': [
                        {'AttributeName': 'pipeline_name', 'KeyType': 'HASH'},
                        {'AttributeName': 'execution_date', 'KeyType': 'RANGE'}
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {'ReadCapacityUnits': 5, 'WriteCapacityUnits': 5}
                }
            ],
            ProvisionedThroughput={'ReadCapacityUnits': 5, 'WriteCapacityUnits': 5}
        )

        print(f"✅ Created table '{table_name}'")
        print("   - PK: pipeline_name")
        print("   - SK: execution_timestamp")
        print("   - GSI: status-index (for filtering by status)")
        print("   - GSI: execution-date-index (for date range queries)")

    except Exception as e:
        print(f"❌ Error creating table: {e}")
        raise


def record_pipeline_execution(
    endpoint_url: str,
    pipeline_name: str,
    status: str,
    execution_date: str,
    duration_seconds: float = None,
    error_message: str = None,
    metrics: dict = None
):
    """
    Record a pipeline execution event.

    Args:
        endpoint_url: DynamoDB endpoint
        pipeline_name: Name of the pipeline (e.g., "rates_daily")
        status: One of: STARTED, RUNNING, COMPLETED, FAILED, PARTIAL_SUCCESS
        execution_date: Date being processed (YYYY-MM-DD)
        duration_seconds: Execution duration
        error_message: Error details if failed
        metrics: Dict of pipeline metrics (rows_extracted, rows_validated, etc.)
    """

    dynamodb = boto3.resource('dynamodb', endpoint_url=endpoint_url, region_name='us-east-1')
    table = dynamodb.Table('pipeline_observability')

    execution_timestamp = datetime.utcnow().isoformat()

    item = {
        'pipeline_name': pipeline_name,
        'execution_timestamp': execution_timestamp,
        'execution_date': execution_date,
        'status': status,
        'timestamp_utc': execution_timestamp
    }

    if duration_seconds is not None:
        item['duration_seconds'] = Decimal(str(duration_seconds))

    if error_message:
        item['error_message'] = error_message

    if metrics:
        # Convert all numeric values to Decimal for DynamoDB
        item['metrics'] = {
            k: Decimal(str(v)) if isinstance(v, (int, float)) else v
            for k, v in metrics.items()
        }

    table.put_item(Item=item)
    print(f"✅ Recorded {status} event for {pipeline_name} at {execution_timestamp}")


def get_latest_execution(endpoint_url: str, pipeline_name: str):
    """Get the most recent execution status for a pipeline."""

    dynamodb = boto3.resource('dynamodb', endpoint_url=endpoint_url, region_name='us-east-1')
    table = dynamodb.Table('pipeline_observability')

    response = table.query(
        KeyConditionExpression='pipeline_name = :pipeline',
        ExpressionAttributeValues={':pipeline': pipeline_name},
        ScanIndexForward=False,  # Descending order (newest first)
        Limit=1
    )

    if response['Items']:
        return response['Items'][0]
    return None


def get_pipeline_health(endpoint_url: str, pipeline_name: str, days: int = 7):
    """
    Get pipeline health summary for the last N days.

    Returns:
        Dict with success_rate, avg_duration, recent_failures, etc.
    """

    dynamodb = boto3.resource('dynamodb', endpoint_url=endpoint_url, region_name='us-east-1')
    table = dynamodb.Table('pipeline_observability')

    # Query recent executions
    from datetime import timedelta
    cutoff_date = (datetime.utcnow() - timedelta(days=days)).date().isoformat()

    response = table.query(
        IndexName='execution-date-index',
        KeyConditionExpression='pipeline_name = :pipeline AND execution_date >= :cutoff',
        ExpressionAttributeValues={
            ':pipeline': pipeline_name,
            ':cutoff': cutoff_date
        }
    )

    executions = response['Items']
    total = len(executions)

    if total == 0:
        return {'status': 'NO_DATA', 'total_executions': 0}

    completed = sum(1 for e in executions if e['status'] == 'COMPLETED')
    failed = sum(1 for e in executions if e['status'] == 'FAILED')

    durations = [float(e.get('duration_seconds', 0)) for e in executions if 'duration_seconds' in e]
    avg_duration = sum(durations) / len(durations) if durations else 0

    return {
        'total_executions': total,
        'completed': completed,
        'failed': failed,
        'success_rate': f"{(completed/total)*100:.1f}%",
        'avg_duration_seconds': round(avg_duration, 2),
        'recent_failures': [e for e in executions if e['status'] == 'FAILED'][:5]
    }


def main():
    parser = argparse.ArgumentParser(description='Initialize DynamoDB observability table')
    parser.add_argument('--endpoint', default='http://localhost:8000', help='DynamoDB endpoint URL')
    parser.add_argument('--verify-only', action='store_true', help='Only verify table exists')
    parser.add_argument('--test-write', action='store_true', help='Write a test execution record')

    args = parser.parse_args()

    if args.verify_only:
        dynamodb = boto3.client('dynamodb', endpoint_url=args.endpoint, region_name='us-east-1')
        tables = dynamodb.list_tables()['TableNames']
        if 'pipeline_observability' in tables:
            print("✅ pipeline_observability table exists")
        else:
            print("❌ pipeline_observability table does NOT exist")
        return

    if args.test_write:
        record_pipeline_execution(
            endpoint_url=args.endpoint,
            pipeline_name='rates_daily',
            status='COMPLETED',
            execution_date=datetime.utcnow().date().isoformat(),
            duration_seconds=45.2,
            metrics={
                'frankfurter_rows': 150,
                'exchangerate_rows': 150,
                'validated_rows': 150,
                'flagged_rows': 0
            }
        )

        # Show latest
        latest = get_latest_execution(args.endpoint, 'rates_daily')
        print(f"\nLatest execution: {latest}")

        # Show health
        health = get_pipeline_health(args.endpoint, 'rates_daily', days=7)
        print(f"\nPipeline health (7d): {health}")

        return

    # Default: create table
    create_observability_table(args.endpoint)


if __name__ == "__main__":
    main()
