import os
import sqlite3
import pandas as pd
import geopandas as gpd

class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        print(f"[DatabaseManager] Initializing connection to {self.db_path}")

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def store_network(self, network_gdf: gpd.GeoDataFrame, table_name: str):
        """ Stores a GeoDataFrame into SQLite by converting geometries to WKT strings. """
        if network_gdf.empty:
            return
            
        print(f"[DatabaseManager] Persisting {len(network_gdf)} segments to table '{table_name}'...")
        # Create a copy so we don't modify the active memory dataframe
        df = pd.DataFrame(network_gdf.copy())
        
        # Convert shapely geometry column to Well-Known Text (WKT) for plain SQLite compatibility
        if 'geometry' in df.columns:
            df['geometry_wkt'] = df['geometry'].apply(lambda x: x.wkt if x else None)
            df = df.drop(columns=['geometry'])
            
        # Convert any complex dicts/lists to JSON strings
        for col in df.columns:
            if df[col].apply(lambda x: isinstance(x, (dict, list))).any():
                df[col] = df[col].astype(str)

        with self.get_connection() as conn:
            df.to_sql(table_name, conn, if_exists='replace', index=False)
            
        print(f"[DatabaseManager] Successfully persisted {table_name}.")

    def store_conflicts(self, conflict_gdf: gpd.GeoDataFrame, table_name: str = "abm_conflicts"):
        """ Stores the raw synthetic conflict logs into SQLite. """
        if conflict_gdf is None or conflict_gdf.empty:
            return
            
        print(f"[DatabaseManager] Persisting {len(conflict_gdf)} ABM hazards to table '{table_name}'...")
        df = pd.DataFrame(conflict_gdf.copy())
        
        if 'geometry' in df.columns:
            df['geometry_wkt'] = df['geometry'].apply(lambda x: x.wkt if x else None)
            # Add lat/lon explicit columns for easy querying
            df['longitude'] = df['geometry'].apply(lambda x: x.x if x else None)
            df['latitude'] = df['geometry'].apply(lambda x: x.y if x else None)
            df = df.drop(columns=['geometry'])

        with self.get_connection() as conn:
            df.to_sql(table_name, conn, if_exists='replace', index=False)
            
        print(f"[DatabaseManager] Successfully persisted {table_name}.")

    def execute_query(self, query: str):
        with self.get_connection() as conn:
            return pd.read_sql_query(query, conn)

    def load_network(self, table_name: str) -> gpd.GeoDataFrame:
        """ Loads a SQLite table back into a GeoDataFrame using the geometry_wkt column. """
        print(f"[DatabaseManager] Loading network from table '{table_name}'...")
        with self.get_connection() as conn:
            df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
            
        from shapely.wkt import loads
        if 'geometry_wkt' in df.columns:
            df['geometry'] = df['geometry_wkt'].apply(lambda x: loads(x) if x else None)
            df = df.drop(columns=['geometry_wkt'])
            
        return gpd.GeoDataFrame(df, geometry='geometry', crs='EPSG:4326')
