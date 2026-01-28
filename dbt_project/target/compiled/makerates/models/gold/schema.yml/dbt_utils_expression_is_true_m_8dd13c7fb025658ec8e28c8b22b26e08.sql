



select
    1
from "silver"."main_gold"."mart_data_quality_metrics"

where not(currency_count >= 100)

