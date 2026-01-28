"""
Tests for PostgreSQL Star Schema Loader

Tests cover:
- Dimension table lookups and creation
- Fact table upserts (fact_rates_current)
- Fact table appends (fact_rates_history)
- Change detection (store only changes >0.01%)
- Materialized view refreshes
- Analytics queries
"""

import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from src.storage.postgres_star_loader import PostgresStarLoader
from src.extraction.models import ExtractionResult, ExtractionMethod, SourceTier
from src.transformation.schemas import CurrencyRate


# Skip tests if PostgreSQL is not available
pytest_plugins = []

try:
    import psycopg2
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False


@pytest.fixture
def loader():
    """Create PostgresStarLoader instance"""
    if not POSTGRES_AVAILABLE:
        pytest.skip("PostgreSQL not available")

    return PostgresStarLoader(
        host="localhost",
        port=5432,
        database="test_currency_rates",
        user="postgres",
        password="postgres",
    )


@pytest.fixture
def clean_database(loader):
    """Clean database before each test"""
    try:
        # Drop test database if exists
        import psycopg2
        temp_config = loader.config.copy()
        temp_config["database"] = "postgres"
        conn = psycopg2.connect(**temp_config)
        conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        cursor.execute(f"DROP DATABASE IF EXISTS {loader.config['database']}")
        cursor.close()
        conn.close()

        # Initialize fresh schema
        loader.init_schema()

    except Exception as e:
        pytest.skip(f"Could not initialize database: {e}")

    yield loader


@pytest.fixture
def sample_extraction_result():
    """Create sample extraction result"""
    return ExtractionResult(
        extraction_id=uuid4(),
        source_name="test-source",
        source_tier=SourceTier.PRIMARY,
        extraction_timestamp=datetime.now(),
        http_status_code=200,
        raw_response={
            "base_code": "USD",
            "conversion_rates": {
                "EUR": 0.92,
                "GBP": 0.79,
                "JPY": 149.50,
            }
        },
        request_url="https://test.com/api",
        extraction_method=ExtractionMethod.API_REQUEST,
        extraction_duration_ms=150.0,
    )


@pytest.fixture
def sample_currency_rates():
    """Create sample currency rates"""
    timestamp = datetime.now()
    extraction_id = uuid4()

    return [
        CurrencyRate(
            extraction_id=extraction_id,
            source_name="test-source",
            source_tier="primary",
            base_currency="USD",
            target_currency="EUR",
            exchange_rate=0.92,
            rate_timestamp=timestamp,
        ),
        CurrencyRate(
            extraction_id=extraction_id,
            source_name="test-source",
            source_tier="primary",
            base_currency="USD",
            target_currency="GBP",
            exchange_rate=0.79,
            rate_timestamp=timestamp,
        ),
        CurrencyRate(
            extraction_id=extraction_id,
            source_name="test-source",
            source_tier="primary",
            base_currency="USD",
            target_currency="JPY",
            exchange_rate=149.50,
            rate_timestamp=timestamp,
        ),
    ]


class TestDimensionTables:
    """Test dimension table operations"""

    def test_get_or_create_currency_key(self, clean_database):
        """Test currency dimension lookup and creation"""
        loader = clean_database

        with loader.get_connection() as conn:
            cursor = conn.cursor()

            # Create new currency
            key1 = loader._get_or_create_currency_key(cursor, "USD")
            assert key1 > 0

            # Get existing currency (should return same key)
            key2 = loader._get_or_create_currency_key(cursor, "USD")
            assert key1 == key2

            # Create different currency
            key3 = loader._get_or_create_currency_key(cursor, "EUR")
            assert key3 > 0
            assert key3 != key1

            cursor.close()

    def test_get_or_create_source_key(self, clean_database):
        """Test source dimension lookup and creation"""
        loader = clean_database

        with loader.get_connection() as conn:
            cursor = conn.cursor()

            # Create new source
            key1 = loader._get_or_create_source_key(cursor, "test-api", "primary")
            assert key1 > 0

            # Get existing source
            key2 = loader._get_or_create_source_key(cursor, "test-api", "primary")
            assert key1 == key2

            cursor.close()

    def test_get_or_create_date_key(self, clean_database):
        """Test date dimension lookup and creation"""
        loader = clean_database

        with loader.get_connection() as conn:
            cursor = conn.cursor()

            # Test date
            test_date = datetime(2024, 1, 15, 10, 30, 0)
            expected_key = 20240115

            # Get or create date key
            key1 = loader._get_or_create_date_key(cursor, test_date)
            assert key1 == expected_key

            # Get existing (should return same)
            key2 = loader._get_or_create_date_key(cursor, test_date)
            assert key1 == key2

            cursor.close()


class TestFactTables:
    """Test fact table operations"""

    def test_load_to_fact_rates_current(self, clean_database, sample_currency_rates):
        """Test loading to fact_rates_current (OLTP table)"""
        loader = clean_database

        # Load rates
        loader.load_silver(sample_currency_rates)

        # Verify records inserted
        with loader.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM fact_rates_current")
            count = cursor.fetchone()[0]
            assert count == 3  # USD to EUR, GBP, JPY
            cursor.close()

    def test_upsert_to_fact_rates_current(self, clean_database):
        """Test UPDATE behavior in fact_rates_current"""
        loader = clean_database
        timestamp1 = datetime.now()
        extraction_id = uuid4()

        # Initial load
        initial_rates = [
            CurrencyRate(
                extraction_id=extraction_id,
                source_name="test-source",
                source_tier="primary",
                base_currency="USD",
                target_currency="EUR",
                exchange_rate=0.92,
                rate_timestamp=timestamp1,
            )
        ]
        loader.load_silver(initial_rates)

        # Update with new rate (significant change)
        timestamp2 = timestamp1 + timedelta(hours=4)
        updated_rates = [
            CurrencyRate(
                extraction_id=uuid4(),
                source_name="test-source",
                source_tier="primary",
                base_currency="USD",
                target_currency="EUR",
                exchange_rate=0.94,  # Changed by >0.01%
                rate_timestamp=timestamp2,
            )
        ]
        loader.load_silver(updated_rates)

        # Verify only 1 record in current (updated in place)
        with loader.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM fact_rates_current")
            assert cursor.fetchone()[0] == 1

            # Verify rate was updated
            cursor.execute(
                "SELECT exchange_rate, previous_rate FROM fact_rates_current WHERE rate_key = 1"
            )
            result = cursor.fetchone()
            assert float(result[0]) == 0.94  # New rate
            assert float(result[1]) == 0.92  # Previous rate stored

            cursor.close()

    def test_append_to_fact_rates_history(self, clean_database):
        """Test APPEND behavior in fact_rates_history (OLAP table)"""
        loader = clean_database
        timestamp1 = datetime.now()
        extraction_id = uuid4()

        # Load 1: Initial rate
        rates1 = [
            CurrencyRate(
                extraction_id=extraction_id,
                source_name="test-source",
                source_tier="primary",
                base_currency="USD",
                target_currency="EUR",
                exchange_rate=0.92,
                rate_timestamp=timestamp1,
            )
        ]
        loader.load_silver(rates1)

        # Load 2: Updated rate (significant change)
        timestamp2 = timestamp1 + timedelta(hours=4)
        rates2 = [
            CurrencyRate(
                extraction_id=uuid4(),
                source_name="test-source",
                source_tier="primary",
                base_currency="USD",
                target_currency="EUR",
                exchange_rate=0.94,
                rate_timestamp=timestamp2,
            )
        ]
        loader.load_silver(rates2)

        # Verify 2 records in history (append-only)
        with loader.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM fact_rates_history")
            assert cursor.fetchone()[0] == 2  # Both rates stored
            cursor.close()


class TestChangeDetection:
    """Test 'store only changes' optimization"""

    def test_should_store_significant_change(self, clean_database):
        """Test that significant rate changes are stored"""
        loader = clean_database
        extraction_id = uuid4()
        timestamp = datetime.now()

        # Initial rate: 0.92
        initial_rates = [
            CurrencyRate(
                extraction_id=extraction_id,
                source_name="test-source",
                source_tier="primary",
                base_currency="USD",
                target_currency="EUR",
                exchange_rate=0.92,
                rate_timestamp=timestamp,
            )
        ]
        loader.load_silver(initial_rates)

        # New rate: 0.94 (2.17% change - SIGNIFICANT)
        new_timestamp = timestamp + timedelta(hours=4)
        new_rates = [
            CurrencyRate(
                extraction_id=uuid4(),
                source_name="test-source",
                source_tier="primary",
                base_currency="USD",
                target_currency="EUR",
                exchange_rate=0.94,
                rate_timestamp=new_timestamp,
            )
        ]
        loader.load_silver(new_rates)

        # Verify both rates in history (change stored)
        with loader.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM fact_rates_history")
            assert cursor.fetchone()[0] == 2
            cursor.close()

    def test_should_skip_insignificant_change(self, clean_database):
        """Test that insignificant rate changes are skipped"""
        loader = clean_database
        extraction_id = uuid4()
        timestamp = datetime.now()

        # Initial rate: 0.920000
        initial_rates = [
            CurrencyRate(
                extraction_id=extraction_id,
                source_name="test-source",
                source_tier="primary",
                base_currency="USD",
                target_currency="EUR",
                exchange_rate=0.920000,
                rate_timestamp=timestamp,
            )
        ]
        loader.load_silver(initial_rates)

        # New rate: 0.920005 (0.0005% change - INSIGNIFICANT, < 0.01%)
        new_timestamp = timestamp + timedelta(hours=4)
        insignificant_rates = [
            CurrencyRate(
                extraction_id=uuid4(),
                source_name="test-source",
                source_tier="primary",
                base_currency="USD",
                target_currency="EUR",
                exchange_rate=0.920005,
                rate_timestamp=new_timestamp,
            )
        ]
        loader.load_silver(insignificant_rates)

        # Verify only 1 rate in history (change skipped)
        with loader.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM fact_rates_history")
            assert cursor.fetchone()[0] == 1  # Only initial rate
            cursor.close()

    def test_change_detection_reduction(self, clean_database):
        """Test that change detection reduces storage by ~90%"""
        loader = clean_database
        extraction_id = uuid4()
        timestamp = datetime.now()

        # Load 10 rates with minimal changes
        rates = []
        for i in range(10):
            rates.append(
                CurrencyRate(
                    extraction_id=extraction_id,
                    source_name="test-source",
                    source_tier="primary",
                    base_currency="USD",
                    target_currency="EUR",
                    exchange_rate=0.9200 + (i * 0.000001),  # Tiny changes
                    rate_timestamp=timestamp + timedelta(hours=i * 4),
                )
            )

        # Load all rates
        for rate_batch in [rates[i:i+1] for i in range(len(rates))]:
            loader.load_silver(rate_batch)

        # Verify storage reduction
        with loader.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM fact_rates_history")
            history_count = cursor.fetchone()[0]

            # Should store only 1 (initial) because all changes are insignificant
            assert history_count == 1
            reduction_pct = ((10 - history_count) / 10) * 100
            assert reduction_pct >= 80  # At least 80% reduction

            cursor.close()


class TestMaterializedViews:
    """Test materialized view operations"""

    def test_refresh_materialized_views(self, clean_database, sample_currency_rates):
        """Test refreshing materialized views"""
        loader = clean_database

        # Load data
        loader.load_silver(sample_currency_rates)

        # Refresh views
        loader.refresh_materialized_views()

        # Verify vw_rates_latest has data
        with loader.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM vw_rates_latest")
            count = cursor.fetchone()[0]
            assert count == 3  # USD to EUR, GBP, JPY
            cursor.close()

    def test_vw_rates_daily_agg_query(self, clean_database):
        """Test daily aggregation materialized view"""
        loader = clean_database
        timestamp = datetime(2024, 1, 15, 10, 0, 0)

        # Load multiple rates for same day
        rates = [
            CurrencyRate(
                extraction_id=uuid4(),
                source_name="test-source",
                source_tier="primary",
                base_currency="USD",
                target_currency="EUR",
                exchange_rate=0.92,
                rate_timestamp=timestamp,
            ),
            CurrencyRate(
                extraction_id=uuid4(),
                source_name="test-source",
                source_tier="primary",
                base_currency="USD",
                target_currency="EUR",
                exchange_rate=0.94,  # Different rate (significant change)
                rate_timestamp=timestamp + timedelta(hours=4),
            ),
        ]

        for rate_batch in [rates[i:i+1] for i in range(len(rates))]:
            loader.load_silver(rate_batch)

        # Refresh views
        loader.refresh_materialized_views()

        # Query daily aggregates
        with loader.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT avg_rate, min_rate, max_rate, sample_count
                FROM vw_rates_daily_agg
                WHERE base_currency = 'USD'
                    AND target_currency = 'EUR'
                    AND date = '2024-01-15'
            """)
            result = cursor.fetchone()

            assert result is not None
            avg_rate, min_rate, max_rate, sample_count = result
            assert float(min_rate) == 0.92
            assert float(max_rate) == 0.94
            assert sample_count == 2

            cursor.close()


class TestAnalyticsQueries:
    """Test analytics query methods"""

    def test_get_latest_rate(self, clean_database, sample_currency_rates):
        """Test getting latest rate for a currency pair"""
        loader = clean_database

        # Load rates
        loader.load_silver(sample_currency_rates)
        loader.refresh_materialized_views()

        # Get latest rate
        rate = loader.get_latest_rate("USD", "EUR")
        assert rate == 0.92

    def test_get_daily_aggregates(self, clean_database):
        """Test getting daily aggregated rates"""
        loader = clean_database
        timestamp = datetime(2024, 1, 15, 10, 0, 0)

        # Load rates over 3 days
        rates = []
        for day in range(3):
            for hour in [0, 8, 16]:
                rates.append(
                    CurrencyRate(
                        extraction_id=uuid4(),
                        source_name="test-source",
                        source_tier="primary",
                        base_currency="USD",
                        target_currency="EUR",
                        exchange_rate=0.92 + (day * 0.01) + (hour * 0.001),
                        rate_timestamp=timestamp + timedelta(days=day, hours=hour),
                    )
                )

        # Load sequentially to trigger change detection
        for rate in rates:
            loader.load_silver([rate])

        loader.refresh_materialized_views()

        # Get daily aggregates
        start_date = datetime(2024, 1, 15)
        end_date = datetime(2024, 1, 17)
        aggregates = loader.get_daily_aggregates("USD", "EUR", start_date, end_date)

        assert len(aggregates) >= 1  # At least one day has aggregates
        for agg in aggregates:
            assert "date" in agg
            assert "avg_rate" in agg
            assert "min_rate" in agg
            assert "max_rate" in agg


class TestPartitioning:
    """Test table partitioning"""

    def test_rates_inserted_into_correct_partition(self, clean_database):
        """Test that rates are inserted into correct monthly partition"""
        loader = clean_database

        # Rate for January 2024
        jan_rate = CurrencyRate(
            extraction_id=uuid4(),
            source_name="test-source",
            source_tier="primary",
            base_currency="USD",
            target_currency="EUR",
            exchange_rate=0.92,
            rate_timestamp=datetime(2024, 1, 15, 10, 0, 0),
        )
        loader.load_silver([jan_rate])

        # Verify inserted into fact_rates_history_2024_01 partition
        with loader.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM fact_rates_history_2024_01
            """)
            count = cursor.fetchone()[0]
            assert count == 1
            cursor.close()


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
