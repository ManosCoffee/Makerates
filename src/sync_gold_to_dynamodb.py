#!/usr/bin/env python3
"""
Sync Validated Rates (DuckDB) to DynamoDB
Reads validated rates from the local DuckDB 'analytics.duckdb' and writes to DynamoDB.
Uses shared configuration and DynamoDB utility.
"""

import os
import sys
import duckdb
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, Any
from utils.helpers import load_config
from utils.dynamodb import DynamoDBClient

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def parse_config(job_config: Dict[str, Any]) -> Dict[str, str]:
    """
    Parse environment variables based on settings.yaml config.
    Applies defaults and checks for required variables.
    """
    env_vars = job_config.get('env_vars', {})
    required = env_vars.get('required', [])
    optional = env_vars.get('optional', [])
    defaults = job_config.get('defaults', {})
    
    parsed_config = {}
    
    # Process all potential keys
    all_keys = set(required + optional)
    
    for key in all_keys:
        # Get from env, then default, then None
        val = os.getenv(key, defaults.get(key))
        
        parsed_config[key] = val
    
    # Check required
    missing = [key for key in required if not parsed_config.get(key)]
    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)
        
    return parsed_config

def sync_rates_to_dynamodb():
    try:
        settings = load_config("settings.yaml")
        job_config = settings.get("sync_job", {})
        config = parse_config(job_config)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)

    # Extract config variables
    duckdb_path = config["DUCKDB_PATH"]
    table_name = config["DYNAMODB_TABLE_NAME"]
    endpoint_url = config.get("DYNAMODB_ENDPOINT_URL") or config.get("AWS_ENDPOINT_URL")
    region = config.get("DYNAMODB_REGION") or config.get("AWS_REGION")
    mode = config["MODE"]

    # Verify DuckDB path
    # If path is relative, check if it exists in current dir or project root
    if not os.path.exists(duckdb_path):
        # Fallback: Check if it's in dbt_project/
        fallback_path = os.path.join("dbt_project", duckdb_path)
        if os.path.exists(fallback_path):
            duckdb_path = fallback_path
        elif os.path.exists("analytics.duckdb"): # Common check
            duckdb_path = "analytics.duckdb"
        else:
            logger.error(f"DuckDB database not found at {duckdb_path}. Please run 'dbt run' first.")
            sys.exit(1)

    logger.info(f"Starting DynamoDB Sync. Source: {duckdb_path}, Target: {table_name}, Mode: {mode}")

    # --- 2. Read from DuckDB ---
    try:
        con = duckdb.connect(duckdb_path, read_only=True)
    except Exception as e:
        logger.error(f"Failed to connect to DuckDB: {e}")
        sys.exit(1)

    query = """
    SELECT 
        f.rate_date,
        f.base_currency,
        f.target_currency,
        c.country_name,
        c.region,
        f.exchange_rate,
        f.inverse_rate,
        f.consensus_variance,
        f.validation_status,
        -- Computed/Metadata
        concat(f.base_currency, '/', f.target_currency) as currency_pair
    FROM main_validation.fact_rates_validated f
    LEFT JOIN main_analytics.dim_countries c 
        ON f.target_currency = c.currency_code
    """
    
    if mode == "daily":
        start_dt = (datetime.now(timezone.utc) - timedelta(days=3)).strftime('%Y-%m-%d')
        query += f" WHERE f.rate_date >= '{start_dt}'"
        
    logger.info("Executing DuckDB Query...")
    try:
        results = con.execute(query).fetchall()
        columns = [desc[0] for desc in con.description]
        logger.info(f"Fetched {len(results)} rows.")
    except Exception as e:
        logger.error(f"Failed to execute query: {e}")
        con.close()
        sys.exit(1)
        
    con.close()
        
    if not results:
        logger.info("No data to sync.")
        return

    # --- 3. Write to DynamoDB ---
    try:
        ddb_client = DynamoDBClient(
            table_name=table_name,
            endpoint_url=endpoint_url,
            region_name=region
        )
    except Exception as e:
        logger.error(f"Failed to initialize DynamoDB client: {e}")
        sys.exit(1)
    
    logger.info(f"Writing to DynamoDB Table: {table_name}...")
    
    ids_synced = 0
    # Use batch_writer from the underlying table resource for efficiency where possible
    # We access the internal table resource directly for batch operations
    with ddb_client.table.batch_writer() as batch:
        for row in results:
            item = dict(zip(columns, row))
            
            # Type Conversions
            if hasattr(item['rate_date'], 'isoformat'):
                item['rate_date'] = item['rate_date'].isoformat()
            
            # Decimal conversion for DynamoDB
            for key in ['exchange_rate', 'inverse_rate', 'consensus_variance']:
                if item.get(key) is not None:
                     item[key] = Decimal(str(item[key]))
            
            # Add Sync Metadata
            item['synced_at'] = datetime.now(timezone.utc).isoformat()
            
            batch.put_item(Item=item)
            ids_synced += 1
            
    logger.info(f"Successfully synced {ids_synced} items to DynamoDB.")

if __name__ == "__main__":
    sync_rates_to_dynamodb()
