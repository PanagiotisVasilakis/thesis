# 5G Network Optimization Thesis

This repository contains the code and configuration for a thesis project on optimizing 5G handover decisions using a Network Exposure Function (NEF) emulator and a machine learning service. The implementation lives primarily in the [`5g-network-optimization`](5g-network-optimization/) directory.

See [5g-network-optimization/README.md](5g-network-optimization/README.md) for a detailed explanation of the system architecture, setup instructions, and usage examples.

## Running Tests

Before running the tests, install the required system libraries and Python dependencies:

```bash
./scripts/install_system_deps.sh
pip install -r requirements.txt
pytest
```

For integration tests and more advanced scenarios, refer to the documentation in the `5g-network-optimization` folder.

## Useful Scripts

- `scripts/install_deps.sh` – install Python dependencies listed in `requirements.txt`.
- `scripts/install_system_deps.sh` – install OS libraries needed by the services and tests.
