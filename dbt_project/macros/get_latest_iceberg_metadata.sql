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
       1. Check environment variable (passed from Kestra via DynamoDB lookup)
       2. Fallback to glob() for S3 metadata discovery (existing logic)
       3. Return none if neither works (graceful degradation)

       Args:
         table_path: S3 path to Iceberg table root (for fallback glob)
         table_name: Table name for env var lookup (e.g., "frankfurter_rates")
    #}

    {# Build environment variable name from table_name #}
    {# frankfurter_rates → FRANKFURTER_METADATA_LOCATION #}
    {% set env_var_name = table_name | upper | replace('_RATES', '') ~ '_METADATA_LOCATION' %}

    {# Try to get metadata from environment variable first #}
    {% set metadata_from_env = env_var(env_var_name, '') %}

    {% if metadata_from_env != '' %}
        {# Success! Metadata passed via Kestra #}
        {{ log("✅ Using metadata from environment: " ~ metadata_from_env, info=True) }}
        {{ return(metadata_from_env) }}
    {% else %}
        {# Fallback to glob() method (existing logic) #}
        {{ log("⚠️  Environment variable " ~ env_var_name ~ " not set, falling back to glob()", info=True) }}

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
