-- Debug script to test DuckDB iceberg_scan() function
-- Run this with: duckdb analytics.duckdb < debug_iceberg_scan.sql

-- Install extensions
INSTALL httpfs;
INSTALL iceberg;
LOAD httpfs;
LOAD iceberg;

-- Configure S3 (MinIO)
SET s3_endpoint='minio:9000';
SET s3_use_ssl=false;
SET s3_access_key_id='minioadmin';
SET s3_secret_access_key='minioadmin123';
SET s3_url_style='path';

-- Test 1: Check if we can list files in S3
SELECT * FROM glob('s3://silver-bucket/iceberg/frankfurter_rates/metadata/*.metadata.json') LIMIT 5;

-- Test 2: Try iceberg_scan with latest metadata file
SELECT * FROM iceberg_scan('s3://silver-bucket/iceberg/frankfurter_rates/metadata/00002-3067c0e2-1a9d-4c4a-8266-708043aa3d10.metadata.json') LIMIT 10;

-- Test 3: Check table schema
DESCRIBE SELECT * FROM iceberg_scan('s3://silver-bucket/iceberg/frankfurter_rates/metadata/00002-3067c0e2-1a9d-4c4a-8266-708043aa3d10.metadata.json');

-- Test 4: Count rows
SELECT COUNT(*) as row_count FROM iceberg_scan('s3://silver-bucket/iceberg/frankfurter_rates/metadata/00002-3067c0e2-1a9d-4c4a-8266-708043aa3d10.metadata.json');

-- Test 5: Show all sources
SELECT DISTINCT source FROM iceberg_scan('s3://silver-bucket/iceberg/frankfurter_rates/metadata/00002-3067c0e2-1a9d-4c4a-8266-708043aa3d10.metadata.json');
