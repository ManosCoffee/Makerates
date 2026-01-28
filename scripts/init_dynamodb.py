#!/usr/bin/env python3
"""
DynamoDB Table Initialization Script
Creates all required tables for MakeRates:
1. currency_rates (Hot Data, Validated Rates)
2. api_quota_tracker (API Usage & Limits)

Usage:
    python scripts/init_dynamodb.py --endpoint http://localhost:8000
"""

import argparse
import sys
import boto3
from botocore.exceptions import ClientError

def get_table_definitions():
    """Returns the schema definitions for all tables."""
    return {
        "currency_rates": {
            "KeySchema": [
                {"AttributeName": "currency_pair", "KeyType": "HASH"},  # Partition key
                {"AttributeName": "rate_date", "KeyType": "RANGE"},  # Sort key
            ],
            "AttributeDefinitions": [
                {"AttributeName": "currency_pair", "AttributeType": "S"},
                {"AttributeName": "rate_date", "AttributeType": "S"},
                {"AttributeName": "target_currency", "AttributeType": "S"},
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "target_currency-rate_date-index",
                    "KeySchema": [
                        {"AttributeName": "target_currency", "KeyType": "HASH"},
                        {"AttributeName": "rate_date", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            "TTL": {
                "Enabled": True,
                "AttributeName": "expiration_timestamp"
            },
            "Tags": [
                {"Key": "Project", "Value": "MakeRates"},
                {"Key": "Layer", "Value": "Hot"},
            ]
        },
        "api_quota_tracker": {
            "KeySchema": [
                {"AttributeName": "api_source", "KeyType": "HASH"},
                {"AttributeName": "tracking_date", "KeyType": "RANGE"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "api_source", "AttributeType": "S"},
                {"AttributeName": "tracking_date", "AttributeType": "S"},
            ],
            "TTL": {
                "Enabled": True,
                "AttributeName": "ttl"
            },
            "Tags": [
                {"Key": "Project", "Value": "MakeRates"},
                {"Key": "Purpose", "Value": "QuotaTracking"},
            ]
        }
    }

def create_table(dynamodb, client, table_name, schema):
    """Creates a single table with the given schema."""
    try:
        # Check if exists
        try:
            client.describe_table(TableName=table_name)
            print(f"✅ Table '{table_name}' already exists")
            
            # Ensure TTL even if exists
            if schema.get("TTL"):
                try:
                    client.update_time_to_live(
                        TableName=table_name,
                        TimeToLiveSpecification=schema["TTL"]
                    )
                    # print(f"   (Verified TTL on '{schema['TTL']['AttributeName']}')")
                except Exception:
                    pass
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                raise

        print(f"📦 Creating table '{table_name}'...")
        
        # Build create args
        create_args = {
            "TableName": table_name,
            "KeySchema": schema["KeySchema"],
            "AttributeDefinitions": schema["AttributeDefinitions"],
            "BillingMode": "PAY_PER_REQUEST",
            "Tags": schema.get("Tags", [])
        }
        if "GlobalSecondaryIndexes" in schema:
            create_args["GlobalSecondaryIndexes"] = schema["GlobalSecondaryIndexes"]

        dynamodb.create_table(**create_args)
        
        # Wait
        waiter = client.get_waiter("table_exists")
        waiter.wait(TableName=table_name)
        print(f"✅ Table '{table_name}' created successfully")

        # Enable TTL
        if schema.get("TTL"):
            print(f"   ⏳ Enabling TTL on '{schema['TTL']['AttributeName']}'...")
            client.update_time_to_live(
                TableName=table_name,
                TimeToLiveSpecification=schema["TTL"]
            )
            print("   ✅ TTL enabled")
            
        return True

    except Exception as e:
        print(f"❌ Error creating {table_name}: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Initialize DynamoDB Tables")
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    print("🚀 DynamoDB Initialization")
    print(f"Endpoint: {args.endpoint or 'AWS DynamoDB'}\n")

    conn_args = {"region_name": args.region}
    if args.endpoint:
        conn_args["endpoint_url"] = args.endpoint

    client = boto3.client("dynamodb", **conn_args)
    dynamodb = boto3.resource("dynamodb", **conn_args)
    
    definitions = get_table_definitions()
    
    success = True
    for name, schema in definitions.items():
        if not create_table(dynamodb, client, name, schema):
            success = False
            
    if success:
        print("\n✅ All tables initialized successfully")
        sys.exit(0)
    else:
        print("\n❌ One or more tables failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
