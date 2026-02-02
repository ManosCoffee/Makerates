import os
import sys
import argparse
import logging
from datetime import datetime
from typing import Dict, Any, Optional
import pyarrow as pa
from duckdb import DuckDBPyConnection, connect
from pyiceberg.catalog import load_catalog
from utils.s3_helper import get_s3_client, check_s3_prefix_exists
from utils.helpers import load_config
from utils.logging_config import root_logger as logger

# Configure Logging (Already done in root_logger)
from utils.dynamodb import DynamoDBClient

class IcebergLoader:
    """
    Handles Loading of Bronze JSONL data into Silver Iceberg tables.
    Encapsulates Configuration, DuckDB processing, and Iceberg interactions.
    """

    def __init__(self, mode: str, start_date: str, end_date: str):
        self.mode = mode
        self.start_date = start_date
        self.end_date = end_date

        # 1. Load Configurations
        self.settings = load_config("settings.yaml")
        self.storage_config = load_config("storage.yaml")

        # 2. Parse & Validate Environment Variables
        self.env_config = self._load_environment_variables()

        # 3. Setup Connections
        self.con = self._setup_duckdb()
        self.s3_client = get_s3_client() # Helper uses boto3 directly, but we might keep it accessible

        # 4. Primary Keys List
        self.pk_list = [k.strip() for k in self.env_config["PRIMARY_KEYS"].split(",")]

        # 5. DynamoDB Table Names from settings
        self.dynamodb_tables = self.settings.get("dynamodb_tables", {})

    def _load_environment_variables(self) -> Dict[str, str]:
        """Loads and validates environment variables based on settings.yaml."""
        config: Dict[str, str] = {}
        job_settings = self.settings['iceberg_job']
        
        # Check Required
        missing = []
        for var in job_settings['env_vars']['required']:
            val = os.environ.get(var)
            if not val:
                missing.append(var)
            config[var] = val

        if missing:
            logger.error(f"Missing required environment variables: {missing}")
            sys.exit(1)

        # Load Optional / Defaults
        defaults = job_settings.get('defaults', {})
        for var in job_settings['env_vars']['optional']:
            default_val = defaults.get(var)
            config[var] = os.environ.get(var, default_val)
        return config

    def _setup_duckdb(self) -> DuckDBPyConnection:
        """Configures DuckDB with S3/MinIO settings."""
        con = connect()
        con.sql("INSTALL httpfs; LOAD httpfs;")
        
        endpoint = self.env_config.get("AWS_ENDPOINT_URL")
        access_key = self.env_config.get("AWS_ACCESS_KEY_ID")
        secret_key = self.env_config.get("AWS_SECRET_ACCESS_KEY")
        region = self.env_config.get("AWS_REGION")

        if endpoint:
            # Clean endpoint for httpfs compatibility if needed
            clean_endpoint = endpoint.replace('http://', '').replace('https://', '')
            con.sql(f"SET s3_endpoint='{clean_endpoint}';")
            con.sql("SET s3_use_ssl=false;")
            con.sql("SET s3_url_style='path';")
        
        if access_key and secret_key:
            con.sql(f"SET s3_access_key_id='{access_key}';")
            con.sql(f"SET s3_secret_access_key='{secret_key}';")
        
        if region:
            con.sql(f"SET s3_region='{region}';")

        return con

    def _get_date_params(self, dt: datetime) -> Dict[str, str]:
        """Format date parameters for template substitution."""
        return {
            "year": dt.strftime("%Y"),
            "month": dt.strftime("%m"),
            "day": dt.strftime("%d") # Logic fix: Day number only
        }

    def generate_source_pattern(self) -> str:
        """
        Determine S3 Glob Pattern using Configured Templates.
        Priority Order: Daily -> Backfill Day -> Backfill Month -> Backfill Recursive
        """
        source_bucket = self.env_config["SOURCE_BUCKET"]
        source_prefix = self.env_config.get("SOURCE_PREFIX", "")
        
        bronze_cfg = self.storage_config['storage']['bronze']
        patterns = bronze_cfg['patterns']

        # 1. Resolve Base Path
        try:
            base_path_resolved = bronze_cfg['base_path'].format(
                bucket=source_bucket,
                prefix=source_prefix if source_prefix else ""
            )
        except KeyError as e:
             raise ValueError(f"Missing param for base_path template: {e}")

        # Cleanup double slashes
        base_path_resolved = base_path_resolved.replace("//rates", "/rates")

        target_dt = datetime.strptime(self.start_date, "%Y-%m-%d")
        today_dt = datetime.now()
        
        candidates = []

        if self.mode == "daily":
            # Strategy 1: Daily Pattern
            pat = patterns['daily'].format(base_path=base_path_resolved, **self._get_date_params(target_dt))
            check_path = pat.rsplit('/', 1)[0]
            candidates.append((check_path, pat))
            
        elif self.mode == "backfill":
            # Strategy A: Today Day
            pat_day = patterns['backfill_day'].format(base_path=base_path_resolved, **self._get_date_params(today_dt))
            candidates.append((pat_day.rsplit('/', 1)[0], pat_day))

            # Strategy B: Today Month
            pat_month = patterns['backfill_month'].format(base_path=base_path_resolved, **self._get_date_params(today_dt))
            candidates.append((pat_month.rsplit('/', 1)[0], pat_month))
            
            # Strategy C: Target Month
            pat_target = patterns['backfill_month'].format(base_path=base_path_resolved, **self._get_date_params(target_dt))
            candidates.append((pat_target.rsplit('/', 1)[0], pat_target))

        # Universal Fallback
        pat_root = patterns['backfill_root'].format(base_path=base_path_resolved)
        check_root = pat_root.split('/**')[0]
        candidates.append((check_root, pat_root))

        logger.info(f"Resolving Source Pattern for mode={self.mode}...")
        
        for check_prefix, glob_pattern in candidates:
            # S3 Helper expects full path (s3://...) and handles stripping internally now.
            logger.info(f"Checking prefix: {check_prefix}")
            if check_s3_prefix_exists(self.s3_client, source_bucket, check_prefix):
                logger.info(f"✅ Found data at: {check_prefix}. Using pattern: {glob_pattern}")
                return glob_pattern
                
        raise ValueError(f"No data found for mode {self.mode}")

    def get_arrow_batch(self, source_pattern: str) -> Optional[pa.Table]:
        """
        Reads JSONL from S3 using DuckDB, deduplicates, and returns a PyArrow Table.
        Handles flattened dlt schema (rates__usd, rates__aed, etc.) and reconstructs MAP.
        """
        logger.info(f"Scanning source pattern: {source_pattern}")

        # Step 1: Read with auto schema detection to get all flattened columns
        query = f"""
        CREATE OR REPLACE TEMP TABLE bronze_flattened AS
        SELECT *
        FROM read_json_auto('{source_pattern}',
            format='newline_delimited',
            filename=true,
            maximum_object_size=50000000
        );
        """
        try:
            self.con.sql(query)
        except Exception as e:
            if "No files found" in str(e):
                 logger.warning(f"No files match pattern: {source_pattern}")
                 return None
            raise e

        # Step 2: Reconstruct the rates MAP from flattened rates__* columns
        # Get list of all rates__* columns dynamically
        rates_cols_query = """
        SELECT column_name
        FROM (DESCRIBE SELECT * FROM bronze_flattened)
        WHERE column_name LIKE 'rates__%'
        """
        rates_cols = [row[0] for row in self.con.sql(rates_cols_query).fetchall()]

        if rates_cols:
            # Build MAP using map_from_entries with FILTER to exclude NULLs
            # Create list of struct entries: {key: 'USD', value: rates__usd}
            # Filter out NULL values to avoid Arrow errors
            currency_keys_raw = [col.replace('rates__', '').upper() for col in rates_cols]

            # Filter out empty or invalid keys (defensive check)
            valid_pairs = [(col, key) for col, key in zip(rates_cols, currency_keys_raw) if key and len(key) > 0]

            if not valid_pairs:
                # No valid currency columns found
                rates_map_expr = "MAP([], [])::MAP(VARCHAR, DOUBLE) AS rates"
                logger.warning("No valid rates__* columns found after filtering, creating empty rates MAP")
            else:
                logger.info(f"Reconstructing MAP from {len(valid_pairs)} valid flattened rate columns (filtering NULLs and empty keys)")
                currency_keys_list = [key for _, key in valid_pairs]
                logger.info(f"Currency keys: {currency_keys_list}")

                # Build CASE expressions to create structs only for non-NULL values
                struct_list = ", ".join([
                    f"CASE WHEN {col} IS NOT NULL THEN "
                    f"{{key: '{key}', value: CAST({col} AS DOUBLE)}} "
                    f"END"
                    for col, key in valid_pairs
                ])

                # Use list_filter to remove NULL struct entries AND validate keys are not NULL/empty
                # COALESCE with empty MAP to handle edge cases on subsequent runs
                # This prevents Arrow validation errors from NULL keys
                rates_map_expr = f"COALESCE(map_from_entries(list_filter([{struct_list}], x -> x IS NOT NULL AND x.key IS NOT NULL AND x.key != '')), MAP([], [])::MAP(VARCHAR, DOUBLE)) AS rates"
                logger.debug(f"MAP expression (first 200 chars): {rates_map_expr[:200]}...")
        else:
            # Fallback: empty MAP if no rates columns found
            rates_map_expr = "MAP([], [])::MAP(VARCHAR, DOUBLE) AS rates"
            logger.warning("No rates__* columns found, creating empty rates MAP")


        # Create bronze_raw table with reconstructed MAP
        columns = [
            "extraction_id",
            "extraction_timestamp",
            "source",
            "source_tier",
            "base_currency",
            "rate_date",
            rates_map_expr,
            "http_status_code",
            "filename"
        ]

        reconstruct_query = f"""
        CREATE OR REPLACE TEMP TABLE bronze_raw AS
        SELECT
            {', '.join(columns)}
        FROM bronze_flattened;
        """
        self.con.sql(reconstruct_query)
        logger.info("✅ Successfully reconstructed rates MAP from flattened schema")
        
        # Deduplication Logic
        # Read PKs from Env Config (List)
        pk_cols_sql = ", ".join(self.pk_list)
        
        # For daily mode: Accept latest data (3-day lookback for weekends/holidays)
        # For backfill mode: Use strict date range
        if self.mode == "daily":
            # Daily: Accept data from past 3 days (handles weekends/holidays when APIs return latest available)
            filter_clause = f"""
                WHERE CAST(rate_date AS DATE) >= CAST('{self.start_date}' AS DATE) - INTERVAL '3 days'
            """
        else:
            # Backfill: strict date range
            filter_clause = f"""
                WHERE CAST(rate_date AS DATE) >= CAST('{self.start_date}' AS DATE)
                  AND CAST(rate_date AS DATE) <= CAST('{self.end_date}' AS DATE)
            """
        
        final_query = f"""
        SELECT * EXCLUDE (filename, rn)
        FROM (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY {pk_cols_sql} 
                    ORDER BY extraction_timestamp DESC
                ) as rn
            FROM bronze_raw
            {filter_clause}
        )
        WHERE rn = 1
        """
        
        logger.info(f"Executing DuckDB Query with Deduplication on keys: {self.pk_list} based on extraction_timestamp")

        # CRITICAL: Validate MAP has no NULL keys before Arrow conversion (prevents idempotency issues)
        validation_query = f"""
        SELECT COUNT(*) as invalid_count
        FROM ({final_query}) validated
        WHERE EXISTS (
            SELECT 1 FROM unnest(map_keys(validated.rates)) AS k(key)
            WHERE k.key IS NULL OR k.key = ''
        )
        """
        try:
            invalid_result = self.con.sql(validation_query).fetchone()
            if invalid_result and invalid_result[0] > 0:
                logger.error(f"❌ CRITICAL: Found {invalid_result[0]} rows with NULL or empty MAP keys!")
                logger.error("This will cause Arrow validation errors. Filtering out invalid rows...")
                # Add filter to exclude rows with invalid MAP keys
                final_query = f"""
                SELECT * FROM ({final_query}) validated
                WHERE NOT EXISTS (
                    SELECT 1 FROM unnest(map_keys(validated.rates)) AS k(key)
                    WHERE k.key IS NULL OR k.key = ''
                )
                """
                logger.info("✅ Applied filter to exclude invalid MAP entries")
        except Exception as e:
            logger.warning(f"MAP validation query failed (might be empty result): {e}")

        try:
            arrow_result = self.con.sql(final_query).arrow()

            if isinstance(arrow_result, pa.RecordBatchReader):
                arrow_table = arrow_result.read_all()
            else:
                arrow_table = arrow_result

            logger.info(f"Read {arrow_table.num_rows} rows (after dedup) for period {self.start_date} to {self.end_date}")

            # Diagnostic: Check rates column and timestamp for NULL issues
            if 'rates' in arrow_table.schema.names and arrow_table.num_rows > 0:
                logger.info("Validating rates MAP column...")
                rates_col = arrow_table.column('rates')

                # Sample the first few rows to check for issues
                for i in range(min(3, len(rates_col))):
                    map_value = rates_col[i]
                    if map_value.is_valid:
                        logger.debug(f"Row {i} rates: {map_value.as_py()}")

            # Check for NULL timestamp column (suspected root cause!)
            if 'timestamp' in arrow_table.schema.names:
                timestamp_col = arrow_table.column('timestamp')
                null_count = timestamp_col.null_count
                logger.info(f"Timestamp column: {null_count} NULLs out of {len(timestamp_col)} rows")
                if null_count > 0:
                    logger.warning(f"⚠️ Found {null_count} NULL values in timestamp column - this may cause Arrow validation errors!")

            return arrow_table

        except Exception as e:
            logger.error(f"Failed to create Arrow table from DuckDB: {e}")
            logger.error(f"Final query (first 500 chars): {final_query[:500]}")
            raise

    def load_to_iceberg(self, arrow_table: pa.Table):
        """
        UPSERTS the Arrow table into the Iceberg Catalog:
        - Inserts new rows or Updates existing rows based on the join_cols.
        - Maintains incremental updates (more efficient than replacing the entire table)

        NOTES: 
        1. The incoming arrow data are prefiltered (dedup-ed) based on latest extraction.
        2. This operation is now IDEMPOTENT :
           - Deduplicated Input
           - The `table.upsert()` method uses `join_cols` to match rows for updates 
        """
        catalog_name = self.env_config["ICEBERG_CATALOG"]
        namespace = self.env_config["ICEBERG_NAMESPACE"]
        table_name = self.env_config["TABLE_NAME"]
        
        try:
            catalog = load_catalog(catalog_name)
            full_table_name = f"{namespace}.{table_name}"
            logger.info(f"Loading table: {full_table_name}")
            
            # Ensure Namespace Exists
            try:
                catalog.create_namespace(namespace)
                logger.info(f"Created/Verified namespace: {namespace}")
            except Exception:
                pass 

            try:
                table = catalog.load_table(full_table_name)
                logger.info(f"Table {full_table_name} exists. Checking for schema evolution...")

                # Schema Evolution: Add new columns if present in arrow_table
                existing_fields = {field.name for field in table.schema().fields}
                incoming_fields = set(arrow_table.schema.names)
                new_fields = incoming_fields - existing_fields

                if new_fields:
                    logger.info(f"Schema evolution: Adding {len(new_fields)} new columns: {sorted(new_fields)}")
                    with table.update_schema() as update:
                        update.union_by_name(arrow_table.schema)
                    logger.info("✅ Schema evolved successfully")
                else:
                    logger.info("No schema evolution needed")

            except Exception as e:
                logger.info(f"Table {full_table_name} not found. Creating...")
                target_loc = self.env_config.get("TARGET_BUCKET")
                # Ensure it ends with a table name 
                if target_loc:
                     location = f"{target_loc}/{table_name}"
                else:
                     location = None # Let catalog decide
                
                table = catalog.create_table(
                    identifier=full_table_name,
                    schema=arrow_table.schema,
                    location=location
                )
                
                

            logger.info(f"Upserting {arrow_table.num_rows} rows using keys: {self.pk_list}...")

            # Validate arrow table before upsert (defensive check for MAP schema issues)
            try:
                # Check if rates column exists and log its type
                if 'rates' in arrow_table.schema.names:
                    rates_field = arrow_table.schema.field('rates')
                    logger.info(f"Rates column type: {rates_field.type}")

                    # Quick validation: try to access the column (doesn't modify data)
                    rates_col = arrow_table.column('rates')
                    logger.info(f"✅ Rates column accessible, {len(rates_col)} entries")
            except Exception as e:
                logger.error(f"Arrow table validation failed: {e}")
                logger.error(f"Schema: {arrow_table.schema}")
                raise

            # CRITICAL FIX: PyIceberg's upsert() has a bug with MAP types that causes
            # "Map array keys array should have no nulls" on subsequent runs
            # https://github.com/apache/arrow/issues/38553 related issue on pyarrow + MAP bug

            # We use delete+append strategy for idempotency instead of buggy merge upsert
            logger.info(f"Processing {arrow_table.num_rows} rows using delete+append (idempotent, MAP-safe)...")

            try:
                # Extract unique combinations of primary key values
                pk_values_set = set()
                for i in range(arrow_table.num_rows):
                    pk_tuple = tuple(arrow_table.column(pk)[i].as_py() for pk in self.pk_list)
                    pk_values_set.add(pk_tuple)

                # Build delete predicate: (rate_date='2024-01-01' AND source='x' AND base_currency='USD') OR ...
                delete_predicates = []
                for pk_values in pk_values_set:
                    row_predicates = []
                    for pk, value in zip(self.pk_list, pk_values):
                        if isinstance(value, str):
                            row_predicates.append(f"{pk} = '{value}'")
                        else:
                            row_predicates.append(f"{pk} = {value}")
                    delete_predicates.append(f"({' AND '.join(row_predicates)})")

                # Delete existing rows with matching keys (idempotency)
                if delete_predicates:
                    combined_predicate = " OR ".join(delete_predicates)
                    logger.info(f"Deleting {len(pk_values_set)} existing row(s) with matching keys...")
                    logger.debug(f"Delete predicate: {combined_predicate[:300]}...")
                    table.delete(combined_predicate)
                    logger.info("✅ Deleted existing rows")

                # Append new data (no merge, avoids MAP bug)
                logger.info(f"Appending {arrow_table.num_rows} rows...")
                table.append(arrow_table)
                logger.info(f"✅ Successfully inserted {arrow_table.num_rows} rows")

            except Exception as e:
                logger.error(f"Delete+Append strategy failed: {e}")
                raise
            except Exception as e:
                if "Map array keys array should have no nulls" in str(e):
                    logger.error("═" * 80)
                    logger.error("ARROW VALIDATION ERROR: NULL keys detected in MAP column")
                    logger.error("═" * 80)
                    logger.error("This might be caused by:")
                    logger.error("1. NULL timestamp column (check logs above)")
                    logger.error("2. Schema mismatch between existing and new data")
                    logger.error("3. PyIceberg upsert merge issue with MAP types")
                    logger.error("═" * 80)
                raise
            
            # --- DYNAMODB STATE UPDATE ---
            try:
                table.refresh()
                latest_metadata_location = table.metadata_location
                logger.info(f"Latest Metadata Location: {latest_metadata_location}")
                
                # Initialize DynamoDBClient wrapper
                metadata_table = self.dynamodb_tables.get("iceberg_metadata", "iceberg_metadata")
                ddb = DynamoDBClient(table_name=metadata_table)
                ddb.put_item({
                    "table_name": table_name,
                    "metadata_location": latest_metadata_location,
                    "updated_at": datetime.now().isoformat()
                })
                logger.info(f"✅ Updated DynamoDB state for {table_name} in table {metadata_table}")

            except Exception as e:
                logger.warning(f"Failed to update DynamoDB state (continuing): {e}")
            
        except Exception as e:
            logger.error(f"Iceberg operation failed: {e}")
            sys.exit(1)

    def run(self):
        """Main execution flow."""
        try:
            source_pattern = self.generate_source_pattern()
            arrow_table = self.get_arrow_batch(source_pattern)
            
            if arrow_table is None or arrow_table.num_rows == 0:
                logger.info("No records found. Skipping upsert.")
                return

            self.load_to_iceberg(arrow_table)
            
        except Exception as e:
            logger.error(f"Job failed: {e}")
            sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Compact Bronze JSONL to Silver Iceberg (Upsert)")
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", help="YYYY-MM-DD (Defaults to start-date)",required=False)
    parser.add_argument("--mode", choices=["daily", "backfill"], default="daily")
    
    args = parser.parse_args()
    end_date = args.end_date if args.end_date else args.start_date
    
    job = IcebergLoader(args.mode, args.start_date, end_date)
    job.run()

if __name__ == "__main__":
    main()
