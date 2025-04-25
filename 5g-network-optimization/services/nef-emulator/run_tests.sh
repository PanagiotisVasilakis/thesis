#!/bin/bash
# save this as run_tests.sh

# Set up environment
echo "Setting up test environment..."
mkdir -p output

# Check if NEF emulator is running
echo "Checking if NEF emulator is running..."
curl -s http://localhost:8080/docs > /dev/null
if [ $? -eq 0 ]; then
    echo "✓ NEF emulator is running"
    NEF_RUNNING=true
else
    echo "✗ NEF emulator is not running"
    echo "Some integration tests will be skipped"
    NEF_RUNNING=false
fi

# Check if ML service is running
echo "Checking if ML service is running..."
curl -s http://localhost:5050/api/health > /dev/null
if [ $? -eq 0 ]; then
    echo "✓ ML service is running"
    ML_RUNNING=true
else
    echo "✗ ML service is not running"
    echo "Some integration tests will be skipped"
    ML_RUNNING=false
fi

# Run tests
echo -e "\n============================================"
echo "Running Mobility Models Tests..."
echo "============================================"
python tests/test_mobility_models.py

echo -e "\n============================================"
echo "Running ML Components Tests..."
echo "============================================"
python tests/test_ml_components.py

# Only run integration tests if services are running
if [ "$NEF_RUNNING" = true ] || [ "$ML_RUNNING" = true ]; then
    echo -e "\n============================================"
    echo "Running Integration Tests..."
    echo "============================================"
    python tests/test_integration.py
else
    echo -e "\n============================================"
    echo "Skipping Integration Tests (services not running)"
    echo "============================================"
fi

echo -e "\n============================================"
echo "All tests completed!"
echo "============================================"

# Create a summary report
echo "Creating test summary report..."
echo "# 5G Network Optimization - Test Results" > test_summary.md
echo "Generated on: $(date)" >> test_summary.md
echo "" >> test_summary.md
echo "## Environment Status" >> test_summary.md
echo "- NEF Emulator: $([ "$NEF_RUNNING" = true ] && echo 'Running' || echo 'Not Running')" >> test_summary.md
echo "- ML Service: $([ "$ML_RUNNING" = true ] && echo 'Running' || echo 'Not Running')" >> test_summary.md
echo "" >> test_summary.md

# List generated visualizations
echo "## Generated Visualizations" >> test_summary.md
for img in *.png output/*.png; do
    if [ -f "$img" ]; then
        echo "- [$img]($img) - $(basename "$img" .png | tr '_' ' ')" >> test_summary.md
    fi
done

echo "" >> test_summary.md
echo "## Next Steps" >> test_summary.md
echo "1. Fix any failing tests" >> test_summary.md
echo "2. Implement RF models for signal propagation" >> test_summary.md
echo "3. Enhance ML service with monitoring" >> test_summary.md
echo "4. Create Kubernetes deployment configuration" >> test_summary.md

echo "Test summary created: test_summary.md"