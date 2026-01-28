"""
Simple CLI entrypoint for QuotaManager
Outputs JSON with available APIs for Kestra to parse
"""

import os
import json
import sys
from utils.quota_manager import QuotaManager
from utils.logging_config import root_logger as logger
from utils.helpers import load_config


def main():
    # Get DynamoDB endpoint from env
    endpoint = os.getenv("DYNAMODB_ENDPOINT", "http://localhost:8000")

    # Default fail-open state
    available_apis = {api: True for api in load_config("apis.yaml").keys()}

    try:
        # Initialize quota manager
        manager = QuotaManager(endpoint_url=endpoint)

        # Get simplified statuses
        # returns dict: {'frankfurter': True, 'exchangerate': False, ...}
        real_stats = manager.get_all_api_statuses()

        # Log details for debugging
        stats = manager.get_usage_stats()
        for s in stats:
             logger.info(
                f"{s['api_source']}: {s['requests']}/{s['quota']} "
                f"({s['usage_pct']}%), remaining: {s['remaining']}, "
                f"status: {s['status']}"
            )

        print(f"::{{\"outputs\": {json.dumps(real_stats)} }}::")
        logger.info(f"Final Statuses: {real_stats}")
        sys.exit(0)

    except Exception as e:
        logger.error(f"Error checking quotas: {e}", exc_info=True)

        # Output fallback JSON (fail-open)
        logger.info(f"Fallback to: {available_apis}")
        print(f"::{{\"outputs\": {json.dumps(available_apis)} }}::")

        sys.exit(0)


if __name__ == "__main__":
    main()