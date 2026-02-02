"""
CurrencyLayer - Bronze Ingestion Pipeline with dlt

Extracts currency rates from CurrencyLayer API.
Supports:
1. Daily Live Rates (/live)
2. Historical Range (/timeframe) - Requires Professional/Enterprise Plan

dlt provides:
- Schema tracking
- Extraction State management
- Data lineage
"""

import dlt
import requests
import os
import argparse
import sys
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from utils.quota_manager import QuotaManager
from utils.helpers import load_config
from utils.logging_config import root_logger as logger

# Base URL
CURRENCYLAYER_BASE_URL = "http://api.currencylayer.com" 

@dlt.source(name="currencylayer")
def currencylayer_source(date: Optional[str] = None):
    """
    dlt source factory for Daily/Single-Date CurrencyLayer extraction.
    Args:
        date: "YYYY-MM-DD" or None (for live)
        Note: Free Tier only supports Source=USD.
    """
    api_key = os.getenv("CURRENCYLAYER_API_KEY")
    if not api_key:
        raise ValueError("CURRENCYLAYER_API_KEY not found in environment variables.")

    @dlt.resource(
        name="rates",
        write_disposition="append",
        primary_key="extraction_id"
    )
    def get_rates():
        config = load_config("apis.yaml")
        base_url = config['currencylayer']['base_url']

        # Endpoint: /historical (if date) or /live
        if date:
            endpoint = config['currencylayer']['endpoints']['historical']
            url = f"{base_url}{endpoint.format(api_key=api_key, date=date)}"
        else:
            endpoint = config['currencylayer']['endpoints']['live']
            url = f"{base_url}{endpoint.format(api_key=api_key)}"

        try:
            response = requests.get(url, timeout=10)

            # CRITICAL: Detect quota exhaustion BEFORE raising
            if response.status_code == 429:
                logger.error("CurrencyLayer returned 429 (rate limited)")
                quota_mgr = QuotaManager(endpoint_url=os.getenv("DYNAMODB_ENDPOINT", "http://localhost:8000"))
                failover_api = quota_mgr.mark_api_throttled(api_source="currencylayer")

                if failover_api:
                    logger.warning(f"Failover to {failover_api} recommended")

                raise RuntimeError("CurrencyLayer quota exhausted (HTTP 429), marked as throttled")

            response.raise_for_status()
            data = response.json()

            # Check for quota exhaustion in response body (CurrencyLayer returns 200 with error)
            if not data.get("success"):
                error_info = data.get("error", {})
                error_code = error_info.get("code")

                # Error code 104: Monthly request volume reached
                if error_code == 104:
                    logger.error(f"CurrencyLayer quota exhausted (error code 104)")
                    quota_mgr = QuotaManager(endpoint_url=os.getenv("DYNAMODB_ENDPOINT", "http://localhost:8000"))
                    quota_mgr.mark_api_throttled(api_source="currencylayer")
                    raise RuntimeError("CurrencyLayer quota exhausted (error code 104), marked as throttled")

                raise RuntimeError(f"CurrencyLayer API Error {error_code}: {error_info.get('info')}")

            # Build Record
            timestamp = data.get("timestamp")
            
            # CurrencyLayer Free Tier is USD base
            base_currency = data.get("source", "USD") 
            
            rates_dict = data.get("quotes", {})
            # Quotes are like "USDGBP": 0.72. We need to strip the base.
            # CRITICAL: Cast all values to float to prevent type-versioned columns in DuckDB
            cleaned_rates = {k.replace(base_currency, ""): float(v) for k, v in rates_dict.items()}

            extraction_ts = datetime.now()
            rate_date = data.get("date", datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d') if timestamp else extraction_ts.strftime('%Y-%m-%d'))

            record = {
                "extraction_id": f"cl_{rate_date}_{base_currency}_{int(extraction_ts.timestamp())}",
                "extraction_timestamp": extraction_ts.isoformat(),
                "source": "currencylayer",
                "source_tier": "secondary", # Paid/Limited source
                "base_currency": base_currency,
                "rate_date": rate_date,
                "rates": cleaned_rates,
                "timestamp": timestamp,
                "api_response_raw": data,
                "http_status_code": response.status_code
            }
            yield record

        except Exception as e:
            logger.error(f"Failed to fetch from CurrencyLayer: {e}")
            raise

    return get_rates


@dlt.source(name="currencylayer")
def currencylayer_range_source(start_date: str, end_date: str):
    """
    dlt source factory for Historical Time Series (Range).
    Uses /timeframe endpoint (Requires Professional Plan).
    """
    api_key = os.getenv("CURRENCYLAYER_API_KEY")
    
    @dlt.resource(
        name="rates",
        write_disposition="append",
        primary_key="extraction_id"
    )
    def get_historical_range():
        config = load_config("apis.yaml")
        base_url = config['currencylayer']['base_url']
        endpoint = config['currencylayer']['endpoints']['timeframe']

        # Endpoint: /timeframe
        url = f"{base_url}{endpoint.format(api_key=api_key, start_date=start_date, end_date=end_date)}"
        
        try:
            logger.info(f"Fetching CurrencyLayer Timeframe: {start_date} to {end_date}")
            response = requests.get(url, timeout=30)

            # CRITICAL: Detect quota exhaustion BEFORE raising
            if response.status_code == 429:
                logger.error("CurrencyLayer returned 429 (rate limited)")
                quota_mgr = QuotaManager(endpoint_url=os.getenv("DYNAMODB_ENDPOINT", "http://localhost:8000"))
                quota_mgr.mark_api_throttled(api_source="currencylayer")
                raise RuntimeError("CurrencyLayer quota exhausted (HTTP 429), marked as throttled")

            response.raise_for_status()
            data = response.json()

            # Check for quota exhaustion in response body
            if not data.get("success"):
                error_info = data.get("error", {})
                error_code = error_info.get("code")

                # Error code 104: Monthly request volume reached
                if error_code == 104:
                    logger.error(f"CurrencyLayer quota exhausted (error code 104)")
                    quota_mgr = QuotaManager(endpoint_url=os.getenv("DYNAMODB_ENDPOINT", "http://localhost:8000"))
                    quota_mgr.mark_api_throttled(api_source="currencylayer")
                    raise RuntimeError("CurrencyLayer quota exhausted (error code 104), marked as throttled")

                raise RuntimeError(f"CurrencyLayer API Error {error_code}: {error_info.get('info')} - Note: Timeframe requires Professional Plan.")

            base_currency = data.get("source", "USD")
            quotes_by_date = data.get("quotes", {}) # Format: {"2021-01-01": {"USDGBP": ...}}

            # Flatten: Yield one record per day
            for date_key, rates_dict in quotes_by_date.items():
                # CRITICAL: Cast all values to float to prevent type-versioned columns
                cleaned_rates = {k.replace(base_currency, ""): float(v) for k, v in rates_dict.items()}
                extraction_ts = datetime.now()

                yield {
                    "extraction_id": f"cl_{date_key}_{base_currency}_{int(extraction_ts.timestamp())}",
                    "extraction_timestamp": extraction_ts.isoformat(),
                    "source": "currencylayer",
                    "source_tier": "secondary",
                    "base_currency": base_currency,
                    "rate_date": date_key,
                    "rates": cleaned_rates,
                    "api_response_raw": data,
                    "http_status_code": response.status_code
                }

        except Exception as e:
            logger.error(f"Failed to fetch CurrencyLayer range: {str(e)}")
            raise

    return get_historical_range

def run_currencylayer_pipeline(date: str = None):
    # Quota management boilerplate
    dynamodb_endpoint = os.getenv("DYNAMODB_ENDPOINT", "http://localhost:8000")
    quota_manager = QuotaManager(endpoint_url=dynamodb_endpoint)
    
    try:
        pipeline = dlt.pipeline(pipeline_name="currencylayer_to_bronze", destination="filesystem", dataset_name="currencylayer")
        run_info = pipeline.run(currencylayer_source(date=date), write_disposition="append")
        quota_manager.record_request("currencylayer", True)
        print(run_info)
    except Exception as e:
        quota_manager.record_request("currencylayer", False)
        raise

def run_currencylayer_backfill(start_date: str, end_date: str):
    logger.info(f"🚀 Starting CurrencyLayer Backfill: {start_date} to {end_date}")
    dynamodb_endpoint = os.getenv("DYNAMODB_ENDPOINT", "http://localhost:8000")
    quota_manager = QuotaManager(endpoint_url=dynamodb_endpoint)

    try:
        pipeline = dlt.pipeline(pipeline_name="currencylayer_backfill", destination="filesystem", dataset_name="currencylayer")
        info = pipeline.run(currencylayer_range_source(start_date, end_date), write_disposition="append")
        quota_manager.record_request("currencylayer", True)
        print(info)
        return info
    except Exception as e:
        quota_manager.record_request("currencylayer", False)
        logger.error(f"CurrencyLayer Backfill Failed: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="CurrencyLayer Ingestion Pipeline (Daily or Range)")
    parser.add_argument("--start-date", help="Backfill Start Date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="Backfill End Date (YYYY-MM-DD)")
    args = parser.parse_args()

    # Note: QuotaManager initialized inside functions to ensure correct scope/env usage

    if args.start_date and args.end_date:
        # Range/Backfill Mode
        run_currencylayer_backfill(args.start_date, args.end_date)
    else:
        # Daily Mode
        run_currencylayer_pipeline()

if __name__ == "__main__":
    main()
