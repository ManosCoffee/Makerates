
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

select
    extraction_id as unique_field,
    count(*) as n_records

from "silver"."main_silver"."stg_currencylayer"
where extraction_id is not null
group by extraction_id
having count(*) > 1



  
  
      
    ) dbt_internal_test