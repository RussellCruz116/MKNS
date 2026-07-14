"""
Generate a static, chunk-loaded MaKeNeS dashboard.

The chunked dashboard optimizes the road network GeoJSON by dropping redundant columns 
and using coordinate rounding, making it highly lightweight and usable while preserving 
access to the full scored network.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
from collections import defaultdict
from pathlib import Path


SCORE_FIELD = "SpeedSafetyScore"
CLUSTER_FIELD = "SubSupervisorID"
OBJECT_ID_FIELD = "OBJECTID"


def as_float(value, fallback=0.0) -> float:
    try:
        if value is None:
            return fallback
        number = float(value)
        if math.isnan(number):
            return fallback
        return number
    except (TypeError, ValueError):
        return fallback


def bbox_from_geometry(geometry) -> list[float] | None:
    if not geometry:
        return None

    coords = geometry.get("coordinates")
    if coords is None:
        return None

    xs: list[float] = []
    ys: list[float] = []

    def walk(node):
        if not isinstance(node, list):
            return
        if len(node) >= 2 and all(isinstance(v, (int, float)) for v in node[:2]):
            xs.append(float(node[0]))
            ys.append(float(node[1]))
            return
        for child in node:
            walk(child)

    walk(coords)
    if not xs or not ys:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def merge_bbox(current: list[float] | None, new: list[float] | None) -> list[float] | None:
    if new is None:
        return current
    if current is None:
        return new
    return [
        min(current[0], new[0]),
        min(current[1], new[1]),
        max(current[2], new[2]),
        max(current[3], new[3]),
    ]


def safe_filename(name: str) -> str:
    keep = []
    for char in name:
        if char.isalnum() or char in ("-", "_"):
            keep.append(char)
        else:
            keep.append("_")
    return "".join(keep).strip("_") or "unknown_cluster"


def country_from_cluster(cluster: str) -> str:
    lower = cluster.lower()
    if lower.startswith("thailand"):
        return "Thailand"
    if lower.startswith("maharashtra"):
        return "Maharashtra"
    return "Unknown"


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, separators=(",", ":"))


def build_html() -> str:
    return r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="initial-scale=1,maximum-scale=1,user-scalable=no">
  <title>MaKeNeS Digital Twin Analytics - Explorer Portal</title>
  <script src="https://cdn.jsdelivr.net/npm/maplibre-gl@4.5.0/dist/maplibre-gl.js"></script>
  <link href="https://cdn.jsdelivr.net/npm/maplibre-gl@4.5.0/dist/maplibre-gl.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
  <style>
    /* ============================================================
       DESIGN TOKENS
       ============================================================ */
    :root {
        --bg-body: #080e14;
        --bg-sidebar-start: #0c1620;
        --bg-sidebar-end: #111e2a;
        --bg-glass: rgba(14, 26, 38, 0.80);
        --bg-glass-hover: rgba(22, 38, 52, 0.90);
        --bg-glass-subtle: rgba(255, 255, 255, 0.025);
        --bg-overlay: rgba(10, 20, 30, 0.92);

        --accent-cyan: #00e5ff;
        --accent-cyan-dim: rgba(0, 229, 255, 0.18);
        --accent-cyan-glow: rgba(0, 229, 255, 0.25);
        --accent-orange: #ff9800;
        --accent-orange-dim: rgba(255, 152, 0, 0.15);
        --accent-orange-glow: rgba(255, 152, 0, 0.35);
        --accent-red: #ff5252;
        --accent-green: #66bb6a;
        --accent-purple: #e040fb;
        --accent-amber: #ffab40;
        --accent-blue: #40c4ff;

        --text-primary: #f5f8fa;
        --text-secondary: #8a9ba8;
        --text-muted: #5c7080;
        --text-accent: #00e5ff;

        --border-subtle: rgba(255, 255, 255, 0.06);
        --border-glass: rgba(0, 229, 255, 0.15);
        --border-card: rgba(255, 255, 255, 0.04);

        --font-display: 'Outfit', sans-serif;
        --font-body: 'Inter', sans-serif;

        --sp-xs: 4px;
        --sp-sm: 8px;
        --sp-md: 16px;
        --sp-lg: 24px;
        --sp-xl: 32px;

        --radius-sm: 6px;
        --radius-md: 12px;
        --radius-lg: 18px;

        --shadow-sm: 0 2px 8px rgba(0,0,0,0.5);
        --shadow-card: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        --shadow-sidebar: 4px 0 32px 0 rgba(0, 0, 0, 0.5);
        --shadow-glow: 0 0 12px rgba(0, 229, 255, 0.4);
        
        --transition-fast: 0.15s ease;
        --transition-normal: 0.3s ease;
    }

    /* ============================================================
       BASE LAYOUT
       ============================================================ */
    html, body {
        height: 100%;
        margin: 0;
        font-family: var(--font-body);
        background: var(--bg-body);
        color: var(--text-primary);
        overflow: hidden;
    }
    #map {
        position: absolute;
        inset: 0 0 0 380px;
        background: #0b0d10;
    }
    #sidebar {
        position: absolute;
        inset: 0 auto 0 0;
        width: 380px;
        background: linear-gradient(135deg, var(--bg-sidebar-start), var(--bg-sidebar-end));
        border-right: 1px solid var(--border-subtle);
        box-sizing: border-box;
        padding: var(--sp-lg);
        overflow-y: auto;
        box-shadow: none;
        z-index: 10;
        display: flex;
        flex-direction: column;
        gap: var(--sp-md);
    }

    /* Custom scrollbar for sidebar */
    #sidebar::-webkit-scrollbar {
        width: 6px;
    }
    #sidebar::-webkit-scrollbar-track {
        background: rgba(0, 0, 0, 0.1);
    }
    #sidebar::-webkit-scrollbar-thumb {
        background: rgba(255, 255, 255, 0.1);
        border-radius: 3px;
    }
    #sidebar::-webkit-scrollbar-thumb:hover {
        background: rgba(255, 255, 255, 0.25);
    }

    /* ============================================================
       TYPOGRAPHY & HERO HEADERS
       ============================================================ */
    h1, h2, h3 {
        font-family: var(--font-display);
        color: var(--text-primary);
        margin: 0;
    }
    h1 {
        font-size: 24px;
        font-weight: 700;
        letter-spacing: -0.5px;
    }
    h2 {
        font-size: 16px;
        font-weight: 600;
        color: var(--accent-cyan);
    }
    .muted {
        color: var(--text-secondary);
        font-size: 12px;
        line-height: 1.5;
    }

    /* ============================================================
       VIEW MODE BUTTONS
       ============================================================ */
    .view-mode-container {
        display: flex;
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius-sm);
        overflow: hidden;
        background: rgba(0, 0, 0, 0.2);
    }
    .mode-btn {
        flex: 1;
        padding: 10px;
        border: none;
        background: transparent;
        color: var(--text-secondary);
        cursor: pointer;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        transition: background var(--transition-fast), color var(--transition-fast);
        outline: none;
    }
    .mode-btn:hover {
        color: var(--text-primary);
        background: rgba(255, 255, 255, 0.02);
    }
    .mode-btn.active {
        background: var(--accent-cyan-dim) !important;
        color: var(--accent-cyan) !important;
        box-shadow: none;
    }

    /* ============================================================
       GLASSMORPHIC METRIC CARDS
       ============================================================ */
    .metric-row {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: var(--sp-sm);
    }
    .metric {
        background: #111e2a;
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: var(--radius-sm);
        padding: var(--sp-sm) var(--sp-md);
        box-shadow: none;
        display: flex;
        flex-direction: column;
        justify-content: center;
        transition: transform var(--transition-fast), border-color var(--transition-fast);
    }
    .metric:hover {
        transform: translateY(-1px);
        border-color: var(--border-subtle);
    }
    .metric strong {
        display: block;
        font-size: 22px;
        font-family: var(--font-display);
        color: var(--text-primary);
        font-weight: 700;
    }
    .metric span {
        color: var(--text-muted);
        font-size: 9px;
        text-transform: uppercase;
        letter-spacing: 1px;
        font-weight: 600;
        margin-top: 2px;
    }
    .metric.accent-card strong {
        color: var(--accent-cyan);
    }
    .metric.danger-card {
        border-left: 3px solid var(--accent-orange);
    }
    .metric.danger-card strong {
        color: var(--accent-orange);
    }

    /* ============================================================
       CONTROLS & SELECTORS
       ============================================================ */
    .control-group {
        background: rgba(255, 255, 255, 0.015);
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius-md);
        padding: var(--sp-md);
        display: flex;
        flex-direction: column;
        gap: var(--sp-sm);
    }
    label {
        display: block;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        color: var(--text-muted);
        font-weight: 600;
        margin-bottom: 2px;
    }
    select, input {
        width: 100%;
        box-sizing: border-box;
        border-radius: var(--radius-sm);
        border: 1px solid var(--border-subtle);
        background: rgba(14, 26, 38, 0.6);
        color: var(--text-primary);
        padding: 10px var(--sp-md);
        font: inherit;
        font-size: 13px;
        outline: none;
        transition: border-color var(--transition-fast), background var(--transition-fast);
    }
    select:focus, input:focus {
        border-color: var(--accent-cyan);
        background: rgba(14, 26, 38, 0.85);
    }
    
    /* ============================================================
       BUTTONS & INTERACTION
       ============================================================ */
    .btn {
        width: 100%;
        box-sizing: border-box;
        border-radius: var(--radius-sm);
        border: 1px solid rgba(0, 229, 255, 0.3);
        background: linear-gradient(135deg, #00acc1, #00838f);
        color: white;
        padding: 11px var(--sp-md);
        font: inherit;
        font-weight: 600;
        font-size: 13px;
        cursor: pointer;
        transition: transform var(--transition-fast), box-shadow var(--transition-fast);
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        box-shadow: none;
    }
    .btn:hover {
        transform: translateY(-1.5px);
        box-shadow: none;
    }
    .btn:active {
        transform: translateY(0);
    }
    .btn.secondary {
        background: rgba(255, 255, 255, 0.04);
        border-color: var(--border-subtle);
        color: var(--text-secondary);
        box-shadow: none;
    }
    .btn.secondary:hover {
        background: rgba(255, 255, 255, 0.08);
        color: var(--text-primary);
        border-color: var(--text-muted);
        box-shadow: none;
        transform: translateY(-1px);
    }

    /* ============================================================
       LISTS AND LIST ITEMS
       ============================================================ */
    .list-header {
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 1px;
        color: var(--text-muted);
        font-weight: 600;
        border-bottom: 1px solid var(--border-subtle);
        padding-bottom: var(--sp-xs);
        margin-top: var(--sp-sm);
    }
    #clusterList {
        display: flex;
        flex-direction: column;
        gap: var(--sp-xs);
        max-height: 250px;
        overflow-y: auto;
        padding-right: 4px;
    }
    .cluster-item {
        padding: 10px 12px;
        border: 1px solid var(--border-card);
        border-radius: var(--radius-sm);
        background: rgba(255, 255, 255, 0.015);
        cursor: pointer;
        transition: background var(--transition-fast), border-color var(--transition-fast), transform var(--transition-fast);
        display: flex;
        flex-direction: column;
        gap: 3px;
    }
    .cluster-item:hover {
        background: rgba(255, 255, 255, 0.035);
        border-color: var(--text-muted);
        transform: translateX(1px);
    }
    .cluster-item.active {
        border-color: var(--accent-cyan);
        background: rgba(0, 229, 255, 0.03);
    }
    .cluster-title {
        font-size: 12.5px;
        font-weight: 600;
        color: var(--text-primary);
    }
    .cluster-meta {
        color: var(--text-secondary);
        font-size: 10.5px;
    }

    /* ============================================================
       CHART CONTAINER
       ============================================================ */
    .chart-box {
        padding: var(--sp-md);
        background: #111e2a;
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: var(--radius-sm);
        box-shadow: none;
        min-height: 120px;
        position: relative;
    }

    /* ============================================================
       LEGEND & FLOATING PANELS
       ============================================================ */
    .legend {
        position: absolute;
        right: var(--sp-lg);
        bottom: 30px;
        width: 230px;
        padding: var(--sp-md);
        background: #0f172a;
        color: var(--text-primary);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: var(--radius-sm);
        box-shadow: none;
        z-index: 5;
    }
    .legend-title {
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 1px;
        color: var(--text-muted);
        font-weight: 700;
        margin-bottom: 8px;
    }
    .legend-scale {
        height: 10px;
        border-radius: var(--radius-pill);
        overflow: hidden;
        display: flex;
        margin-bottom: 6px;
    }
    .legend-scale span {
        flex: 1;
    }
    .legend-labels {
        display: flex;
        justify-content: space-between;
        color: var(--text-secondary);
        font-size: 10px;
    }
    #status {
        font-size: 11px;
        color: var(--accent-cyan);
        min-height: 16px;
        font-weight: 500;
    }

    /* ============================================================
       MAPLIBRE POPUP THEME OVERRIDES (Dark Accordion Style)
       ============================================================ */
    .maplibregl-popup {
        z-index: 12;
    }
    .maplibregl-popup-content {
        background: #1e293b !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: var(--radius-sm) !important;
        color: var(--text-primary) !important;
        padding: 0 !important;
        box-shadow: none;
        font-family: var(--font-body);
        font-size: 12px;
        overflow: hidden;
    }
    .maplibregl-popup-tip {
        border-top-color: #1e293b !important;
        border-bottom-color: #1e293b !important;
    }
    .maplibregl-popup-close-button {
        color: var(--text-secondary) !important;
        outline: none;
        padding: 6px 10px !important;
        font-size: 16px !important;
        transition: color var(--transition-fast);
        z-index: 20;
    }
    .maplibregl-popup-close-button:hover {
        color: var(--accent-red) !important;
        background: transparent !important;
    }

    /* Popup internal elements */
    .popup-title-container {
        padding: 14px 16px 8px;
        border-bottom: 1px solid var(--border-subtle);
    }
    .popup-title {
        font-family: var(--font-display);
        font-size: 14px;
        font-weight: 700;
        margin-bottom: 3px;
        color: var(--text-primary);
    }
    .popup-body {
        max-height: 320px;
        overflow-y: auto;
        padding: 8px 16px 16px;
    }
    .popup-accordion-header {
        background: rgba(255,255,255,0.025);
        border: 1px solid var(--border-subtle);
        padding: 6px 10px;
        border-radius: var(--radius-sm);
        margin-top: 6px;
        font-weight: 600;
        font-size: 11px;
        color: var(--text-secondary);
        cursor: pointer;
        display: flex;
        justify-content: space-between;
        align-items: center;
        transition: background var(--transition-fast), color var(--transition-fast);
    }
    .popup-accordion-header:hover {
        background: rgba(255,255,255,0.05);
        color: var(--text-primary);
    }
    .popup-accordion-content {
        padding: 8px 10px;
        border: 1px solid var(--border-subtle);
        border-top: none;
        background: rgba(0,0,0,0.2);
        border-bottom-left-radius: var(--radius-sm);
        border-bottom-right-radius: var(--radius-sm);
        display: none;
    }
    .popup-accordion-content.expanded {
        display: block;
    }
    .popup-row {
        margin: var(--sp-xs) 0;
        line-height: 1.5;
        white-space: normal;
        word-break: break-word;
    }
    .popup-row b {
        color: var(--text-muted);
        font-weight: 500;
    }
    .popup-tag {
        display: inline-block;
        padding: 2px 6px;
        background: var(--accent-cyan-dim);
        border: 1px solid var(--border-glass);
        color: var(--accent-cyan);
        border-radius: var(--radius-pill);
        font-size: 9.5px;
        font-weight: 600;
        text-transform: uppercase;
        margin-right: 4px;
        margin-top: 4px;
    }

    /* ============================================================
       RESPONSIVE BREAKPOINTS
       ============================================================ */
    @media (max-width: 900px) {
        #sidebar {
            width: 100%;
            height: 42%;
            inset: auto 0 0 auto;
            border-right: none;
            border-top: 1px solid var(--border-subtle);
        }
        #map {
            inset: 0 0 42% 0;
        }
        .legend {
            display: none;
        }
    }

    /* Floating Active Scenarios Ledger */
    #active-ledger {
        position: absolute;
        top: 20px;
        right: 60px;
        background: #0f172a;
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: var(--radius-sm);
        padding: 10px 14px;
        box-shadow: none;
        z-index: 15;
        max-width: 320px;
        display: none;
        flex-direction: column;
        gap: 6px;
    }
    #active-ledger-title {
        font-family: var(--font-display);
        font-size: 10px;
        font-weight: 700;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    #active-ledger-pills {
        display: flex;
        flex-wrap: wrap;
        gap: var(--sp-xs);
    }
    .ledger-pill {
        background: var(--accent-cyan-dim);
        border: 1px solid var(--border-glass);
        color: var(--accent-cyan);
        border-radius: var(--radius-pill);
        padding: 2px 8px;
        font-size: 10px;
        font-weight: 600;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .ledger-pill span {
        cursor: pointer;
        color: var(--text-secondary);
        font-weight: bold;
        transition: color var(--transition-fast);
    }
    .ledger-pill span:hover {
        color: var(--accent-red);
    }
    
    /* Bottom Toast Notification Container */
    #toast-container {
        position: absolute;
        bottom: 30px;
        left: 50%;
        transform: translateX(-50%);
        z-index: 100;
        display: flex;
        flex-direction: column;
        gap: 8px;
        pointer-events: none;
    }
    .toast-msg {
        background: rgba(14, 26, 38, 0.95);
        border-left: 4px solid var(--accent-cyan);
        border-radius: var(--radius-sm);
        color: var(--text-primary);
        padding: 10px 20px;
        font-size: 12.5px;
        font-weight: 500;
        box-shadow: none;
        opacity: 0;
        transform: translateY(20px);
        transition: opacity var(--transition-fast), transform var(--transition-fast);
        pointer-events: auto;
    }
    .toast-msg.show {
        opacity: 1;
        transform: translateY(0);
    }
  </style>
</head>
<body>
  <aside id="sidebar">
    <!-- Brand / Status Block -->
    <div style="display:flex; justify-content:space-between; align-items:flex-start;">
        <div>
            <h1>MKNS</h1>
            <p style="font-size:9.5px; color:var(--text-muted); margin:0; text-transform:uppercase; letter-spacing:1px; font-weight:600;">Digital Twin Analytics</p>
        </div>
        <div style="text-align:right;">
            <div style="width:7px; height:7px; border-radius:50%; background:var(--accent-green); display:inline-block; box-shadow: none; margin-right:3px;"></div>
            <span style="font-size:9px; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.8px; font-weight:600;">Live</span>
        </div>
    </div>
    
    <p style="font-size:11px; color:var(--text-secondary); line-height:1.45; border-left:2px solid var(--accent-cyan); padding-left:8px; margin:0;">
        Mobility Agents and Kinematic Environment Network Simulator &mdash; <span style="color:var(--accent-cyan); font-weight:500;">AI-Supervised</span>
    </p>

    <!-- Standard vs What-If Mode Selector (Tab Layout) -->
    <div style="display: flex; gap: 8px; margin-bottom: 10px;">
        <button id="modeStandard" class="mode-btn active" style="flex: 1; padding: 12px; border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); font-family: var(--font-display); font-weight: 700; cursor: pointer; transition: 0.2s;">Standard S³</button>
        <button id="modeWhatIf" class="mode-btn" style="flex: 1; padding: 12px; border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); font-family: var(--font-display); font-weight: 700; cursor: pointer; transition: 0.2s;">What-If S³</button>
    </div>
    
    <!-- Standard S3 Subtabs (Only visible when Standard S3 is active) -->
    <div id="standardSubtabs" style="display: flex; gap: 4px; border-bottom: 1px solid var(--border-subtle); padding-bottom: 8px; margin-bottom: 10px;">
        <button id="subtabFilters" class="mode-btn active" style="font-size: 10px; padding: 6px 12px; border-radius: 4px; text-transform: none; letter-spacing: 0;">Explorer & Filters</button>
        <button id="subtabTop100" class="mode-btn" style="font-size: 10px; padding: 6px 12px; border-radius: 4px; text-transform: none; letter-spacing: 0;">Top 100 Worst Roads</button>
    </div>

    <div id="whatIfNotification" style="display: none; padding: 8px; background: rgba(0, 229, 255, 0.05); border: 1px dashed var(--accent-cyan); border-radius: var(--radius-sm); color: var(--accent-cyan); font-size: 11px; margin-bottom: 10px; font-weight: 600;">
        Viewing fully optimized AI-suggested interventions.
    </div>

    <!-- Explorer & Filters Container -->
    <div id="standardFiltersContainer" style="display: flex; flex-direction: column; gap: var(--sp-md); flex: 1; min-height: 0;">
        <!-- Metrics Cards Grid -->
        <div class="metric-row">
          <div class="metric"><strong id="totalSegments">...</strong><span>Total Segments</span></div>
          <div class="metric accent-card"><strong id="meanScore">0.0</strong><span id="meanScoreLabel">Mean S³ Score</span></div>
          <div class="metric"><strong id="loadedSegments">0</strong><span>Loaded Now</span></div>
          <div class="metric danger-card"><strong id="highRisk">...</strong><span>Priority Review</span></div>
        </div>

        <!-- Controls Card -->
        <div class="control-group">
          <div>
            <label for="countryFilter">Target Country</label>
            <select id="countryFilter">
              <option value="All">All Countries</option>
            </select>
          </div>

          <div>
            <label for="clusterSelect">Risk Cluster Selector</label>
            <select id="clusterSelect"></select>
          </div>

          <div>
            <label for="scoreFilter">Score Tier Filter</label>
            <select id="scoreFilter">
              <option value="All">All Scores</option>
              <option value="Severe">Severe Risk (&lt;30)</option>
              <option value="Moderate">Moderate Risk (30-70)</option>
              <option value="Safe">Safe System (&gt;70)</option>
            </select>
          </div>

          <div style="display:grid; grid-template-columns:1.2fr 1fr; gap:var(--sp-xs); margin-top:4px;">
            <button id="applyFilters" class="btn">Apply Filters</button>
            <button id="loadTop100" class="btn secondary">Load Top 100</button>
          </div>
        </div>

        <!-- Interactive Histogram Chart -->
        <div class="chart-box">
          <canvas id="scoreChart"></canvas>
        </div>

        <!-- Explorer Controls & Toggles -->
        <div style="display:flex; flex-direction:column; gap:var(--sp-xs); flex:1; min-height:0;">
          <input id="searchBox" placeholder="Search roads by name...">
          
          <!-- Layer Toggles -->
          <div style="margin-top:4px; padding:10px; background:rgba(255,255,255,0.015); border:1px solid var(--border-subtle); border-radius:var(--radius-sm); display:flex; flex-direction:column; gap:6px;">
              <label style="display:flex; align-items:center; gap:8px; color:var(--text-secondary); cursor:pointer; margin:0;">
                  <input type="checkbox" id="toggleAbmConflicts" checked style="width:auto; margin:0; accent-color:var(--accent-red);">
                  Show ABM Hazard Markings
              </label>
              <label style="display:flex; align-items:center; gap:8px; color:var(--text-secondary); cursor:pointer; margin:0;">
                  <input type="checkbox" id="toggleOnlyHazards" style="width:auto; margin:0; accent-color:var(--accent-amber);">
                  Only Show Segments with Hazards
              </label>
          </div>

          <!-- ABM Simulation Replays -->
          <div class="list-header">ABM Simulation Replays</div>
          <div id="abmReplayList" style="display:flex; flex-direction:column; gap:6px; margin-top:4px; max-height:180px; overflow-y:auto;">
              <div style="font-size:11px; color:var(--text-muted); text-align:center; padding:10px;">Loading simulation data...</div>
          </div>

          <div class="list-header">Explorer Controls</div>
          <div id="status">Loading manifest...</div>
          <button id="resetFilters" class="btn secondary" style="margin-top:6px;">Reset Filter Views</button>
        </div>
    </div>

    <!-- Standard S3 Top 100 Worst Roads Subtab Container -->
    <div id="standardTop100Container" style="display: none; flex-direction: column; gap: 8px; overflow-y: auto; flex: 1; min-height: 0; padding-right: 4px;">
      <div style="font-size: 11px; color: var(--text-secondary); line-height: 1.45; margin-bottom: 4px; background: rgba(0, 229, 255, 0.04); padding: 8px; border-left: 2px solid var(--accent-cyan); border-radius: var(--radius-sm);">
        Click any road segment card below to automatically zoom to its location. Ranks 1 to 5 include an interactive ABM simulation replay video.
      </div>
      <div id="top100List" style="display: flex; flex-direction: column; gap: 8px;">
        <div style="font-size: 11px; color: var(--text-muted); text-align: center; padding: 10px;">Loading network...</div>
      </div>
    </div>
  </aside>

  <main id="map"></main>
  
  <div id="active-ledger">
    <div id="active-ledger-title">Active Interventions</div>
    <div id="active-ledger-pills"></div>
  </div>
  
  <div id="toast-container"></div>
  
  <div class="legend">
    <div id="legendTitle" class="legend-title">Speed Safety Score (S³)</div>
    <div class="legend-scale">
      <span style="background:#d73027"></span>
      <span style="background:#f46d43"></span>
      <span style="background:#fdae61"></span>
      <span style="background:#fee08b"></span>
      <span style="background:#ffd54f"></span>
      <span style="background:#e6f598"></span>
      <span style="background:#d9ef8b"></span>
      <span style="background:#a6d96a"></span>
      <span style="background:#66bd63"></span>
      <span style="background:#006837"></span>
    </div>
    <div class="legend-labels"><span>0 (Severe Risk)</span><span>100 (Safe System)</span></div>
    
    <div style="margin-top: 12px; border-top: 1px solid var(--border-subtle); padding-top: 12px;">
      <div class="legend-title">ABM Hazards</div>
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px;">
        <div style="font-size:11px; display:flex; align-items:center; gap:6px;">
            <span style="width:10px; height:10px; border-radius:50%; background:var(--accent-purple); border:1.5px solid rgba(255,255,255,0.6); display:inline-block;"></span>VRU
        </div>
        <div style="font-size:11px; display:flex; align-items:center; gap:6px;">
            <span style="width:10px; height:10px; border-radius:2px; background:var(--accent-red); border:1.5px solid rgba(255,255,255,0.6); display:inline-block;"></span>V2V
        </div>
        <div style="font-size:11px; display:flex; align-items:center; gap:6px;">
            <span style="width:10px; height:10px; border-radius:2px; background:var(--accent-blue); border:1.5px solid rgba(255,255,255,0.6); display:inline-block;"></span>V2O
        </div>
        <div style="font-size:11px; display:flex; align-items:center; gap:6px;">
            <span style="width:10px; height:10px; border-radius:50%; background:var(--accent-amber); border:1.5px solid rgba(255,255,255,0.6); display:inline-block;"></span>PET
        </div>
      </div>
    </div>
  </div>

  <script>
    const map = new maplibregl.Map({
      container: "map",
      style: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
      center: [88.5, 17.5],
      zoom: 4.5
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");

    let manifest = null;
    let allGeojsonData = null;
    let scoreChart = null;
    let frameData = null;
    let currentMode = 'standard'; // 'standard' or 'whatif'
    const clusterSelectEl = document.getElementById("clusterSelect");
    const countryFilterEl = document.getElementById("countryFilter");
    const statusEl = document.getElementById("status");
    const searchBoxEl = document.getElementById("searchBox");

    const modeStandardEl = document.getElementById("modeStandard");
    const modeWhatIfEl = document.getElementById("modeWhatIf");
    const legendTitleEl = document.getElementById("legendTitle");

    function scoreColorExpression(field) {
      return [
        "interpolate", ["linear"], ["coalesce", ["get", field], 0],
        0, "#d73027",
        10, "#f46d43",
        20, "#fdae61",
        30, "#fee08b",
        40, "#ffd54f",
        50, "#e6f598",
        60, "#d9ef8b",
        70, "#a6d96a",
        80, "#66bd63",
        90, "#1a9850",
        100, "#006837"
      ];
    }

    function fitBbox(bbox) {
      if (!bbox) return;
      map.fitBounds([[bbox[0], bbox[1]], [bbox[2], bbox[3]]], { padding: 45, maxZoom: 12, duration: 800 });
    }

    function setStatus(text) {
      statusEl.textContent = text;
    }

    function formatNumber(value) {
      return Number(value || 0).toLocaleString();
    }

    function populateClusterSelector() {
      const country = countryFilterEl.value;
      const filtered = manifest.clusters.filter(c => country === "All" || c.country === country);
      clusterSelectEl.innerHTML = `<option value="All">All Clusters (${filtered.length})</option>` +
        filtered.map(c => `<option value="${c.id}">${c.id} (${formatNumber(c.count)})</option>`).join("");
      clusterSelectEl.value = "All";
    }

    function getFilteredFeatures() {
      if (!allGeojsonData) return [];
      const country = countryFilterEl.value;
      const cluster = clusterSelectEl.value;
      const search = searchBoxEl.value.trim().toLowerCase();
      const scoreTier = document.getElementById("scoreFilter") ? document.getElementById("scoreFilter").value : "All";
      const onlyHazards = document.getElementById("toggleOnlyHazards") ? document.getElementById("toggleOnlyHazards").checked : false;

      return allGeojsonData.features.filter(f => {
        const props = f.properties || {};
        const subId = String(props.SubSupervisorID || "").toLowerCase();
        const scoreField = currentMode === 'standard' ? 'SpeedSafetyScore' : 'WhatIf_SpeedSafetyScore';
        const score = props[scoreField];

        if (scoreTier !== "All" && score !== undefined) {
          if (scoreTier === "Severe" && score >= 30) return false;
          if (scoreTier === "Moderate" && (score < 30 || score > 70)) return false;
          if (scoreTier === "Safe" && score <= 70) return false;
        }

        if (onlyHazards) {
          const oid = String(props.OBJECTID);
          const conflicts = window.conflictIndex ? window.conflictIndex[oid] : null;
          if (!conflicts || conflicts.total === 0) return false;
        }

        if (country !== "All") {
          if (country === "Thailand" && !subId.startsWith("thailand")) return false;
          if (country === "India" && !subId.startsWith("maharashtra")) return false;
        }

        if (cluster !== "All" && props.SubSupervisorID !== cluster) return false;

        if (search) {
          const name = (props.names_primary || "").toLowerCase();
          const engName = (props.english_ro || "").toLowerCase();
          if (!name.includes(search) && !engName.includes(search)) return false;
        }

        return true;
      });
    }

    function updateMetricsAndChart(features) {
      document.getElementById("loadedSegments").textContent = formatNumber(features.length);
      
      const scoreField = currentMode === 'standard' ? 'SpeedSafetyScore' : 'WhatIf_SpeedSafetyScore';
      
      // Calculate scores average and high risk count
      let sum = 0;
      let count = 0;
      let highRiskCount = 0;
      
      features.forEach(f => {
        const val = f.properties[scoreField];
        if (val !== undefined && val !== null) {
          sum += val;
          count++;
          if (val <= 30) {
            highRiskCount++;
          }
        }
      });
      
      const mean = count > 0 ? (sum / count).toFixed(1) : "0.0";
      document.getElementById("meanScore").textContent = mean;
      document.getElementById("meanScoreLabel").textContent = currentMode === 'standard' ? "Mean S³ Score" : "Mean What-If Score";
      document.getElementById("highRisk").textContent = formatNumber(highRiskCount);
      
      updateScoreChart(features, scoreField);
    }

    function applyMapFilter() {
      if (!allGeojsonData) return;
      setStatus("Filtering map layers...");
      
      const filteredFeatures = getFilteredFeatures();

      map.getSource("segments").setData({
        type: "FeatureCollection",
        features: filteredFeatures
      });

      updateMetricsAndChart(filteredFeatures);
      setStatus(`Displaying ${formatNumber(filteredFeatures.length)} filtered segments.`);
    }

    function updateScoreChart(features, field) {
      const scores = features.map(f => f.properties[field]).filter(s => s !== undefined);
      const binCount = 10;
      const histogramBins = Array(binCount).fill(0);
      scores.forEach(s => {
        const idx = Math.min(Math.floor(s / 10), 9);
        if (idx >= 0 && idx < 10) histogramBins[idx]++;
      });
      const binLabels = ["0-10", "10-20", "20-30", "30-40", "40-50", "50-60", "60-70", "70-80", "80-90", "90-100"];
      const binColors = [
        "#ff5252", "#ff7343", "#ff9800", "#ffd54f", "#ffe082",
        "#c5e1a5", "#a6d96a", "#81c784", "#4caf50", "#1a9641"
      ];

      const ctx = document.getElementById("scoreChart").getContext("2d");
      if (scoreChart) {
        scoreChart.destroy();
      }

      scoreChart = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: binLabels,
          datasets: [{
            data: histogramBins,
            backgroundColor: binColors,
            borderRadius: 4,
            borderSkipped: false
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: 'rgba(7, 16, 23, 0.95)',
              titleColor: '#fff',
              bodyColor: '#aaa',
              borderColor: 'rgba(255,255,255,0.06)',
              borderWidth: 1
            }
          },
          scales: {
            x: {
              grid: { display: false },
              ticks: { color: '#8a9ba8', font: { size: 9 } }
            },
            y: {
              grid: { color: 'rgba(255,255,255,0.04)' },
              ticks: { color: '#8a9ba8', font: { size: 9 }, precision: 0 }
            }
          }
        }
      });
    }

    function switchViewMode(mode) {
      if (currentMode === mode) return;
      currentMode = mode;
      
      const whatIfNotification = document.getElementById("whatIfNotification");
      const standardSubtabs = document.getElementById("standardSubtabs");
      const filtersContainer = document.getElementById("standardFiltersContainer");
      const top100Container = document.getElementById("standardTop100Container");
      
      if (mode === 'standard') {
        modeStandardEl.classList.add("active");
        modeStandardEl.style.background = "var(--accent-cyan-dim)";
        modeStandardEl.style.color = "var(--accent-cyan)";
        modeWhatIfEl.classList.remove("active");
        modeWhatIfEl.style.background = "transparent";
        modeWhatIfEl.style.color = "var(--text-secondary)";
        legendTitleEl.textContent = "Speed Safety Score (S³)";
        whatIfNotification.style.display = "none";
        standardSubtabs.style.display = "flex";
        
        const isFiltersActive = document.getElementById("subtabFilters").classList.contains("active");
        if (isFiltersActive) {
          filtersContainer.style.display = "flex";
          top100Container.style.display = "none";
        } else {
          filtersContainer.style.display = "none";
          top100Container.style.display = "flex";
        }
        
        if (map.getLayer("segments-line")) {
          map.setPaintProperty("segments-line", "line-color", scoreColorExpression("SpeedSafetyScore"));
        }
      } else {
        modeStandardEl.classList.remove("active");
        modeStandardEl.style.background = "transparent";
        modeStandardEl.style.color = "var(--text-secondary)";
        modeWhatIfEl.classList.add("active");
        modeWhatIfEl.style.background = "rgba(102, 187, 106, 0.15)";
        modeWhatIfEl.style.color = "#66bb6a";
        legendTitleEl.textContent = "What-If Safety Score";
        whatIfNotification.style.display = "block";
        standardSubtabs.style.display = "none";
        filtersContainer.style.display = "flex";
        top100Container.style.display = "none";
        
        if (map.getLayer("segments-line")) {
          map.setPaintProperty("segments-line", "line-color", scoreColorExpression("WhatIf_SpeedSafetyScore"));
        }
      }
      
      if (allGeojsonData) {
        updateMetricsAndChart(getFilteredFeatures());
      }
    }

    window.togglePopupSection = function(header) {
      const content = header.nextElementSibling;
      const icon = header.querySelector('.icon');
      if (content.classList.contains('expanded')) {
        content.classList.remove('expanded');
        if (icon) icon.textContent = '+';
      } else {
        content.classList.add('expanded');
        if (icon) icon.textContent = '−';
      }
    };

    function popupHtml(props) {
      const isStd = currentMode === 'standard';
      
      const s3 = Number(isStd ? (props.SpeedSafetyScore || 0) : (props.WhatIf_SpeedSafetyScore || props.SpeedSafetyScore || 0)).toFixed(1);
      
      // Safe system alignment status
      const alignedVal = isStd ? props.SafeSystemAligned : (props.WhatIf_SafeSystemAligned ?? props.SafeSystemAligned);
      const isAligned = alignedVal === 1 || alignedVal === "1" || alignedVal === true || Number(s3) > 30;
      
      const tagHtml = isAligned 
        ? '<span class="popup-tag" style="background:rgba(102,187,106,0.15); border-color:rgba(102,187,106,0.3); color:#66bb6a;">Safe System Aligned</span>' 
        : '<span class="popup-tag" style="background:rgba(255,152,0,0.15); border-color:rgba(255,152,0,0.3); color:#ff9800;">Review Required</span>';
      
      // Rubrics: Standard vs What-If
      const scoreKin = isStd ? props.Score_Kinematics : (props.WhatIf_Score_Kinematics ?? props.Score_Kinematics);
      const scoreFric = isStd ? props.Score_Friction : (props.WhatIf_Score_Friction ?? props.Score_Friction);
      const scoreVru = isStd ? props.Score_VRU : (props.WhatIf_Score_VRU ?? props.Score_VRU);
      const scoreSpeed = isStd ? props.Score_Speeding : (props.WhatIf_Score_Speeding ?? props.Score_Speeding);
      const scoreAI = isStd ? props.Score_AI : (props.WhatIf_Score_AI ?? props.Score_AI);
      const scoreStress = isStd ? props.Score_Stress : (props.WhatIf_Score_Stress ?? props.Score_Stress);
      const scoreInfra = isStd ? props.Score_Infrastructure : (props.WhatIf_Score_Infrastructure ?? props.Score_Infrastructure);
      
      const sumRubrics = Number(scoreKin||0) + Number(scoreFric||0) + Number(scoreVru||0) + Number(scoreSpeed||0) + Number(scoreAI||0) + Number(scoreStress||0) + Number(scoreInfra||0);
      
      const rawAiAdjust = props.AI_Score_Adjustment !== undefined ? Number(props.AI_Score_Adjustment) : 0.0;
      // Clamp to sensible range so the reviewer isn't confused by unbounded ABM penalties
      const aiAdjust = Math.max(-15, Math.min(15, rawAiAdjust));
      
      const rawScore = props.SpeedSafetyScore_PreShipRaw !== undefined ? Number(props.SpeedSafetyScore_PreShipRaw) : sumRubrics;
      
      const aiAdjustHtml = Math.abs(aiAdjust) > 0.1 ? ` <span style="font-weight:bold; color:${aiAdjust < 0 ? '#ff5252' : '#66bb6a'};">(${aiAdjust < 0 ? '' : '+'}${aiAdjust.toFixed(1)} AI Adjustment)</span>` : '';
      
      // Decoded lookup tables
      const aiSpeedIntervention = manifest.lookup_tables && props.AI_SpeedIntervention_code !== undefined
        ? (manifest.lookup_tables.AI_SpeedIntervention[props.AI_SpeedIntervention_code] || "No speed intervention recommended")
        : (props.AI_SpeedIntervention || "No speed intervention recommended");
      const violatedRules = manifest.lookup_tables && props.Violated_Rules_code !== undefined
        ? (manifest.lookup_tables.Violated_Rules[props.Violated_Rules_code] || "None")
        : (props.Violated_Rules || "None");
      const whatIfActionDetails = manifest.lookup_tables && props.WhatIf_Action_Details_code !== undefined
        ? (manifest.lookup_tables.WhatIf_Action_Details[props.WhatIf_Action_Details_code] || "No modifications recommended")
        : (props.WhatIf_Action_Details || "No modifications recommended");
      
      // Speeds: Standard vs What-If
      const speedLimit = isStd ? (props.SpeedLimit ?? "n/a") : (props.WhatIf_SpeedLimit ?? props.SpeedLimit ?? "n/a");
      const f85Speed = isStd ? (props.F85thPercentileSpeed ?? "n/a") : (props.WhatIf_F85thPercentileSpeed ?? props.F85thPercentileSpeed ?? "n/a");
      const medianSpeed = isStd ? (props.MedianSpeed ?? "n/a") : (props.WhatIf_MedianSpeed ?? props.MedianSpeed ?? "n/a");
      const pctOver = isStd ? (props.PercentOverLimit ?? 0) : (props.WhatIf_PercentOverLimit ?? props.PercentOverLimit ?? 0);
      
      const wrapRubric = (val, max) => `${Number(val || 0).toFixed(1)} / ${Number(max || 10).toFixed(0)}`;
      
      return `
        <div class="popup-title-container">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div class="popup-title">Segment ${props.OBJECTID ?? "unknown"} (${isStd ? "Standard" : "What-If"})</div>
                <div style="text-align: right;">
                    <div style="font-size:15px; font-weight:700; color:${Number(s3) <= 30 ? '#ff5252' : '#66bb6a'};" title="Statistically curved to distribute review priority">${isStd ? "Curved Map S³:" : "What-If S³:"} ${s3}</div>
                    <div style="font-size:10px; font-weight:600; color:#8a9ba8;" title="Actual sum of rubrics and AI adjustment">Raw Calculation: ${rawScore.toFixed(1)}</div>
                </div>
            </div>
            <div class="popup-row"><b>Supervisor:</b> ${props.SubSupervisorID ?? "n/a"} | <b>Zone:</b> ${props.InferredZone || "Generic"}</div>
            ${tagHtml}
        </div>
        
        ${!isStd ? `
        ${(() => {
            const diff = s3 - props.SpeedSafetyScore;
            let diffColor = '#8a9ba8';
            let diffPrefix = '';
            if (diff > 0.1) { diffColor = '#66bb6a'; diffPrefix = '+'; }
            else if (diff < -0.1) { diffColor = '#ff5252'; diffPrefix = ''; } // JS will add the minus sign

            return `
            <div style="margin-top: 10px; padding: 10px; background: rgba(0, 229, 255, 0.05); border: 1px dashed var(--accent-cyan); border-radius: var(--radius-sm);">
                <div style="font-size: 11px; font-weight: 700; color: var(--accent-cyan); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">What-If Projection</div>
                <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px;">
                    <div>
                        <div style="color: #8a9ba8;">Original S³</div>
                        <div style="font-size: 14px; font-weight: 700; color: #ff9800;">\${Number(props.SpeedSafetyScore).toFixed(1)}</div>
                    </div>
                    <div style="font-size: 16px; color: var(--accent-cyan);">→</div>
                    <div>
                        <div style="color: #8a9ba8;">Simulated S³</div>
                        <div style="font-size: 14px; font-weight: 700; color: #66bb6a;">\${s3}</div>
                    </div>
                    <div style="text-align: right;">
                        <div style="color: #8a9ba8;">Delta</div>
                        <div style="font-size: 14px; font-weight: 700; color: \${diffColor};">\${diffPrefix}\${diff.toFixed(1)}</div>
                    </div>
                </div>
                <hr style="border: 0; border-top: 1px solid rgba(0,229,255,0.2); margin: 8px 0;">
                <div style="display: flex; justify-content: space-between; font-size: 10.5px;">
                    <div><span style="color: #8a9ba8;">Cost:</span> <span style="color: #ff5252; font-weight: 600;">\${props.Intervention_Cost || "n/a"}</span></div>
                    <div><span style="color: #8a9ba8;">Safety ROI:</span> <span style="color: #66bb6a; font-weight: 600;">\${props.Safety_ROI || "n/a"}</span></div>
                </div>
                <div style="margin-top: 6px; font-size: 10px; color: var(--text-secondary); line-height: 1.4;">
                    <b>Simulated Action:</b> \${whatIfActionDetails}
                </div>
            </div>
            `;
        })()}
        ` : ''}

        <div class="popup-body">
            <div class="popup-accordion-header" onclick="togglePopupSection(this)">
                <span>Kinematics & Speeds</span>
                <span class="icon">+</span>
            </div>
            <div class="popup-accordion-content">
                <div class="popup-row"><b>Posted Limit:</b> ${speedLimit} km/h</div>
                <div class="popup-row"><b>85th% Speed:</b> ${f85Speed} km/h</div>
                <div class="popup-row"><b>Median Speed:</b> ${medianSpeed} km/h</div>
                <div class="popup-row"><b>Percent Over Speed:</b> ${(Number(pctOver || 0) * 100).toFixed(1)}%</div>
                <div class="popup-row"><b>Sample Size (avg):</b> ${formatNumber(props.SampleSize_avg)}</div>
            </div>

            <div class="popup-accordion-header" onclick="togglePopupSection(this)">
                <span>Infrastructure & exposure</span>
                <span class="icon">+</span>
            </div>
            <div class="popup-accordion-content">
                <div class="popup-row"><b>Road Class:</b> ${props.RoadClass ?? "n/a"}</div>
                <div class="popup-row"><b>Pop Density:</b> ${formatNumber(props.PopDensity_100m)} / km²</div>
                <div class="popup-row"><b>Building Density:</b> ${Number(props.BuildingDensity_100m || 0).toFixed(1)}%</div>
                <div class="popup-row"><b>Urban Population:</b> ${formatNumber(props.UrbanCentre_Pop)}</div>
                <div class="popup-row"><b>Schools (500m):</b> ${props.POI_Schools_500m ?? 0}</div>
                <div class="popup-row"><b>Crosswalks:</b> ${props.Mapillary_Crosswalks ?? 0}</div>
                <div class="popup-row"><b>OSM Crossings:</b> ${props.OSM_Crossings_500m ?? 0}</div>
                <div class="popup-row"><b>Street Lighting:</b> ${props.OSM_StreetLighting_500m ?? 0}</div>
                <div class="popup-row"><b>Cycleways:</b> ${props.OSM_Cycleways_500m ?? 0}</div>
                <div class="popup-row"><b>Sidewalks:</b> ${props.OSM_Sidewalks_500m ?? 0}</div>
            </div>

            <div class="popup-accordion-header" onclick="togglePopupSection(this)">
                <span>Safety Rubric Breakdown</span>
                <span class="icon">+</span>
            </div>
            <div class="popup-accordion-content">
                <table style="width:100%; font-size:11px; border-collapse:collapse; color:#8a9ba8;">
                    <tr><td style="padding:2px 0;">Kinematics:</td><td style="text-align:right; font-weight:600; color:#eceff1;">${wrapRubric(scoreKin, props.Max_Kinematics ?? 15)}</td></tr>
                    <tr><td style="padding:2px 0;">Visual Friction:</td><td style="text-align:right; font-weight:600; color:#eceff1;">${wrapRubric(scoreFric, props.Max_Friction ?? 10)}</td></tr>
                    <tr><td style="padding:2px 0;">VRU Risk:</td><td style="text-align:right; font-weight:600; color:#eceff1;">${wrapRubric(scoreVru, props.Max_VRU ?? 10)}</td></tr>
                    <tr><td style="padding:2px 0;">Speeding Rate:</td><td style="text-align:right; font-weight:600; color:#eceff1;">${wrapRubric(scoreSpeed, props.Max_Speeding ?? 10)}</td></tr>
                    <tr><td style="padding:2px 0;">AI Review:</td><td style="text-align:right; font-weight:600; color:#eceff1;">${wrapRubric(scoreAI, props.Max_AI ?? 10)}</td></tr>
                    <tr><td style="padding:2px 0;">Active Stress:</td><td style="text-align:right; font-weight:600; color:#eceff1;">${wrapRubric(scoreStress, props.Max_Stress ?? 10)}</td></tr>
                    <tr><td style="padding:2px 0;">Infrastructure:</td><td style="text-align:right; font-weight:600; color:var(--accent-cyan);">${wrapRubric(scoreInfra, props.Max_Infrastructure ?? 10)}</td></tr>
                </table>
            </div>

            ${(() => {
              const oid = String(props.OBJECTID);
              const conflicts = window.conflictIndex ? window.conflictIndex[oid] : null;
              if (conflicts && conflicts.total > 0) {
                return `
                  <div class="popup-accordion-header" onclick="togglePopupSection(this)">
                      <span>Simulated Conflict Hazards</span>
                      <span class="icon" style="color: #ff5252; font-weight: bold; background: rgba(255, 82, 82, 0.15); padding: 1px 6px; border-radius: 4px; font-size: 10px;">${conflicts.total}</span>
                  </div>
                  <div class="popup-accordion-content" style="display: block;">
                      <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:6px; margin:4px 0;">
                          <div style="background:rgba(255,82,82,0.12); padding:6px; border-radius:4px; text-align:center; border: 1px solid rgba(255,82,82,0.25);">
                              <div style="font-size:8px; color:#cfd8dc; text-transform:uppercase; font-weight:600;">V2V</div>
                              <div style="font-size:13px; font-weight:700; color:#ff5252;">${conflicts.V2V}</div>
                          </div>
                          <div style="background:rgba(255,235,59,0.1); padding:6px; border-radius:4px; text-align:center; border: 1px solid rgba(255,235,59,0.2);">
                              <div style="font-size:8px; color:#cfd8dc; text-transform:uppercase; font-weight:600;">V2O</div>
                              <div style="font-size:13px; font-weight:700; color:#ffeb3b;">${conflicts.V2O}</div>
                          </div>
                          <div style="background:rgba(255,152,0,0.12); padding:6px; border-radius:4px; text-align:center; border: 1px solid rgba(255,152,0,0.25);">
                              <div style="font-size:8px; color:#cfd8dc; text-transform:uppercase; font-weight:600;">VRU</div>
                              <div style="font-size:13px; font-weight:700; color:#ff9800;">${conflicts.VRU}</div>
                          </div>
                      </div>
                  </div>
                `;
              } else {
                return `
                  <div class="popup-accordion-header" onclick="togglePopupSection(this)">
                      <span>Simulated Conflict Hazards</span>
                      <span class="icon" style="color: #66bb6a; font-weight: bold; background: rgba(102, 187, 106, 0.15); padding: 1px 6px; border-radius: 4px; font-size: 10px;">0</span>
                  </div>
                  <div class="popup-accordion-content">
                      <div style="font-size:10px; color:#8a9ba8; text-align:center; padding:6px 0;">
                          No simulated conflicts recorded.
                      </div>
                  </div>
                `;
              }
            })()}

            <div class="popup-accordion-header" onclick="togglePopupSection(this)">
                <span>AI Swarm Interventions</span>
                <span class="icon">+</span>
            </div>
            <div class="popup-accordion-content">
                <div class="popup-row" style="font-size:11px; color:#ffb74d;"><b>AI Recommendation:</b><br>${aiSpeedIntervention}${aiAdjustHtml}</div>
                <div class="popup-row" style="font-size:11px; color:#ff5252;"><b>Violated Rules:</b> ${violatedRules}</div>
                ${isStd ? `
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; margin:6px 0;">
                    <div style="background:rgba(255,82,82,0.08); padding:6px; border-radius:4px; text-align:center;">
                        <div style="font-size:8.5px; color:#8a9ba8; text-transform:uppercase;">Cost</div>
                        <div style="font-size:11.5px; font-weight:600; color:#ff5252;">${props.Intervention_Cost || "n/a"}</div>
                    </div>
                    <div style="background:rgba(102,187,106,0.08); padding:6px; border-radius:4px; text-align:center;">
                        <div style="font-size:8.5px; color:#8a9ba8; text-transform:uppercase;">Safety ROI</div>
                        <div style="font-size:11.5px; font-weight:600; color:#66bb6a;">${props.Safety_ROI || "n/a"}</div>
                    </div>
                </div>
                <div class="popup-row" style="font-size:11px; color:var(--accent-cyan); font-style:italic;"><b>Simulated What-If Action:</b><br>${whatIfActionDetails}</div>
                ` : ''}
                ${(() => {
                  const oid = String(props.OBJECTID);
                  const hasVideo = frameData && frameData[oid] ? true : false;
                  return hasVideo ? `
                    <button onclick="event.stopPropagation(); playSimulation('\${oid}')" style="margin-top:10px; width:100%; padding:8px; background:linear-gradient(135deg, #00acc1, #00838f); color:#fff; border:none; border-radius:6px; cursor:pointer; font-weight:600; font-size:12px; transition: background 0.2s; box-shadow: none;">
                      ▶ Play ABM Simulation
                    </button>` : '';
                })()}
            </div>
        </div>`;
    }

    async function loadTop100() {
      if (!allGeojsonData) return;
      setStatus("Extracting Top 100 critical segments...");
      const filtered = getFilteredFeatures();
      const sorted = [...filtered].sort((a, b) => {
        return (a.properties.SpeedSafetyScore || 999) - (b.properties.SpeedSafetyScore || 999);
      }).slice(0, 100);

      map.getSource("segments").setData({
        type: "FeatureCollection",
        features: sorted
      });
      document.getElementById("loadedSegments").textContent = sorted.length.toString();
      updateScoreChart(sorted, currentMode === 'standard' ? 'SpeedSafetyScore' : 'WhatIf_SpeedSafetyScore');
      fitBbox(manifest.top100_bbox || manifest.bbox);
      setStatus("Displaying Top 100 priority segments.");
    }

    map.on("load", async () => {
      // Load Manifest
      manifest = await (await fetch("manifest.json")).json();
      document.getElementById("totalSegments").textContent = formatNumber(manifest.total_segments);
      document.getElementById("meanScore").textContent = manifest.mean_score.toFixed(1);
      document.getElementById("highRisk").textContent = formatNumber(manifest.high_risk_segments);

      const countries = [...new Set(manifest.clusters.map(c => c.country))].filter(c => c !== "Unknown");
      for (const country of countries) {
        const option = document.createElement("option");
        option.value = country;
        option.textContent = country;
        countryFilterEl.appendChild(option);
      }
      populateClusterSelector();

      // Register map source and layers
      map.addSource("segments", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "segments-line",
        type: "line",
        source: "segments",
        paint: {
          "line-color": scoreColorExpression("SpeedSafetyScore"),
          "line-width": ["interpolate", ["linear"], ["zoom"], 4, 1.2, 9, 3.5, 13, 6],
          "line-opacity": 0.9
        }
      });

      map.on("click", "segments-line", e => {
        if (!e.features || !e.features.length) return;
        new maplibregl.Popup({ maxWidth: '340px' })
          .setLngLat(e.lngLat)
          .setHTML(popupHtml(e.features[0].properties))
          .addTo(map);
      });
      map.on("mouseenter", "segments-line", () => map.getCanvas().style.cursor = "pointer");
      map.on("mouseleave", "segments-line", () => map.getCanvas().style.cursor = "");

      // Register custom SVG icons for high-contrast hazard shapes
      function addSvgIcon(name, svgMarkup) {
        const img = new Image(24, 24);
        const svg = new Blob([svgMarkup], {type: 'image/svg+xml;charset=utf-8'});
        const url = URL.createObjectURL(svg);
        img.onload = () => {
          map.addImage(name, img);
          URL.revokeObjectURL(url);
        };
        img.src = url;
      }

      addSvgIcon('hazard-v2v', `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24"><path d="M12 2L2 22h20L12 2z" fill="#ff5252" stroke="#ffffff" stroke-width="1.5"/></svg>`);
      addSvgIcon('hazard-v2o', `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24"><path d="M12 2L2 12l10 10 10-10L12 2z" fill="#ffeb3b" stroke="#ffffff" stroke-width="1.5"/></svg>`);
      addSvgIcon('hazard-vru', `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24"><path d="M8.25 2h7.5L22 8.25v7.5L15.75 22h-7.5L2 15.75v-7.5L8.25 2z" fill="#ff9800" stroke="#ffffff" stroke-width="1.5"/></svg>`);

      // __FRAME_DATA_PLACEHOLDER__
      if (typeof frameData !== 'undefined' && frameData) {
        initAbmReplayList();
      } else {
        try {
          const frameResp = await fetch("frame_data.json");
          if (frameResp.ok) {
            frameData = await frameResp.json();
            initAbmReplayList();
          }
        } catch (err) {
          console.error("Failed to load frame_data.json:", err);
        }
      }

      function initAbmReplayList() {
        const container = document.getElementById("abmReplayList");
        if (!frameData) {
          container.innerHTML = `<div style="font-size:11px; color:var(--text-muted); text-align:center; padding:10px;">No replay data available.</div>`;
          return;
        }
        const sids = Object.keys(frameData);
        if (sids.length === 0) {
          container.innerHTML = `<div style="font-size:11px; color:var(--text-muted); text-align:center; padding:10px;">No priority replays available.</div>`;
          return;
        }
        
        container.innerHTML = sids.map(sid => {
          return `
            <div style="padding: 10px; background: rgba(255,255,255,0.015); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); display: flex; flex-direction: column; gap: 4px;">
              <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:11.5px; font-weight:600; color:var(--text-primary);">Segment ${sid}</span>
                <span style="font-size:9.5px; background:var(--accent-orange-dim); color:var(--accent-orange); padding:1px 6px; border-radius:10px; font-weight:600; text-transform:uppercase;">Priority</span>
              </div>
              <button onclick="playSimulation('${sid}')" class="btn" style="padding: 6px 12px; font-size:11.5px; margin-top:4px;">
                ▶ Play ABM Simulation
              </button>
            </div>
          `;
        }).join("");
      }

      // Asynchronously fetch optimized GeoJSON network (chunked for GitHub Pages)
      setStatus("Downloading road network chunks...");
      try {
        const chunkNames = [
          "makenes_scored_optimized_part1.geojson",
          "makenes_scored_optimized_part2.geojson",
          "makenes_scored_optimized_part3.geojson"
        ];
        const chunkPromises = chunkNames.map(async (name, i) => {
          setStatus(`Downloading chunk ${i+1}/${chunkNames.length}...`);
          const resp = await fetch(name);
          if (!resp.ok) throw new Error(`Chunk ${name} fetch failed`);
          return resp.json();
        });
        const chunks = await Promise.all(chunkPromises);
        allGeojsonData = { type: "FeatureCollection", features: [] };
        for (const chunk of chunks) {
          allGeojsonData.features = allGeojsonData.features.concat(chunk.features);
        }
        
        map.getSource("segments").setData(allGeojsonData);
        updateMetricsAndChart(allGeojsonData.features);
        populateTop100List();
        fitBbox(manifest.bbox);
        setStatus("Network loaded. System ready.");
      } catch (err) {
        console.error("Failed to load optimized GeoJSON:", err);
        setStatus("Failed to load optimized network GeoJSON.");
      }

      // Asynchronously fetch conflicts GeoJSON (hazard markings) - chunked
      try {
        const confChunks = [
          "makenes_scored_conflicts_part1.geojson",
          "makenes_scored_conflicts_part2.geojson"
        ];
        const confPromises = confChunks.map(name => fetch(name).then(r => r.ok ? r.json() : null));
        const confParts = (await Promise.all(confPromises)).filter(Boolean);
        const conflictData = { type: "FeatureCollection", features: [] };
        for (const part of confParts) {
          conflictData.features = conflictData.features.concat(part.features);
        }
        if (conflictData.features.length > 0) {
          // Build index for O(1) segment lookups
          window.conflictIndex = {};
          conflictData.features.forEach(feat => {
            const sid = feat.properties.segment_id;
            if (sid !== undefined && sid !== null) {
              const sidStr = String(sid);
              if (!window.conflictIndex[sidStr]) {
                window.conflictIndex[sidStr] = { V2V: 0, V2O: 0, VRU: 0, total: 0 };
              }
              const t = feat.properties.type;
              if (t === 'V2V') window.conflictIndex[sidStr].V2V++;
              else if (t === 'V2O') window.conflictIndex[sidStr].V2O++;
              else if (t === 'VRU' || t === 'PET') window.conflictIndex[sidStr].VRU++;
              window.conflictIndex[sidStr].total++;
            }
          });
          // Re-populate the list to show hazard count labels
          populateTop100List();

          map.addSource('abm-conflicts', {
              type: 'geojson',
              data: conflictData,
              cluster: true,
              clusterMaxZoom: 14,
              clusterRadius: 20
          });

          // Add hazard layers
          map.addLayer({
              id: 'abm-clusters',
              type: 'circle',
              source: 'abm-conflicts',
              filter: ['has', 'point_count'],
              paint: {
                  'circle-color': [
                      'step',
                      ['get', 'point_count'],
                      'rgba(0, 229, 255, 0.6)',
                      100,
                      'rgba(255, 171, 64, 0.6)',
                      500,
                      'rgba(255, 82, 82, 0.6)'
                  ],
                  'circle-radius': [
                      'step',
                      ['get', 'point_count'],
                      15,
                      100,
                      20,
                      500,
                      25
                  ],
                  'circle-stroke-width': 1,
                  'circle-stroke-color': '#fff'
              }
          });

          map.addLayer({
              id: 'abm-cluster-count',
              type: 'symbol',
              source: 'abm-conflicts',
              filter: ['has', 'point_count'],
              layout: {
                  'text-field': '{point_count_abbreviated}',
                  'text-font': ['Open Sans Bold', 'Arial Unicode MS Bold'],
                  'text-size': 12
              },
              paint: {
                  'text-color': '#fff'
              }
          });

          map.addLayer({
              'id': 'abm-points',
              'type': 'symbol',
              'source': 'abm-conflicts',
              'filter': ['!', ['has', 'point_count']],
              'layout': {
                  'icon-image': [
                      'match',
                      ['get', 'type'],
                      'V2V', 'hazard-v2v',
                      'V2O', 'hazard-v2o',
                      'VRU', 'hazard-vru',
                      'PET', 'hazard-vru',
                      'hazard-v2v'
                  ],
                  'icon-size': [
                      'interpolate', ['linear'], ['zoom'],
                      4, 0.7,
                      9, 1.0,
                      13, 1.5
                  ],
                  'icon-allow-overlap': true
              }
          });

          map.on('click', 'abm-points', (e) => {
              const prop = e.features[0].properties;
              const type = prop.type;
              const ttc = (prop.ttc !== undefined && prop.ttc !== null) ? Number(prop.ttc).toFixed(2) : '0.00';
              const pet = (prop.pet !== undefined && prop.pet !== null) ? Number(prop.pet).toFixed(2) : '0.00';
              
              let title = type === 'PET' ? 'Near Miss (PET)' : `Simulated Conflict (${type})`;
              let color = type === 'VRU' ? '#e040fb' : type === 'V2V' ? '#ff5252' : type === 'V2O' ? '#40c4ff' : '#ffab40';
              
              let html = `<div style="color:#eceff1; font-family:'Inter',sans-serif; font-size:12px; padding:10px;">
                  <h4 style="margin:0 0 6px 0; color:${color}; font-family:'Outfit',sans-serif; font-size:14px;">${title}</h4>
                  <span style="font-size:9.5px; color:#080e14; background:${color}; padding:2px 6px; border-radius:10px; font-weight:600; text-transform:uppercase;">Simulated Conflict</span>
                  <hr style="margin:8px 0; border:0; border-top:1px solid rgba(255,255,255,0.06);">
                  ${type !== 'PET' ? `<b style="color:#8a9ba8;">Time-To-Collision:</b> <span style="font-weight:700; color:#eceff1;">${ttc}s</span><br>` : `<b style="color:#8a9ba8;">Post-Encroachment Time:</b> <span style="font-weight:700; color:#eceff1;">${pet}s</span><br>`}
                  <div style="font-size:10.5px; color:#8a9ba8; margin-top:8px; line-height:1.45; background:rgba(255,255,255,0.015); padding:8px; border-radius:6px; border:1px solid rgba(255,255,255,0.04);">
                      This simulated event indicates a conflict modeled by the agent swarm under stress.
                  </div>
              </div>`;

              new maplibregl.Popup({ maxWidth: '280px' })
                  .setLngLat(e.lngLat)
                  .setHTML(html)
                  .addTo(map);
          });
          
          map.on('mouseenter', 'abm-points', () => map.getCanvas().style.cursor = 'pointer');
          map.on('mouseleave', 'abm-points', () => map.getCanvas().style.cursor = '');
        }
      } catch (err) {
        console.error("Failed to load abm conflicts:", err);
      }
    });

    document.getElementById("applyFilters").addEventListener("click", applyMapFilter);
    document.getElementById("loadTop100").addEventListener("click", loadTop100);
    countryFilterEl.addEventListener("change", () => {
      populateClusterSelector();
      applyMapFilter();
    });
    clusterSelectEl.addEventListener("change", applyMapFilter);
    searchBoxEl.addEventListener("input", applyMapFilter);
    
    const scoreFilterEl = document.getElementById("scoreFilter");
    if (scoreFilterEl) scoreFilterEl.addEventListener("change", applyMapFilter);
    
    const toggleHazardsEl = document.getElementById("toggleOnlyHazards");
    if (toggleHazardsEl) toggleHazardsEl.addEventListener("change", applyMapFilter);
    
    document.getElementById("resetFilters").addEventListener("click", () => {
      countryFilterEl.value = "All";
      populateClusterSelector();
      searchBoxEl.value = "";
      if (document.getElementById("scoreFilter")) {
          document.getElementById("scoreFilter").value = "All";
      }
      if (document.getElementById("toggleOnlyHazards")) {
          document.getElementById("toggleOnlyHazards").checked = false;
      }
      applyMapFilter();
      fitBbox(manifest.bbox);
    });

    // Subtabs toggle logic
    const subtabFiltersEl = document.getElementById("subtabFilters");
    const subtabTop100El = document.getElementById("subtabTop100");
    const filtersContainerEl = document.getElementById("standardFiltersContainer");
    const top100ContainerEl = document.getElementById("standardTop100Container");

    function switchSubtab(subtab) {
      if (subtab === 'filters') {
        subtabFiltersEl.classList.add("active");
        subtabFiltersEl.style.background = "var(--accent-cyan-dim)";
        subtabFiltersEl.style.color = "var(--accent-cyan)";
        subtabTop100El.classList.remove("active");
        subtabTop100El.style.background = "transparent";
        subtabTop100El.style.color = "var(--text-secondary)";
        filtersContainerEl.style.display = "flex";
        top100ContainerEl.style.display = "none";
      } else {
        subtabFiltersEl.classList.remove("active");
        subtabFiltersEl.style.background = "transparent";
        subtabFiltersEl.style.color = "var(--text-secondary)";
        subtabTop100El.classList.add("active");
        subtabTop100El.style.background = "var(--accent-cyan-dim)";
        subtabTop100El.style.color = "var(--accent-cyan)";
        filtersContainerEl.style.display = "none";
        top100ContainerEl.style.display = "flex";
        populateTop100List();
      }
    }

    subtabFiltersEl.addEventListener("click", () => switchSubtab('filters'));
    subtabTop100El.addEventListener("click", () => switchSubtab('top100'));

    let top100SortedFeatures = [];

    function populateTop100List() {
      const listEl = document.getElementById("top100List");
      if (!allGeojsonData || !allGeojsonData.features) {
        listEl.innerHTML = `<div style="font-size:11px; color:var(--text-muted); text-align:center; padding:10px;">No network data loaded.</div>`;
        return;
      }
      
      const filtered = getFilteredFeatures();
      
      // Sort segments by SpeedSafetyScore ascending
      top100SortedFeatures = [...filtered]
        .filter(f => f.properties && f.properties.SpeedSafetyScore !== undefined)
        .sort((a, b) => a.properties.SpeedSafetyScore - b.properties.SpeedSafetyScore)
        .slice(0, 100);
        
      if (top100SortedFeatures.length === 0) {
        listEl.innerHTML = `<div style="font-size:11px; color:var(--text-muted); text-align:center; padding:10px;">No segments found.</div>`;
        return;
      }
      
      const getScoreColor = (score) => {
        if (score < 10) return "#d73027";
        if (score < 20) return "#f46d43";
        if (score < 30) return "#fdae61";
        if (score < 40) return "#fee08b";
        if (score < 50) return "#ffd54f";
        if (score < 60) return "#e6f598";
        if (score < 70) return "#d9ef8b";
        if (score < 80) return "#a6d96a";
        if (score < 90) return "#66bd63";
        return "#1a9850";
      };

      listEl.innerHTML = top100SortedFeatures.map((feat, index) => {
        const props = feat.properties;
        const s3 = Number(props.SpeedSafetyScore || 0).toFixed(1);
        const limit = props.SpeedLimit || 50;
        const f85 = Number(props.F85thPercentileSpeed || 0).toFixed(1);
        const zone = props.InferredZone || 'Generic Road';
        const roadName = props.english_ro || props.names_primary || `Segment ${props.OBJECTID}`;
        const oid = String(props.OBJECTID);
        
        // Show video button for any segment that has video data in frameData
        const hasVideo = frameData && frameData[oid];
        const showVideoButton = hasVideo;
        const videoBtn = showVideoButton ? `
          <button onclick="event.stopPropagation(); playSimulation('${oid}')" class="btn" style="padding:4px 8px; font-size:10px; margin-top:6px; background:linear-gradient(135deg, #00acc1, #00838f); border:none; color:white; width:auto; display:inline-block;">
            ▶ Play ABM Replay
          </button>` : '';

        // Tally of conflict hazards for sidebar
        const conflicts = window.conflictIndex ? window.conflictIndex[oid] : null;
        const conflictTally = conflicts && conflicts.total > 0 
          ? `<span style="font-size: 9px; padding: 1px 5px; border-radius: 3px; background: rgba(255, 82, 82, 0.15); color: #ff5252; border: 1px solid rgba(255, 82, 82, 0.3); font-weight: 600;">⚠️ ${conflicts.total} Conflicts</span>`
          : '';
          
        return `
          <div onclick="zoomToSegmentByIndex(${index})" style="padding: 10px; background: rgba(255,255,255,0.015); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); display: flex; flex-direction: column; gap: 4px; cursor: pointer; transition: background 0.15s, border-color 0.15s;" onmouseover="this.style.background='rgba(255,255,255,0.03)'; this.style.borderColor='var(--accent-cyan-dim)'" onmouseout="this.style.background='rgba(255,255,255,0.015)'; this.style.borderColor='var(--border-subtle)'">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="font-size:11.5px; font-weight:600; color:var(--text-primary); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:220px;">Rank ${index + 1}: ${roadName}</span>
              <span style="font-size:11px; font-weight:700; color:${getScoreColor(props.SpeedSafetyScore)};">${s3}</span>
            </div>
            <div style="font-size:10px; color:var(--text-secondary); display:flex; justify-content:space-between; align-items:center;">
              <span>Zone: ${zone} | Limit: ${limit} km/h | F85: ${f85} km/h</span>
              ${conflictTally}
            </div>
            ${videoBtn}
          </div>
        `;
      }).join("");
    }

    window.zoomToSegmentByIndex = function(idx) {
      const feat = top100SortedFeatures[idx];
      if (!feat) return;
      
      let coords = feat.geometry.coordinates;
      let centroid;
      if (feat.geometry.type === 'LineString') {
        const mid = Math.floor(coords.length / 2);
        centroid = coords[mid];
      } else if (feat.geometry.type === 'MultiLineString') {
        const line = coords[Math.floor(coords.length / 2)];
        centroid = line[Math.floor(line.length / 2)];
      } else {
        centroid = coords;
      }
      
      map.flyTo({
        center: centroid,
        zoom: 14,
        essential: true,
        duration: 1000
      });
      
      new maplibregl.Popup({ maxWidth: '340px' })
        .setLngLat(centroid)
        .setHTML(popupHtml(feat.properties))
        .addTo(map);
    };

    modeStandardEl.addEventListener("click", () => switchViewMode('standard'));
    modeWhatIfEl.addEventListener("click", () => switchViewMode('whatif'));

    document.getElementById("toggleAbmConflicts").addEventListener("change", (e) => {
        const vis = e.target.checked ? "visible" : "none";
        if (map.getLayer("abm-clusters")) map.setLayoutProperty("abm-clusters", "visibility", vis);
        if (map.getLayer("abm-cluster-count")) map.setLayoutProperty("abm-cluster-count", "visibility", vis);
        if (map.getLayer("abm-points")) map.setLayoutProperty("abm-points", "visibility", vis);
    });

    window.playSimulation = function(segmentId) {
      const data = frameData[segmentId];
      if (!data || !data.frames || data.frames.length === 0) return;
      const frames = data.frames;
      const shape = data.shape || [];
      
      // Create or get modal
      let modal = document.getElementById('abmModal');
      if (!modal) {
          modal = document.createElement('div');
          modal.id = 'abmModal';
          modal.style.position = 'fixed';
          modal.style.top = '0'; modal.style.left = '0';
          modal.style.width = '100%'; modal.style.height = '100%';
          modal.style.backgroundColor = 'rgba(0,0,0,0.9)';
          modal.style.zIndex = '9999';
          modal.style.display = 'flex';
          modal.style.flexDirection = 'column';
          modal.style.justifyContent = 'center';
          modal.style.alignItems = 'center';
          
          const closeBtn = document.createElement('button');
          closeBtn.innerText = 'Close';
          closeBtn.style.position = 'absolute';
          closeBtn.style.top = '20px'; closeBtn.style.right = '20px';
          closeBtn.style.padding = '10px 20px'; closeBtn.style.fontSize = '16px';
          closeBtn.style.cursor = 'pointer'; closeBtn.style.background = '#444';
          closeBtn.style.color = '#fff'; closeBtn.style.border = 'none'; closeBtn.style.borderRadius = '5px';
          closeBtn.onclick = () => {
              modal.style.display = 'none';
              window.cancelAnimationFrame(modal.animId);
              if (window.miniMapInstance) {
                  window.miniMapInstance.remove();
                  window.miniMapInstance = null;
              }
          };
          modal.appendChild(closeBtn);
          
          const title = document.createElement('h2');
          title.id = 'abmModalTitle';
          title.style.color = '#FFD54F';
          title.style.marginBottom = '10px';
          modal.appendChild(title);

          const frameCounter = document.createElement('div');
          frameCounter.id = 'frameCounter';
          frameCounter.style.color = '#4FC3F7';
          frameCounter.style.fontSize = '18px';
          frameCounter.style.fontWeight = 'bold';
          frameCounter.style.marginBottom = '10px';
          modal.appendChild(frameCounter);
          
          const mapContainer = document.createElement('div');
          mapContainer.id = 'abmMap';
          mapContainer.style.position = 'relative';
          mapContainer.style.width = '800px'; mapContainer.style.height = '600px';
          mapContainer.style.border = '2px solid #555'; mapContainer.style.borderRadius = '8px';
          
          const videoLegend = document.createElement('div');
          videoLegend.id = 'videoLegend';
          videoLegend.style.position = 'absolute';
          videoLegend.style.bottom = '20px';
          videoLegend.style.left = '20px';
          videoLegend.style.background = 'rgba(20, 20, 20, 0.9)';
          videoLegend.style.color = '#fff';
          videoLegend.style.padding = '10px 15px';
          videoLegend.style.borderRadius = '6px';
          videoLegend.style.border = '1px solid #444';
          videoLegend.style.fontFamily = 'sans-serif';
          videoLegend.style.fontSize = '12px';
          videoLegend.style.zIndex = '10000';
          videoLegend.innerHTML = `
              <h4 style="margin:0 0 8px 0; color:#FFD54F; font-size:13px;">Actor Legend</h4>
              <div style="margin-bottom:4px;"><span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:#e040fb; margin-right:6px; border:1px solid #fff; vertical-align:middle;"></span>Pedestrian</div>
              <div style="margin-bottom:4px;"><span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:#76ff03; margin-right:6px; border:1px solid #fff; vertical-align:middle;"></span>Cyclist</div>
              <div style="margin-bottom:4px;"><span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:#ffab40; margin-right:6px; border:1px solid #fff; vertical-align:middle;"></span>PTW (Motorcycle)</div>
              <div style="margin-bottom:4px;"><span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:#40c4ff; margin-right:6px; border:1px solid #fff; vertical-align:middle;"></span>Car</div>
              <div style="margin-bottom:4px;"><span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:#ff5252; margin-right:6px; border:1px solid #fff; vertical-align:middle;"></span>HGV (Truck)</div>
              <div><span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:#777; margin-right:6px; border:1px solid #fff; vertical-align:middle;"></span>Obstruction</div>
          `;
          mapContainer.appendChild(videoLegend);
          modal.appendChild(mapContainer);
          document.body.appendChild(modal);
      }
      
      modal.style.display = 'flex';
      document.getElementById('abmModalTitle').innerText = 'Segment ID: ' + segmentId + ' - ABM Physics Replay';
      document.getElementById('frameCounter').innerText = 'Loading segment satellite map patch...';
      
      if (window.miniMapInstance) {
          window.miniMapInstance.remove();
          window.miniMapInstance = null;
      }
      
      const miniMap = new maplibregl.Map({
          container: 'abmMap',
          style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
          center: shape[0] || [0,0],
          zoom: 17,
          interactive: true
      });
      window.miniMapInstance = miniMap;
      
      const bounds = new maplibregl.LngLatBounds();
      shape.forEach(p => bounds.extend(p));
      // Force MapLibre to resize after being placed in a visible container
      setTimeout(() => {
          miniMap.resize();
          miniMap.fitBounds(bounds, { padding: 80, animate: false });
      }, 50);
      
      miniMap.on('load', () => {
          miniMap.addSource('segment-line', {
              type: 'geojson',
              data: {
                  type: 'Feature',
                  geometry: {
                      type: 'LineString',
                      coordinates: shape
                  }
              }
          });
          
          miniMap.addLayer({
              id: 'segment-line-glow',
              type: 'line',
              source: 'segment-line',
              paint: {
                  'line-color': '#fff',
                  'line-width': 6,
                  'line-opacity': 0.4
              }
          });

          miniMap.addSource('actors', {
              type: 'geojson',
              data: { type: 'FeatureCollection', features: [] }
          });

          miniMap.addLayer({
              id: 'actor-points',
              type: 'circle',
              source: 'actors',
              paint: {
                  'circle-radius': [
                      'match',
                      ['get', 'type'],
                      'Pedestrian', 6,
                      'Cyclist', 7,
                      'Obstruction', 8,
                      10
                  ],
                  'circle-color': [
                      'match',
                      ['get', 'type'],
                      'Pedestrian', '#e040fb',
                      'Cyclist', '#76ff03',
                      'PTW', '#ffab40',
                      'HGV', '#ff5252',
                      'Obstruction', '#777',
                      '#40c4ff'
                  ],
                  'circle-opacity': 0.85,
                  'circle-stroke-width': 1.5,
                  'circle-stroke-color': '#ffffff'
              }
          });

          let currentFrame = 0;
          let lastTime = 0;
          function draw(time) {
              if (modal.style.display === 'none') return;
              
              if (time - lastTime > 60) { // ~15 frames per second
                  lastTime = time;
                  
                  if (currentFrame >= frames.length) {
                      currentFrame = 0;
                  }
                  
                  const actors = frames[currentFrame] || [];
                  const features = actors.map(a => ({
                      type: 'Feature',
                      geometry: {
                          type: 'Point',
                          coordinates: [a.x, a.y]
                      },
                      properties: {
                          id: a.id,
                          type: a.type
                      }
                  }));
                  
                  miniMap.getSource('actors').setData({
                      type: 'FeatureCollection',
                      features: features
                  });
                  
                  document.getElementById('frameCounter').innerText = 'Frame: ' + currentFrame + ' / ' + frames.length;
                  currentFrame++;
              }
              modal.animId = window.requestAnimationFrame(draw);
          }
          modal.animId = window.requestAnimationFrame(draw);
      });
    };
  </script>
</body>
</html>
"""

def generate(scored_geojson: Path, docs_dir: Path) -> None:
    import geopandas as gpd
    import pandas as pd
    import json
    import shutil
    import shapely
    import sys
    import os
    
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)
    
    print("Loading scored GeoJSON for optimization...")
    gdf = gpd.read_file(scored_geojson)
    
    whatif_geojson = scored_geojson.parent / "makenes_whatif_scored.geojson"
    if whatif_geojson.exists():
        print("Loading What-If GeoJSON and merging columns...")
        gdf_wi = gpd.read_file(whatif_geojson)
        # Cast OBJECTID to str in both to prevent type mismatches
        gdf['OBJECTID'] = gdf['OBJECTID'].astype(str)
        gdf_wi['OBJECTID'] = gdf_wi['OBJECTID'].astype(str)
        
        wi_cols = [
            'OBJECTID', 'SpeedSafetyScore', 'SpeedLimit', 'F85thPercentileSpeed', 'MedianSpeed', 
            'PercentOverLimit', 'SafeSystemAligned',
            'Score_Kinematics', 'Score_Friction', 'Score_VRU', 'Score_Speeding', 
            'Score_AI', 'Score_Stress', 'Score_Infrastructure'
        ]
        wi_cols = [c for c in wi_cols if c in gdf_wi.columns]
        df_wi_sub = gdf_wi[wi_cols].copy()
        
        rename_map = {
            'SpeedSafetyScore': 'WhatIf_SpeedSafetyScore',
            'SpeedLimit': 'WhatIf_SpeedLimit',
            'F85thPercentileSpeed': 'WhatIf_F85thPercentileSpeed',
            'MedianSpeed': 'WhatIf_MedianSpeed',
            'PercentOverLimit': 'WhatIf_PercentOverLimit',
            'SafeSystemAligned': 'WhatIf_SafeSystemAligned',
            'Score_Kinematics': 'WhatIf_Score_Kinematics',
            'Score_Friction': 'WhatIf_Score_Friction',
            'Score_VRU': 'WhatIf_Score_VRU',
            'Score_Speeding': 'WhatIf_Score_Speeding',
            'Score_AI': 'WhatIf_Score_AI',
            'Score_Stress': 'WhatIf_Score_Stress',
            'Score_Infrastructure': 'WhatIf_Score_Infrastructure'
        }
        df_wi_sub.rename(columns=rename_map, inplace=True)
        gdf = gdf.merge(df_wi_sub, on='OBJECTID', how='left')
    
    print("Filtering columns and simplifying geometries...")
    # Keep only the columns needed by the dashboard to minimize file size (exclude unused and redundant metrics)
    cols = [c for c in [
        'OBJECTID', 'SpeedSafetyScore', 'SafeSystemAligned', 'SubSupervisorID', 
        'names_primary', 'english_ro', 'RoadClass', 'SpeedLimit', 'F85thPercentileSpeed', 
        'MedianSpeed', 'PercentOverLimit', 'PopDensity_100m', 'POI_Schools_500m', 
        'OSM_Crossings_500m', 'OSM_Sidewalks_500m', 'OSM_StreetLighting_500m', 
        'Violated_Rules', 'WhatIf_Action_Details', 'geometry',
        'AI_Score_Adjustment', 'AI_SpeedIntervention', 'InferredZone',
        'SampleSize_avg', 'SegmentConflicts_VRU',
        'SegmentConflicts_V2V', 'SegmentConflicts_V2O', 'SegmentPETs',
        'BuildingDensity_100m', 'UrbanCentre_Pop',
        'Mapillary_Crosswalks', 'OSM_Cycleways_500m', 'Intervention_Cost', 'Safety_ROI',
        'Score_Kinematics', 
        'Score_Friction', 
        'Score_VRU', 
        'Score_Speeding', 
        'Score_AI', 
        'Score_Stress', 
        'Score_Infrastructure', 
        'Max_Kinematics', 
        'Max_Friction', 
        'Max_VRU', 
        'Max_Speeding', 
        'Max_AI', 
        'Max_Stress', 
        'Max_Infrastructure',
        'SpeedSafetyScore_PreShipRaw',
        'WhatIf_SpeedSafetyScore', 'WhatIf_SpeedLimit', 'WhatIf_F85thPercentileSpeed', 
        'WhatIf_MedianSpeed', 'WhatIf_PercentOverLimit', 'WhatIf_SafeSystemAligned',
        'WhatIf_Score_Kinematics', 
        'WhatIf_Score_Friction',
        'WhatIf_Score_VRU',
        'WhatIf_Score_Speeding',
        'WhatIf_Score_AI',
        'WhatIf_Score_Stress',
        'WhatIf_Score_Infrastructure'
    ] if c in gdf.columns]
    
    gdf_opt = gdf[cols].copy()
    
    # Categorize long repetitive text columns to reduce size
    lookup_tables = {}
    for col in ['AI_SpeedIntervention', 'WhatIf_Action_Details', 'Violated_Rules']:
        if col in gdf_opt.columns:
            gdf_opt[col] = gdf_opt[col].fillna('None').astype(str).str.strip()
            unique_vals = sorted(gdf_opt[col].unique())
            lookup_tables[col] = unique_vals
            val_to_code = {val: i for i, val in enumerate(unique_vals)}
            gdf_opt[col + '_code'] = gdf_opt[col].map(val_to_code)
            gdf_opt.drop(columns=[col], inplace=True)

    # Round float columns to 1 decimal place
    for col in gdf_opt.columns:
        if gdf_opt[col].dtype == 'float64' and col != 'geometry':
            gdf_opt[col] = gdf_opt[col].round(1)
            
    # Do not simplify geometries (keep raw coordinates for maximum detail)
    pass
        
    output_path = docs_dir / "makenes_scored_optimized.geojson"
    print(f"Saving optimized GeoJSON to {output_path}...")
    gdf_opt.to_file(output_path, driver="GeoJSON")
    
    # Post-process to round coordinates to 5 decimal places to preserve high detail
    print("Rounding coordinates in output GeoJSON to 5 decimal places...")
    try:
        import json
        with open(output_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        def rc(obj):
            if isinstance(obj, list):
                if len(obj) == 2 and isinstance(obj[0], (int, float)) and isinstance(obj[1], (int, float)):
                    return [round(obj[0], 5), round(obj[1], 5)]
                return [rc(x) for x in obj]
            elif isinstance(obj, dict):
                return {k: rc(v) for k, v in obj.items()}
            return obj
            
        data['features'] = [rc(f) for f in data['features']]
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, separators=(',', ':'))
        import os
        print(f"Compressed GeoJSON saved. Size: {os.path.getsize(output_path) / 1024 / 1024:.2f} MB")
        
        # Inline chunking to split the monolithic GeoJSON to stay strictly under GitHub file limits
        print("Invoking inline GeoJSON chunking to split optimized GeoJSON...")
        try:
            from scripts.setup_ghpages import split_geojson
            split_geojson(str(output_path))
            if output_path.exists():
                output_path.unlink()
                print("Monolithic optimized GeoJSON file deleted to preserve space.")
        except Exception as e:
            print(f"Failed to chunk/delete monolithic optimized GeoJSON: {e}")
    except Exception as e:
        print(f"Post-processing coordinate compression failed: {e}")
    
    # Calculate stats
    total_segments = len(gdf_opt)
    mean_score = float(gdf_opt['SpeedSafetyScore'].mean())
    high_risk_segments = int((gdf_opt['SpeedSafetyScore'] <= 30).sum())
    
    # Calculate bounding box
    bounds = gdf_opt.total_bounds # [minx, miny, maxx, maxy]
    bbox = [float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3])]
    
    # Sort top 100 to get their bounding box
    top100 = gdf_opt.sort_values(by="SpeedSafetyScore").head(100)
    top100_bounds = top100.total_bounds
    top100_bbox = [float(top100_bounds[0]), float(top100_bounds[1]), float(top100_bounds[2]), float(top100_bounds[3])]
    
    # Get unique countries or sub-supervisors for sidebar filters
    clusters_meta = []
    if 'SubSupervisorID' in gdf_opt.columns:
        clusters = gdf_opt['SubSupervisorID'].dropna().unique()
        for cluster in sorted(clusters):
            cluster_df = gdf_opt[gdf_opt['SubSupervisorID'] == cluster]
            country = "Thailand" if "thailand" in str(cluster).lower() else "India"
            clusters_meta.append({
                "id": str(cluster),
                "country": country,
                "count": len(cluster_df),
                "mean_score": float(cluster_df['SpeedSafetyScore'].mean()),
                "high_risk_count": int((cluster_df['SpeedSafetyScore'] <= 30).sum())
            })
            
    # Run Mesa ABM Simulation for Top 5 segments to generate playbacks (or load if exists)
    print("Running Mesa ABM Simulation for Top 5 segments...")
    try:
        frame_data_path = docs_dir / "frame_data.json"
        all_frame_logs = {}
        if frame_data_path.exists():
            print(f"   Loading existing frame logs from {frame_data_path} to skip simulation...")
            with open(frame_data_path, 'r', encoding='utf-8') as f:
                existing_logs = json.load(f)
                all_frame_logs = {int(k): v for k, v in existing_logs.items()}
        else:
            from prototypes.analytical_model.abm_engine import MaKeNeSABM
            from prototypes.analytical_model.network_topology import NetworkTopology
            gdf_copy = gdf.copy()
            gdf_copy['OBJECTID'] = pd.to_numeric(gdf_copy['OBJECTID'], errors='coerce').fillna(0).astype(int)
            
            # Build Network Topology
            print("   Building Network Topology for 1-hop neighbor loading...")
            topology = NetworkTopology(gdf_copy)
            
            # Filter replay candidates to visually meaningful segments (>= 200m)
            gdf_copy['geom_length_m'] = gdf_copy.geometry.length * 111320.0
            replay_candidates = gdf_copy[gdf_copy['geom_length_m'] >= 200.0]
            if replay_candidates.empty:
                replay_candidates = gdf_copy
            top_5_sids = replay_candidates.sort_values(by='SpeedSafetyScore', ascending=True).head(5)['OBJECTID'].values
            
            neighbor_sids = set()
            for sid in top_5_sids:
                neighbor_sids.update(topology.get_neighbors(sid))
                
            replay_sids = set(top_5_sids) | neighbor_sids
            top_5_segments = gdf_copy[gdf_copy['OBJECTID'].isin(replay_sids)]
            
            if not top_5_segments.empty:
                abm = MaKeNeSABM(top_5_segments, topology=topology, ptw_ratio=0.65)
                abm.video_sids = set(top_5_sids)
                _, _, _, frame_logs = abm.run_simulation(steps=600, region_id="chunked_dashboard")
                
                for frame_idx, frame_data in enumerate(frame_logs):
                    for actor in frame_data:
                        sid = actor.get('segment_id')
                        if sid is not None:
                            sid = int(sid)
                            if sid not in all_frame_logs:
                                all_frame_logs[sid] = {'frames': [], 'shape': []}
                            while len(all_frame_logs[sid]['frames']) <= frame_idx:
                                all_frame_logs[sid]['frames'].append([])
                            all_frame_logs[sid]['frames'][frame_idx].append(actor)

                # Inject LineString geometries
                for idx, row in gdf_copy.iterrows():
                    sid = int(row['OBJECTID'])
                    if sid in all_frame_logs and row.geometry:
                        coords_list = []
                        if row.geometry.geom_type == 'LineString':
                            coords_list = list(row.geometry.coords)
                        elif row.geometry.geom_type == 'MultiLineString':
                            for line in row.geometry.geoms:
                                coords_list.extend(list(line.coords))
                        # Convert tuples to list of lists [lng, lat]
                        coords_list = [[float(c[0]), float(c[1])] for c in coords_list]
                        all_frame_logs[sid]['shape'] = coords_list

            # Save to docs/frame_data.json
            print(f"Saving top 5 ABM simulation frame logs to {frame_data_path}...")
            with open(frame_data_path, 'w', encoding='utf-8') as f:
                json.dump({str(k): v for k, v in all_frame_logs.items()}, f)
    except Exception as e:
        print(f"Failed to run Mesa ABM simulation or save/load frame logs: {e}")

    # Clean up obsolete folders if they exist
    chunks_dir = docs_dir / "chunks"
    summary_dir = docs_dir / "summary"
    if chunks_dir.exists():
        shutil.rmtree(chunks_dir)
    if summary_dir.exists():
        shutil.rmtree(summary_dir)
        
    # Copy conflicts GeoJSON if it exists in the source directory
    conflicts_src = scored_geojson.parent / "makenes_scored_conflicts.geojson"
    if conflicts_src.exists():
        print(f"Copying conflicts GeoJSON to {docs_dir}...")
        conflicts_dest = docs_dir / "makenes_scored_conflicts.geojson"
        shutil.copy(conflicts_src, conflicts_dest)
        
        # Inline chunking for conflicts
        print("Invoking inline GeoJSON chunking for conflicts...")
        try:
            from scripts.setup_ghpages import split_geojson
            split_geojson(str(conflicts_dest))
            if conflicts_dest.exists():
                conflicts_dest.unlink()
                print("Monolithic conflicts GeoJSON file deleted to preserve space.")
        except Exception as e:
            print(f"Failed to chunk/delete monolithic conflicts GeoJSON: {e}")
        
    print("Writing manifest.json...")
    manifest_data = {
        "total_segments": total_segments,
        "mean_score": mean_score,
        "high_risk_segments": high_risk_segments,
        "bbox": bbox,
        "top100_bbox": top100_bbox,
        "clusters": clusters_meta,
        "lookup_tables": lookup_tables
    }
    
    with open(docs_dir / "manifest.json", "w") as f:
        json.dump(manifest_data, f)
        
    print("Writing index.html...")
    html_content = build_html()
    frame_data_str = json.dumps({str(k): v for k, v in all_frame_logs.items()})
    html_content = html_content.replace("// __FRAME_DATA_PLACEHOLDER__", f"frameData = {frame_data_str};")
    (docs_dir / "index.html").write_text(html_content, encoding="utf-8")
    print("Done!")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a static optimized MaKeNeS dashboard.")
    parser.add_argument("--scored-geojson", required=True, type=Path)
    parser.add_argument("--docs-dir", required=True, type=Path)
    args = parser.parse_args()
    generate(args.scored_geojson, args.docs_dir)


if __name__ == "__main__":
    main()
