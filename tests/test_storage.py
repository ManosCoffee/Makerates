"""
Tests for storage layer

Test both DuckDB and PostgreSQL (PostgreSQL tests skipped if DB not available).
"""

import pytest
import os
from pathlib import Path

from src.storage.duckdb_loader import DuckDBLoader
from src.transformation.transformer import BronzeToSilverTransformer


class TestDuckDBStorage:
    """Test DuckDB storage layer"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        """Setup and teardown test database"""
        self.test_db = "test_currency.duckdb"

        # Clean up before test
        if Path(self.test_db).exists():
            Path(self.test_db).unlink()

        yield

        # Clean up after test
        if Path(self.test_db).exists():
            Path(self.test_db).unlink()

    def test_schema_initialization(self):
        """Verify schema is created successfully"""
        loader = DuckDBLoader(self.test_db)

        # Query tables
        tables = loader.conn.execute("SHOW TABLES").fetchall()
        table_names = [t[0] for t in tables]

        assert "bronze_extraction" in table_names
        assert "silver_rates" in table_names

        # Query views
        views = loader.conn.execute(
            "SELECT name FROM duckdb_views() WHERE schema_name = 'main'"
        ).fetchall()
        view_names = [v[0] for v in views]

        assert "gold_latest_rates" in view_names

        loader.close()

    def test_bronze_layer_insert(self, sample_extraction_result):
        """Verify bronze layer stores extraction results"""
        loader = DuckDBLoader(self.test_db)

        # Insert bronze record
        loader.load_bronze(sample_extraction_result)

        # Query back
        result = loader.conn.execute(
            "SELECT source_name, http_status_code FROM bronze_extraction"
        ).fetchone()

        assert result[0] == "exchangerate-api"
        assert result[1] == 200

        loader.close()

    def test_silver_layer_insert(self, sample_extraction_result):
        """Verify silver layer stores transformed rates"""
        loader = DuckDBLoader(self.test_db)

        # Transform bronze to silver
        transformer = BronzeToSilverTransformer()
        rates = transformer.transform(sample_extraction_result)

        # Load to bronze first (foreign key requirement)
        loader.load_bronze(sample_extraction_result)

        # Load to silver
        loader.load_silver(rates)

        # Query back
        count = loader.conn.execute("SELECT COUNT(*) FROM silver_rates").fetchone()

        assert count[0] == len(rates)

        loader.close()

    def test_gold_view_latest_rates(self, sample_extraction_result):
        """Verify gold view returns only current rates"""
        loader = DuckDBLoader(self.test_db)

        # Load data
        transformer = BronzeToSilverTransformer()
        rates = transformer.transform(sample_extraction_result)
        loader.load_bronze(sample_extraction_result)
        loader.load_silver(rates)

        # Query gold view
        eur_rate = loader.get_latest_rate("USD", "EUR")

        assert eur_rate is not None
        assert eur_rate > 0

        loader.close()

    def test_scd_type_2_updates(self, sample_extraction_result):
        """Verify SCD Type 2 (slowly changing dimensions) works"""
        loader = DuckDBLoader(self.test_db)

        # Load first batch
        transformer = BronzeToSilverTransformer()
        rates = transformer.transform(sample_extraction_result)
        loader.load_bronze(sample_extraction_result)
        loader.load_silver(rates)

        # Modify rate and load second batch
        sample_extraction_result.raw_response["conversion_rates"]["EUR"] = 0.95
        sample_extraction_result.extraction_id = pytest.importorskip(
            "uuid"
        ).uuid4()  # New ID
        rates2 = transformer.transform(sample_extraction_result)
        loader.load_bronze(sample_extraction_result)
        loader.load_silver(rates2)

        # Query history - should have 2 EUR rates
        history = loader.get_rate_history("USD", "EUR", days=30)

        assert len(history) >= 2  # Old and new rate

        loader.close()


class TestPostgreSQLStorage:
    """Test PostgreSQL storage layer (skip if DB not available)"""

    @pytest.fixture(autouse=True)
    def check_postgres_available(self):
        """Skip tests if PostgreSQL not available"""
        try:
            from src.storage.postgres_loader import PostgresLoader

            loader = PostgresLoader()
            loader.init_schema()
            yield loader
        except Exception as e:
            pytest.skip(f"PostgreSQL not available: {e}")

    def test_postgres_schema_initialization(self, check_postgres_available):
        """Verify PostgreSQL schema is created"""
        loader = check_postgres_available

        with loader.get_connection() as conn:
            cursor = conn.cursor()

            # Check tables exist
            cursor.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                """
            )
            tables = [row[0] for row in cursor.fetchall()]

            assert "bronze_extraction" in tables
            assert "silver_rates" in tables

            cursor.close()

    def test_postgres_bronze_insert(
        self, check_postgres_available, sample_extraction_result
    ):
        """Verify PostgreSQL bronze layer insert"""
        loader = check_postgres_available

        loader.load_bronze(sample_extraction_result)

        # Query back
        with loader.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT source_name, http_status_code FROM bronze_extraction LIMIT 1"
            )
            result = cursor.fetchone()
            cursor.close()

        assert result[0] == "exchangerate-api"
        assert result[1] == 200
