
    
    

with all_values as (

    select
        pipeline_status as value_field,
        count(*) as n_records

    from "silver"."main_gold"."mart_data_quality_metrics"
    group by pipeline_status

)

select *
from all_values
where value_field not in (
    'HEALTHY','WARNING','DEGRADED','STALE'
)


