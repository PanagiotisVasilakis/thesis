# Monitoring Stack

This directory contains configuration for Prometheus and Grafana used during development. When `docker-compose` is started from the project root, these services collect metrics from the NEF emulator and the ML service.

## Prometheus

Prometheus scrapes the `/metrics` endpoint exposed by each service. The scrape targets are defined in `prometheus/prometheus.yml`:

```yaml
scrape_configs:
  - job_name: "ml_service"
    metrics_path: /metrics
    static_configs:
      - targets: ["ml-service:5050"]
  - job_name: "nef_emulator"
    metrics_path: /metrics
    static_configs:
      - targets: ["nef-emulator:8080"]
```

The configuration also includes a job for Prometheus itself. Adjust the targets if the service names or ports change.

The NEF emulator exposes counters like `nef_handover_decisions_total` and the
`nef_request_duration_seconds` histogram on this endpoint.

Start Prometheus with Docker Compose, or run the container manually and mount this directory at `/etc/prometheus`.

## Grafana

Grafana reads data from Prometheus and provides dashboards. The sample dashboard under `grafana/dashboards/ml_service.json` visualizes request latency, prediction counts and training statistics from the ML service. When Grafana is launched via Docker Compose it automatically picks up dashboards from `grafana/dashboards`.

Login with the default admin credentials (`admin` / `admin`) and add the Prometheus data source at `http://prometheus:9090` if it is not preconfigured. You can then import or customize dashboards to monitor additional metrics.

