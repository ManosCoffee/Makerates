"""
Frankfurter (the ECB wrapper API ) - Bronze Ingestion Pipeline with dlt

dlt provides:
- Schema tracking and evolution
- Extraction State management (last extraction timestamp)
- Data lineage
- Error handling and retries
"""

import dlt
import requests
import os
from datetime import datetime
from typing import Dict, Any
from utils.quota_manager import QuotaManager
from utils.logging_config import root_logger as logger


@dlt.source(name="frankfurter")
def frankfurter_source():
    """
    A dlt source factory function that fetches latest EUR exchange rates from Frankfurter API.
    """

    @dlt.resource(
        name="rates",
        write_disposition="append",  # Append each extraction (time-series data)
        primary_key="extraction_id"
    )
    def get_rates():
        """
        Fetch latest rates from Frankfurter API.

        Returns records with full metadata for Bronze layer:
        - extraction_id: Unique identifier for this extraction
        - extraction_timestamp: When the data was extracted
        - source: Data source name ("frankfurter")
        - base_currency: Base currency (EUR)
        - rates: Dictionary of all exchange rates
        - api_response_raw: Complete API response for audit trail
        """

        # Fetch from public Frankfurter API (no need to self-host)
        url = "https://api.frankfurter.app/latest?from=USD"

        try:
            response = requests.get(url, timeout=10)

            # CRITICAL: Detect quota exhaustion BEFORE raising
            if response.status_code == 429:
                logger.error("Frankfurter returned 429 (rate limited)")
                # Mark as throttled, get failover API
                quota_mgr = QuotaManager(endpoint_url=os.getenv("DYNAMODB_ENDPOINT", "http://localhost:8000"))
                failover_api = quota_mgr.mark_api_throttled(api_source="frankfurter")

                if failover_api:
                    logger.warning(f"Failover to {failover_api} recommended")

                raise RuntimeError("Frankfurter quota exhausted (HTTP 429), marked as throttled")

            response.raise_for_status()
            data = response.json()

            # Build record with comprehensive metadata
            record = {
                "extraction_id": f"frankfurter_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "extraction_timestamp": datetime.now().isoformat(),
                "source": "frankfurter",
                "source_tier": "primary",  # Frankfurter is ECB-based (institutional)
                "base_currency": data.get("base", "EUR"),
                "rate_date": data.get("date"),  # Official ECB rate date
                "rates": data.get("rates", {}),  # All currency pairs
                "api_response_raw": data,  # Complete response for audit
                "http_status_code": response.status_code,
                "response_size_bytes": len(response.content),
            }

            yield record

        except requests.exceptions.RequestException as e:
            # dlt will handle this error and log it
            raise RuntimeError(f"Failed to fetch from Frankfurter API: {e}")

    # Return the resource (required by dlt)
    return get_rates


@dlt.source(name="frankfurter") # Configuration phase : accepts parameters and predetermines what data slice we need
def frankfurter_range_source(start_date: str, end_date: str):
    """
    A factory function that produces a "dlt source" that fetches a range of historical rates from Frankfurter API.
    Uses the efficient time-series endpoint: /v1/{start_date}..{end_date}
    """

    @dlt.resource(
        name="rates",
        write_disposition="append",
        primary_key="extraction_id"
    )
    def get_historical_rates():
        """
        A ready-to-run "dlt resource" unit that yields records for each day in the range lazily.
        Data in control line-by-line with dlt! :)
        """
        # Frankfurter Time Series Endpoint
        url = f"https://api.frankfurter.app/{start_date}..{end_date}?from=USD"
        
        try:
            response = requests.get(url, timeout=30) # Longer timeout for range

            # CRITICAL: Detect quota exhaustion BEFORE raising
            if response.status_code == 429:
                logger.error("Frankfurter returned 429 (rate limited)")
                quota_mgr = QuotaManager(endpoint_url=os.getenv("DYNAMODB_ENDPOINT", "http://localhost:8000"))
                failover_api = quota_mgr.mark_api_throttled(api_source="frankfurter")

                if failover_api:
                    logger.warning(f"Failover to {failover_api} recommended")

                raise RuntimeError("Frankfurter quota exhausted (HTTP 429), marked as throttled")

            response.raise_for_status()
            data = response.json()
            
            # The API returns: {"amount": 1.0, "base": "EUR", "start_date": "...", "end_date": "...", "rates": {"2024-01-01": {...}, ...}}
            base_currency = data.get("base", "EUR")
            all_rates = data.get("rates", {})
            
            # Iterate through each date in the response
            for date_str, rates_dict in all_rates.items():
                yield {
                    "extraction_id": f"frankfurter_{date_str}",
                    "extraction_timestamp": datetime.now().isoformat(),
                    "source": "frankfurter",
                    "source_tier": "primary",
                    "base_currency": base_currency,
                    "rate_date": date_str,
                    "rates": rates_dict,
                    "api_response_raw": data,  # Store complete response for schema consistency
                    "http_status_code": response.status_code,
                    "response_size_bytes": len(response.content) # Approx share
                }
                
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to fetch historical range from Frankfurter: {e}")

    return get_historical_rates


def run_frankfurter_pipeline():
    """
    Execute the Frankfurter to Bronze pipeline.

    dlt will:
    1. Extract data using the source
    2. Track schema changes
    3. Load to filesystem (MinIO S3)
    4. Log all operations for observability
    5. Record API usage in quota tracker
    """

    # Initialize quota manager for tracking API usage
    dynamodb_endpoint = os.getenv("DYNAMODB_ENDPOINT", "http://localhost:8000")
    quota_manager = QuotaManager(endpoint_url=dynamodb_endpoint)

    try:
        # Create pipeline pointing to MinIO (configured in .dlt/secrets.toml)
        pipeline = dlt.pipeline(
            pipeline_name="frankfurter_api",
            destination="filesystem",  # Uses MinIO via S3 protocol
            dataset_name="frankfurter",
        )

        # Run the pipeline
        load_info = pipeline.run(
            frankfurter_source(),
            write_disposition="append"
        )

        # Record successful API request in quota tracker
        quota_manager.record_request(api_source="frankfurter", success=True)
        logger.info("✅ Recorded Frankfurter API usage in quota tracker")

        # Print observability info
        print(f"\n✅ Frankfurter Pipeline Complete!")
        print(f"Pipeline: {load_info.pipeline.pipeline_name}")
        print(f"Destination: {load_info.pipeline.destination.destination_type}")
        print(f"Dataset: {load_info.pipeline.dataset_name}") 
        print(f"Load ID: {load_info.loads_ids[0] if load_info.loads_ids else 'N/A'}")

        return load_info

    except Exception as e:
        # Record failed API request
        quota_manager.record_request(api_source="frankfurter", success=False)
        logger.error(f" Frankfurter pipeline failed: {e}")
        raise


def run_frankfurter_backfill(start_date: str, end_date: str):
    """Execute the batch/backfill Frankfurter pipeline for a date range."""
    logger.info(f"🚀 Starting Frankfurter Backfill: {start_date} to {end_date}")
    
    dynamodb_endpoint = os.getenv("DYNAMODB_ENDPOINT", "http://localhost:8000")
    quota_manager = QuotaManager(endpoint_url=dynamodb_endpoint)

    try:
        pipeline = dlt.pipeline(
            pipeline_name="frankfurter_backfill",
            destination="filesystem",
            dataset_name="frankfurter",
        )
        
        load_info = pipeline.run(
            frankfurter_range_source(start_date, end_date),
            write_disposition="append"
        )
        
        quota_manager.record_request(api_source="frankfurter", success=True)
        logger.info("✅ Recorded Frankfurter API usage in quota tracker")
        print(load_info)
        return load_info
        
    except Exception as e:
        quota_manager.record_request(api_source="frankfurter", success=False)
        logger.error(f"Frankfurter Backfill Failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Frankfurter Ingestion Pipeline")
    parser.add_argument("--start-date", help="Backfill Start Date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="Backfill End Date (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.start_date and args.end_date:
        run_frankfurter_backfill(args.start_date, args.end_date)
    else:
        run_frankfurter_pipeline()
