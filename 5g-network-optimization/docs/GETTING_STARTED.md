# Getting Started

This guide explains how to set up the development environment and run the full workflow for the 5G Network Optimization project.

## Prerequisites

- **Python 3.8+** – required for the helper scripts and tests.
- **Docker** and **Docker Compose** – used to build and run the NEF emulator, ML service and monitoring stack.
- Optionally, [virtualenv](https://virtualenv.pypa.io/en/latest/) or a similar tool to manage Python packages locally.

## Environment Setup

1. Clone this repository and change into the project directory:
   ```bash
   git clone <repo-url>
   cd 5g-network-optimization
   ```
2. Install the Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
   This installs packages needed by the services and the helper scripts.

## Running the Services

Build and launch all containers with Docker Compose:
```bash
docker-compose up --build
```
The NEF emulator will start on `http://localhost:8080` and the ML service on `http://localhost:5050`.

## Collecting Training Data

After the services are running you can collect training data and train a model using the provided script:
```bash
python services/ml-service/collect_training_data.py --train
```
The script gathers radio metrics from the NEF emulator and sends them to the ML service, which trains a model once enough data is collected.

## Monitoring and User Interfaces

- **NEF Dashboard** – navigate to <http://localhost:8080/dashboard> to view the emulator's built-in UI.
- **Grafana** – dashboards with metrics are available at <http://localhost:3000> (default credentials are `admin`/`admin`).

With these steps you have a local environment capable of generating mobility events, collecting training data and visualizing metrics.
