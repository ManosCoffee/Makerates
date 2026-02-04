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



### Prerequisites
- **OS**: macOS or Linux (cross-platform compatible)
- **Docker / Docker Desktop**
- **just** the *Rust* based command runner that overthrows complex Makefiles 
([Just start using it!](https://berkkaraal.com/blog/2024/12/06/just-start-using-it/)📖)
- **8GB RAM** 

### Technologies Included Out-Of-The-Box
***You don't have to worry about them :  the infrastructure is already packaged for you***

| Component | Technology | Description | Version |
| :--- | :--- | :--- | :--- |
| **Orchestration** | [Kestra](https://kestra.io) | Declarative Workflow orchestration & scheduling | `latest` |
| **Object Storage** | [MinIO](https://min.io) | S3-compatible object storage | `latest` |
| **Compute & Analytics storage** | [DuckDB](https://duckdb.org) | Analytical OLAP database with single-node processing | `>=1.0.0` |
| **Transformation** | [dbt](https://www.getdbt.com) | SQL-based transformations for Consensus Checks and Analytics tables | `1.8` (dbt-duckdb 1.10.0) |
| **Iceberg processing** | [PyIceberg](https://py.iceberg.apache.org/) | Python processing library for Apache Iceberg (Open table format) | `>=0.6.0` |
| **Cache & state management** | [DynamoDB Local](https://aws.amazon.com/dynamodb/) | AWS NoSQL database with lightning fast access | `latest` |
| **Catalog** | [PostgreSQL](https://www.postgresql.org) | Metadata catalog for Kestra & Iceberg | `15-alpine` |
| **Language** | [Python](https://www.python.org) | Core extraction & loading logic  | `>=3.12` |


## 🚀 Quick Start (2 Minutes)

### Preliminaries
- **API Keys**: Acquire API keys for free-tier accounts from **BOTH** commercial providers (ExchangeRate-API, CurrencyLayer - Frankfurter is free) 

  Follow the instructions : 📃[**API Keys Guide**](get-api-keys.md)
- **Ensure JUST is installed**: ```$ brew install just```🍎  or ```$ sudo apt install just```🐧

  ```bash
  just --version
  ```

That's it!


### Setup & Run
```bash
# 1. Spin-up local infrastructure and initialize  services (Wait...)
just init

# 2. Select-Menu appears : choose [1-7] or Esc and run pipeline manually
just 



just run

# 3. Open Kestra UI
just ui-kestra
# Login: admin@kestra.io / Kestra123
```

### Run the Pipeline
1. In Kestra UI, go to **Executions** → **Create Execution**.
2. Select **`makerates.rates_daily`**.
3. Click **Execute**.


![daily_flow](images/gifs/walkthrough_daily_flow.gif)


![backfill_flow](images/gifs/walkthrough_backfill_flow.gif)


![show_analytics_data_sample](images/gifs/menu_show_analytics.gif)

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
| :--- | :--- |
| **Core Connection** | |
| `just init` | **Start Here**: Initialize full stack & open interactive menu |
| `just run` | Spin up infrastructure (Docker + DynamoDB init) |
| `just stop-makerates` | Stop all running containers |
| `just reset` | **Hard Reset**: Wipe data, volumes & restart fresh |
| **Interfaces** | |
| `just menu` | Open the CLI interactive menu |
| `just open-daily-topology` | Open *Daily Rates* flow in Kestra UI |
| `just open-backfill-topology` | Open *Backfill* flow in Kestra UI |
| `just open-minio` | Open MinIO Console (S3 Browser) |
| `just open-dynamo` | Open DynamoDB Admin UI |
| **Data Inspection** | |
| `just duck-it` | Run SQL queries on Gold/Silver data (DuckDB) |
| **Maintenance** | |
| `just logs` | Tail Kestra server logs |
| `just restart-kestra` | Fast restart of Kestra service only |
| `just clean-iceberg` | Fix/Wipe Iceberg catalog state |

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
