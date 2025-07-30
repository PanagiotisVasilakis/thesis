# Contributor Guidelines

All contributors must use **Python 3.10** for any development. Verify that Python 3.10 is available on your system (the project Dockerfiles and shell scripts reference python3.10 explicitly).

Install all dependencies before working:
- Run `scripts/install_system_deps.sh` to install required system packages.
- Run `scripts/install_deps.sh` to install Python packages from `requirements.txt`.

Before committing any changes:
1. Format all Python files using `black`.
2. Run `pytest` from the repository root and ensure all tests pass.

