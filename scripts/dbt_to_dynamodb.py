#!/usr/bin/env python3
"""
dbt to DynamoDB Sync Script
Syncs validated currency rates from dbt-duckdb to DynamoDB hot tier.

This script:
1. Reads fact_rates_validated from DuckDB (Silver layer)
2. Transforms data for DynamoDB schema
3. Batch writes to DynamoDB with TTL (7 days)
4. Supports full and incremental sync modes

Usage:
    python scripts/dbt_to_dynamodb.py --endpoint http://localhost:8000
    python scripts/dbt_to_dynamodb.py --mode incremental --days 1
    python scripts/dbt_to_dynamodb.py  # Full sync to AWS DynamoDB
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Any

import boto3
import duckdb
from botocore.exceptions import ClientError


class DbtDynamoDBSync:
    """Sync validated currency rates from dbt-DuckDB to DynamoDB."""

    def __init__(
        self,
        duckdb_path: str,
        dynamodb_endpoint: str = None,
        region: str = "us-east-1",
        table_name: str = "currency_rates",
    ):
        """
        Initialize the sync client.

        Args:
            duckdb_path: Path to DuckDB database file
            dynamodb_endpoint: DynamoDB endpoint (None for AWS)
            region: AWS region
            table_name: DynamoDB table name
        """
        self.duckdb_path = duckdb_path
        self.table_name = table_name

        # Initialize DuckDB connection
        if not Path(duckdb_path).exists():
            raise FileNotFoundError(
                f"DuckDB database not found: {duckdb_path}\n"
                f"Run 'dbt run' first to create the Silver layer models."
            )

        self.duckdb_conn = duckdb.connect(duckdb_path, read_only=True)

        # Initialize DynamoDB client
        dynamodb_kwargs = {"region_name": region}
        if dynamodb_endpoint:
            dynamodb_kwargs["endpoint_url"] = dynamodb_endpoint

        self.dynamodb = boto3.resource("dynamodb", **dynamodb_kwargs)
        self.dynamodb_client = boto3.client("dynamodb", **dynamodb_kwargs)
        self.table = self.dynamodb.Table(table_name)

    def extract_validated_rates(
        self, mode: str = "full", days: int = 7
    ) -> List[Dict[str, Any]]:
        """
        Extract validated rates from dbt fact_rates_validated table.

        Args:
            mode: Sync mode ('full' or 'incremental')
            days: Number of days to look back for incremental sync

        Returns:
            List of rate records as dictionaries
        """
        print(f"📊 Extracting rates from DuckDB ({mode} mode)...")

        # Build query based on sync mode
        if mode == "incremental":
            cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).date()
            query = f"""
                SELECT
                    currency_pair,
                    rate_date,
                    base_currency,
                    target_currency,
                    exchange_rate,
                    inverse_rate,
                    extraction_timestamp,
                    source,
                    validation_status,
                    severity,
                    consensus_variance,
                    dbt_loaded_at
                FROM main_silver.fact_rates_validated
                WHERE rate_date >= '{cutoff_date}'
                ORDER BY rate_date DESC, currency_pair
            """
        else:
            query = """
                SELECT
                    currency_pair,
                    rate_date,
                    base_currency,
                    target_currency,
                    exchange_rate,
                    inverse_rate,
                    extraction_timestamp,
                    source,
                    validation_status,
                    severity,
                    consensus_variance,
                    dbt_loaded_at
                FROM main_silver.fact_rates_validated
                ORDER BY rate_date DESC, currency_pair
            """

        try:
            result = self.duckdb_conn.execute(query).fetchdf()
            records = result.to_dict("records")
            print(f"✅ Extracted {len(records)} validated rates")
            return records

        except Exception as e:
            print(f"❌ Error extracting from DuckDB: {e}")
            raise

    def transform_for_dynamodb(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Transform dbt records to DynamoDB item format.

        Args:
            records: List of records from DuckDB

        Returns:
            List of DynamoDB items ready for batch write
        """
        print(f"🔄 Transforming {len(records)} records for DynamoDB...")

        # Calculate TTL (7 days from now)
        ttl_timestamp = int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp())

        dynamodb_items = []

        for record in records:
            # Convert floats to Decimal for DynamoDB
            item = {
                # Primary Key
                "currency_pair": record["currency_pair"],
                "rate_date": str(record["rate_date"]),
                # Rate data
                "base_currency": record["base_currency"],
                "target_currency": record["target_currency"],
                "exchange_rate": Decimal(str(record["exchange_rate"])),
                "inverse_rate": Decimal(str(record["inverse_rate"])),
                # Metadata
                "source": record["source"],
                "validation_status": record["validation_status"],
                "severity": record["severity"],
                "consensus_variance": Decimal(str(record["consensus_variance"])),
                # Timestamps
                "extraction_timestamp": record["extraction_timestamp"].isoformat(),
                "dbt_loaded_at": record["dbt_loaded_at"].isoformat(),
                "synced_at": datetime.now(timezone.utc).isoformat(),
                # TTL for automatic cleanup (7 days)
                "expiration_timestamp": ttl_timestamp,
            }

            dynamodb_items.append(item)

        print(f"✅ Transformed {len(dynamodb_items)} items")
        return dynamodb_items

    def batch_write_to_dynamodb(
        self, items: List[Dict[str, Any]], batch_size: int = 25
    ) -> Dict[str, int]:
        """
        Batch write items to DynamoDB with retry logic.

        Args:
            items: List of DynamoDB items
            batch_size: Number of items per batch (max 25 for DynamoDB)

        Returns:
            Dictionary with success/failure counts
        """
        print(f"📤 Writing {len(items)} items to DynamoDB (table: {self.table_name})...")

        total_items = len(items)
        success_count = 0
        failure_count = 0

        # Split into batches (DynamoDB limit: 25 items per batch)
        for i in range(0, total_items, batch_size):
            batch = items[i : i + batch_size]

            try:
                with self.table.batch_writer() as batch_writer:
                    for item in batch:
                        batch_writer.put_item(Item=item)
                        success_count += 1

                # Progress indicator
                if (i + batch_size) % 100 == 0 or (i + batch_size) >= total_items:
                    print(f"  ✓ Processed {min(i + batch_size, total_items)}/{total_items} items")

            except ClientError as e:
                print(f"❌ Batch write error: {e.response['Error']['Message']}")
                failure_count += len(batch)
                continue

            except Exception as e:
                print(f"❌ Unexpected error in batch {i}-{i+batch_size}: {e}")
                failure_count += len(batch)
                continue

        print(f"\n✅ Sync completed: {success_count} success, {failure_count} failed")

        return {"success": success_count, "failed": failure_count}

    def get_table_stats(self) -> Dict[str, Any]:
        """
        Get current DynamoDB table statistics.

        Returns:
            Dictionary with table stats
        """
        try:
            response = self.dynamodb_client.describe_table(TableName=self.table_name)
            table = response["Table"]

            return {
                "status": table["TableStatus"],
                "item_count": table.get("ItemCount", 0),
                "size_bytes": table.get("TableSizeBytes", 0),
            }
        except Exception as e:
            print(f"⚠️ Could not get table stats: {e}")
            return {}

    def sync(self, mode: str = "full", days: int = 7) -> bool:
        """
        Execute the full sync process.

        Args:
            mode: Sync mode ('full' or 'incremental')
            days: Days to look back for incremental sync

        Returns:
            True if sync was successful
        """
        try:
            # Print table stats before sync
            print("\n" + "=" * 60)
            print("📊 DynamoDB Table Stats (Before Sync)")
            print("=" * 60)
            stats = self.get_table_stats()
            for key, value in stats.items():
                print(f"{key}: {value}")
            print()

            # Extract from DuckDB
            records = self.extract_validated_rates(mode=mode, days=days)

            if not records:
                print("⚠️ No records to sync")
                return True

            # Transform for DynamoDB
            items = self.transform_for_dynamodb(records)

            # Write to DynamoDB
            result = self.batch_write_to_dynamodb(items)

            # Print table stats after sync
            print("\n" + "=" * 60)
            print("📊 DynamoDB Table Stats (After Sync)")
            print("=" * 60)
            stats = self.get_table_stats()
            for key, value in stats.items():
                print(f"{key}: {value}")
            print("=" * 60 + "\n")

            return result["failed"] == 0

        except Exception as e:
            print(f"❌ Sync failed: {e}")
            return False

        finally:
            # Close DuckDB connection
            self.duckdb_conn.close()


def main():
    """Main entry point for dbt to DynamoDB sync."""
    parser = argparse.ArgumentParser(
        description="Sync validated currency rates from dbt-DuckDB to DynamoDB"
    )
    parser.add_argument(
        "--duckdb-path",
        default="dbt_project/silver.duckdb",
        help="Path to DuckDB database (default: dbt_project/silver.duckdb)",
    )
    parser.add_argument(
        "--endpoint",
        default=None,
        help="DynamoDB endpoint (e.g., http://localhost:8000 for local)",
    )
    parser.add_argument(
        "--table-name",
        default="currency_rates",
        help="DynamoDB table name (default: currency_rates)",
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region (default: us-east-1)",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "incremental"],
        default="full",
        help="Sync mode: 'full' or 'incremental' (default: full)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Days to look back for incremental sync (default: 7)",
    )

    args = parser.parse_args()

    print("🚀 dbt to DynamoDB Sync")
    print(f"DuckDB: {args.duckdb_path}")
    print(f"DynamoDB Endpoint: {args.endpoint or 'AWS DynamoDB'}")
    print(f"Region: {args.region}")
    print(f"Table: {args.table_name}")
    print(f"Mode: {args.mode}")
    if args.mode == "incremental":
        print(f"Days lookback: {args.days}")
    print()

    try:
        # Initialize sync client
        sync_client = DbtDynamoDBSync(
            duckdb_path=args.duckdb_path,
            dynamodb_endpoint=args.endpoint,
            region=args.region,
            table_name=args.table_name,
        )

        # Execute sync
        success = sync_client.sync(mode=args.mode, days=args.days)

        if success:
            print("✅ Sync completed successfully")
            sys.exit(0)
        else:
            print("❌ Sync completed with errors")
            sys.exit(1)

    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
