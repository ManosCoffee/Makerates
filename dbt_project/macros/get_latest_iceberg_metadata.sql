{% macro iceberg_table_exists(table_path) %}
    {#
       Checks if an Iceberg table exists by looking for metadata files.
       Returns true if metadata files exist, false otherwise.
    #}

    {% set query %}
        SELECT COUNT(*) as cnt
        FROM glob('{{ table_path }}/metadata/*.metadata.json')
    {% endset %}

    {% set result = run_query(query) %}

    {% if execute %}
        {% if result and result.rows and result.rows[0][0] > 0 %}
            {{ return(true) }}
        {% else %}
            {{ return(false) }}
        {% endif %}
    {% else %}
        {{ return(true) }}
    {% endif %}

{% endmacro %}

{% macro get_latest_iceberg_metadata(table_path) %}
    {#
       Finds the latest metadata JSON file for an Iceberg table.
       Workaround for DuckDB not supporting PyIceberg's random UUID filenames in version guessing.
       Returns NULL if table doesn't exist (graceful degradation).
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
            {{ return(none) }}
        {% endif %}
    {% else %}
        {{ return(table_path ~ '/metadata/placeholder.metadata.json') }}
    {% endif %}

{% endmacro %}
