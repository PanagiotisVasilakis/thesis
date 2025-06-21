# Kubernetes Deployment Guide

This folder contains Kubernetes manifests and tips for running the NEF emulator and ML service in a cluster. The `ml-service.yaml` file provides a Deployment and Service for the ML component. A similar configuration can be created for the NEF emulator.

## Prerequisites

- Kubernetes cluster (e.g. minikube, kind or managed provider)
- Docker images for both services available in your registry
- `kubectl` configured to access your cluster

## 1. Build and Push Images

From the repository root build the images and push them to a registry accessible by your cluster:

```bash
# Build NEF emulator image
docker build -t <registry>/nef-emulator:latest -f services/nef-emulator/backend/Dockerfile.backend services/nef-emulator
# Build ML service image
docker build -t <registry>/ml-service:latest services/ml-service
# Push images
docker push <registry>/nef-emulator:latest
docker push <registry>/ml-service:latest
```

Update `ml-service.yaml` to use the registry paths. Edit the `image` field under
`spec.template.spec.containers` so the Deployment pulls your pushed image.

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

The ML service exposes port 5050 inside the cluster. Use port forwarding to access it locally if needed:

```bash
kubectl port-forward svc/ml-service 5050:5050
```

You can now send API requests to the ML service while it communicates with the NEF emulator in your cluster.

