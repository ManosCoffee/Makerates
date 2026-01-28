



select
    1
from "analytics"."main_validation"."consensus_check"

where not(variance_pct > 0.005)

