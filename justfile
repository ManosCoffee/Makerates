# Justfile for Makerates Pipeine

# List all available commands
default:
    @just --list

# Run
run:
    @echo "🚀 Spinning Up Docker Services..."
    docker compose up -d
    @echo "Initializing DynamoDB tables..."
    uv run python scripts/init_dynamodb.py --endpoint http://localhost:8000
    @echo "✅ Done! Makerates is running."

# Rebuild the worker image and restart Kestra (Full Reload)
reload:
    @echo "🔄 Rebuilding worker image..."
    docker compose build ingestion-base
    @echo " Restarting Kestra to load new env vars..."
    docker compose up -d kestra
    @echo " Initializing DynamoDB tables..."
    uv run python scripts/init_dynamodb.py --endpoint http://localhost:8000
    @echo "✅ Done! Kestra is running with new config."

# Initialize DynamoDB Tables (Running local script)
init-db:
    uv run python scripts/init_dynamodb.py

# Restart only Kestra (Fast config reload)
restart-kestra:
    docker compose up -d --force-recreate kestra

# View Kestra logs
logs:
    docker logs -f makerates-kestra
    docker compose down --volumes --remove-orphans
    docker compose up -d --build

# Open Kestra UI
ui-kestra:
    open http://localhost:8080

# Open MinIO Console
ui-minio:
    open http://localhost:9001

# Open DuckDB Analytics (Gold)
db-analytics:
    duckdb dbt_project/analytics.duckdb

# Open DuckDB Validation (Check flagged rates)
db-validation:
    duckdb dbt_project/analytics.duckdb "SELECT * FROM main_validation.consensus_check WHERE status = 'FLAGGED'"

# Hard Reset: Stop containers, wipe volumes, delete DB, and restart
reset:
    @echo "🧨 Stopping makerates containers..."
    -docker stop $(docker ps -q --filter "name=makerates-*")
    @echo " Removing volumes and containers..."
    docker compose down --volumes --remove-orphans
    @echo "Deleting local DuckDB..."
    rm -f dbt_project/analytics.duckdb
    @echo "🔄 Restarting..."
    just run
