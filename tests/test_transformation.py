"""
Tests for transformation layer

Verify Pydantic validation happens HERE (not in extraction).
"""

import pytest
from src.transformation.transformer import (
    BronzeToSilverTransformer,
    TransformationError,
)


class TestTransformationValidation:
    """Test that transformation layer DOES validate schemas"""

    def test_valid_schema_transforms_successfully(self, sample_extraction_result):
        """Verify valid schema is transformed correctly"""
        transformer = BronzeToSilverTransformer()
        rates = transformer.transform(sample_extraction_result)

        # Assert we got currency rates
        assert len(rates) > 0
        assert rates[0].base_currency == "USD"
        assert rates[0].target_currency in ["EUR", "GBP", "JPY", "CHF"]
        assert rates[0].exchange_rate > 0

    def test_invalid_schema_raises_error(self, invalid_extraction_result):
        """Verify invalid schema raises TransformationError (NOT extraction error)"""
        transformer = BronzeToSilverTransformer()

        with pytest.raises(TransformationError) as exc_info:
            transformer.transform(invalid_extraction_result)

        # Assert error mentions validation
        assert "validation" in str(exc_info.value).lower()

    def test_unpivot_creates_individual_rates(self, sample_extraction_result):
        """Verify transformation unpivots nested rates into individual records"""
        transformer = BronzeToSilverTransformer()
        rates = transformer.transform(sample_extraction_result)

        # Original response has 5 currencies (USD, EUR, GBP, JPY, CHF)
        # We transform ALL of them (including USD/USD = 1.0)
        assert len(rates) == 5

        # Check structure
        for rate in rates:
            assert rate.base_currency == "USD"
            assert len(rate.target_currency) == 3
            assert rate.exchange_rate > 0
            assert rate.source_name == "exchangerate-api"

    def test_currency_code_standardization(self, sample_extraction_result):
        """Verify currency codes are uppercase and 3 characters"""
        transformer = BronzeToSilverTransformer()
        rates = transformer.transform(sample_extraction_result)

        for rate in rates:
            assert rate.base_currency == rate.base_currency.upper()
            assert rate.target_currency == rate.target_currency.upper()
            assert len(rate.base_currency) == 3
            assert len(rate.target_currency) == 3


class TestFrankfurterTransformation:
    """Test Frankfurter-specific transformation"""

    def test_frankfurter_date_parsing(self, sample_extraction_result):
        """Verify Frankfurter date string is parsed to timestamp"""
        # Modify sample to be Frankfurter format
        sample_extraction_result.source_name = "frankfurter-ecb"
        sample_extraction_result.raw_response = {
            "amount": 1.0,
            "base": "USD",
            "date": "2024-01-24",
            "rates": {"EUR": 0.9234, "GBP": 0.7912},
        }

        transformer = BronzeToSilverTransformer()
        rates = transformer.transform(sample_extraction_result)

        # Assert timestamp was parsed from date string
        assert len(rates) == 2
        assert rates[0].rate_timestamp is not None
        assert rates[0].rate_timestamp.year == 2024
        assert rates[0].rate_timestamp.month == 1
        assert rates[0].rate_timestamp.day == 24
