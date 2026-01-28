



select
    1
from "silver"."main_silver"."fact_rates_validated"

where not((SELECT COUNT(DISTINCT target_currency) FROM fact_rates_validated WHERE rate_date = (SELECT MAX(rate_date) FROM fact_rates_validated)) >= 100)

