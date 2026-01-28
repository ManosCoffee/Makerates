{% macro read_iceberg(table_name) %}
    {# 
       Reads an Iceberg table using DuckDB's iceberg_scan. 
       We use the Postgres Catalog connection details.
       Ideally, these are passed via env vars or profile, but for now we hardcode the known internal Docker DNS key 
       or rely on the 'iceberg_scan' being able to read the metadata location if we passed that.
       
       However, 'iceberg_scan' usually takes a path to a metadata JSON or a connection.
       
       Strategy: 
       Since we are using valid Iceberg tables on S3, we can point iceberg_scan to the METADATA JSON file.
       BUT finding the "latest" metadata.json is hard without a catalog.
       
       Better Strategy for DuckDB + Iceberg Catalog:
       We use the 'iceberg_scan' with the catalog connection if supported, OR we rely on the fact that
       compact_to_iceberg writes to `s3://silver-bucket/iceberg/<table_name>`.
       
       Actually, standard iceberg_scan needs a path.
       If we want to use the Catalog, we need the `iceberg` extension in DuckDB to support catalog checks, which is experimental.
       
       Robust Alternative used in Compaction:
       We are WRITING with PyIceberg.
       To READ in DBT (DuckDB), we might need to point to the `metadata/` folder and find the latest version?
       
       Wait! DuckDB's `iceberg_scan` can take a folder path and find the latest metadata if it follows standard layout?
       Let's try pointing to the table root: `s3://silver-bucket/iceberg/<table_name>`
    #}
    
    iceberg_scan('s3://{{ env_var("SILVER_BUCKET", "silver-bucket") }}/iceberg/{{ table_name }}', allow_moved_paths=true)

{% endmacro %}
