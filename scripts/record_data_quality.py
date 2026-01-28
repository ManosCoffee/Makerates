"""
Record Data Quality Metrics to DynamoDB Observability Table

Queries DuckDB Silver layer for actual data quality metrics:
- Rows extracted per source (Frankfurter, ExchangeRate-API)
- Rows validated (passed consensus check)
- Rows flagged (anomalies detected)
- Currency coverage

This is OBSERVABILITY for DATA PARSING, not pipeline lifecycle
(Kestra already tracks pipeline start/stop/failure).
"""

import os
import sys
import argparse
import duckdb
import json
from datetime import datetime
from decimal import Decimal
import boto3
from pathlib import Path


def get_data_quality_metrics(duckdb_path: str, execution_date: str) -> dict:
    """
    Query DuckDB Silver layer for data quality metrics.

    Args:
        duckdb_path: Path to silver.duckdb file
        execution_date: Date being processed (YYYY-MM-DD)

    Returns:
        Dict with data quality metrics
    """

    # Check if DuckDB file exists
    if not Path(duckdb_path).exists():
        print(f"⚠️  DuckDB file not found: {duckdb_path}")
        return {
            "error": "duckdb_file_not_found",
            "message": f"Silver layer not yet created: {duckdb_path}"
        }

    try:
        conn = duckdb.connect(duckdb_path, read_only=True)

        # Get Frankfurter extraction count
        frankfurter_count = conn.execute(
            "SELECT COUNT(*) FROM main_silver.stg_frankfurter WHERE rate_date = ?",
            [execution_date]
        ).fetchone()[0]

        # Get ExchangeRate-API extraction count
        exchangerate_count = conn.execute(
            "SELECT COUNT(*) FROM main_silver.stg_exchangerate WHERE rate_date = ?",
            [execution_date]
        ).fetchone()[0]

        # Get validated rates count (passed all checks)
        validated_count = conn.execute(
            "SELECT COUNT(*) FROM main_silver.fact_rates_validated WHERE rate_date = ?",
            [execution_date]
        ).fetchone()[0]

        # Get flagged anomalies count
        flagged_count = conn.execute(
            "SELECT COUNT(*) FROM main_silver.consensus_check WHERE rate_date = ?",
            [execution_date]
        ).fetchone()[0]

        # Get currency coverage (distinct currencies validated)
        currency_count = conn.execute(
            "SELECT COUNT(DISTINCT target_currency) FROM main_silver.fact_rates_validated WHERE rate_date = ?",
            [execution_date]
        ).fetchone()[0]

        # Get severity breakdown for flagged rates
        severity_breakdown = {}
        if flagged_count > 0:
            severity_rows = conn.execute(
                "SELECT severity, COUNT(*) as count FROM main_silver.consensus_check WHERE rate_date = ? GROUP BY severity",
                [execution_date]
            ).fetchall()
            severity_breakdown = {row[0]: row[1] for row in severity_rows}

        conn.close()

        return {
            "extraction": {
                "frankfurter_rows": frankfurter_count,
                "exchangerate_rows": exchangerate_count,
                "total_rows": frankfurter_count + exchangerate_count
            },
            "validation": {
                "validated_rows": validated_count,
                "flagged_rows": flagged_count,
                "validation_rate": f"{(validated_count / (validated_count + flagged_count) * 100):.1f}%" if (validated_count + flagged_count) > 0 else "0.0%"
            },
            "coverage": {
                "currency_count": currency_count,
                "expected_minimum": 100  # ECB typically has 150+ currencies
            },
            "anomalies": {
                "total_flagged": flagged_count,
                "severity_breakdown": severity_breakdown
            }
        }

    except Exception as e:
        print(f"❌ Error querying DuckDB: {e}")
        return {
            "error": "duckdb_query_failed",
            "message": str(e)
        }


def record_to_dynamodb(endpoint_url: str, pipeline_name: str, execution_date: str, metrics: dict):
    """Record data quality metrics to DynamoDB observability table."""

    dynamodb = boto3.resource('dynamodb', endpoint_url=endpoint_url, region_name='us-east-1')
    table = dynamodb.Table('pipeline_observability')

    execution_timestamp = datetime.utcnow().isoformat()

    # Convert all numeric values to Decimal for DynamoDB
    def convert_to_decimal(obj):
        if isinstance(obj, dict):
            return {k: convert_to_decimal(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_to_decimal(v) for v in obj]
        elif isinstance(obj, (int, float)):
            return Decimal(str(obj))
        else:
            return obj

    item = {
        'pipeline_name': pipeline_name,
        'execution_timestamp': execution_timestamp,
        'execution_date': execution_date,
        'status': 'DATA_QUALITY_RECORDED',  # Distinct from pipeline lifecycle
        'timestamp_utc': execution_timestamp,
        'metrics': convert_to_decimal(metrics)
    }

    try:
        table.put_item(Item=item)
        print(f"✅ Recorded data quality metrics for {execution_date}")
        print(json.dumps(metrics, indent=2, default=str))

    except Exception as e:
        print(f"❌ Failed to record to DynamoDB: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='Record data quality metrics to observability table')
    parser.add_argument('--date', required=True, help='Execution date (YYYY-MM-DD)')
    parser.add_argument('--duckdb-path', default='dbt_project/silver.duckdb', help='Path to silver DuckDB')

    args = parser.parse_args()

    # Get DynamoDB endpoint from env
    endpoint = os.getenv("DYNAMODB_ENDPOINT", "http://localhost:8000")

    # Query data quality metrics from DuckDB
    print(f"📊 Querying data quality metrics for {args.date}...")
    metrics = get_data_quality_metrics(args.duckdb_path, args.date)

    # Check for errors
    if "error" in metrics:
        print(f"⚠️  {metrics['message']}")
        # Still record the error to observability table for tracking
        record_to_dynamodb(endpoint, 'rates_daily', args.date, metrics)
        sys.exit(0)  # Don't fail pipeline on observability issues

    # Record to DynamoDB
    record_to_dynamodb(endpoint, 'rates_daily', args.date, metrics)

    # Print summary
    print(f"\n📈 Data Quality Summary:")
    print(f"  Extraction: {metrics['extraction']['total_rows']} rows")
    print(f"  Validated: {metrics['validation']['validated_rows']} rows ({metrics['validation']['validation_rate']})")
    print(f"  Flagged: {metrics['validation']['flagged_rows']} anomalies")
    print(f"  Coverage: {metrics['coverage']['currency_count']} currencies")

    if metrics['anomalies']['total_flagged'] > 0:
        print(f"\n⚠️  Anomalies detected:")
        for severity, count in metrics['anomalies']['severity_breakdown'].items():
            print(f"    {severity}: {count}")


if __name__ == "__main__":
    main()
