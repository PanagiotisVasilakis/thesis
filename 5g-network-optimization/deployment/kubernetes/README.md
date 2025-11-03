# Kubernetes Deployment Guide

This folder contains Kubernetes manifests and tips for running the NEF emulator and ML service in a cluster. The `nef-emulator.yaml` and `ml-service.yaml` files provide Deployment and Service definitions for both components.

## Prerequisites

- Kubernetes cluster (e.g. minikube, kind or managed provider)
- Docker images for both services available in your registry
- `kubectl` configured to access your cluster

## Environment Variables

Both deployments rely on the variables listed in the [root README](../../../README.md#environment-variables).
Define them via `kubectl set env` or by editing the manifests before applying.

## 1. Build and Push Images

Build the Docker images and push them to a registry accessible by your cluster.
Refer to the [root README](../../../README.md#building-docker-images) for the exact commands.
Update `nef-emulator.yaml` and `ml-service.yaml` to point to your registry images.

## 2. Deploy the NEF Emulator

Apply the manifest containing both the Deployment and Service:

```bash
kubectl apply -f nef-emulator.yaml
```

The file sets environment variables such as `ML_HANDOVER_ENABLED`, `A3_HYSTERESIS_DB`
and `A3_TTT_S`. Edit it or use `kubectl set env` if you need to override them.

## 3. Deploy the ML Service

Apply the provided manifest:

```bash
kubectl apply -f ml-service.yaml
```

The manifest references the NEF emulator at `http://nef-emulator:8080`, so ensure the service name matches.

## 4. Verify

List running pods and services:

```bash
kubectl get pods
kubectl get services
```

Use port forwarding to access the services locally if needed:

```bash
kubectl port-forward svc/nef-emulator 8080:80
kubectl port-forward svc/ml-service 5050:5050
```

You can now send API requests to either service from your workstation.

## 5. Monitoring with Prometheus and Grafana

The `monitoring/` folder in the repository provides configuration for Prometheus and Grafana. Prometheus scrapes metrics from both services at their `/metrics` endpoints, as shown in `monitoring/prometheus/prometheus.yml`. Grafana connects to the Prometheus service and ships with a sample dashboard for the ML service.

To run the monitoring stack inside your cluster you can apply the `prometheus-grafana.yaml` manifest or create Deployments manually from these configurations. The same Docker Compose setup works for local testing. Make sure the scrape targets in `prometheus.yml` match the service names used in your manifests.

## Exposing Services

Both `ml-service` and `nef-emulator` are published as ClusterIP services by default. To access them from outside the cluster you can either create `NodePort` services or configure an Ingress controller:

```bash
# Example NodePort exposure
kubectl expose deployment ml-service --type=NodePort --port=5050
kubectl expose deployment nef-emulator --type=NodePort --port=8080
```

With an Ingress controller installed, update the manifests with ingress rules pointing at the corresponding services. This is the preferred approach in production environments.

## Multi-region Deployments
To run the system across several regions you can replicate the manifests
into separate Kubernetes clusters. Each cluster handles traffic for its
geographic region while sharing the same Docker images and configuration.

1. **Create a cluster per region** – provision a Kubernetes cluster in every
   target region (for example using managed services like GKE, EKS or AKS).
2. **Apply the manifests** – deploy `nef-emulator.yaml`, `ml-service.yaml`
   and `prometheus-grafana.yaml` to each cluster using the respective
   `kubectl` context.
3. **Global routing** – place a cloud load balancer or DNS layer in front of
   the regional clusters. Route users to the nearest region using geo DNS or
   latency-based rules.
4. **Synchronise models** – store trained models in a central registry
   (e.g. object storage or MLflow). The pods in each region pull the model on
   startup so predictions stay consistent.

With this setup you can scale the services closer to end users and achieve
redundancy if an entire region goes down.
