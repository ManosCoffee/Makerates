{% macro get_latest_iceberg_metadata(table_path) %}
    {# 
       Finds the latest metadata JSON file for an Iceberg table.
       Workaround for DuckDB not supporting PyIceberg's random UUID filenames in version guessing.
    #}
    
    {% set query %}
        SELECT file
        FROM glob('{{ table_path }}/metadata/*.metadata.json')
        ORDER BY file DESC
        LIMIT 1
    {% endset %}

    {% set result = run_query(query) %}
    
    {% if execute %}
        {% if result and result.rows %}
            {{ return(result.columns[0].values()[0]) }}
        {% else %}
            {{ exceptions.raise_compiler_error("No metadata file found at " ~ table_path) }}
        {% endif %}
    {% else %}
        {{ return(table_path ~ '/metadata/placeholder.metadata.json') }}
    {% endif %}

{% endmacro %}
