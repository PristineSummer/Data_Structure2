# Navigation System Web GUI

## Overview

This project is a web-based navigation system showcase for a Data Structures course project. The supported interface is the Web GUI: a Flask API backend serving a React/Vite/TypeScript frontend with Leaflet and Canvas-based map rendering.

The system demonstrates large-scale synthetic city maps, shortest-path routing, traffic-aware routing, algorithm traces, traffic simulation, congestion visualization, POI search, incident experiments, and exportable demo results.

## Web GUI Features

- Default demo scale is 10,000 vertices, with 30,000 still available for larger demos.
- Interactive Leaflet map with Canvas-rendered roads, vertices, vehicles, heatmap, search traces, POIs, and route overlays.
- Static shortest route and traffic-aware route planning with A* and Dijkstra support.
- Real algorithm trace playback for visited vertices and relaxed edges.
- A* vs Dijkstra race panel with timing, visited-node count, and route statistics.
- Route explanation panel that compares static and traffic-aware decisions.
- Guided demo mode that generates/loads the map, starts traffic, injects an incident, and compares routes.
- Manual incident lab for testing traffic changes by clicking on the map.
- Coordinate query for nearest vertices and associated roads.
- Time-and-coordinate traffic query for nearby road traffic at a selected simulation step.
- POI search and preset scenarios for hospital, gas station, parking, repair, and restaurant routes.
- Congestion dashboard, overview minimap, hover information cards, and export to Markdown + JSON.

## Desktop GUI Deprecation Notice

The PySide6 desktop GUI is fully deprecated for the final version of this project. It is not maintained, not recommended, and not part of the supported demo workflow.

The repository may still contain legacy files such as `main_gui.py` for historical reference, but reviewers and teammates should use only the Web GUI described in this README.

## Tech Stack

- Backend: Python, Flask, `NavigationEngine`
- Frontend: React, Vite, TypeScript
- Map UI: Leaflet with `CRS.Simple`
- Rendering: layered HTML Canvas
- Algorithms: KD-Tree nearest queries, Dijkstra, A*, traffic-aware routing
- Traffic: simulated vehicles, road capacity, congestion levels, heatmap visualization

## Quick Start

Clone the repository and enter the project root:

```powershell
git clone <your-repository-url>
cd data-structure-main
```

Create and activate a local Python virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation scripts, use:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Install Python dependencies:

```powershell
python -m pip install -r requirements.txt
```

Install frontend dependencies:

```powershell
npm --prefix web_client install
```

Build the Web GUI:

```powershell
cmd /c npm --prefix web_client run build
```

Start the Flask server:

```powershell
python web_server.py
```

Open the Web GUI:

```text
http://localhost:5681
```

The server also opens the browser automatically after startup.

## Running on a Custom Port

The default Web GUI port is `5681`.

To use another port in PowerShell:

```powershell
$env:NAV_WEB_PORT="5682"
python web_server.py
```

Then open:

```text
http://localhost:5682
```

To return to the default port in the same terminal:

```powershell
Remove-Item Env:NAV_WEB_PORT
python web_server.py
```

## Development Workflow

For frontend development, edit files under `web_client/src/`.

Run a type check:

```powershell
cmd /c npm --prefix web_client run typecheck
```

Build production assets:

```powershell
cmd /c npm --prefix web_client run build
```

The build output is written to `web_ui/`, and `web_server.py` serves that directory in production mode.

During active frontend development, Vite can also run separately:

```powershell
cmd /c npm --prefix web_client run dev
```

The Vite development server uses port `5173`. For final demonstration, use the Flask-served production build at port `5681`.

## Testing

Recommended final checks:

```powershell
cmd /c npm --prefix web_client run typecheck
cmd /c npm --prefix web_client run build
python -X utf8 test_web_api.py
```

Optional broader regression checks:

```powershell
python -X utf8 test_phase1.py
python -X utf8 test_phase2.py
python -X utf8 test_traffic_simulator.py
python -X utf8 test_phase4.py
```

## Project Structure

```text
data-structure-main/
├── navigation/                  # Graph, KD-Tree, routing, traffic, POI, and engine logic
├── web_client/                  # React + Vite + TypeScript frontend source
├── web_ui/                      # Production frontend build served by Flask
├── web_server.py                # Flask API, static hosting, and React history fallback
├── test_web_api.py              # Web API regression tests
├── test_phase1.py               # Graph, map generation, and serializer tests
├── test_phase2.py               # KD-Tree, pathfinding, and engine tests
├── test_traffic_simulator.py    # Traffic simulation tests
├── test_phase4.py               # Extended engine, traffic, POI, and DTO tests
├── README_API.md                # API-oriented reference notes
└── *.md                         # Additional course, team, and handoff documents
```

## Troubleshooting

### The browser still shows an old interface

Rebuild the frontend and hard-refresh the browser:

```powershell
cmd /c npm --prefix web_client run build
```

Then press `Ctrl + F5` in the browser.

### Port 5681 is already in use

Check the process:

```powershell
Get-NetTCPConnection -LocalPort 5681 -ErrorAction SilentlyContinue |
  Select-Object LocalAddress,LocalPort,State,OwningProcess
```

Stop the process if needed:

```powershell
Stop-Process -Id <OwningProcess>
```

Or start on another port:

```powershell
$env:NAV_WEB_PORT="5682"
python web_server.py
```

### npm is not recognized

Install Node.js, reopen the terminal, and run:

```powershell
npm --version
```

Then reinstall frontend dependencies:

```powershell
npm --prefix web_client install
```

### Flask or Python dependencies are missing

Activate the virtual environment and reinstall requirements:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Notes for Reviewers

- The supported demo entry point is `python web_server.py`.
- The supported browser URL is `http://localhost:5681` unless `NAV_WEB_PORT` is set.
- The Web GUI is the final presentation surface for this project.
- The PySide6 desktop GUI is deprecated and should not be used for evaluation.
- Generated map caches are stored under `data/generated/` and are not intended to be committed.
