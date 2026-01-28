{% macro safe_read_json(pattern, fallback_pattern) %}
    {# 
        Safely reads JSON files. 
        If 'pattern' matches files, reads them.
        If 'pattern' matches NO files, reads 'fallback_pattern' (limit 1) with WHERE 1=0 
        to return empty result with correct inferred schema.
    #}
    
    {% set files_query %}
        SELECT count(*) FROM glob('{{ pattern }}')
    {% endset %}

    {% set results = run_query(files_query) %}
    
    {% if execute %}
        {% set file_count = results.columns[0].values()[0] %}
        
        {% if file_count > 0 %}
            -- Files found, read normal
            (SELECT * FROM read_json_auto('{{ pattern }}', format='newline_delimited'))
        {% else %}
            -- Main pattern empty, check fallback
            {% set fallback_query %}
                SELECT count(*) FROM glob('{{ fallback_pattern }}')
            {% endset %}
            {% set fallback_results = run_query(fallback_query) %}
            {% set fallback_count = fallback_results.columns[0].values()[0] %}
            
            {% if fallback_count > 0 %}
                -- Fallback found (history), infer schema but return 0 rows.
                (SELECT * FROM read_json_auto('{{ fallback_pattern }}', format='newline_delimited')
                WHERE 1=0)
            {% else %}
                -- TOTAL FAILURE: No files anywhere. Return dummy structure to prevent crash.
                -- Must include columns used in staging models: filename, http_status_code, source, rates__*
                (SELECT 
                    NULL::VARCHAR as filename, 
                    NULL::BIGINT as http_status_code, 
                    NULL::VARCHAR as source,
                    NULL::VARCHAR as base_currency,
                    NULL::VARCHAR as extraction_id,
                    NULL::VARCHAR as extraction_timestamp,
                    NULL::VARCHAR as rate_date,
                    NULL::DOUBLE as rates__EUR -- minimum dummy to satisfy UNPIVOT
                WHERE 1=0)
            {% endif %}
        {% endif %}
    {% else %}
        -- Compile time dummy
        (SELECT * FROM read_json_auto('{{ pattern }}', format='newline_delimited'))
    {% endif %}

{% endmacro %}
