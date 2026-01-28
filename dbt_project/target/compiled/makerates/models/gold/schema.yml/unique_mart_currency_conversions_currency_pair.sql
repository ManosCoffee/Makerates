
    
    

select
    currency_pair as unique_field,
    count(*) as n_records

from "silver"."main_gold"."mart_currency_conversions"
where currency_pair is not null
group by currency_pair
having count(*) > 1


