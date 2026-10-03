# City of Calgary 311 Operations — Frontend

React + Tailwind MVP for the 311 operations/dispatch dashboard.

## Run locally

```bash
cd frontend
cp .env.example .env
# Add your Mapbox public token to VITE_MAPBOX_ACCESS_TOKEN in .env
npm install
npm run dev
```

Open the URL Vite prints (usually `http://localhost:5173`).

Required env var (Vite): `VITE_MAPBOX_ACCESS_TOKEN`

## Structure

```
src/
├── App.jsx                   # Layout + routes
├── components/
│   ├── Sidebar.jsx           # Left navigation
│   ├── CalgaryMap.jsx        # Mapbox map + overlays
│   ├── MapLayersPanel.jsx    # Floating layers panel
│   └── MapSearchFilters.jsx  # Floating search / filters
└── pages/
    ├── Dashboard.jsx         # Default page (full map workspace)
    ├── Requests.jsx
    ├── Dispatch.jsx
    ├── Crews.jsx
    └── Reports.jsx
```
