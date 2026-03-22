# NEF Emulator User Guide

Welcome to the NEF (Network Exposure Function) Emulator! This guide will help you get started with creating and running 5G network simulations.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Understanding 5G Terminology](#understanding-5g-terminology)
3. [Dashboard Overview](#dashboard-overview)
4. [Creating Your First Scenario](#creating-your-first-scenario)
5. [Running Simulations](#running-simulations)
6. [Import/Export Scenarios](#importexport-scenarios)
7. [API Access](#api-access)
8. [Troubleshooting](#troubleshooting)

---

## Quick Start

1. **Login** at `/login` with your credentials
2. **Create a gNB** (base station) from the dashboard
3. **Add Cells** (coverage areas) to your gNB
4. **Create UEs** (mobile devices) and assign them to cells
5. **Define Paths** for UE movement
6. **Go to Map** to start the simulation

---

## Understanding 5G Terminology

| Term | Full Name | Description |
|------|-----------|-------------|
| **gNB** | gNodeB | 5G base station - the radio equipment that provides wireless coverage |
| **Cell** | Cell | Coverage area served by an antenna. Each gNB can have multiple cells |
| **UE** | User Equipment | Mobile devices like phones, tablets, or IoT sensors |
| **SUPI** | Subscription Permanent ID | Unique 15-digit identifier for each UE (e.g., `202010000000001`) |
| **Path** | Movement Path | GPS trajectory that a UE follows during simulation |

---

## Dashboard Overview

The dashboard (`/dashboard`) is your main control center:

### Stat Cards (Top Row)
- **gNBs** - Number of base stations
- **Cells** - Number of coverage areas  
- **UEs** - Number of mobile devices
- **Paths** - Number of movement trajectories

### Data Tables
Each table lets you **Create**, **Edit**, and **Delete** items:
- Click the **+** button to add new items
- Click the **pencil icon** to edit
- Click the **trash icon** to delete

---

## Creating Your First Scenario

### Step 1: Create a gNB (Base Station)
1. Click the **+** button in the gNBs section
2. Fill in:
   - **gNB_id**: 6-character identifier (e.g., `AAAAA1`)
   - **Name**: Human-readable name (e.g., `Tower-1`)
   - **Location**: Description of location
3. Click **Save**

### Step 2: Add a Cell
1. Click the **+** button in the Cells section
2. Fill in:
   - **cell_id**: Unique cell identifier
   - **Name**: Human-readable name
   - **Select gNB**: Choose the parent base station
3. **Click on the map** to set location
4. **Adjust radius** (5-500 meters)
5. Click **Save**

### Step 3: Create a UE
1. Click the **+** button in the UEs section
2. Fill in:
   - **SUPI**: 15-digit ID (e.g., `202010000000001`)
   - **Name**: Device name (e.g., `Phone-1`)
   - **IPv4/IPv6**: Network addresses
   - **Path**: Select a movement path (optional)
   - **Speed**: LOW or HIGH
3. Click **Save**

### Step 4: Define a Path
1. Click the **+** button in the Paths section
2. **Click on the map** to add waypoints
3. Choose a **color** for the path
4. Click **Save**

---

## Running Simulations

### Map Page (`/map`)

1. Navigate to **Emulator → Map** in the sidebar
2. You'll see:
   - **Map** with cells (red circles) and UEs (walking icons)
   - **UE Buttons** below the map
   - **Events Table** showing API activity

### Starting UE Movement
- Click individual UE buttons to start/stop that UE
- Click **Start All** to move all UEs simultaneously
- Use the **refresh dropdown** to set update frequency (1s, 2s, 5s...)

### Understanding Map Markers
- **Red pins with 📶**: Cell locations
- **Blue walking icons**: UE positions
- **Colored lines**: Movement paths
- **Grey walking icons**: UEs not connected to any cell

---

## Import/Export Scenarios

### Exporting
1. Go to **Emulator → Export**
2. Click **Copy** to copy JSON to clipboard
3. Or click **Save** to download as file

### Importing
1. Go to **Emulator → Import**
2. Paste or load your JSON scenario
3. Click **Import**

> ⚠️ **Note**: Import works best on an empty database. Use `make db-reset` before importing.

---

## API Access

### Swagger UI (Interactive API Docs)
- **Internal APIs**: `/docs`
- **3GPP Northbound APIs**: `/nef/docs`

### ReDoc (Reference Documentation)
- **Internal APIs**: `/redoc`
- **Northbound APIs**: `/nef/redoc`

### Key Endpoints
| Endpoint | Description |
|----------|-------------|
| `POST /api/v1/login/access-token` | Get authentication token |
| `GET /api/v1/gNBs` | List all base stations |
| `GET /api/v1/Cells` | List all cells |
| `GET /api/v1/UEs` | List all UEs |
| `POST /api/v1/ue_movement/start-loop` | Start UE movement |

---

## Troubleshooting

### Login Issues
- Check your username/password
- Ensure the backend service is running
- Clear browser cache and localStorage

### Map Not Loading
- Check if cells exist (required for map bounds)
- Verify browser supports Leaflet.js
- Check browser console for errors

### UE Not Moving
- Verify UE has a path assigned
- Check that path has waypoints
- Ensure "Start" button was clicked

### API Errors
- Check authentication token is valid
- Verify Content-Type is `application/json`
- Review error response for details

---

## Getting Help

- **API Documentation**: `/docs` and `/nef/docs`
- **Source Code**: Check the `backend/app/` directory
- **Logs**: `docker compose logs -f backend`

Happy simulating! 🚀
