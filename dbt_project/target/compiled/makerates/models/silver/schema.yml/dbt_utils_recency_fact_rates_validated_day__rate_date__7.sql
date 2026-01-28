






with recency as (

    select 

      
      
        max(rate_date) as most_recent

    from "silver"."main_silver"."fact_rates_validated"

    

)

select

    
    most_recent,
    cast(

    (now() + cast(-7 as bigint) * interval 1 day) as timestamp) as threshold

from recency
where most_recent < cast(

    (now() + cast(-7 as bigint) * interval 1 day) as timestamp)

