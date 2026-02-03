# MakeRates - FX Currency Intelligence Service 

<img width="2400" height="1350" alt="Make-rates" src="https://github.com/user-attachments/assets/08b72999-5b88-46c3-8ea6-ad9af60ea4bc" />

  A versatile and scalable way to integrate currency exchange rates from trusted API's : 
   **Make** currency analytics easy!
---
A POC case study for Make.com

<div align="center">
  
  ![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
  ![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
  ![Kestra](https://img.shields.io/badge/Kestra-7F00FF?style=for-the-badge&logoColor=white)
  ![dbt](https://img.shields.io/badge/dbt-FF694B?style=for-the-badge&logo=dbt&logoColor=white)
  ![DuckDB](https://img.shields.io/badge/DuckDB-FFF000?style=for-the-badge&logo=duckdb&logoColor=black)
  ![MinIO](https://img.shields.io/badge/MinIO-C72E49?style=for-the-badge&logo=minio&logoColor=white)
  ![Amazon DynamoDB](https://img.shields.io/badge/Amazon%20DynamoDB-4053D6?style=for-the-badge&logo=amazondynamodb&logoColor=white)
  ![Apache Iceberg](https://img.shields.io/badge/Apache%20Iceberg-29B6F6?style=for-the-badge&logo=apacheiceberg&logoColor=white)
  ![Just](https://img.shields.io/badge/Just-121011?style=for-the-badge&logo=just&logoColor=white)
  ![uv](https://img.shields.io/badge/uv-DE5FE7?style=for-the-badge&logo=python&logoColor=white)

</div>

## 🚀 Quick Start (2 Minutes)

### Prerequisites
- **OS**: Linux or macOS (cross-platform compatible)
- **Docker & Docker Compose**
- **Python 3.12+** with `uv` (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **just** command runner (`cargo install just` or see [installation guide](https://github.com/casey/just#installation))
- **8GB RAM** recommended






### Setup & Run
```bash
# 1. Install dependencies (editable mode + dev tools)
uv pip install -e ".[dev]"

# 2. Start infrastructure (Docker + DynamoDB Init)
just run

# 3. Open Kestra UI
just ui-kestra
# Login: admin@kestra.io / Kestra123
```

### Run the Pipeline
1. In Kestra UI, go to **Executions** → **Create Execution**.
2. Select **`makerates.rates_daily`**.
3. Click **Execute**.


![gifff](images/gifs/walkthrough_daily_flow.gif)


![gifff](images/gifs/walkthrough_backfill_flow.gif)




### Inspect Results
```bash
# Check Analytics (Gold Layer)
just db-analytics
# Run SQL: SELECT * FROM mart_latest_rates;
```

---

## 🏗 Architecture

**ELT Data Flow**:
1. **Extract**: Fetch JSON from **Frankfurter** (ECB), **ExchangeRate-API**, **CurrencyLayer**.
2. **Load**: Store raw JSONL in **MinIO (Bronze)**.
3. **Compact**: Deduplicate into **Iceberg/Parquet (Silver)**.
4. **Transform**: **dbt** + **DuckDB** for validation & business logic (Gold).
5. **Sync**: Upsert validated rates to **DynamoDB** (Hot Tier).

**Validation Strategy**:
- **Consensus Check**: Flags deviation > 0.5% between sources.
- **Failover**: Auto-switches sources if quotas or APIs fail.

---

## 🛠 Useful Commands (Justfile)

| Command | Description |
|---------|-------------|
| `just run` | Start infrastructure |
| `just ui-kestra` | Open Kestra UI (localhost:8080) |
| `just ui-minio` | Open MinIO Console (localhost:9001) |
| `just db-analytics` | Open DuckDB CLI (Gold Layer) |
| `just db-validation` | Check flagged/rejected rates |
| `just logs` | View Kestra container logs |
| `just reload` | Rebuild worker & restart Kestra (Full Reload) |
| `just clean-start` | **Reset**: Delete volumes & rebuild |

---

## 📂 Documentation
- **[SCHEMA_GUIDE.md](SCHEMA_GUIDE.md)**: Detailed schema designs.
- **[DATA_INSPECTION_GUIDE.md](DATA_INSPECTION_GUIDE.md)**: Query recipes.
- **[OLD_README.md](OLD_README.md)**: Previous detailed documentation.

---

## 🔑 Configuration (.env)
Create a `.env` file (gitignored) with your API keys:
```ini
# API Keys (Get free keys from provider websites)
EXCHANGERATE_API_KEY=your_key_here
CURRENCYLAYER_API_KEY=your_key_here

# Local AWS/MinIO Config (Defaults provided in docker-compose)
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin123
```
