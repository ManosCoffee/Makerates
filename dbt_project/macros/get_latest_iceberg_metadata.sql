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

{% macro get_latest_iceberg_metadata(table_path, table_name) %}
    {#
       Finds the latest metadata JSON file for an Iceberg table.

       Strategy (in priority order):
       1. Check dbt variable (passed via --vars from Kestra)
       2. Check environment variable (passed via env from Kestra)
       3. Fallback to glob() for S3 metadata discovery (existing logic)
       4. Return none if nothing works (graceful degradation)

       Args:
         table_path: S3 path to Iceberg table root (for fallback glob)
         table_name: Table name for var lookup (e.g., "frankfurter_rates")
    #}

    {# Build variable name from table_name #}
    {# frankfurter_rates → frankfurter_metadata_location #}
    {% set var_name = table_name | replace('_rates', '_metadata_location') %}
    {% set env_var_name = table_name | upper | replace('_RATES', '') ~ '_METADATA_LOCATION' %}

    {# Try to get metadata from dbt variable first (--vars) #}
    {% set metadata_from_var = var(var_name, '') %}

    {% if metadata_from_var != '' %}
        {# Success! Metadata passed via dbt --vars #}
        {{ log("✅ Using metadata from dbt var '" ~ var_name ~ "': " ~ metadata_from_var, info=True) }}
        {{ return(metadata_from_var) }}
    {% endif %}

    {# Try environment variable second #}
    {% set metadata_from_env = env_var(env_var_name, '') %}

    {% if metadata_from_env != '' %}
        {# Success! Metadata passed via environment #}
        {{ log("✅ Using metadata from environment: " ~ metadata_from_env, info=True) }}
        {{ return(metadata_from_env) }}
    {% else %}
        {# Fallback to glob() method (existing logic) #}
        {{ log("⚠️  Variable '" ~ var_name ~ "' and env var '" ~ env_var_name ~ "' not set, falling back to glob()", info=True) }}

        {% set query %}
            SELECT file
            FROM glob('{{ table_path }}/metadata/*.metadata.json')
            ORDER BY file DESC
            LIMIT 1
        {% endset %}

        {% set result = run_query(query) %}

        {% if execute %}
            {% if result and result.rows %}
                {% set metadata_path = result.columns[0].values()[0] %}
                {{ log("✅ Found metadata via glob: " ~ metadata_path, info=True) }}
                {{ return(metadata_path) }}
            {% else %}
                {{ log("❌ No metadata found via glob for " ~ table_path, info=True) }}
                {{ return(none) }}
            {% endif %}
        {% else %}
            {# During parse phase, return placeholder #}
            {{ return(table_path ~ '/metadata/placeholder.metadata.json') }}
        {% endif %}
    {% endif %}

{% endmacro %}
