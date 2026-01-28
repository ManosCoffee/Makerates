



select
    1
from "silver"."main_gold"."mart_data_quality_metrics"

where not(days_since_rate <= 2)

