# dbt Deployment Options: Docker vs Kestra Native CLI

## Overview

This document evaluates two approaches for running dbt in the Kestra pipeline:
1. **Current**: Dockerized dbt (via `makerates-ingestion-base` image)
2. **Alternative**: Kestra native dbt CLI plugin

## Option 1: Dockerized dbt (Current Implementation)

### How It Works
```yaml
- id: transform_silver
  type: io.kestra.plugin.docker.Run
  containerImage: makerates-ingestion-base:latest
  workingDir: /app/dbt_project
  commands:
    - bash -c "dbt run && dbt test"
```

### Pros
✅ **Environment Consistency**: Same image used for all tasks (extraction, transformation, sync)
✅ **Dependency Control**: dbt and all Python deps (DuckDB, httpfs) in one image
✅ **Version Pinning**: Explicit control over dbt version via `pyproject.toml`
✅ **Local Testing**: Can run exact same image locally with `docker run`
✅ **No Plugin Complexity**: Uses standard Docker plugin (well-tested, stable)
✅ **Python Integration**: dbt runs in same environment as custom scripts
✅ **Network Consistency**: Uses same `makerates-network` as other tasks

### Cons
❌ **Build Time**: Must rebuild image for dbt project changes
❌ **Image Size**: Larger image (~500MB) with all dependencies
❌ **No Native dbt UI**: Kestra doesn't render dbt artifacts (run results, docs)
❌ **Limited dbt Features**: Can't use Kestra's dbt-specific features (if any)

### Best For
- **MVP/POC**: Simple, proven approach with minimal moving parts
- **Integrated Pipelines**: dbt is part of larger Python-based workflow
- **Strict Environments**: Need exact dependency versions across dev/prod

---

## Option 2: Kestra Native dbt CLI Plugin

### How It Works
```yaml
- id: transform_silver
  type: io.kestra.plugin.dbt.cli.DbtCLI
  docker:
    image: ghcr.io/kestra-io/dbt-duckdb:latest
  profiles: |
    makerates:
      outputs:
        dev:
          type: duckdb
          path: '{{ workingDir }}/silver.duckdb'
  commands:
    - dbt run
    - dbt test
```

### Pros
✅ **Official Plugin**: Designed specifically for dbt in Kestra
✅ **No Custom Image**: Uses Kestra's pre-built dbt images
✅ **Faster Iteration**: Change dbt project without rebuilding Docker image
✅ **dbt Artifacts**: Potential for better UI integration (run results, lineage)
✅ **Simpler Config**: Less YAML for dbt-specific tasks

### Cons
❌ **DuckDB + S3 Complexity**: May need custom Dockerfile for `httpfs` extension
❌ **Network Configuration**: Unclear how to join `makerates-network` with plugin
❌ **Profile Management**: Need to manage `profiles.yml` in Kestra (not in repo)
❌ **Dependency Coordination**: dbt image might not match Python env versions
❌ **Less Control**: Kestra controls dbt version, update cadence
❌ **Debugging**: Harder to reproduce locally (Kestra-specific setup)

### Best For
- **Pure dbt Workflows**: Transformation-only pipelines (no custom Python)
- **Standard dbt**: Using common dbt adapters (Postgres, Snowflake, BigQuery)
- **Rapid Development**: Frequent dbt model changes without image rebuilds

---

## Comparison Matrix

| Factor | Dockerized (Current) | Kestra Native Plugin |
|--------|---------------------|----------------------|
| **Setup Complexity** | Medium (Dockerfile) | Low (use Kestra image) |
| **DuckDB + S3 Support** | ✅ Full control | ⚠️ May need custom image |
| **Network Integration** | ✅ Easy (`makerates-network`) | ⚠️ Unclear with plugin |
| **Local Testing** | ✅ Exact same Docker image | ❌ Need Kestra locally |
| **Iteration Speed** | ❌ Rebuild for dbt changes | ✅ Just update flow |
| **Version Control** | ✅ Everything in repo | ⚠️ Profiles in Kestra |
| **Observability** | ✅ Logs, custom tracking | ✅ Native dbt artifacts |
| **Python Integration** | ✅ Same env as scripts | ❌ Separate container |
| **Maintenance** | Medium (own image) | Low (Kestra maintains) |
| **MVP Speed** | ✅ Already working | ❌ Need to test/migrate |

---

## Recommendation for MVP/POC

### **Stick with Dockerized dbt (Current Approach)**

**Reasoning**:

1. **It's Already Working**: Current implementation is stable and tested. Migration introduces risk for uncertain gain.

2. **DuckDB + S3 is Non-Standard**: The `httpfs` extension and MinIO S3 configuration is custom. Kestra's dbt image may not support this out-of-the-box.

3. **Network Integration Proven**: Current setup correctly uses `makerates-network`. Plugin networking is untested.

4. **Simpler Debugging**: If something breaks, you can run the exact Docker image locally:
   ```bash
   docker run --rm --network makerates-network \
     makerates-ingestion-base:latest dbt_project
   ```

5. **Minimal Additional Overhead**: The dbt project is small (5 models, ~100 LOC). Rebuild time is negligible.

6. **Python Integration**: The pipeline uses custom Python scripts (`sync_to_dynamodb_simple.py`, `record_pipeline_event.py`). Keeping dbt in the same image simplifies the environment.

### When to Reconsider

**Consider migrating to Kestra native plugin if:**
- ✅ Kestra releases official DuckDB-S3 image
- ✅ dbt becomes the primary workload (not mixed with Python scripts)
- ✅ Need Kestra's dbt UI features (lineage graph, test results)
- ✅ Team expertise shifts to pure dbt (less Python)

---

## Hybrid Approach (Future)

For production scale, consider:

1. **Separation of Concerns**:
   - Bronze ingestion: Custom Docker image (Python + dlt)
   - Silver transformation: Kestra dbt plugin (pure SQL)
   - Gold sync: Custom Docker image (Python + boto3)

2. **Build Optimization**:
   - Multi-stage Dockerfile: Separate Python deps from dbt
   - Cache dbt packages layer separately
   - Use dbt artifacts for incremental builds

3. **dbt Cloud Integration** (if budget allows):
   - Kestra triggers dbt Cloud job
   - Best UI, observability, and testing
   - No Docker management

---

## Implementation Note

**No changes recommended for MVP.**

Current Kestra task works well:
```yaml
- id: transform_silver
  type: io.kestra.plugin.docker.Run
  containerImage: makerates-ingestion-base:latest
  pullPolicy: NEVER
  networkMode: makerates-network
  workingDir: /app/dbt_project
  env:
    MINIO_ENDPOINT: "minio:9000"
    MINIO_ROOT_USER: minioadmin
    MINIO_ROOT_PASSWORD: minioadmin123
  commands:
    - bash -c "dbt run && dbt test"
  timeout: PT10M
```

**Keep it simple. Optimize later.**

---

## References

- Kestra dbt Plugin: https://kestra.io/plugins/plugin-dbt
- dbt Docker Images: https://github.com/dbt-labs/dbt-core/pkgs/container/dbt-core
- DuckDB httpfs Extension: https://duckdb.org/docs/extensions/httpfs
