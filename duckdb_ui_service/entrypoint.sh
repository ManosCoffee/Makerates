#!/bin/bash
set -e

# Configuration
S3_BUCKET="s3://analytics-bucket"
DB_FILE="analytics.duckdb"
LOCAL_PATH="/db/anal.duckdb"

echo "----------------------------------------------------------------"
echo "Starting DuckUI Container"
echo "Target File: ${LOCAL_PATH}"
echo "Source: ${S3_BUCKET}/${DB_FILE}"
echo "----------------------------------------------------------------"

# Check if AWS credentials are provided
if [ -z "$AWS_ACCESS_KEY_ID" ] || [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
    echo "ERROR: AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set."
    exit 1
fi

# Download the file
echo "Downloading database from MinIO..."
aws s3 cp "${S3_BUCKET}/${DB_FILE}" "${LOCAL_PATH}" \
    --endpoint-url "${MINIO_ENDPOINT}" \
    --region us-east-1

if [ $? -eq 0 ]; then
    echo "Download successful."
else
    echo "ERROR: Failed to download file via AWS CLI."
    exit 1
fi

# Start DuckUI
# DuckUI defaults to port 4213. We need to ensure it listens on 0.0.0.0
# 'duckui' CLI often accepts a filename argument.
echo "Launching DuckUI..."
# Note: Check if duckui supports host binding. If not, this might need a proxy or relying on default 0.0.0.0
# According to some npm packages, --host might be required.
exec duckui "${LOCAL_PATH}" --host 0.0.0.0 --port 4213
