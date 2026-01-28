"""
Tests for extraction layer

Verify ELT pattern: extraction stores raw JSON without validation.
"""

import pytest
import responses
from src.extraction.exchangerate_api import ExchangeRateAPIExtractor
from src.extraction.frankfurter import FrankfurterExtractor
from src.extraction.orchestrator import ExtractionOrchestrator


class TestExtractionMinimalValidation:
    """Test that extraction layer does NOT validate schemas"""

    @responses.activate
    def test_extraction_stores_valid_json(self, sample_exchangerate_api_response):
        """Verify extraction stores valid JSON without schema validation"""
        # Mock API response
        responses.add(
            responses.GET,
            "https://v6.exchangerate-api.com/v6/test_key/latest/USD",
            json=sample_exchangerate_api_response,
            status=200,
        )

        extractor = ExchangeRateAPIExtractor(api_key="test_key")
        result = extractor.extract(base_currency="USD")

        # Assert extraction succeeded
        assert result.http_status_code == 200
        assert result.error_message is None
        assert result.raw_response == sample_exchangerate_api_response
        assert "conversion_rates" in result.raw_response

    @responses.activate
    def test_extraction_stores_unexpected_schema(self):
        """Verify extraction stores JSON even if schema is unexpected (TRUE ELT)"""
        # Mock response with UNEXPECTED schema (missing fields)
        unexpected_response = {
            "result": "success",
            "base_code": "USD",
            "weird_field": "this_is_not_in_our_schema",
            # Missing 'conversion_rates' - extraction should still store it
        }

        responses.add(
            responses.GET,
            "https://v6.exchangerate-api.com/v6/test_key/latest/USD",
            json=unexpected_response,
            status=200,
        )

        extractor = ExchangeRateAPIExtractor(api_key="test_key")
        result = extractor.extract(base_currency="USD")

        # Assert extraction succeeded even with unexpected schema
        assert result.http_status_code == 200
        assert result.error_message is None
        assert result.raw_response == unexpected_response
        assert "weird_field" in result.raw_response

    @responses.activate
    def test_extraction_handles_http_error(self):
        """Verify extraction returns error result (not exception) on HTTP error"""
        responses.add(
            responses.GET,
            "https://v6.exchangerate-api.com/v6/test_key/latest/USD",
            json={"error": "Invalid API key"},
            status=403,
        )

        extractor = ExchangeRateAPIExtractor(api_key="test_key")
        result = extractor.extract(base_currency="USD")

        # Assert error is captured in result
        assert result.http_status_code == 403
        assert result.error_message is not None
        assert "403" in result.error_message


class TestFailoverOrchestration:
    """Test primary/fallback orchestration"""

    @responses.activate
    def test_failover_to_ecb_on_primary_failure(self, sample_frankfurter_response):
        """Verify orchestrator uses fallback when primary fails"""
        # Mock primary to fail
        responses.add(
            responses.GET,
            "https://v6.exchangerate-api.com/v6/test_key/latest/USD",
            json={"error": "Service unavailable"},
            status=503,
        )

        # Mock fallback to succeed
        responses.add(
            responses.GET,
            "https://api.frankfurter.app/latest",
            json=sample_frankfurter_response,
            status=200,
        )

        primary = ExchangeRateAPIExtractor(api_key="test_key")
        fallback = FrankfurterExtractor()
        orchestrator = ExtractionOrchestrator(primary, fallback, enable_failover=True)

        results = orchestrator.extract(base_currency="USD")

        # Assert we got 2 results (primary failure + fallback success)
        assert len(results) == 2
        assert results[0].error_message is not None  # Primary failed
        assert results[1].http_status_code == 200  # Fallback succeeded

    @responses.activate
    def test_no_failover_when_disabled(self):
        """Verify orchestrator doesn't use fallback when failover disabled"""
        # Mock primary to fail
        responses.add(
            responses.GET,
            "https://v6.exchangerate-api.com/v6/test_key/latest/USD",
            json={"error": "Service unavailable"},
            status=503,
        )

        primary = ExchangeRateAPIExtractor(api_key="test_key")
        fallback = FrankfurterExtractor()
        orchestrator = ExtractionOrchestrator(primary, fallback, enable_failover=False)

        results = orchestrator.extract(base_currency="USD")

        # Assert we only got 1 result (primary failure, no fallback)
        assert len(results) == 1
        assert results[0].error_message is not None
