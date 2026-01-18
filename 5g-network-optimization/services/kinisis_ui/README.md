# Kinisis UI

Modern React-based UI for the 5G Network Emulator (NEF).

## Features

- 🗺️ **Interactive Map** - Visualize cells, UEs, and paths with Leaflet
- 🧠 **ML Control** - Toggle between ML and A3 handover modes
- 📊 **Analytics** - Compare ML vs A3 performance with charts
- 📥 **Scenarios** - Load pre-built test scenarios
- 📤 **Export** - Save configurations and results

## Quick Start

### Development

```bash
# Install dependencies
npm install

# Start dev server (with API proxy)
npm run dev
```

Visit `http://localhost:3000`

### Production

```bash
# Build
npm run build

# Or use Docker
docker build -t kinisis-ui .
docker run -p 80:80 kinisis-ui
```

## API Configuration

Set in `.env`:
```
VITE_API_URL=/api/v1
```

For development, API calls are proxied to `https://localhost:4443` (see `vite.config.js`).

## Project Structure

```
src/
├── api/           # API clients (nefClient, mlClient)
├── components/    # Reusable React components
│   ├── Layout/    # Sidebar, Header
│   ├── Map/       # Map components
│   ├── Dashboard/ # Stats cards
│   ├── ML/        # Mode toggle, signal panel
│   └── Analytics/ # Charts
├── pages/         # Route pages
├── hooks/         # Custom hooks
├── context/       # React context
└── styles/        # CSS
```

## Technologies

- React 18 + Vite
- Tailwind CSS
- React-Leaflet
- Recharts
- Axios
