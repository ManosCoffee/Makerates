
    
    

select
    extraction_id as unique_field,
    count(*) as n_records

from "silver"."main_silver"."fact_rates_validated"
where extraction_id is not null
group by extraction_id
having count(*) > 1


