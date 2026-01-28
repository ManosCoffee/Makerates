



select
    1
from "silver"."main_silver"."consensus_check"

where not(variance_pct > 0.005)

