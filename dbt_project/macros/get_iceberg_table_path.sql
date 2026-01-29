{% macro get_iceberg_table_path(table_name) %}
    {#
       Constructs the full path to an Iceberg table.
       Uses dbt variables that can be passed from Kestra.

       Usage from Kestra:
       dbt build --vars '{"silver_bucket": "s3://silver-bucket", "iceberg_base_path": "iceberg"}'
    #}

    {% set silver_bucket = var('silver_bucket', 's3://silver-bucket') %}
    {% set iceberg_base_path = var('iceberg_base_path', 'iceberg') %}

    {{ return(silver_bucket ~ '/' ~ iceberg_base_path ~ '/' ~ table_name) }}

{% endmacro %}
