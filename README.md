# Data Visualizer

A web app that turns your data into charts instantly. Upload a CSV, paste a Google Sheets link, or type raw numbers — it auto-suggests the best chart types and lets you customize and download them.

## Features

- Supports CSV, Excel, TSV, and plain text/log files
- Imports directly from Google Sheets URLs
- Auto-suggests up to 8 chart types based on your data
- 32 chart types: bar, line, scatter, pie, heatmap, violin, and more
- Customizable colors, titles, labels, grid, and dark mode
- Download charts as PNG, SVG, PDF, or JPEG

## Running Locally

```bash
pip install -r requirements.txt
python app.py
```

Then open `http://localhost:5000`.

## Deployment

Configured for [Render](https://render.com). Connect your GitHub repo and Render will use `render.yaml` to deploy automatically.

## Stack

- **Backend:** Python, Flask, Pandas, Matplotlib
- **Frontend:** Vanilla JS, HTML/CSS




Public on https://data-visualizer-c5jk.onrender.com/
May take a while to load due to free account