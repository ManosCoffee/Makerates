# Justfile cookbook to run Makerates

set dotenv-load := true

# set quiet := true

# List all available commands
default:
    @just --list

init:
    just run 
    just init-minio-buckets

# Run
run:
    @echo "🚀 Spinning Up Docker Services..."
    docker compose build ingestion-base --no-cache
    docker compose up -d 
    @echo "Initializing DynamoDB tables..."
    uv run python scripts/init_dynamodb.py --endpoint http://localhost:8000
    @echo "✅ Done! Makerates is running."

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
open-daily-topology:
    @if [ "$(uname)" = "Darwin" ]; then open http://localhost:8080/ui/main/flows/edit/makerates/rates_daily/topology; else xdg-open http://localhost:8080/ui/main/flows/edit/makerates/rates_daily/topology || echo "Please open: http://localhost:8080/ui/main/flows/edit/makerates/rates_daily/topology"; fi

open-backfill-topology:
    @if [ "$(uname)" = "Darwin" ]; then open http://localhost:8080/ui/main/flows/edit/makerates/rates_backfill/topology; else xdg-open http://localhost:8080/ui/main/flows/edit/makerates/rates_backfill/topology || echo "Please open: http://localhost:8080/ui/main/flows/edit/makerates/rates_backfill/topology"; fi

# Open MinIO Console
ui-minio:
    @if [ "$(uname)" = "Darwin" ]; then open http://localhost:9001; else xdg-open http://localhost:9001 || echo "Please open: http://localhost:9001"; fi

# DUCKDB

# Open DuckDB Analytics Preview Access database from local file (mounted via kestra)
duck-it:
    @echo "📊 Accessing DuckDB from Docker volume and showcasing example tables..."
    @echo "Validated rates (consensus mechanism filtering applied: \n)"
    @docker run --rm -it -v $(pwd)/data:/data -w /data duckdb/duckdb:latest duckdb analytics.duckdb \
        "SELECT * FROM main_validation.fact_rates_validated ORDER BY extraction_id DESC LIMIT 10;" 
    @echo "Overall rate analysis - weekly stats \n"
    @docker run --rm -it -v $(pwd)/data:/data -w /data duckdb/duckdb:latest duckdb analytics.duckdb \
        "SELECT * FROM main_analytics.mart_rate_analysis LIMIT 30;"
    @echo "Conversion rates, ready to plug in financial data services . (Many-to-Many)\n"
    @docker run --rm -it -v $(pwd)/data:/data -w /data duckdb/duckdb:latest duckdb analytics.duckdb \
        "SELECT * FROM main_analytics.mart_currency_conversions LIMIT 30;" 
    @echo "Rate volatility and risk assessment - 7day & 30day metrics \n"
    @docker run --rm -it -v $(pwd)/data:/data -w /data duckdb/duckdb:latest duckdb analytics.duckdb \
        "SELECT * FROM main_analytics.mart_rate_volatility LIMIT 30;"

# Create analytics bucket in MinIO (if missing)
init-minio-buckets:
    @echo "🪣 Creating necessary buckets in MinIO..."
    @docker run --rm --network makerates-network -e AWS_ACCESS_KEY_ID=$MINIO_ROOT_USER -e AWS_SECRET_ACCESS_KEY=$MINIO_ROOT_PASSWORD amazon/aws-cli --endpoint-url http://minio:9000 s3 mb s3://bronze-bucket || echo "Bronze bucket might already exist."
    @docker run --rm --network makerates-network -e AWS_ACCESS_KEY_ID=$MINIO_ROOT_USER -e AWS_SECRET_ACCESS_KEY=$MINIO_ROOT_PASSWORD amazon/aws-cli --endpoint-url http://minio:9000 s3 mb s3://silver-bucket || echo "Silver bucket might already exist."
    @docker run --rm --network makerates-network -e AWS_ACCESS_KEY_ID=$MINIO_ROOT_USER -e AWS_SECRET_ACCESS_KEY=$MINIO_ROOT_PASSWORD amazon/aws-cli --endpoint-url http://minio:9000 s3 mb s3://analytics-bucket || echo "Analytics bucket might already exist."
    @echo "✅ Buckets created."

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
    @CONTAINERS=$$(docker ps -q --filter "name=^makerates"); if [ -n "$$CONTAINERS" ]; then echo "$$CONTAINERS" | xargs docker stop; else echo "No makerates containers running"; fi   

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
    just init
