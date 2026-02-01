"""
ExchangeRate-API to Bronze Pipeline (dlt)

Extracts currency rates from ExchangeRate-API and loads them to
MinIO Bronze layer with full observability.

dlt provides automatically:
- Schema tracking and evolution
- State management (last extraction timestamp)
- Data lineage
- Error handling and retries
"""

import dlt
import requests
import os
from datetime import datetime
from typing import Dict, Any
from utils.quota_manager import QuotaManager
from utils.helpers import load_config
from utils.logging_config import root_logger as logger


@dlt.source(name="exchangerate")
def exchangerate_source(api_key: str = None, use_v6: bool = False):
    """
    dlt source that fetches latest USD exchange rates from ExchangeRate-API.

    Args:
        api_key: ExchangeRate-API key (optional for v4 free tier)
                 Get free key at: https://www.exchangerate-api.com/
        use_v6: If True, use v6 API with API key (more features). If False, use free v4 API.
    """

    # Get API key from parameter or environment
    api_key = api_key or os.getenv("EXCHANGERATE_API_KEY")

    config = load_config("apis.yaml")

    # Determine which API version to use
    if use_v6 and api_key:
        base_url = config['exchangerate']['base_url_v6']
        endpoint_template = config['exchangerate']['endpoints']['latest_v6']
        endpoint = endpoint_template.format(api_key=api_key, base_currency='USD')
        url = f"{base_url}{endpoint}"
    else:
        # Use free v4 API (no key required)
        base_url = config['exchangerate']['base_url_v4']
        endpoint = config['exchangerate']['endpoints']['latest_v4'].format(base_currency='USD')
        url = f"{base_url}{endpoint}"

    @dlt.resource(
        name="rates",
        write_disposition="append",  # Append each extraction (time-series data)
        primary_key="extraction_id"
    )
    def get_rates():
        """
        Fetch latest rates from ExchangeRate-API.

        Returns records with full metadata for Bronze layer:
        - extraction_id: Unique identifier for this extraction
        - extraction_timestamp: When the data was extracted
        - source: Data source name ("exchangerate")
        - base_currency: Base currency (USD)
        - rates: Dictionary of all exchange rates
        - api_response_raw: Complete API response for audit trail
        """

        try:
            response = requests.get(url, timeout=10)

            # CRITICAL: Detect quota exhaustion BEFORE raising
            if response.status_code == 429:
                logger.error("ExchangeRate-API returned 429 (rate limited)")
                quota_mgr = QuotaManager(endpoint_url=os.getenv("DYNAMODB_ENDPOINT", "http://localhost:8000"))
                failover_api = quota_mgr.mark_api_throttled(api_source="exchangerate")

                if failover_api:
                    logger.warning(f"Failover to {failover_api} recommended")

                raise RuntimeError("ExchangeRate-API quota exhausted (HTTP 429), marked as throttled")

            response.raise_for_status()
            data = response.json()

            # Build record with comprehensive metadata
            record = {
                "extraction_id": f"exchangerate_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "extraction_timestamp": datetime.now().isoformat(),
                "source": "exchangerate",
                "source_tier": "secondary",  # ExchangeRate-API is secondary source for consensus
                "base_currency": data.get("base", "USD"),
                "rate_date": data.get("date", datetime.now().strftime('%Y-%m-%d')),
                "rate_timestamp": data.get("time_last_updated"),  # Unix timestamp if available
                "rates": data.get("rates", {}),  # All currency pairs
                "api_response_raw": data,  # Complete response for audit
                "http_status_code": response.status_code,
                "response_size_bytes": len(response.content),
            }

            yield record

        except requests.exceptions.RequestException as e:
            # dlt will handle this error and log it
            raise RuntimeError(f"Failed to fetch from ExchangeRate-API: {e}")

    # Return the resource (required by dlt)
    return get_rates


def run_exchangerate_pipeline(api_key: str = None, use_v6: bool = False):
    """
    Execute the ExchangeRate-API to Bronze pipeline.

    Args:
        api_key: ExchangeRate-API key (optional for v4 free tier)
        use_v6: Use v6 API with key (more features) vs v4 free API

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
            pipeline_name="exchangerate_to_bronze",
            destination="filesystem",  # Uses MinIO via S3 protocol
            dataset_name="exchangerate",
        )

        # Run the pipeline
        load_info = pipeline.run(
            exchangerate_source(api_key=api_key, use_v6=use_v6),
            write_disposition="append"
        )

        # Record successful API request in quota tracker
        quota_manager.record_request(api_source="exchangerate", success=True)
        logger.info("✅ Recorded ExchangeRate-API usage in quota tracker")

        # Print observability info
        print(f"\n✅ ExchangeRate-API Pipeline Complete!")
        print(f"Pipeline: {load_info.pipeline.pipeline_name}")
        print(f"Destination: {load_info.pipeline.destination.destination_type}")
        print(f"Dataset: {load_info.pipeline.dataset_name}")
        print(f"Rows loaded: {load_info.metrics.get('rows_loaded', 'N/A')}")
        print(f"Load ID: {load_info.loads_ids[0] if load_info.loads_ids else 'N/A'}")

        return load_info

    except Exception as e:
        # Record failed API request
        quota_manager.record_request(api_source="exchangerate", success=False)
        logger.error(f"❌ ExchangeRate-API pipeline failed: {e}")
        raise


if __name__ == "__main__":
    # Run the pipeline directly
    # Free v4 API (no key required):
    run_exchangerate_pipeline()

    # Or use v6 with API key (uncomment below):
    # run_exchangerate_pipeline(api_key="your_api_key_here", use_v6=True)
