#!/bin/bash

# Test compact_to_iceberg.py locally
# Usage: ./test_compact.sh <start_date> <end_date> [mode]

# Export Environment Variables pointing to Localhost ports
# MinIO: localhost:9000
# Postgres: localhost:5433 (External port for iceberg-catalog-db)
# Creds: Standard dev creds

export AWS_ACCESS_KEY_ID=minioadmin
export AWS_SECRET_ACCESS_KEY=minioadmin123
export AWS_REGION=us-east-1
export AWS_ENDPOINT_URL=http://localhost:9000

export SOURCE_BUCKET="s3://bronze-bucket"
export SOURCE_PREFIX="frankfurter"
export TARGET_BUCKET="s3://silver-bucket/iceberg"
export TABLE_NAME="frankfurter_rates"
export ICEBERG_CATALOG="default"
export ICEBERG_NAMESPACE="default"

# Catalog Config (Postgres on Host Port 5433)
export PYICEBERG_CATALOG__DEFAULT__TYPE="sql"
# Note: Use 'localhost' host, port 5433 (mapped in docker-compose)
export PYICEBERG_CATALOG__DEFAULT__URI="postgresql+psycopg2://iceberg:iceberg@localhost:5433/iceberg_catalog"
export PYICEBERG_CATALOG__DEFAULT__S3__ENDPOINT="http://localhost:9000"
export PYICEBERG_CATALOG__DEFAULT__WAREHOUSE="s3://silver-bucket/iceberg"

# Clean Command
if [ "$1" == "clean" ]; then
    echo "🧹 Dropping table default.frankfurter_rates..."
    uv run python -c "from pyiceberg.catalog import load_catalog; print('Dropping...'); load_catalog('default').drop_table('default.${TABLE_NAME}')"
    echo "✅ Table dropped."
    exit 0
fi

# Run Script
if [[ "$1" == --* ]]; then
    echo "⚡ Passing arguments directly to python script..."
    uv run python src/compact_to_iceberg.py "$@"
else
    # Positional Arguments Backwards Compatibility
    START_DATE=${1:-"2026-01-08"}
    END_DATE=${2:-"2026-01-20"}
    MODE=${3:-"backfill"}

    echo "🚀 Running compact_to_iceberg locally (Positional Args)..."
    echo "📅 Range: $START_DATE to $END_DATE ($MODE)"

    uv run python src/compact_to_iceberg.py \
        --start-date "$START_DATE" \
        --end-date "$END_DATE" \
        --mode "$MODE"
fi
