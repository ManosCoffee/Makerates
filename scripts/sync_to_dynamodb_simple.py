#!/usr/bin/env python3
"""
Sync Validated Rates from Iceberg (S3) to DynamoDB

Reads validated rates from the Silver layer (Iceberg format) and writes to DynamoDB.
Source: s3://silver-bucket/iceberg/fact_rates_validated
Target: DynamoDB (currency_rates)
"""

import argparse
import sys
import os
import boto3
import duckdb
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from botocore.exceptions import ClientError

def sync_rates_to_dynamodb(
    s3_path: str,
    dynamodb_endpoint: str = None,
    table_name: str = "currency_rates",
    mode: str = "full",
    days: int = 7,
) -> dict:
    
    print(f"Starting DynamoDB Sync (Mode: {mode})")
    
    # 1. Setup DuckDB with Iceberg/S3 support
    conn = duckdb.connect()
    
    # AWS Credentials for S3 Read
    aws_key = os.getenv("AWS_ACCESS_KEY_ID", "minio")
    aws_secret = os.getenv("AWS_SECRET_ACCESS_KEY", "minio123")
    aws_endpoint = os.getenv("AWS_ENDPOINT_URL", "http://minio:9000")
    
    try:
        conn.execute("INSTALL iceberg; LOAD iceberg;")
        conn.execute("INSTALL httpfs; LOAD httpfs;")
        
        # Configure S3/MinIO
        conn.execute(f"""
            SET s3_region='us-east-1';
            SET s3_access_key_id='{aws_key}';
            SET s3_secret_access_key='{aws_secret}';
            SET s3_endpoint='{aws_endpoint.replace('http://', '').replace('https://', '')}';
            SET s3_use_ssl=false;
            SET s3_url_style='path';
        """)
    except Exception as e:
        print(f"Failed to initialize DuckDB extensions: {e}")
        return {"success": 0, "failed": 1}

    # 2. Build Query
    # Reading from Iceberg table on S3
    table_source = f"iceberg_scan('{s3_path}')"
    
    where_clause = ""
    if mode == "incremental":
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).date()
        where_clause = f"WHERE rate_date >= '{cutoff_date}'"
    
    query = f"""
    SELECT
        currency_pair,
        rate_date::VARCHAR as rate_date,
        base_currency,
        target_currency,
        exchange_rate,
        inverse_rate,
        extraction_timestamp::VARCHAR as extraction_timestamp,
        source,
        validation_status,
        severity,
        consensus_variance,
        dbt_loaded_at::VARCHAR as dbt_loaded_at
    FROM {table_source}
    {where_clause}
    ORDER BY rate_date DESC, currency_pair
    """

    print("Querying Iceberg table on S3...")
    try:
        result = conn.execute(query).fetchall()
        columns = [desc[0] for desc in conn.description]
        print(f"Extracted {len(result)} rates from Silver layer")
    except Exception as e:
        print(f"Error querying Iceberg table: {e}")
        if "IO Error" in str(e) or "File not found" in str(e):
             print("Tip: Ensure DBT has successfully created the Iceberg table in S3.")
        return {"success": 0, "failed": 1}
    finally:
        conn.close()

    if not result:
        print("No rates found to sync.")
        return {"success": 0, "failed": 0}

    # 3. Write to DynamoDB
    dynamodb_kwargs = {"region_name": "us-east-1"}
    if dynamodb_endpoint:
        dynamodb_kwargs["endpoint_url"] = dynamodb_endpoint
    
    dynamodb = boto3.resource("dynamodb", **dynamodb_kwargs)
    table = dynamodb.Table(table_name)
    
    # Calculate TTL (7 days from now)
    ttl_timestamp = int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp())
    
    success_count = 0
    failed_count = 0
    
    print(f"Writing {len(result)} items to DynamoDB table '{table_name}'...")
    
    with table.batch_writer() as batch:
        for row in result:
            try:
                item = dict(zip(columns, row))
                
                # Convert floats to Decimal
                item["exchange_rate"] = Decimal(str(item["exchange_rate"]))
                if item.get("inverse_rate"):
                     item["inverse_rate"] = Decimal(str(item["inverse_rate"]))
                else: 
                     item["inverse_rate"] = Decimal("0")
                
                if item.get("consensus_variance"):
                    item["consensus_variance"] = Decimal(str(item["consensus_variance"]))
                else:
                    item["consensus_variance"] = Decimal("0")

                # Metadata
                item["synced_at"] = datetime.now(timezone.utc).isoformat()
                item["expiration_timestamp"] = ttl_timestamp
                
                batch.put_item(Item=item)
                success_count += 1
                
                if success_count % 500 == 0:
                    print(f"Synced {success_count} items...")
                    
            except Exception as e:
                # Log first failure only to avoid spam
                if failed_count == 0:
                    print(f"Error converting/writing item: {e}")
                failed_count += 1

    print(f"Sync Complete. Success: {success_count}, Failed: {failed_count}")
    return {"success": success_count, "failed": failed_count}

def main():
    parser = argparse.ArgumentParser(description="Sync Iceberg to DynamoDB")
    parser.add_argument("--s3-path", default="s3://silver-bucket/iceberg/fact_rates_validated", help="S3 Path to Iceberg table")
    parser.add_argument("--endpoint", default=None, help="DynamoDB Endpoint")
    parser.add_argument("--table-name", default="currency_rates", help="DynamoDB Table Name")
    parser.add_argument("--mode", choices=["full", "incremental"], default="full", help="Sync Mode")
    parser.add_argument("--days", type=int, default=7, help="Lookback days for incremental sync")
    
    args = parser.parse_args()
    
    stats = sync_rates_to_dynamodb(
        s3_path=args.s3_path,
        dynamodb_endpoint=args.endpoint,
        table_name=args.table_name,
        mode=args.mode,
        days=args.days
    )
    
    if stats["failed"] > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
