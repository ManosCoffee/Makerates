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
from pathlib import Path
from utils.helpers import load_config
from utils.dynamodb import DynamoDBClient
from utils.helpers import parse_env_vars_config

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# ENV VARS FOR JOB CONFIG 
JOB_CONFIG_FILE = "settings.yaml"


def sync_rates_to_dynamodb():
    try:
        settings = load_config(JOB_CONFIG_FILE)
        job_config = settings.get("sync_job", {})
        config = parse_env_vars_config(job_config)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)

    # Extract config variables
    raw_duckdb_path = os.getenv("DUCKDB_PATH", "analytics.duckdb")
    table_name = config["DYNAMODB_TABLE_NAME"]
    
    duckdb_path = Path(raw_duckdb_path)
    
    # Verify DuckDB path
    if not duckdb_path.exists():
        # Fallback 1: Check in current directory strictly
        local_fallback = Path("data/analytics.duckdb")
        
        # Fallback 2: Check in dbt_project/
        project_fallback = Path("dbt_project/analytics.duckdb")

        if local_fallback.exists():
             logger.info(f"Found database at local fallback: {local_fallback}")
             duckdb_path = local_fallback
        elif project_fallback.exists():
             logger.info(f"Found database at project fallback: {project_fallback}")
             duckdb_path = project_fallback
        else:
            logger.error(f"DuckDB database not found at {duckdb_path} (absolute: {duckdb_path.absolute()})")
            logger.error("Please ensure 'dbt run' completes successfully and creates the file.")
            sys.exit(1)

    logger.info(f"Starting DynamoDB Sync. Source: {duckdb_path}, Target: {table_name}")

    # ---  Read from DuckDB ---
    try:
        # Use str(duckdb_path) because DuckDB python API might expect string
        con = duckdb.connect(str(duckdb_path), read_only=True)
    except Exception as e:
        logger.error(f"Failed to connect to DuckDB: {e}")
        sys.exit(1)

    # Query latest rate date
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
            concat(f.base_currency, '/', f.target_currency) as currency_pair
        FROM main_validation.fact_rates_validated f
        LEFT JOIN main_analytics.dim_countries c 
            ON f.target_currency = c.currency_code
        WHERE f.rate_date = (SELECT MAX(rate_date) FROM main_validation.fact_rates_validated)
    """
    
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

    # ---  Write to DynamoDB ---
    try:
        ddb_client = DynamoDBClient(
            table_name=table_name
        )
    except Exception as e:
        logger.error(f"Failed to initialize DynamoDB client: {e}")
        sys.exit(1)
    
    logger.info(f"Writing to DynamoDB Table: {table_name}...")
    
    ids_synced = 0
    # Use batch_writer from the underlying table resource for efficiency
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
