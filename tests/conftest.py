"""
Pytest configuration and fixtures

Shared fixtures for testing extraction, transformation, and storage.
"""

import pytest
from datetime import datetime
from uuid import uuid4

from src.extraction.models import ExtractionResult, SourceTier, ExtractionMethod


@pytest.fixture
def sample_exchangerate_api_response():
    """Sample valid response from ExchangeRate-API"""
    return {
        "result": "success",
        "documentation": "https://www.exchangerate-api.com/docs",
        "terms_of_use": "https://www.exchangerate-api.com/terms",
        "time_last_update_unix": 1706104800,
        "time_last_update_utc": "Wed, 24 Jan 2024 14:00:00 +0000",
        "time_next_update_unix": 1706191200,
        "time_next_update_utc": "Thu, 25 Jan 2024 14:00:00 +0000",
        "base_code": "USD",
        "conversion_rates": {
            "USD": 1.0,
            "EUR": 0.9234,
            "GBP": 0.7912,
            "JPY": 149.32,
            "CHF": 0.8567,
        },
    }


@pytest.fixture
def sample_frankfurter_response():
    """Sample valid response from Frankfurter (ECB)"""
    return {
        "amount": 1.0,
        "base": "USD",
        "date": "2024-01-24",
        "rates": {
            "EUR": 0.9234,
            "GBP": 0.7912,
            "JPY": 149.32,
            "CHF": 0.8567,
        },
    }


@pytest.fixture
def sample_extraction_result(sample_exchangerate_api_response):
    """Sample ExtractionResult for testing transformation"""
    return ExtractionResult(
        extraction_id=uuid4(),
        source_name="exchangerate-api",
        source_tier=SourceTier.COMMERCIAL,
        extraction_timestamp=datetime.utcnow(),
        http_status_code=200,
        raw_response=sample_exchangerate_api_response,
        request_url="https://v6.exchangerate-api.com/v6/test_key/latest/USD",
        extraction_method=ExtractionMethod.SCHEDULED,
        extraction_duration_ms=245.3,
    )


@pytest.fixture
def invalid_extraction_result():
    """ExtractionResult with invalid schema (for testing validation)"""
    return ExtractionResult(
        extraction_id=uuid4(),
        source_name="exchangerate-api",
        source_tier=SourceTier.COMMERCIAL,
        extraction_timestamp=datetime.utcnow(),
        http_status_code=200,
        raw_response={
            "result": "success",
            "base_code": "USD",
            # Missing 'conversion_rates' - should fail validation
        },
        request_url="https://v6.exchangerate-api.com/v6/test_key/latest/USD",
        extraction_method=ExtractionMethod.SCHEDULED,
        extraction_duration_ms=100.0,
    )
