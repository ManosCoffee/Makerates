#!/usr/bin/env python3
"""
API Quota Tracker - DynamoDB Table Initialization

Creates a table to track API usage and prevent quota errors with automatic failover.

Table Design:
- Partition Key: api_source (e.g., "frankfurter", "exchangerate")
- Sort Key: tracking_date (YYYY-MM-DD)
- Attributes:
  - request_count: Current requests today
  - quota_limit: Daily quota limit
  - status: active | throttled | failed_over
  - last_request_at: ISO timestamp
  - failover_to: Next API to try if quota exceeded
- TTL: 30 days for historical analysis

Usage:
    python scripts/init_quota_tracker.py --endpoint http://localhost:8000
"""

import argparse
import sys
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError


def create_quota_tracker_table(
    dynamodb_client, table_name: str = "api_quota_tracker"
) -> bool:
    """Create the API quota tracking table."""
    try:
        # Check if table exists
        try:
            dynamodb_client.describe_table(TableName=table_name)
            print(f"✅ Table '{table_name}' already exists")
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                raise

        print(f"📦 Creating quota tracker table '{table_name}'...")

        response = dynamodb_client.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "api_source", "KeyType": "HASH"},
                {"AttributeName": "tracking_date", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "api_source", "AttributeType": "S"},
                {"AttributeName": "tracking_date", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
            Tags=[
                {"Key": "Project", "Value": "MakeRates"},
                {"Key": "Purpose", "Value": "QuotaTracking"},
            ],
        )

        # Wait for table creation
        waiter = dynamodb_client.get_waiter("table_exists")
        waiter.wait(TableName=table_name)

        print(f"✅ Table '{table_name}' created successfully")

        # Enable TTL (30 days retention)
        print(f"⏰ Enabling TTL on 'ttl' attribute...")
        dynamodb_client.update_time_to_live(
            TableName=table_name,
            TimeToLiveSpecification={
                "Enabled": True,
                "AttributeName": "ttl",
            },
        )

        print(f"✅ TTL enabled (30-day retention)")
        return True

    except Exception as e:
        print(f"❌ Error creating table: {e}")
        return False


def initialize_api_quotas(dynamodb, table_name: str = "api_quota_tracker") -> None:
    """Initialize quota settings for each API source."""
    table = dynamodb.Table(table_name)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # API quota configuration
    api_configs = [
        {
            "api_source": "frankfurter",
            "tracking_date": today,
            "request_count": 0,
            "quota_limit": 10000,  # No official limit, but be conservative
            "quota_period": "daily",
            "status": "active",
            "failover_to": "exchangerate",
            "priority": 1,  # Primary source
            "last_request_at": None,
            "notes": "ECB data via Frankfurter - no API key required",
        },
        {
            "api_source": "exchangerate",
            "tracking_date": today,
            "request_count": 0,
            "quota_limit": 1500,  # Free tier: 1500/month = ~50/day (conservative)
            "quota_period": "daily",
            "status": "active",
            "failover_to": None,  # No failover (last resort)
            "priority": 2,  # Secondary source
            "last_request_at": None,
            "notes": "ExchangeRate-API free tier - 1500 requests/month",
        },
    ]

    print(f"\n📊 Initializing API quota settings for {today}...")

    for config in api_configs:
        try:
            # Calculate TTL (30 days from now)
            ttl = int((datetime.now(timezone.utc).timestamp())) + (30 * 24 * 60 * 60)
            config["ttl"] = ttl
            config["created_at"] = datetime.now(timezone.utc).isoformat()

            table.put_item(Item=config)
            print(f"  ✅ {config['api_source']}: {config['quota_limit']} req/day")

        except Exception as e:
            print(f"  ❌ Error initializing {config['api_source']}: {e}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Initialize API Quota Tracker table"
    )
    parser.add_argument(
        "--endpoint",
        default=None,
        help="DynamoDB endpoint (e.g., http://localhost:8000)",
    )
    parser.add_argument(
        "--table-name",
        default="api_quota_tracker",
        help="Table name (default: api_quota_tracker)",
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region (default: us-east-1)",
    )
    parser.add_argument(
        "--init-quotas",
        action="store_true",
        help="Initialize today's quota settings",
    )

    args = parser.parse_args()

    print("🚀 API Quota Tracker Initialization")
    print(f"Endpoint: {args.endpoint or 'AWS DynamoDB'}")
    print(f"Table: {args.table_name}\n")

    # Initialize clients
    dynamodb_kwargs = {"region_name": args.region}
    if args.endpoint:
        dynamodb_kwargs["endpoint_url"] = args.endpoint

    dynamodb_client = boto3.client("dynamodb", **dynamodb_kwargs)
    dynamodb = boto3.resource("dynamodb", **dynamodb_kwargs)

    # Create table
    success = create_quota_tracker_table(dynamodb_client, args.table_name)

    if success and args.init_quotas:
        initialize_api_quotas(dynamodb, args.table_name)

    if success:
        print("\n✅ Quota tracker initialization completed")
        sys.exit(0)
    else:
        print("\n❌ Quota tracker initialization failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
