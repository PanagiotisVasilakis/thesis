#!/bin/bash

echo "Testing server startup with mobility model integration..."

# Navigate to the NEF emulator directory
cd backend/app

# Try to start the server (don't actually expose it, just test if it loads)
if python -c "from app.main import app; print('Server initialization successful')" &> server_init.log; then
    echo "✅ Server initialization successful"
    cat server_init.log
else
    echo "❌ Server initialization failed"
    cat server_init.log
    exit 1
fi
