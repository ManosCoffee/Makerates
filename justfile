# Justfile cookbook to run Makerates

set dotenv-load := true
set quiet := true

# VARS (Local control)
LOCALHOST:= "http://localhost"
DYNAMO_INTERNAL_PORT:= "8000"
DYNAMO_SERVING_PORT:= "8001"
MINIO_SERVING_PORT:= "9001"
KESTRA_UI_PORT:= "8080"




# List all available commands
default:
    @just --list

init:
    just logo
    just run 
    just init-minio-buckets
    just menu
    

## Run
run:
    @echo "🚀 Spinning Up Docker Services..."
    docker compose build ingestion-base --no-cache
    docker compose up -d
    @echo "Initializing DynamoDB tables..."
    uv run python scripts/init_dynamodb.py --endpoint {{LOCALHOST}}:{{DYNAMO_INTERNAL_PORT}}
    @echo "✅ Done! Makerates is running."

# Test multi-platform compatibility
test-multiarch:
    @echo "🧪 Testing multi-platform build for amd64 and arm64..."
    docker buildx build \
        --platform linux/amd64,linux/arm64 \
        --file Dockerfile.ingestion \
        --tag makerates-ingestion-test:multiarch \
        --progress=plain \
        .
    @echo "Multi-platform build successfully!"


## Initialize DynamoDB Tables (Running local script)
init-db:
    uv run python scripts/init_dynamodb.py

## Create analytics bucket in MinIO (if missing)
init-minio-buckets:
    @echo "🪣 Creating necessary buckets in MinIO..."
    @docker run --rm --network makerates-network -e AWS_ACCESS_KEY_ID=$MINIO_ROOT_USER -e AWS_SECRET_ACCESS_KEY=$MINIO_ROOT_PASSWORD amazon/aws-cli --endpoint-url $MINIO_ENDPOINT s3 mb s3://bronze-bucket || echo "Bronze bucket might already exist."
    @docker run --rm --network makerates-network -e AWS_ACCESS_KEY_ID=$MINIO_ROOT_USER -e AWS_SECRET_ACCESS_KEY=$MINIO_ROOT_PASSWORD amazon/aws-cli --endpoint-url $MINIO_ENDPOINT s3 mb s3://silver-bucket || echo "Silver bucket might already exist."
    @docker run --rm --network makerates-network -e AWS_ACCESS_KEY_ID=$MINIO_ROOT_USER -e AWS_SECRET_ACCESS_KEY=$MINIO_ROOT_PASSWORD amazon/aws-cli --endpoint-url $MINIO_ENDPOINT s3 mb s3://analytics-bucket || echo "Analytics bucket might already exist."
    @echo "✅ Buckets created."

## KESTRA SPECIFIC
# Restart only Kestra (Fast config reload)
restart-kestra:
    docker compose up -d --force-recreate kestra

# View Kestra logs
logs:
    docker logs -f makerates-kestra

# Open Kestra UI in "Topology" view (parameterized helper)
_open-kestra-topology MODE:
    #!/usr/bin/env bash
    URL="{{LOCALHOST}}:{{KESTRA_UI_PORT}}/ui/main/flows/edit/makerates/{{MODE}}/topology"
    if [ "$(uname)" = "Darwin" ]; then
        open "$URL"
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$URL"
    else
        echo "Please open: $URL"
    fi

# Open daily rates topology
open-daily-topology:
    @just _open-kestra-topology rates_daily
    @echo ""
    @echo "Use dummy credentials for the local POC:"
    @printf "> USERNAME: \033[33m%s\033[0m\n" "$KESTRA_USR"
    @printf "> PASSWORD: \033[33m%s\033[0m\n" "$KESTRA_PSWD"

# Open backfill rates topology
open-backfill-topology:
    @just _open-kestra-topology rates_backfill
    @echo ""
    @echo "Use dummy credentials for the local POC:"
    @printf "> USERNAME: \033[33m%s\033[0m\n" "$KESTRA_USR"
    @printf "> PASSWORD: \033[33m%s\033[0m\n" "$KESTRA_PSWD"


## Auxiliary UI's
open-minio:
    #!/usr/bin/env bash
    URL="{{LOCALHOST}}:{{MINIO_SERVING_PORT}}"
    if [ "$(uname)" = "Darwin" ]; then
        open "$URL"
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$URL"
    else
        echo "Please open: $URL"
    fi
    echo ""
    echo "Use dummy credentials for the local POC :"
    echo -e "> USERNAME: \033[33mminioadmin\033[0m"
    echo -e "> PASSWORD: \033[33mminioadmin123\033[0m"

# Open DynamoDB Admin UI
open-dynamo:
    #!/usr/bin/env bash
    URL="{{LOCALHOST}}:{{DYNAMO_SERVING_PORT}}"
    if [ "$(uname)" = "Darwin" ]; then
        open "$URL"
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$URL"
    else
        echo "Please open: $URL"
    fi
    

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


# CLEAN-UPS & RESETS
## Clean corrupted Iceberg catalog tables (fixes constraint violations)
clean-iceberg:
    @echo "🧹 Cleaning Iceberg catalog tables..."
    docker exec makerates-iceberg-db psql -U iceberg -d iceberg_catalog -c "DROP TABLE IF EXISTS iceberg_tables CASCADE; DROP TABLE IF EXISTS iceberg_namespace_properties CASCADE; DROP TABLE IF EXISTS iceberg_namespaces CASCADE;"
    @echo "✅ Iceberg catalog cleaned. Tables will reinitialize on next run."

clean-s3:
    @echo "🧹 Cleaning MinIO S3 buckets..."
    docker run --rm --network makerates-network -e AWS_ACCESS_KEY_ID=$MINIO_ROOT_USER -e AWS_SECRET_ACCESS_KEY=$MINIO_ROOT_PASSWORD amazon/aws-cli --endpoint-url $MINIO_ENDPOINT s3 rm s3://silver-bucket/iceberg --recursive || echo "No data to remove!"
    docker run --rm --network makerates-network -e AWS_ACCESS_KEY_ID=$MINIO_ROOT_USER -e AWS_SECRET_ACCESS_KEY=$MINIO_ROOT_PASSWORD amazon/aws-cli --endpoint-url $MINIO_ENDPOINT s3 rm s3://bronze-bucket/ --recursive || echo "No data to remove!"
    @echo "✅ MinIO S3 buckets cleaned. Everything will reinitialize on next run."

stop-makerates:
    #!/usr/bin/env bash
    set -euo pipefail
    CONTAINERS=$(docker ps -q --filter "name=^makerates")
    if [ -n "$CONTAINERS" ]; then
        echo "$CONTAINERS" | xargs docker stop
        echo "✅ Stopped makerates containers"
    else
        echo "ℹ️  No makerates containers running"
    fi

## Hard Reset: Stop containers, wipe volumes, delete DB, and restart
reset:
    @echo "🧹 Cleaning storage..."
    just clean-iceberg
    just clean-s3
    @echo "🗑️ Removing volumes, networks, and containers..."
    @docker compose down --volumes --remove-orphans
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


## AUXILIARY RECIPES
logo:
    @echo "\033[1;35m"
    echo "                               ░██                                         ░██"
    echo "                               ░██                                         ░██"
    echo "    ░█████████████   ░██████   ░██    ░██ ░███████  ░██░████  ░██████   ░████████  ░███████   ░███████"
    echo "    ░██   ░██   ░██       ░██  ░██   ░██ ░██    ░██ ░███           ░██     ░██    ░██    ░██ ░██"
    echo "    ░██   ░██   ░██  ░███████  ░███████  ░█████████ ░██       ░███████     ░██    ░█████████  ░███████"
    echo "    ░██   ░██   ░██ ░██   ░██  ░██   ░██ ░██        ░██      ░██   ░██     ░██    ░██               ░██"
    echo "    ░██   ░██   ░██  ░█████░██ ░██    ░██ ░███████  ░██       ░█████░██     ░████  ░███████   ░███████"
    @echo  "\033[0m"
    echo ""



menu:
    #!/usr/bin/env bash
    while true; do
        clear
        just logo
        # Display menu
        echo -e "\033[95m"
        echo "╔═════════════════════════╗"
        echo "║  Makerates POC - Menu   ║"
        echo "╠═════════════════════════╣"
        echo "║ 1) Run Daily Pipe       ║"
        echo "║ 2) Run a Backfill       ║"
        echo "║ 3) Inspect MinIO S3     ║"
        echo "║ 4) Inspect DynamoDB     ║"
        echo "║ 5) Peek at output data  ║"
        echo "║ 6) Stop Makerates       ║"
        echo "║ 7) Reboot Makerates     ║"
        echo "║ 8) Exit Menu            ║"
        echo "╚═════════════════════════╝"
        echo -ne "\033[0mChoose (1-8): "
        read choice
        case "$choice" in
            1) just open-daily-topology ;;
            2) just open-backfill-topology ;;
            3) just open-minio ;;
            4) just open-dynamo ;;
            5) just duck-it ;;
            6) just stop-makerates ; "👋 So long, see you in Production!"; break ;;
            7) just reset ;;
            8) echo "👋 Goodbye, see you in Production!"; break ;;
            *) echo -e "\033[31m❌ Invalid option. Please choose 1-7\033[0m" ;;
        esac
        [ "$choice" != "7" ] && read -p "Press Enter to continue..."
    done
