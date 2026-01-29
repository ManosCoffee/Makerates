"""
Initialize Iceberg Catalog to prevent race conditions in parallel jobs.
Run this before parallel Iceberg loader tasks.
"""
import os
import sys
from pyiceberg.catalog import load_catalog
from utils.logging_config import root_logger as logger


def main():
    """Initialize Iceberg catalog and namespace."""
    catalog_name = os.environ.get("ICEBERG_CATALOG", "default")
    namespace = os.environ.get("ICEBERG_NAMESPACE", "default")

    logger.info(f"Initializing Iceberg catalog: {catalog_name}")

    try:
        catalog = load_catalog(catalog_name)
        logger.info(f"Catalog '{catalog_name}' loaded")

        # Create namespace if it doesn't exist
        try:
            catalog.create_namespace(namespace)
            logger.info(f"Namespace '{namespace}' created")
        except Exception as e:
            if "already exists" in str(e).lower() or "alreadyexists" in str(e).lower():
                logger.info(f"Namespace '{namespace}' already exists")
            else:
                logger.info(f"Namespace creation: {e}")

        logger.info("Iceberg catalog initialization complete")
        return 0

    except Exception as e:
        logger.error(f"Failed to initialize catalog: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
