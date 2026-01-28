



select
    1
from "silver"."main_gold"."mart_data_quality_metrics"

where not(ok_rate >= 0.90)

