# Integration Test Plan

## Prerequisites
- Ensure MongoDB is running
- Ensure all dependencies are installed

## Step 1: Start the NEF Emulator
```bash
cd backend/app
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## Step 2: Run the API Integration Test
In a separate terminal:
```bash
python tests/integration/test_mobility_integration.py
```

## Step 3: Verify the Results
1. Check the console output for success messages
2. Examine the generated image file 'linear_api_pattern.png'
3. Verify that the trajectory matches expectations

## Step 4: Additional Tests
If the basic integration works, proceed with testing:
1. L-shaped mobility patterns
2. Integration with the UE movement system
3. Performance under load
