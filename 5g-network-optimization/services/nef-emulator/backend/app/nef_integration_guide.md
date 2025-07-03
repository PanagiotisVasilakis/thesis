# Integrating 3GPP Mobility Models with NEF Emulator

## Overview

This guide explains how to use our 3GPP-compliant mobility models with the existing NEF emulator without modifying its code.

### Available Mobility Models
- Linear and L-shaped paths
- Random Waypoint and Random Directional movement
- Manhattan Grid and Urban Grid models
- Reference Point Group mobility

## Step 1: Generate Path Points

Use our mobility models to generate path points in the NEF-compatible format:

```python
from mobility_models.nef_adapter import generate_nef_path_points, save_path_to_json

# Generate a linear path
params = {
    'ue_id': 'test_ue_1',
    'start_position': (0, 0, 0),
    'end_position': (1000, 500, 0),
    'speed': 5.0,
    'duration': 250,
    'time_step': 1.0
}

points = generate_nef_path_points('linear', **params)
json_file = save_path_to_json(points, 'my_path.json')
```

## Step 2: Import the Path into NEF Emulator

You can use the generated JSON file with the NEF emulator API:

1. Login to the NEF emulator to get an access token
2. Create a new path using the NEF API:

```bash
# Example using curl to create a path
curl -X POST "http://localhost:8080/api/v1/paths/" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d @linear_path.json
```

3. Associate the path with a UE in the NEF emulator
4. Start UE movement using the existing API

## Integration in Python Script

```python
import requests
import json

# 1. Login to get token
login_url = "http://localhost:8080/api/v1/login/access-token"
login_data = {
    "username": "your_username",
    "password": "your_password"
}
response = requests.post(login_url, data=login_data)
token = response.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# 2. Create path
with open('linear_path.json', 'r') as f:
    path_data = json.load(f)
    
path_url = "http://localhost:8080/api/v1/paths/"
path_response = requests.post(path_url, json=path_data, headers=headers)
path_id = path_response.json()["id"]
print(f"Created path with ID: {path_id}")

# 3. Update UE to use the path
ue_id = "your_ue_id"  # Get this from your NEF emulator
ue_url = f"http://localhost:8080/api/v1/UE/{ue_id}"
ue_data = {"path_id": path_id}
ue_response = requests.put(ue_url, json=ue_data, headers=headers)

# 4. Start UE movement
start_url = "http://localhost:8080/api/v1/ue-movement/start-loop"
start_data = {"supi": "your_ue_supi"}  # Get SUPI from your UE
start_response = requests.post(start_url, json=start_data, headers=headers)
print("UE movement started")
```

### A3 Rule-Based Handover
The emulator supports a basic 3GPP Event A3 rule. Disable machine learning by
setting `ML_HANDOVER_ENABLED=0` and adjust `A3_HYSTERESIS_DB` and `A3_TTT_S` to
control the hysteresis and time-to-trigger.

### Local ML Mode

Set the environment variable `ML_LOCAL=1` to use the ML logic bundled in the
NEF container instead of contacting the `ml-service` API. Provide the path to
your LightGBM model with the `ml_model_path` argument when instantiating
`HandoverEngine`.

Install the ML package during the image build:

```Dockerfile
RUN pip install -e services/ml-service
```

When running with `ML_LOCAL` enabled you can omit the `ml-service` container in
`docker-compose.yml`:

```yaml
services:
  nef-emulator:
    environment:
      - ML_LOCAL=1
#  ml-service:
#    image: 5g-network-optimization/ml-service:latest
```
