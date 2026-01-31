# Justfile for Makerates Pipeine
set dotenv-load := true

# List all available commands
default:
    @just --list

init:
    just run 
    just init-analytics-bucket

# Run
run:
    @echo "🚀 Spinning Up Docker Services..."
    docker compose build ingestion-base --no-cache
    docker compose up -d 
    @echo "Initializing DynamoDB tables..."
    uv run python scripts/init_dynamodb.py --endpoint http://localhost:8000
    @echo "✅ Done! Makerates is running."

# Rebuild the worker image and restart Kestra (Full Reload)
# reload:
#     @echo "🔄 Rebuilding services..."
#     docker compose build --no-cache
#     @echo "🚀 Restarting all services..."
#     docker compose up -d
#     @echo " Initializing DynamoDB tables..."
#     uv run python scripts/init_dynamodb.py --endpoint http://localhost:8000
#     @echo "✅ Done! Services reloaded."

# Initialize DynamoDB Tables (Running local script)
init-db:
    uv run python scripts/init_dynamodb.py

# Restart only Kestra (Fast config reload)
restart-kestra:
    docker compose up -d --force-recreate kestra

# View Kestra logs
logs:
    docker logs -f makerates-kestra

# Open Kestra UI
ui-kestra:
    open http://localhost:8080

# Open MinIO Console
ui-minio:
    open http://localhost:9001

# DUCKDB
## Initialize DuckDB
# init-duckdb:
#     cd data/duckdb && duckdb analytics.duckdb 
## Open DuckDB Analytics (Gold) - Access database from Docker volume
db-analytics:
    @echo "📊 Accessing DuckDB from Docker volume..."
    docker run --rm -it -v makerates-dbt-data:/data --entrypoint duckdb makerates-ingestion-base:latest /data/analytics.duckdb

## Open DuckDB Validation (Check flagged rates)
db-validation:
    @echo "🔍 Checking flagged rates from Docker volume..."
    docker run --rm -it -v makerates-dbt-data:/data --entrypoint duckdb makerates-ingestion-base:latest /data/analytics.duckdb "SELECT * FROM main_validation.consensus_check WHERE status = 'FLAGGED'"

# Create analytics bucket in MinIO (if missing)
init-analytics-bucket:
    @echo "🪣 Creating analytics-bucket in MinIO..."
    docker run --rm --network makerates-network -e AWS_ACCESS_KEY_ID=$MINIO_ROOT_USER -e AWS_SECRET_ACCESS_KEY=$MINIO_ROOT_PASSWORD amazon/aws-cli --endpoint-url http://minio:9000 s3 mb s3://analytics-bucket || echo "Bucket might already exist."
    @echo "✅ Bucket created."

# Debug S3 Connectivity from DuckDB
debug-s3-connectivity:
    @echo "🔍 Testing S3 access from DuckDB..."
    docker exec -it duckdb-ui duckdb -c "INSTALL httpfs; LOAD httpfs; SET s3_endpoint='minio:9000'; SET s3_use_ssl=false; SET s3_url_style='path'; SET s3_access_key_id='$MINIO_ROOT_USER'; SET s3_secret_access_key='$MINIO_ROOT_PASSWORD'; SELECT * FROM glob('s3://silver-bucket/iceberg/frankfurter_rates/metadata/*.metadata.json');"

# Clean corrupted Iceberg catalog tables (fixes constraint violations)
clean-iceberg:
    @echo "🧹 Cleaning Iceberg catalog tables..."
    docker exec makerates-iceberg-db psql -U iceberg -d iceberg_catalog -c "DROP TABLE IF EXISTS iceberg_tables CASCADE; DROP TABLE IF EXISTS iceberg_namespace_properties CASCADE; DROP TABLE IF EXISTS iceberg_namespaces CASCADE;"
    @echo "✅ Iceberg catalog cleaned. Tables will reinitialize on next run."

clean-s3:
    @echo "🧹 Cleaning MinIO S3 buckets..."
    docker run --rm --network makerates-network -e AWS_ACCESS_KEY_ID=$MINIO_ROOT_USER -e AWS_SECRET_ACCESS_KEY=$MINIO_ROOT_PASSWORD amazon/aws-cli --endpoint-url http://minio:9000 s3 rm s3://silver-bucket/iceberg --recursive || echo "No data to remove!"
    docker run --rm --network makerates-network -e AWS_ACCESS_KEY_ID=$MINIO_ROOT_USER -e AWS_SECRET_ACCESS_KEY=$MINIO_ROOT_PASSWORD amazon/aws-cli --endpoint-url http://minio:9000 s3 rm s3://bronze-bucket/ --recursive || echo "No data to remove!"
    @echo "✅ MinIO S3 buckets cleaned. Everything will reinitialize on next run."

stop-makerates:
    docker ps -q --filter "name=^makerates" | xargs -r docker stop   

# Hard Reset: Stop containers, wipe volumes, delete DB, and restart
reset:
    @echo "🧹 Cleaning storage..."
    just clean-iceberg
    just clean-s3
    @echo "🗑️ Removing volumes, networks, and containers..."
    docker compose down --volumes --remove-orphans
    @echo "🗑️ Removing makerates volumes..."
    -docker volume rm makerates-dbt-data 2>/dev/null || true
    -docker volume rm makerates-minio-data 2>/dev/null || true
    -docker volume rm makerates-iceberg-db-data 2>/dev/null || true
    -docker volume rm makerates-kestra-data 2>/dev/null || true
    -docker volume rm makerates-kestra-db-data 2>/dev/null || true
    @echo "🧹 Cleaning local state..."
    -rm -f dbt_project/analytics.duckdb 2>/dev/null || true
    -rm -rf .dlt 2>/dev/null || true
    -rm -rf dbt_project/target 2>/dev/null || true
    -rm -rf dbt_project/dbt_packages 2>/dev/null || true
    -rm -rf logs 2>/dev/null || true
    @mkdir -p logs
    @echo "✨ Environment is clean."
    @echo "🔄 Restarting..."
    just run
