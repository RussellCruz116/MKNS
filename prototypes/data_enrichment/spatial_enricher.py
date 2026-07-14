"""
MaKeNeS Spatial Enricher
========================
Pre-processing module that attaches real-world spatial datasets to each road
segment *before* the S³ score calculator runs.

Datasets handled:
  1. GHS-POP 2025 rasters     → PopDensity_100m
  2. Google Open Buildings     → BuildingDensity_100m, BuildingCount_100m, AvgBuildingArea_m2
  3. GHSL Urban Centre DB      → UrbanCentre_Pop, UrbanCentre_GDP
  4. ADB ATO Workbooks         → Country_RSA_Fatalities, Country_RSA_FatalityTrend
  5. OSM Overpass API          → POI_Schools_500m, POI_Hospitals_500m, POI_Markets_500m, POI_Transit_500m
  6. Mapillary (stub)          → Mapillary_TrafficSigns, Mapillary_Crosswalks (requires token)
"""
import sys
import importlib

REQUIRED_PACKAGES = {
    "numpy": "numpy",
    "pandas": "pandas",
    "geopandas": "geopandas",
    "shapely": "shapely",
    "pyproj": "pyproj",
    "rasterio": "rasterio",
    "rasterstats": "rasterstats",
    "duckdb": "duckdb",
    "openpyxl": "openpyxl",
}

missing = []

for module, pip_name in REQUIRED_PACKAGES.items():
    if importlib.util.find_spec(module) is None:
        missing.append(pip_name)

if missing:
    print("=" * 70)
    print("ERROR: Missing required Python packages")
    print("=" * 70)
    print("\nInstall them using:\n")
    print(f"pip install {' '.join(missing)}")
    print("\nOr install everything from requirements.txt:")
    print("pip install -r requirements.txt")
    print("=" * 70)
    sys.exit(1)
import os
import time
import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path
import duckdb

# ------------------------------------------------------------------
# 5. OSM Overpass – Expanded with additional infrastructure features
# ------------------------------------------------------------------
# Updated POI categories now include cycleways, sidewalks, crossings,
# traffic calming, street lighting, barriers, road surface, lane count,
# max speed, and land use. These tags are queried in a single Overpass request.
# The processing logic below remains the same but now populates the new columns.

# --------------------------------------------------------------------------- #
#  Country bounding boxes for auto-detection and reverse-geocoding
# --------------------------------------------------------------------------- #
COUNTRY_BBOXES = {
    'india':    {'bbox': (68.0, 6.5, 97.5, 35.7),  'code': 'IND', 'prefix': 'ind'},
    'thailand': {'bbox': (97.3, 5.5, 105.7, 20.5),  'code': 'THA', 'prefix': 'tha'},
    'philippines': {'bbox': (116.0, 4.5, 127.0, 21.2), 'code': 'PHL', 'prefix': 'phl'},
    'vietnam':  {'bbox': (102.1, 8.2, 109.5, 23.4), 'code': 'VNM', 'prefix': 'vnm'},
    'cambodia': {'bbox': (102.3, 9.9, 107.7, 14.7), 'code': 'KHM', 'prefix': 'khm'},
    'myanmar':  {'bbox': (92.1, 9.5, 101.2, 28.5),  'code': 'MMR', 'prefix': 'mmr'},
    'bangladesh': {'bbox': (88.0, 20.6, 92.7, 26.6), 'code': 'BGD', 'prefix': 'bgd'},
    'nepal':    {'bbox': (80.0, 26.3, 88.2, 30.5),  'code': 'NPL', 'prefix': 'npl'},
    'sri lanka': {'bbox': (79.5, 5.9, 82.0, 10.0),  'code': 'LKA', 'prefix': 'lka'},
    'indonesia': {'bbox': (95.0, -11.0, 141.0, 6.1), 'code': 'IDN', 'prefix': 'idn'},
    'malaysia': {'bbox': (99.6, 0.8, 119.3, 7.4),   'code': 'MYS', 'prefix': 'mys'},
}


class SpatialEnricher:
    """
    Enriches a road-network GeoDataFrame with columns from external spatial
    datasets.  Designed to be called once before score_calculator.compute_scores().
    """

    def __init__(self, project_root, country=None):
        """
        Args:
            project_root (str): Absolute path to makenes_project/.
            country (str|None): Two-letter or full country name.  If None,
                                auto-detected from the network's bounding box.
        """
        self.root = Path(project_root)
        self.additional = self.root / 'data' / 'additional datasets'
        self.country_hint = country.lower().strip() if country else None
        self._detected_country = None
        try:
            from dotenv import load_dotenv
            load_dotenv(self.root / '.env')
        except Exception:
            pass

    def _is_cached(self, gdf, columns):
        if not all(c in gdf.columns for c in columns):
            return False
        for c in columns:
            if gdf[c].isna().all():
                return False
        return True

    def _load_cached_enrichment(self, gdf):
        db_path = self.root / 'db' / 'makenes.sqlite'
        if not db_path.exists():
            return gdf
            
        try:
            import sqlite3
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='scored_network_global'")
            if not cursor.fetchone():
                conn.close()
                return gdf
                
            columns_to_cache = [
                'PopDensity_100m', 'BuildingDensity_100m', 'BuildingCount_100m', 'AvgBuildingArea_m2',
                'UrbanCentre_Pop', 'UrbanCentre_GDP', 'Country_RSA_Fatalities', 'Country_RSA_FatalityTrend',
                'POI_Schools_500m', 'POI_Hospitals_500m', 'POI_Markets_500m', 'POI_Transit_500m',
                'OSM_Cycleways_500m', 'OSM_Sidewalks_500m', 'OSM_Crossings_500m', 'OSM_TrafficCalming_500m',
                'OSM_StreetLighting_500m', 'OSM_Barriers_500m', 'OSM_RoadSurface', 'OSM_RoadSmoothness', 'OSM_LaneCount',
                'OSM_MaxSpeed', 'OSM_LandUse', 'Mapillary_TrafficSigns', 'Mapillary_Crosswalks',
                'Overture_POI_Education_500m', 'Overture_POI_Healthcare_500m', 'Overture_POI_Retail_500m',
                'Overture_POI_Worship_500m', 'Overture_BuildingCount_200m'
            ]
            
            cursor.execute("PRAGMA table_info(scored_network_global)")
            table_cols = [row[1] for row in cursor.fetchall()]
            
            available_cols = [c for c in columns_to_cache if c in table_cols]
            if not available_cols or 'OBJECTID' not in table_cols:
                conn.close()
                return gdf
                
            query_cols = ['OBJECTID'] + available_cols
            query = f"SELECT {', '.join(query_cols)} FROM scored_network_global"
            cached_df = pd.read_sql_query(query, conn)
            conn.close()
            
            gdf['OBJECTID'] = pd.to_numeric(gdf['OBJECTID'], errors='coerce')
            cached_df['OBJECTID'] = pd.to_numeric(cached_df['OBJECTID'], errors='coerce')
            
            cached_df = cached_df.drop_duplicates(subset=['OBJECTID'])
            
            # Drop existing columns in gdf to prevent duplicates
            cols_to_drop = [c for c in cached_df.columns if c in gdf.columns and c != 'OBJECTID']
            if cols_to_drop:
                gdf = gdf.drop(columns=cols_to_drop)
                
            gdf_idx = gdf.index
            gdf = gdf.merge(cached_df, on='OBJECTID', how='left')
            gdf.index = gdf_idx
            
            print(f"  [Enricher] Loaded cached enrichment columns from SQLite: {available_cols}")
            
        except Exception as e:
            print(f"  [Enricher] Failed to load cached enrichment: {e}")
            
        return gdf

    # ------------------------------------------------------------------ #
    #  Public entry point
    # ------------------------------------------------------------------ #
    def enrich(self, network_gdf):
        """
        Main enrichment pipeline.  Returns the GeoDataFrame with new columns.
        Each sub-step is wrapped in try/except so a missing dataset never
        crashes the pipeline.
        """
        gdf = network_gdf.copy()

        # 0. Load cached data from SQLite database if available
        gdf = self._load_cached_enrichment(gdf)

        # 0. Detect country from geometry if not given
        self._detected_country = self._detect_country(gdf)
        print(f"  [Enricher] Detected country: {self._detected_country}")

        # 1. GHS-POP rasters → PopDensity_100m
        gdf = self._safe_run('GHS-POP Population', self._enrich_population, gdf)

        # 2. Google Open Buildings → BuildingDensity, BuildingCount, AvgBuildingArea
        gdf = self._safe_run('Google Open Buildings', self._enrich_buildings, gdf)

        # 3. GHSL Urban Centre Database → UrbanCentre_Pop, UrbanCentre_GDP
        gdf = self._safe_run('GHSL Urban Centre DB', self._enrich_ucdb, gdf)

        # 4. ADB ATO Road Safety → Country_RSA_Fatalities, Country_RSA_FatalityTrend
        gdf = self._safe_run('ADB ATO Road Safety', self._enrich_ato, gdf)

        # 5. OSM Overpass → POI counts within 500m
        gdf = self._safe_run('OSM Overpass POIs', self._enrich_osm_pois, gdf)

        # 6. Overture Maps integration (on‑the‑fly via DuckDB httpfs)
        gdf = self._safe_run('Overture Maps', self._enrich_overture_maps, gdf)

        # 7. Mapillary (stub — requires MAPILLARY_ACCESS_TOKEN)
        gdf = self._safe_run('Mapillary Features', self._enrich_mapillary, gdf)

        # 8. HeiGIT Road Surface & Smoothness (new datasets)
        gdf = self._safe_run('HeiGIT Road Surface', self._enrich_heigit_surface, gdf)

        return gdf

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #
    def _safe_run(self, label, func, gdf):
        try:
            print(f"  [Enricher] Running {label}...")
            return func(gdf)
        except Exception as e:
            print(f"  [Enricher] WARN: {label} skipped — {e}")
            return gdf

    def _detect_country(self, gdf):
        """Detect country from bounding box overlap."""
        if self.country_hint:
            # Direct match
            for name, info in COUNTRY_BBOXES.items():
                if self.country_hint in name or self.country_hint == info['code'].lower():
                    return name
            return self.country_hint  # fallback — use as-is

        # Auto-detect from geometry centroid
        bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]
        cx, cy = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
        for name, info in COUNTRY_BBOXES.items():
            bb = info['bbox']
            if bb[0] <= cx <= bb[2] and bb[1] <= cy <= bb[3]:
                return name
        return 'unknown'

    def _get_country_info(self):
        return COUNTRY_BBOXES.get(self._detected_country, {})

    def _estimate_metric_crs(self, gdf):
        """Return a local projected CRS suitable for meter-based buffers."""
        try:
            return gdf.estimate_utm_crs()
        except Exception:
            return 'EPSG:3857'

    def _buffer_in_meters(self, gdf, distance_m):
        metric_crs = self._estimate_metric_crs(gdf)
        buffered = gdf[['geometry']].copy().to_crs(metric_crs)
        buffered['geometry'] = buffered.geometry.buffer(distance_m)
        buffered['_idx'] = range(len(buffered))
        return buffered

    def _assign_counts(self, gdf, column, counts):
        gdf[column] = counts.reindex(range(len(gdf)), fill_value=0.0).round().astype(int).values

    def _get_cluster_bounds(self, gdf, grid_size=0.05):
        """
        Groups the road network geometries into localized bounding box clusters 
        (grid cells) to prevent enormous global bounding boxes.
        Returns a list of tuples: (minx, miny, maxx, maxy).
        """
        clusters = set()
        for geom in gdf.geometry:
            if geom is None or geom.is_empty:
                continue
            bounds = geom.bounds  # minx, miny, maxx, maxy
            # Assign to a grid based on the center of the geometry bounds
            cx = (bounds[0] + bounds[2]) / 2.0
            cy = (bounds[1] + bounds[3]) / 2.0
            grid_x = int(cx / grid_size)
            grid_y = int(cy / grid_size)
            
            # The cluster bounds cover exactly that grid cell
            c_minx = grid_x * grid_size
            c_miny = grid_y * grid_size
            c_maxx = c_minx + grid_size
            c_maxy = c_miny + grid_size
            
            # Add a small buffer/overlap of 0.01 degrees to ensure nodes at the edges are caught
            clusters.add((c_minx - 0.01, c_miny - 0.01, c_maxx + 0.01, c_maxy + 0.01))
            
        return list(clusters)

    # ------------------------------------------------------------------ #
    #  1. GHS-POP Population Rasters
    # ------------------------------------------------------------------ #
    def _enrich_population(self, gdf):
        if self._is_cached(gdf, ['PopDensity_100m']):
            print("    PopDensity_100m loaded from SQLite cache — skipping GHS-POP query.")
            return gdf

        # pyrefly: ignore [missing-import]
        from rasterstats import zonal_stats

        pop_dir = self.additional / 'Population'
        if not pop_dir.exists():
            gdf['PopDensity_100m'] = np.nan
            return gdf

        # Find all .tif files recursively
        tif_files = list(pop_dir.rglob('*.tif'))
        if not tif_files:
            gdf['PopDensity_100m'] = np.nan
            return gdf

        # Auto-detect overlapping tiles
        import rasterio
        network_bounds = gdf.total_bounds  # EPSG:4326 [minx, miny, maxx, maxy]

        # GHS-POP uses Mollweide (ESRI:54009), so we need to check tile bounds
        # in their native CRS, or reproject network bounds
        overlapping_tifs = []
        for tif_path in tif_files:
            try:
                with rasterio.open(tif_path) as src:
                    tif_bounds = src.bounds  # in tile's CRS
                    tif_crs = src.crs

                    # Reproject network bounds to tile CRS for comparison
                    from pyproj import Transformer
                    transformer = Transformer.from_crs('EPSG:4326', tif_crs, always_xy=True)
                    net_min_x, net_min_y = transformer.transform(network_bounds[0], network_bounds[1])
                    net_max_x, net_max_y = transformer.transform(network_bounds[2], network_bounds[3])

                    # Check overlap
                    if (net_min_x <= tif_bounds.right and net_max_x >= tif_bounds.left and
                        net_min_y <= tif_bounds.top and net_max_y >= tif_bounds.bottom):
                        overlapping_tifs.append(str(tif_path))
            except Exception:
                continue

        if not overlapping_tifs:
            print(f"    No overlapping GHS-POP tiles found for network extent")
            gdf['PopDensity_100m'] = np.nan
            return gdf

        print(f"    Found {len(overlapping_tifs)} overlapping GHS-POP tiles")

        # Reproject segment geometries to tile CRS for zonal stats
        # Use the CRS of the first overlapping tile
        with rasterio.open(overlapping_tifs[0]) as src:
            target_crs = src.crs

        # Buffer each segment by 100m using metric CRS, then project to target CRS
        buffered_gdf = self._buffer_in_meters(gdf, 100)
        gdf_proj = buffered_gdf.to_crs(target_crs)

        # Run zonal_stats for each tile and take max across tiles
        all_pop = np.full(len(gdf), np.nan)
        for tif_path in overlapping_tifs:
            try:
                with rasterio.open(tif_path) as src:
                    raster_bounds = src.bounds
                
                sindex = gdf_proj.sindex
                possible_idx = list(sindex.intersection(raster_bounds))
                if not possible_idx:
                    continue
                    
                sub_gdf = gdf_proj.iloc[possible_idx]
                stats = zonal_stats(
                    sub_gdf, tif_path,
                    stats=['mean'],
                    nodata=-200,
                    all_touched=True
                )
                tile_pop = np.array([s['mean'] if s['mean'] is not None else np.nan for s in stats])
                
                original_indices = sub_gdf.index.values
                current_vals = all_pop[original_indices]
                new_vals = np.where(np.isnan(current_vals), tile_pop, np.maximum(np.nan_to_num(current_vals), np.nan_to_num(tile_pop)))
                both_nan = np.isnan(current_vals) & np.isnan(tile_pop)
                new_vals[both_nan] = np.nan
                all_pop[original_indices] = new_vals
            except Exception as e:
                print(f"    Tile {Path(tif_path).name} failed: {e}")

        gdf['PopDensity_100m'] = np.clip(all_pop, 0.0, None)
        enriched_count = (gdf['PopDensity_100m'] > 0).sum()
        print(f"    Enriched {enriched_count}/{len(gdf)} segments with population data")
        return gdf

    # ------------------------------------------------------------------ #
    #  2. Google Open Buildings Rasters
    # ------------------------------------------------------------------ #
    def _enrich_buildings(self, gdf):
        cols = ['BuildingDensity_100m', 'BuildingCount_100m', 'AvgBuildingArea_m2']
        if self._is_cached(gdf, cols):
            print("    Google Open Buildings columns loaded from SQLite cache — skipping building query.")
            return gdf

        from rasterstats import zonal_stats
        import rasterio

        bldg_dir = self.additional / 'buildings data'
        if not bldg_dir.exists():
            for col in cols:
                gdf[col] = np.nan
            return gdf

        country_info = self._get_country_info()
        prefix = country_info.get('prefix', '')

        # Try country-specific subfolder
        country_dirs = [d for d in bldg_dir.iterdir() if d.is_dir()]
        target_dir = None
        for d in country_dirs:
            if self._detected_country and self._detected_country in d.name.lower():
                target_dir = d
                break
        if target_dir is None and country_dirs:
            target_dir = country_dirs[0]

        if target_dir is None:
            for col in ['BuildingDensity_100m', 'BuildingCount_100m', 'AvgBuildingArea_m2']:
                gdf[col] = np.nan
            return gdf

        # Map raster types to output columns
        raster_map = {
            'density': 'BuildingDensity_100m',
            'count': 'BuildingCount_100m',
            'mean_area': 'AvgBuildingArea_m2',
        }

        tif_files = list(target_dir.glob('*.tif'))

        for key, col_name in raster_map.items():
            matching = [f for f in tif_files if key in f.name.lower()]
            if not matching:
                gdf[col_name] = np.nan
                continue

            tif_path = str(matching[0])
            try:
                with rasterio.open(tif_path) as src:
                    target_crs = src.crs
                    nodata_val = src.nodata if src.nodata is not None else -9999
                    raster_bounds = src.bounds
                    
                buffered_gdf = self._buffer_in_meters(gdf, 100)
                gdf_proj = buffered_gdf.to_crs(target_crs)
                
                sindex = gdf_proj.sindex
                possible_idx = list(sindex.intersection(raster_bounds))
                
                col_vals = np.full(len(gdf), np.nan)
                if possible_idx:
                    sub_gdf = gdf_proj.iloc[possible_idx]
                    stats = zonal_stats(
                        sub_gdf, tif_path,
                        stats=['mean'],
                        nodata=nodata_val,
                        all_touched=True
                    )
                    values = np.array([s['mean'] if s['mean'] is not None and not np.isnan(s['mean']) else np.nan for s in stats])
                    col_vals[sub_gdf.index.values] = values
                
                gdf[col_name] = np.clip(col_vals, 0.0, None)
            except Exception as e:
                print(f"    Building raster '{key}' failed: {e}")
                gdf[col_name] = np.nan

        enriched_count = (gdf['BuildingDensity_100m'] > 0).sum()
        print(f"    Enriched {enriched_count}/{len(gdf)} segments with building data")
        return gdf

    # ------------------------------------------------------------------ #
    #  3. GHSL Urban Centre Database
    # ------------------------------------------------------------------ #
    def _enrich_ucdb(self, gdf):
        cols = ['UrbanCentre_Pop', 'UrbanCentre_GDP']
        if self._is_cached(gdf, cols):
            print("    UrbanCentre demographic columns loaded from SQLite cache — skipping UCDB query.")
            return gdf

        demo_dir = self.additional / 'Additional demographic data'
        if not demo_dir.exists():
            gdf['UrbanCentre_Pop'] = np.nan
            gdf['UrbanCentre_GDP'] = np.nan
            return gdf

        # Find .gpkg files — prefer regional ones
        gpkg_files = list(demo_dir.rglob('*.gpkg'))
        if not gpkg_files:
            gdf['UrbanCentre_Pop'] = np.nan
            gdf['UrbanCentre_GDP'] = np.nan
            return gdf

        # Load and merge all UCDB GeoPackages
        ucdb_frames = []
        for gpkg_path in gpkg_files:
            try:
                try:
                    import pyogrio
                    layers = set(pyogrio.list_layers(gpkg_path)[:, 0])
                except Exception:
                    layers = set()

                if 'GHSL_UCDB_THEME_SOCIOECONOMIC_GLOBE_R2024A' in layers:
                    ucdb = gpd.read_file(str(gpkg_path), layer='GHSL_UCDB_THEME_SOCIOECONOMIC_GLOBE_R2024A')
                else:
                    ucdb = gpd.read_file(str(gpkg_path))
                ucdb_frames.append(ucdb)
            except Exception as e:
                print(f"    UCDB file {gpkg_path.name} failed: {e}")

        if not ucdb_frames:
            gdf['UrbanCentre_Pop'] = np.nan
            gdf['UrbanCentre_GDP'] = np.nan
            return gdf

        ucdb_all = gpd.GeoDataFrame(pd.concat(ucdb_frames, ignore_index=True), crs=ucdb_frames[0].crs)
        if ucdb_all.crs is not None and ucdb_all.crs != gdf.crs:
            ucdb_all = ucdb_all.to_crs(gdf.crs)

        pop_col = next((col for col in ['P15', 'UC_p_2015', 'GC_POP_TOT_2025'] if col in ucdb_all.columns), None)
        gdp_col = next(
            (col for col in ['GDP15', 'SC_GDP_SUM_2020', 'SC_GDP_AVG_2020', 'SC_GDP_SUM_2015', 'SC_GDP_AVG_2015'] if col in ucdb_all.columns),
            None,
        )
        if pop_col is None:
            print("    UCDB missing a recognized population column")
            gdf['UrbanCentre_Pop'] = np.nan
            gdf['UrbanCentre_GDP'] = np.nan
            return gdf
        if gdp_col is None:
            ucdb_all['UrbanCentre_GDP'] = np.nan
            gdp_col = 'UrbanCentre_GDP'

        # Compute centroids of road segments for spatial join
        metric_crs = self._estimate_metric_crs(gdf)
        gdf_centroids = gdf[['geometry']].copy().to_crs(metric_crs)
        gdf_centroids['geometry'] = gdf_centroids.geometry.centroid
        ucdb_metric = ucdb_all[['geometry', pop_col, gdp_col]].to_crs(metric_crs)

        # Spatial join: nearest urban centre
        joined = gpd.sjoin_nearest(
            gdf_centroids, ucdb_metric.rename(
                columns={pop_col: 'UrbanCentre_Pop', gdp_col: 'UrbanCentre_GDP'}
            ),
            how='left',
            max_distance=50000
        )

        joined = joined[~joined.index.duplicated(keep='first')]
        gdf['UrbanCentre_Pop'] = joined['UrbanCentre_Pop'].reindex(gdf.index).fillna(np.nan).values
        gdf['UrbanCentre_GDP'] = joined['UrbanCentre_GDP'].reindex(gdf.index).fillna(np.nan).values

        enriched_count = (gdf['UrbanCentre_Pop'] > 0).sum()
        print(f"    Enriched {enriched_count}/{len(gdf)} segments with UCDB data")
        return gdf

    # ------------------------------------------------------------------ #
    #  4. ADB Asian Transport Outlook (ATO) Road Safety
    # ------------------------------------------------------------------ #
    def _enrich_ato(self, gdf):
        cols = ['Country_RSA_Fatalities', 'Country_RSA_FatalityTrend']
        if self._is_cached(gdf, cols):
            print("    ATO Road Safety columns loaded from SQLite cache — skipping ATO query.")
            return gdf

        ato_dir = self.additional / 'additional ADB data'
        if not ato_dir.exists():
            gdf['Country_RSA_Fatalities'] = np.nan
            gdf['Country_RSA_FatalityTrend'] = 'unknown'
            return gdf

        # Find the Road Safety workbook
        rsa_files = list(ato_dir.glob('*ROAD SAFETY*'))
        if not rsa_files:
            rsa_files = list(ato_dir.glob('*RSA*'))
        if not rsa_files:
            gdf['Country_RSA_Fatalities'] = np.nan
            gdf['Country_RSA_FatalityTrend'] = 'unknown'
            return gdf

        rsa_path = rsa_files[0]
        try:
            # Read all sheets
            sheets = pd.read_excel(rsa_path, sheet_name=None, engine='openpyxl')

            # Look for a sheet containing fatality data
            fatality_data = {}
            for sheet_name, df in sheets.items():
                # Normalize column names
                df.columns = [str(c).strip() for c in df.columns]

                # Look for country column and numeric data columns
                country_col = None
                for c in df.columns:
                    if 'country' in c.lower() or 'economy' in c.lower() or 'member' in c.lower():
                        country_col = c
                        break

                if country_col is None:
                    continue

                # Find numeric year columns (most recent data)
                year_cols = [c for c in df.columns if str(c).isdigit() and int(c) >= 2010]
                if not year_cols:
                    continue

                year_cols_sorted = sorted(year_cols, key=lambda x: int(x), reverse=True)

                for _, row in df.iterrows():
                    country_name = str(row.get(country_col, '')).strip().lower()
                    if not country_name or country_name == 'nan':
                        continue

                    # Get most recent non-null value
                    latest_val = None
                    prev_val = None
                    for yc in year_cols_sorted:
                        val = row.get(yc)
                        try:
                            val = float(val)
                            if not np.isnan(val):
                                if latest_val is None:
                                    latest_val = val
                                else:
                                    prev_val = val
                                    break
                        except (ValueError, TypeError):
                            continue

                    if latest_val is not None:
                        # Determine trend
                        trend = 'stable'
                        if prev_val is not None and prev_val > 0:
                            change_pct = (latest_val - prev_val) / prev_val
                            if change_pct > 0.05:
                                trend = 'worsening'
                            elif change_pct < -0.05:
                                trend = 'improving'

                        fatality_data[country_name] = {
                            'fatalities': latest_val,
                            'trend': trend,
                            'sheet': sheet_name
                        }

            if not fatality_data:
                gdf['Country_RSA_Fatalities'] = np.nan
                gdf['Country_RSA_FatalityTrend'] = 'unknown'
                return gdf

            # Match detected country
            country_info = self._get_country_info()
            matched = None
            for key in fatality_data:
                if (self._detected_country and self._detected_country in key) or \
                   (country_info.get('code', '').lower() in key):
                    matched = fatality_data[key]
                    break

            if matched:
                gdf['Country_RSA_Fatalities'] = matched['fatalities']
                gdf['Country_RSA_FatalityTrend'] = matched['trend']
                print(f"    ATO data: {matched['fatalities']} fatalities/100k ({matched['trend']})")
            else:
                gdf['Country_RSA_Fatalities'] = np.nan
                gdf['Country_RSA_FatalityTrend'] = 'unknown'
                print(f"    No ATO match for '{self._detected_country}' among {len(fatality_data)} countries")

        except Exception as e:
            print(f"    ATO Excel parsing failed: {e}")
            gdf['Country_RSA_Fatalities'] = np.nan
            gdf['Country_RSA_FatalityTrend'] = 'unknown'

        return gdf

    # ------------------------------------------------------------------ #
    #  5. OpenStreetMap Overpass API (POI counts)
    # ------------------------------------------------------------------ #
    def _enrich_osm_pois(self, gdf):
        """
        Query OSM Overpass API for schools, hospitals, markets, and transit stops
        using localized coordinate clusters to avoid timeout on large networks.
        """
        osm_cols = [
            'POI_Schools_500m', 'POI_Hospitals_500m', 'POI_Markets_500m', 'POI_Transit_500m',
            'OSM_Cycleways_500m', 'OSM_Sidewalks_500m', 'OSM_Crossings_500m'
        ]
        if self._is_cached(gdf, osm_cols):
            print("    OSM POI and Infrastructure columns loaded from SQLite cache — skipping OSM Overpass query.")
            return gdf

        import urllib.parse
        import json
        import urllib.request
        import ssl
        ssl._create_default_https_context = ssl._create_unverified_context
        import osmium
        from shapely.geometry import Point

        # Define POI categories using OSM tags
        poi_queries = {
            'POI_Schools_500m': '[amenity=school]',
            'POI_Hospitals_500m': '[amenity=hospital]',
            'POI_Markets_500m': '[shop=supermarket]',
            'POI_Transit_500m': '[highway=bus_stop]',
            'OSM_Cycleways_500m': '[highway=cycleway]',
            'OSM_Sidewalks_500m': '[footway=sidewalk]',
            'OSM_Crossings_500m': '[highway=crossing]',
            'OSM_TrafficCalming_500m': '["traffic_calming"]',
            'OSM_StreetLighting_500m': '[highway=street_lamp],["lit"="yes"]',
            'OSM_Barriers_500m': '["barrier"]',
            'OSM_RoadSurface': '["surface"]',
            'OSM_LaneCount': '["lanes"]',
            'OSM_MaxSpeed': '["maxspeed"]',
            'OSM_LandUse': '["landuse"]'
        }

        # Initialize columns
        for col in poi_queries:
            gdf[col] = np.nan

        # Dynamically determine the PBF file based on the country
        detected_country = getattr(self, '_detected_country', 'thailand').lower()
        if 'india' in detected_country:
            filename = 'india-latest.osm.pbf'
            url = "https://download.geofabrik.de/asia/india-latest.osm.pbf"
            size_est = "~1.2GB"
        else:
            filename = 'thailand-latest.osm.pbf'
            url = "https://download.geofabrik.de/asia/thailand-latest.osm.pbf"
            size_est = "~250MB"

        pbf_path = os.path.join(self.root, 'data', filename)
        os.makedirs(os.path.dirname(pbf_path), exist_ok=True)
        
        if not os.path.exists(pbf_path):
            print(f"    Downloading {pbf_path} from Geofabrik ({size_est})...")
            urllib.request.urlretrieve(url, pbf_path)
            print("    Download complete.")

        print("    Parsing local OSM PBF using PyOsmium...")
        poi_points = {col: [] for col in poi_queries}

        class OSMHandler(osmium.SimpleHandler):
            def __init__(self, pts_dict):
                super(OSMHandler, self).__init__()
                self.pts = pts_dict

            def _extract_tags(self, tags, lon, lat):
                amenity = tags.get('amenity', '')
                shop = tags.get('shop', '')
                highway = tags.get('highway', '')
                surface = tags.get('surface', '')
                lanes = tags.get('lanes', '')
                maxspeed = tags.get('maxspeed', '')
                barrier = tags.get('barrier', '')
                lighting = tags.get('lit', '') or tags.get('highway', '')
                landuse = tags.get('landuse', '')
                traffic_calming = tags.get('traffic_calming', '')

                if amenity == 'school': self.pts['POI_Schools_500m'].append((lon, lat))
                elif amenity == 'hospital': self.pts['POI_Hospitals_500m'].append((lon, lat))
                elif shop == 'supermarket': self.pts['POI_Markets_500m'].append((lon, lat))
                elif highway == 'bus_stop': self.pts['POI_Transit_500m'].append((lon, lat))

                if surface: self.pts.setdefault('OSM_RoadSurface', []).append((lon, lat, surface))
                if lanes: self.pts.setdefault('OSM_LaneCount', []).append((lon, lat, lanes))
                if maxspeed: self.pts.setdefault('OSM_MaxSpeed', []).append((lon, lat, maxspeed))
                if barrier: self.pts.setdefault('OSM_Barriers_500m', []).append((lon, lat))
                if traffic_calming: self.pts.setdefault('OSM_TrafficCalming_500m', []).append((lon, lat))
                if landuse: self.pts.setdefault('OSM_LandUse', []).append((lon, lat, landuse))
                if highway == 'street_lamp' or lighting == 'yes': self.pts['OSM_StreetLighting_500m'].append((lon, lat))
                if highway == 'cycleway' or tags.get('highway') == 'cycleway': self.pts['OSM_Cycleways_500m'].append((lon, lat))
                if tags.get('footway') == 'sidewalk' or highway == 'footway': self.pts['OSM_Sidewalks_500m'].append((lon, lat))
                if highway == 'crossing': self.pts['OSM_Crossings_500m'].append((lon, lat))

            def node(self, n):
                if not n.tags: return
                self._extract_tags(n.tags, n.location.lon, n.location.lat)

            def way(self, w):
                if not w.tags: return
                try:
                    loc = w.nodes[0].location
                    self._extract_tags(w.tags, loc.lon, loc.lat)
                except Exception:
                    pass

        handler = OSMHandler(poi_points)
        handler.apply_file(pbf_path, locations=True)

        # For each category, create a GeoDataFrame of POIs and spatial-join count
        for col, points in poi_points.items():
            if not points:
                continue
            
            # Deduplicate points to prevent double counting from overlapping cluster bboxes
            unique_points = list(set(points))

            if isinstance(unique_points[0], tuple) and len(unique_points[0]) == 3:
                geom_points = [(p[0], p[1]) for p in unique_points]
                attr_values = [p[2] for p in unique_points]
            else:
                geom_points = unique_points
                attr_values = None

            poi_gdf = gpd.GeoDataFrame(
                geometry=[Point(p) for p in geom_points],
                crs='EPSG:4326'
            )

            gdf_buffered = self._buffer_in_meters(gdf, 500)
            poi_gdf = poi_gdf.to_crs(gdf_buffered.crs)

            joined = gpd.sjoin(poi_gdf, gdf_buffered, predicate='within', how='inner')
            if not joined.empty:
                # Count how many segments each POI matched
                poi_degrees = joined.index.value_counts()
                # Compute fractional weight for each match to avoid duplicate count inflation
                joined['weight'] = 1.0 / joined.index.map(poi_degrees)
                counts = joined.groupby('_idx')['weight'].sum()
                self._assign_counts(gdf, col, counts)
                if attr_values is not None:
                    attr_lookup = pd.Series(attr_values, index=range(len(attr_values)))
                    attrs = joined.join(attr_lookup.rename('_attr'), how='left').groupby('_idx')['_attr'].agg(
                        lambda values: values.mode().iat[0] if not values.mode().empty else values.dropna().iat[0]
                    )
                    gdf[f"{col}_ATTR"] = attrs.reindex(range(len(gdf)), fill_value='').astype(str).values
            print(f"    {col}: {len(unique_points)} unique POIs found, {(gdf[col] > 0).sum()} segments enriched")

        return gdf

    # ------------------------------------------------------------------ #
    #  6. Overture Maps integration
    # ------------------------------------------------------------------ #
    def _enrich_overture_maps(self, gdf):
        """
        Query Overture Maps transportation and places data on‑the‑fly using DuckDB httpfs.
        Returns additional columns such as Overture_BuildingCount_200m, Overture_POI_* etc.
        """
        overture_cols = [
            'Overture_POI_Education_500m', 'Overture_POI_Healthcare_500m', 'Overture_POI_Retail_500m',
            'Overture_POI_Worship_500m', 'Overture_BuildingCount_200m'
        ]
        if self._is_cached(gdf, overture_cols):
            print("    Overture columns loaded from SQLite cache — skipping Overture query.")
            return gdf

        transport_url = 'https://data.overturemaps.org/transportation/2024-02-08/transportation.parquet'
        places_url = 'https://data.overturemaps.org/places/2024-02-08/places.parquet'

        for col in ['Overture_Surface', 'Overture_Lanes', 'Overture_Maxspeed']:
            gdf[col] = ''
        for col in [
            'Overture_POI_Education_500m',
            'Overture_POI_Healthcare_500m',
            'Overture_POI_Retail_500m',
            'Overture_POI_Worship_500m',
            'Overture_BuildingCount_200m',
        ]:
            gdf[col] = 0

        con = duckdb.connect(database=':memory:')
        try:
            con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
        except Exception as e:
            print(f"    DuckDB extension setup failed: {e}")
            return gdf

        def run_query(url, sql):
            return con.execute(f"SELECT * FROM read_parquet('{url}') WHERE {sql}").fetchdf()

        cluster_bounds = self._get_cluster_bounds(gdf, grid_size=0.1) # Slightly larger grid for Overture to reduce httpfs overhead
        print(f"    Divided network into {len(cluster_bounds)} spatial clusters for Overture.")

        all_transport = []
        all_places = []

        for cb in cluster_bounds:
            minx, miny, maxx, maxy = cb
            envelope_filter = f"ST_Intersects(geometry, ST_MakeEnvelope({minx}, {miny}, {maxx}, {maxy}, 4326))"

            try:
                transport_df = run_query(transport_url, envelope_filter)
                cols_of_interest = ['road_class', 'surface', 'lanes', 'maxspeed', 'geometry']
                for c in cols_of_interest:
                    if c not in transport_df.columns:
                        transport_df[c] = None
                transport_df = transport_df[cols_of_interest]
                transport_gdf = gpd.GeoDataFrame(transport_df, geometry='geometry', crs='EPSG:4326')
                if not transport_gdf.empty:
                    all_transport.append(transport_gdf)
            except Exception as e:
                pass

            try:
                places_df = run_query(places_url, envelope_filter)
                if 'categories' in places_df.columns:
                    places_df['category'] = places_df['categories'].apply(
                        lambda x: x.get('primary', '') if isinstance(x, dict) else ''
                    )
                else:
                    places_df['category'] = ''
                places_df = places_df[['category', 'geometry']]
                places_gdf = gpd.GeoDataFrame(places_df, geometry='geometry', crs='EPSG:4326')
                if not places_gdf.empty:
                    all_places.append(places_gdf)
            except Exception as e:
                pass

        if not all_transport and not all_places:
            print("    Overture queries returned no results.")
            return gdf

        gdf_buffered = self._buffer_in_meters(gdf, 20)

        # -----------------------------------------------------------------
        #  Process Transportation Data
        # -----------------------------------------------------------------
        if all_transport:
            transport_gdf = pd.concat(all_transport, ignore_index=True)
            transport_gdf['wkb'] = transport_gdf.geometry.apply(lambda g: g.wkb)
            transport_gdf = transport_gdf.drop_duplicates(subset=['wkb']).drop(columns=['wkb'])
            transport_gdf = transport_gdf.to_crs(gdf_buffered.crs)

            joined_transport = gpd.sjoin(transport_gdf, gdf_buffered, predicate='intersects', how='inner')
            if not joined_transport.empty:
                agg_funcs = {
                    'surface': lambda x: x.mode()[0] if not x.mode().empty else None,
                    'lanes': lambda x: int(x.mode()[0]) if not x.mode().empty else None,
                    'maxspeed': lambda x: int(x.mode()[0]) if not x.mode().empty else None,
                }
                transport_agg = joined_transport.groupby('_idx').agg(agg_funcs)
                for col, series in transport_agg.items():
                    gdf[f"Overture_{col.capitalize()}"] = series.reindex(range(len(gdf)), fill_value='').astype(str).values

        # -----------------------------------------------------------------
        #  Process Places Data
        # -----------------------------------------------------------------
        if all_places:
            places_gdf = pd.concat(all_places, ignore_index=True)
            places_gdf['wkb'] = places_gdf.geometry.apply(lambda g: g.wkb)
            places_gdf = places_gdf.drop_duplicates(subset=['wkb']).drop(columns=['wkb'])
            
            gdf_buffered_500 = self._buffer_in_meters(gdf, 500)
            places_gdf = places_gdf.to_crs(gdf_buffered_500.crs)

            poi_categories = {
                'Education': ['school', 'college', 'university'],
                'Healthcare': ['hospital', 'clinic', 'pharmacy'],
                'Retail': ['shop', 'market', 'supermarket'],
                'Worship': ['church', 'mosque', 'temple']
            }
            for cat_name, keywords in poi_categories.items():
                mask = places_gdf['category'].str.lower().isin(keywords)
                cat_gdf = places_gdf[mask]
                if not cat_gdf.empty:
                    joined_poi = gpd.sjoin(cat_gdf, gdf_buffered_500, predicate='within', how='inner')
                    counts = joined_poi.groupby('_idx').size()
                    self._assign_counts(gdf, f"Overture_POI_{cat_name}_500m", counts)
                else:
                    gdf[f"Overture_POI_{cat_name}_500m"] = 0

            # Building footprints count
            gdf_buffered_200 = self._buffer_in_meters(gdf, 200)
            building_mask = places_gdf['category'].str.lower() == 'building'
            building_gdf = places_gdf[building_mask]
            if not building_gdf.empty:
                joined_buildings = gpd.sjoin(building_gdf, gdf_buffered_200, predicate='within', how='inner')
                building_counts = joined_buildings.groupby('_idx').size()
                self._assign_counts(gdf, 'Overture_BuildingCount_200m', building_counts)
            else:
                gdf['Overture_BuildingCount_200m'] = 0

        return gdf

    # ------------------------------------------------------------------ #
    #  7. Mapillary Map Features (stub — needs access token)
    # ------------------------------------------------------------------ #
    def _enrich_mapillary(self, gdf):
        """
        Full Mapillary integration: fetch traffic signs and crosswalks using the Graph API with adaptive tiling.
        Utilises caching to avoid repeated requests for the same bbox.
        Requires MAPILLARY_ACCESS_TOKEN environment variable.
        """
        mapillary_cols = ['Mapillary_TrafficSigns', 'Mapillary_Crosswalks']
        if self._is_cached(gdf, mapillary_cols):
            print("    Mapillary columns loaded from SQLite cache — skipping Mapillary query.")
            return gdf

        token = os.environ.get('MAPILLARY_ACCESS_TOKEN', '').strip().strip('"').strip()
        # Initialize columns
        gdf['Mapillary_TrafficSigns'] = 0
        gdf['Mapillary_Crosswalks'] = 0
        
        if not token:
            print("    MAPILLARY_ACCESS_TOKEN not set — skipping Mapillary enrichment.")
            print("    To enable: set MAPILLARY_ACCESS_TOKEN env var from https://mapillary.com/dashboard/developers")
            return gdf
        
        import hashlib
        import json
        import urllib.request
        
        # Simple file‑based cache directory
        cache_dir = os.path.join(self.root, 'cache', 'mapillary')
        os.makedirs(cache_dir, exist_ok=True)
        
        initial_cluster_bounds = self._get_cluster_bounds(gdf, grid_size=0.01) 
        print(f"    Divided network into {len(initial_cluster_bounds)} spatial clusters for Mapillary (0.01 grid).")

        traffic_sign_points = []
        crosswalk_points = []
        request_count = 0
        consecutive_failures = 0
        max_requests = 50000
        
        import concurrent.futures
        import threading
        
        lock = threading.Lock()
        
        def process_cluster(cb):
            nonlocal request_count, consecutive_failures
            if request_count >= max_requests or consecutive_failures >= 50:
                return None, None
                
            min_lon, min_lat, max_lon, max_lat = cb
            bbox = (min_lon, min_lat, max_lon, max_lat)
            cache_key = hashlib.sha256(str(bbox).encode()).hexdigest()
            cache_path = os.path.join(cache_dir, f"{cache_key}.json")
            
            if os.path.exists(cache_path):
                with open(cache_path, 'r') as f:
                    data = json.load(f)
                return data, None
                
            bbox_str = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
            url = f"https://graph.mapillary.com/map_features?access_token={token}&fields=geometry,value&bbox={bbox_str}&layers=trafficsigns&limit=1000"
            
            features = []
            query_failed_with_500 = False
            query_failed_timeout = False
            while url:
                if consecutive_failures >= 50:
                    break
                try:
                    req = urllib.request.Request(url)
                    req.add_header('User-Agent', 'MaKeNeS-SafetyModel/1.0')
                    with urllib.request.urlopen(req, timeout=30) as response:
                        page_data = json.loads(response.read().decode('utf-8'))
                    
                    features.extend(page_data.get('data', []))
                    url = page_data.get('paging', {}).get('next')
                    with lock:
                        request_count += 1
                        consecutive_failures = 0
                    time.sleep(0.15)
                except urllib.error.HTTPError as e:
                    if e.code == 500:
                        query_failed_with_500 = True
                        break
                    else:
                        print(f"    Mapillary HTTP Error: {e}")
                        query_failed_timeout = True
                        with lock:
                            consecutive_failures += 1
                        break
                except Exception as e:
                    print(f"    Mapillary query failed: {e}")
                    query_failed_timeout = True
                    with lock:
                        consecutive_failures += 1
                    break
                    
            if query_failed_with_500:
                mid_lon = (min_lon + max_lon) / 2
                mid_lat = (min_lat + max_lat) / 2
                return None, [
                    (min_lon, min_lat, mid_lon, mid_lat),
                    (mid_lon, min_lat, max_lon, mid_lat),
                    (min_lon, mid_lat, mid_lon, max_lat),
                    (mid_lon, mid_lat, max_lon, max_lat)
                ]
            
            if query_failed_timeout or consecutive_failures >= 50:
                return None, None
                
            data = {'data': features}
            with open(cache_path, 'w') as f:
                json.dump(data, f)
            return data, None

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            # We use a set of futures to handle dynamic appending of new quadrants
            futures = {executor.submit(process_cluster, cb): cb for cb in initial_cluster_bounds}
            
            while futures:
                if consecutive_failures >= 50:
                    print("    [CIRCUIT BREAKER] 50 consecutive Mapillary failures — stopping enrichment to avoid infinite loop.")
                    for f in futures:
                        f.cancel()
                    break
                    
                done, _ = concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    futures.pop(future)
                    try:
                        data, new_bounds = future.result()
                        if new_bounds:
                            for nb in new_bounds:
                                futures[executor.submit(process_cluster, nb)] = nb
                        if data:
                            with lock:
                                for feat in data.get('data', []):
                                    geom = feat.get('geometry', {})
                                    coords = geom.get('coordinates', [])
                                    value = feat.get('value', '')
                                    if coords:
                                        if 'crosswalk' in value.lower() or 'pedestrian' in value.lower():
                                            crosswalk_points.append(tuple(coords))
                                        else:
                                            traffic_sign_points.append(tuple(coords))
                    except Exception as exc:
                        print(f"    Worker exception: {exc}")

        
        print(f"    Mapillary enrichment collected {len(traffic_sign_points)} traffic signs and {len(crosswalk_points)} crosswalks.")
        
        # Spatial join counts
        from shapely.geometry import Point
        for col, pts in [('Mapillary_TrafficSigns', traffic_sign_points), ('Mapillary_Crosswalks', crosswalk_points)]:
            if not pts:
                continue
            poi_gdf = gpd.GeoDataFrame(geometry=[Point(p) for p in pts], crs='EPSG:4326')
            gdf_buffered = self._buffer_in_meters(gdf, 200)
            poi_gdf = poi_gdf.to_crs(gdf_buffered.crs)
            joined = gpd.sjoin(poi_gdf, gdf_buffered, predicate='within', how='inner')
            if not joined.empty:
                # Count how many segments each point matched
                poi_degrees = joined.index.value_counts()
                # Compute fractional weight for each match to avoid duplicate count inflation
                joined['weight'] = 1.0 / joined.index.map(poi_degrees)
                counts = joined.groupby('_idx')['weight'].sum()
                self._assign_counts(gdf, col, counts)
        
        return gdf

    def _enrich_heigit_surface(self, gdf):
        """
        Enriches network segments with road surface and smoothness attributes
        from predicted HeiGIT GeoPackages. Spatial index queries are filtered 
        by network bounding box for high performance.
        """
        detected_country = getattr(self, '_detected_country', 'thailand').lower()
        if 'india' in detected_country:
            filename = 'heigit_ind_roadsurface_lines.gpkg'
        else:
            filename = 'heigit_tha_roadsurface_lines.gpkg'
            
        gpkg_path = self.additional / 'road segments, surface' / filename
        if not gpkg_path.exists():
            print(f"    HeiGIT GPKG {filename} not found — skipping surface enrichment.")
            gdf['OSM_RoadSurface'] = 'paved'
            gdf['OSM_RoadSmoothness'] = 'good'
            return gdf
            
        bbox = tuple(gdf.total_bounds)
        print(f"    Loading HeiGIT surface data within BBOX {bbox}...")
        try:
            import pyogrio
            heigit_gdf = pyogrio.read_dataframe(str(gpkg_path), bbox=bbox)
            if heigit_gdf.empty:
                print("    HeiGIT query returned no overlapping roads.")
                gdf['OSM_RoadSurface'] = 'paved'
                gdf['OSM_RoadSmoothness'] = 'good'
                return gdf
            
            if heigit_gdf.crs != gdf.crs:
                heigit_gdf = heigit_gdf.to_crs(gdf.crs)
                
            print(f"    Loaded {len(heigit_gdf)} HeiGIT segments. Running spatial join...")
            metric_crs = self._estimate_metric_crs(gdf)
            gdf_metric = gdf[['geometry']].copy().to_crs(metric_crs)
            heigit_metric = heigit_gdf[['surface', 'smoothness', 'pred_label', 'geometry']].copy().to_crs(metric_crs)
            
            # Match nearest
            joined = gpd.sjoin_nearest(gdf_metric, heigit_metric, max_distance=50, how='left')
            joined = joined[~joined.index.duplicated(keep='first')]
            
            # Map pred_label if surface is null
            surface_map = {1.0: 'paved', 0.0: 'unpaved', '1.0': 'paved', '0.0': 'unpaved'}
            surface_series = joined['surface'].fillna(joined['pred_label'].map(surface_map)).fillna('paved')
            smoothness_series = joined['smoothness'].fillna('good')
            
            gdf['OSM_RoadSurface'] = surface_series.values
            gdf['OSM_RoadSmoothness'] = smoothness_series.values
            
            unpaved_count = (gdf['OSM_RoadSurface'] == 'unpaved').sum()
            print(f"    HeiGIT surface enrichment complete: {unpaved_count} unpaved segments found.")
        except Exception as e:
            print(f"    HeiGIT surface enrichment failed: {e}")
            gdf['OSM_RoadSurface'] = 'paved'
            gdf['OSM_RoadSmoothness'] = 'good'
            
        return gdf
