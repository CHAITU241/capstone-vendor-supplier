# VendorLens monitoring

VendorLens exposes Prometheus-compatible metrics from the FastAPI process and
can be scraped by a local Prometheus server. This is intentionally a small
demo setup: Prometheus runs as a user-level extracted binary, with no Docker,
Windows service, or administrator installation.

## Start the metrics endpoint

The Python client is included in `backend/requirements.txt`. After installing
the backend requirements and restarting FastAPI, check the endpoint:

```powershell
Invoke-WebRequest http://localhost:8000/metrics/ | Select-Object -ExpandProperty Content
```

The endpoint is mounted directly by the official Prometheus ASGI exposition
app. The application itself continues to run on port 8000.

## Run Prometheus locally

1. From the repository root, download the latest Windows binary into the
   ignored monitoring directory:

```powershell
.\monitoring\prometheus\download-prometheus.ps1
```

   The script uses the official Prometheus GitHub release and requires no
   administrator access. Alternatively, download the Windows
   `prometheus-*-windows-amd64.zip` archive from the [official Prometheus
   downloads page](https://prometheus.io/download/) and extract
   `prometheus.exe` into `monitoring/prometheus/`.
2. Start it:

```powershell
.\monitoring\prometheus\start-prometheus.ps1
```

Prometheus uses `prometheus.yml` in the same directory, stores its local data
under the ignored `data/` folder, and listens only on `127.0.0.1:9090`.
Open the Prometheus UI at <http://localhost:9090>.

## Useful demo queries

Paste these into the Prometheus expression box:

```promql
rate(vendorlens_http_requests_total[5m])
```

```promql
histogram_quantile(0.95, sum by (le) (rate(vendorlens_http_request_duration_seconds_bucket[5m])))
```

```promql
sum by (operation, status) (rate(vendorlens_ai_calls_total[5m]))
```

```promql
rate(vendorlens_ai_tokens_total[5m])
```

```promql
vendorlens_dependency_up
```

## Metrics included

- HTTP request count, status, latency, and in-progress requests.
- AI call count, success/error status, latency, operation, model, and tokens.
- Processing run outcomes and RAG found/not-found counts.
- Retrieved-chunk distribution and deterministic compliance statuses.
- Approved/rejected human decisions.
- PostgreSQL and ChromaDB availability gauges.

Labels use bounded values only. Supplier IDs, filenames, questions, document
contents, and PII are never placed in metric labels.
