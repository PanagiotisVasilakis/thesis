# Kubernetes Deployment Guide

This folder contains Kubernetes manifests and tips for running the NEF emulator and ML service in a cluster. The `ml-service.yaml` file provides a Deployment and Service for the ML component. A similar configuration can be created for the NEF emulator.

## Prerequisites

- Kubernetes cluster (e.g. minikube, kind or managed provider)
- Docker images for both services available in your registry
- `kubectl` configured to access your cluster

## Environment Variables

Both deployments rely on the variables listed in the [root README](../../README.md#environment-variables).
Define them via `kubectl set env` or by editing the manifests before applying.

## 1. Build and Push Images

Build the Docker images and push them to a registry accessible by your cluster.
Refer to the [root README](../../README.md#building-docker-images) for the exact commands.
Update `ml-service.yaml` and any NEF emulator manifest to use the registry image paths.

## 2. Deploy the NEF Emulator

Create a Deployment and Service for the NEF emulator. A minimal example:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nef-emulator
spec:
  replicas: 1
  selector:
    matchLabels:
      app: nef-emulator
  template:
    metadata:
      labels:
        app: nef-emulator
    spec:
      containers:
      - name: nef-emulator
        image: <registry>/nef-emulator:latest
        ports:
        - containerPort: 8080
```

Expose the deployment as a service:

```bash
kubectl expose deployment nef-emulator --port 8080 --target-port 8080
```

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

To run the monitoring stack inside your cluster you can create Deployments using these configurations or reuse the existing Docker Compose setup for local testing. Make sure the scrape targets in `prometheus.yml` match the service names used in your manifests.

## Exposing Services

Both `ml-service` and `nef-emulator` are published as ClusterIP services by default. To access them from outside the cluster you can either create `NodePort` services or configure an Ingress controller:

```bash
# Example NodePort exposure
kubectl expose deployment ml-service --type=NodePort --port=5050
kubectl expose deployment nef-emulator --type=NodePort --port=8080
```

With an Ingress controller installed, update the manifests with ingress rules pointing at the corresponding services. This is the preferred approach in production environments.
