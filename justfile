# Justfile for Makerates Pipeine

# List all available commands
default:
    @just --list

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

# Open DuckDB Analytics (Gold) - Access database from Docker volume
db-analytics:
    @echo "📊 Accessing DuckDB from Docker volume..."
    docker run --rm -it -v makerates-dbt-data:/data --entrypoint duckdb makerates-ingestion-base:latest /data/analytics.duckdb

# Open DuckDB Validation (Check flagged rates)
db-validation:
    @echo "🔍 Checking flagged rates from Docker volume..."
    docker run --rm -it -v makerates-dbt-data:/data --entrypoint duckdb makerates-ingestion-base:latest /data/analytics.duckdb "SELECT * FROM main_validation.consensus_check WHERE status = 'FLAGGED'"

# Clean corrupted Iceberg catalog tables (fixes constraint violations)
clean-iceberg:
    @echo "🧹 Cleaning Iceberg catalog tables..."
    docker exec makerates-iceberg-db psql -U iceberg -d iceberg_catalog -c "DROP TABLE IF EXISTS iceberg_tables CASCADE; DROP TABLE IF EXISTS iceberg_namespace_properties CASCADE; DROP TABLE IF EXISTS iceberg_namespaces CASCADE;"
    @echo "✅ Iceberg catalog cleaned. Tables will reinitialize on next run."

clean-s3:
    @echo "🧹 Cleaning MinIO S3 buckets..."
    docker run --rm --network makerates-network -e AWS_ACCESS_KEY_ID=minioadmin -e AWS_SECRET_ACCESS_KEY=minioadmin123 amazon/aws-cli --endpoint-url http://minio:9000 s3 rm s3://silver-bucket/iceberg --recursive || echo "No data to remove!"
    docker run --rm --network makerates-network -e AWS_ACCESS_KEY_ID=minioadmin -e AWS_SECRET_ACCESS_KEY=minioadmin123 amazon/aws-cli --endpoint-url http://minio:9000 s3 rm s3://bronze-bucket/ --recursive || echo "No data to remove!"
    @echo "✅ MinIO S3 buckets cleaned. Everything will reinitialize on next run."

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
