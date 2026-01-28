---
name: enterprise-currency-governance-intelligence
description: 
    Advanced architectural framework for multi-currency data assets, focusing on high-availability, dual-path processing (Batch/Real-time), and ecosystem synergy with Celonis and Make.com.

    Use this skill when the organization or agent needs to 
    * **Architect Multi-Currency Support:** Design a system for expanding payment options beyond USD.
    * **Establish a "Financial Global Truth":** Create high-integrity sources for currency conversion and production verification.
    * **Implement High-Availability Pipelines:** Design failover and backup mechanisms for external data sources.
    * **Optimize Operational Costs:** Strategize between Real-Time and Batch processing based on TCO and precision needs.
    * **Integrate Ecosystems:** Connect data pipelines to **Make.com** for operational actions or **Celonis** for process mining and KPI normalization.
    * **Evaluate Market Data Sources:** Identify and vet institutional, regulatory, or commercial currency rate providers.
version: 1.0.0
---

# Agent Skill: Enterprise Currency Governance & Intelligence

## 1. Business Scoping: The "Triad of Needs"
This skill defines the currency pipeline not as a script, but as a **Mission-Critical Service** serving three distinct internal pillars:

1.  **The Analytics Team (Celonis):** High-integrity historical data for process mining and global KPI normalization.
2.  **The Finance Team (Audit):** A "Ground Truth" to verify that Production exchange rates are within a ±0.05% tolerance of market fixings.
3.  **The Product Team (Make.com):** Actionable, real-time data for automated workflows, dynamic pricing, and instant alerts.

---

## 2. Processing Paradigms: Real-Time vs. Batch
Selecting the frequency is a strategic trade-off between **Precision** and **Total Cost of Ownership (TCO)**.

| Feature | **Batch Processing (Daily/Hourly)** | **Real-Time / Streaming** |
| :--- | :--- | :--- |
| **Primary Tool** | Airflow / Snowflake / Celonis | Webhooks / Make.com / Kafka |
| **Use Case** | Financial Closing, Tax Reporting, Audit. | Dynamic Checkout, Fraud Detection. |
| **Pros** | Low cost, high consistency, easy to re-process. | Instant reaction to market volatility. |
| **Cons** | Data is "stale" by minutes/hours. | High API costs, complex state management. |

**Senior Recommendation:** Use **Batch** as the primary "Record of Truth" for auditing and **Real-time** only for high-value operational triggers. Implement a **Lambda Architecture** if the business requires concurrent paths.



---

## 3. Resilience & Failover Mechanism
To ensure "Ground Truth" reliability, this skill implements a **Tiered Circuit Breaker Strategy**.

### A. The Primary-Secondary Switch
The pipeline utilizes a **Primary Source** (e.g., Oanda for institutional grade) and a **Fallback Source** (e.g., Frankfurter/ECB for open-source redundancy).
-   **Logic:** If the Primary API returns a 4xx/5xx error or a "Stale Date" flag, the system automatically routes the request to the Fallback.
-   **Alerting:** Triggers a "Degraded Service" alert to the Data Ops team to initiate investigation.

### B. Data Validation "Gatekeepers"
Before any rate is persisted, it must pass three mandatory checkpoints:
1.  **Schema Check:** Detection of unannounced JSON structure changes.
2.  **Zero/Negative Check:** Absolute verification that rates are positive values.
3.  **Volatility Check (Z-Score):** If the rate deviates >15% from the 24-hour moving average, the "Circuit Breaker" trips, preventing erroneous data from corrupting financial reports.



---

## 4. Ecosystem Integration (Make.com & Celonis)

### Make.com: The Operational Edge
-   **Strategy:** Utilize Make.com strictly as the **Action Layer**, not the ETL layer.
-   **Implementation:** When the core Python pipeline detects a significant currency fluctuation (e.g., USD/EUR moves >2%), it pushes a webhook to **Make.com**.
-   **Action:** Make.com triggers automated updates to Slack channels or adjusts "Buffer Margins" in e-commerce stores (Shopify/Magento) to protect margins in real-time.

### Celonis: The Analytical Core
-   **Strategy:** Provide "Time-Travel" capability via **SCD Type 2 (Slowly Changing Dimensions)**.
-   **Implementation:** Storage of rates with `valid_from` and `valid_to` timestamps.
-   **Value:** Enables Celonis users to map historical invoices to the exact exchange rate valid at the specific minute of transaction, allowing for precise **Leakage Analysis** in global procurement.



---

## 5. Deployment & Organizational Communication
A senior leader prioritizes environment parity and stakeholder alignment over raw implementation.

* **Deployment:** Containerized via **Docker** for environment parity. Orchestrated via **Airflow** to manage complex dependencies (e.g., ensuring Source A success before Source B attempt).
* **Stakeholder Communication:** * **To Executives:** "We have mitigated the risk of currency volatility by implementing an automated failover system."
    * **To Analysts:** "You now have a single `DIM_CURRENCY` table in Snowflake that is the corporate 'Gold Standard'."
* **Success Metric:** "Zero manual intervention required during the next API provider outage."

---

## 6. Implementation Philosophy
By selecting an **ELT approach**, we prioritize the **Audit Trail** and data lineage. By using **Docker**, we ensure **Portability**. By integrating with **Make.com and Celonis**, we transform the Data Engineer from a "plumber" into a **strategic enabler** of global business growth.