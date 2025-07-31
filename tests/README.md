# Test Dependencies

This project relies on a fairly heavy stack of libraries for its automated test suite.
The key runtime dependencies that the tests import include **Flask**, **matplotlib**,
**scikit-learn**, **pandas**, and **LightGBM** in addition to the core services
under `5g-network-optimization`.  A few of these packages (such as `matplotlib`)
require system libraries like `libcairo` and `libjpeg` when installed in a clean
environment.

Install all dependencies from the root of the repository:

```bash
pip install -r requirements.txt
```

That file contains both application and test requirements.  If you only wish to
install the minimal set used exclusively by the tests, run:

```bash
pip install -r tests/requirements.txt
```

The test-only file simply references `pytest` and related utilities so that the
full development stack does not need to be installed when running CI.
