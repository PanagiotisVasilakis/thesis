# Kinisis UI

Modern React-based UI for the 5G Network Emulator (NEF).

## 🚀 Quick Start

### Development

```bash
# Install dependencies
npm install

# Start dev server
npm run dev
```

Visit `http://localhost:3000`

### Production (Docker)

```bash
# Build and run with Docker
docker build -t kinisis-ui .
docker run -p 3000:80 kinisis-ui
```

Or add to your existing docker-compose.yml (see `docker-compose.example.yml`)

## 📦 Features

- 🗺️ **Interactive Map** - Leaflet with cells, UEs, and paths
- 🧠 **ML Control** - Toggle between ML and A3 handover modes
- 🏛️ **Entity Management** - Full CRUD for gNBs, Cells, UEs, Paths
- 📊 **Analytics** - Charts comparing ML vs A3 performance
- 📥 **Scenarios** - Load pre-built or custom test scenarios
- 📤 **Export** - Download results as CSV/JSON

## 🛠️ Tech Stack

- **React 18** + **Vite** - Fast dev and build
- **Tailwind CSS** - Modern styling
- **TanStack Table** - Advanced data tables
- **React-Leaflet** - Map visualization
- **Recharts** - Analytics charts
- **Zod** - Form validation
- **React Hot Toast** - Notifications

## 📁 Project Structure

```
src/
├── api/              # API clients (nefClient, mlClient)
├── components/       # Reusable components
│   ├── shared/       # DataTable, Modal, Loading, ErrorBoundary
│   ├── forms/        # Entity forms with validation
│   ├── Layout/       # Sidebar, Header
│   ├── Map/          # Map components
│   ├── ML/           # ML controls and panels
│   ├── Dashboard/    # Stats cards
│   └── Analytics/    # Charts
├── pages/            # Route pages
│   ├── entities/     # Entity management tabs
│   └── ...
└── styles/           # Global CSS
```

## 🔧 Configuration

### Environment Variables

```env
VITE_API_URL=/api/v1
```

### API Proxy (Development)

In `vite.config.js`, API calls are proxied to `https://localhost:4443` during development.

### Production

In production (Docker), nginx proxies `/api/*` to the backend service.

## 🐳 Docker

The app uses a multi-stage build:
1. **Build stage** - Compiles React app with Vite
2. **Production stage** - Serves static files with Nginx

Health check: `http://localhost:3000/health`

## 📚 Available Routes

| Route | Description |
|-------|-------------|
| `/dashboard` | Overview and quick actions |
| `/entities` | Manage gNBs, Cells, UEs, Paths |
| `/map` | Interactive network map |
| `/import` | Load scenarios |
| `/export` | Export configurations |
| `/analytics` | Performance charts |

## 🔒 Authentication

Uses JWT tokens stored in localStorage. Login at `/login` (default: admin/admin).

---

**Part of the 5G Network Optimization thesis project**
