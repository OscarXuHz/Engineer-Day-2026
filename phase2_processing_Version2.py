import osmnx as ox
import pandas as pd
import networkx as nx
import geopandas as gpd
from sklearn.cluster import KMeans
import numpy as np

print("Loading data from Phase 1...")
# 1. Load the original structure (Nodes & Edges)
G = ox.load_graphml('maps/city_network.graphml')

# 2. Load your score data (The GeoJSON with the correct 0.0 - 1.0 scores)
gdf_scored = gpd.read_file('maps/final_city_streets_v2.geojson')

# 3. Inject the scores back into the Graph
# We create a dictionary to map IDs to scores for fast lookup
# OSMnx edges are identified by (u, v, key)
score_dict = {}
for idx, row in gdf_scored.iterrows():
    # We use the index or unique ID if preserved. 
    # Reliability Hack: We iterate through the Graph's edges and match by geometry or ID.
    # Since G and gdf_scored came from the same source, the order *should* be preserved, 
    # but let's be safe and iterate the graph directly to update it.
    pass

# simplified approach: Convert the Scored GeoJSON DIRECTLY back to a Graph
# We need the nodes and edges from the original graph to do this.
nodes, edges = ox.graph_to_gdfs(G)

# Ensure CRS matches
nodes = nodes.to_crs(gdf_scored.crs)
edges = edges.to_crs(gdf_scored.crs)

# Ensure the scored GeoDataFrame has a (u, v, key) MultiIndex
if isinstance(gdf_scored.index, pd.MultiIndex) and gdf_scored.index.nlevels == 3:
    gdf_scored_indexed = gdf_scored
elif {'u', 'v', 'key'}.issubset(gdf_scored.columns):
    gdf_scored_indexed = gdf_scored.set_index(['u', 'v', 'key'])
elif len(gdf_scored) == len(edges):
    # Fallback: preserve original edge order
    gdf_scored_indexed = gdf_scored.copy()
    gdf_scored_indexed.index = edges.index
else:
    raise ValueError(
        "Cannot rebuild edge index. Ensure GeoJSON includes 'u', 'v', 'key' columns "
        "or matches the original edge count."
    )

# Rebuild Graph
G_final = ox.graph_from_gdfs(nodes, gdf_scored_indexed)

print("Calculating Routing Weights...")

# 4. Define the HEI Formula (Heat Exposure Index)
# In Phase 1, High Score = Green (Good).
# In Phase 2, High HEI = Hot (Bad).
# So: HEI = 1.0 - Green_Score
for u, v, k, data in G_final.edges(keys=True, data=True):
    
    # Get the normalized Green Score (Default to 0.1 if missing)
    green_score = data.get('green_score', 0.1)
    
    # HEI: 0.0 (Cool/Park) -> 1.0 (Hot/Highway)
    hei = 1.0 - green_score
    data['hei'] = hei
    
    # WEIGHT 1: Pure Distance (for Fastest Path)
    # OSMnx usually calculates 'length', but let's ensure it's a float
    length = float(data.get('length', 10.0))
    
    # WEIGHT 2: Cool Impedance (The "Cost" of heat)
    # If a road is Hot (HEI=1), we multiply distance by 10.
    # Walking 100m on a hot road feels like walking 1000m.
    # If a road is Cool (HEI=0), we multiply by 1 (No penalty).
    penalty_factor = 1 + (hei * 10) 
    data['cool_cost'] = length * penalty_factor

# Ensure cool_cost is numeric for all edges
for _, _, _, data in G_final.edges(keys=True, data=True):
    val = data.get('cool_cost', None)
    try:
        data['cool_cost'] = float(val)
    except Exception:
        # Fallback to length if invalid
        data['cool_cost'] = float(data.get('length', 10.0))

print("Identifying Intervention Hotspots...")

# 5. Hotspot Clustering (Unsupervised ML)
# We want to find clusters of streets that are HOT (HEI > 0.8)
hot_streets = []
for u, v, k, data in G_final.edges(keys=True, data=True):
    if data['hei'] > 0.8:
        # Get the midpoint of the street for clustering
        # We need the Lat/Lon
        if 'geometry' in data:
            point = data['geometry'].centroid
            hot_streets.append([point.x, point.y])

# Convert to numpy array
X = np.array(hot_streets)

# Run K-Means to find 5 "Hot Zones"
# (This simulates finding the best places to plant trees)
if len(X) > 0:
    kmeans = KMeans(n_clusters=5, random_state=0).fit(X)
    centers = kmeans.cluster_centers_
    print(f"Found {len(centers)} hotspot centers.")
    
    # Save centers to a CSV for the App to load
    df_centers = pd.DataFrame(centers, columns=['x', 'y'])
    df_centers.to_csv('hotspots.csv', index=False)
else:
    print("No hot streets found? Check your HEI calculation.")

# 6. Sanitize boolean-like edge attributes for GraphML
# Some edges store list-like strings (e.g., "[ false, true ]") which break load_graphml.
def _sanitize_edge_bool(data, key):
    if key not in data:
        return
    val = data.get(key)
    if isinstance(val, (list, tuple, set)):
        data[key] = bool(val[0]) if len(val) > 0 else False
        return
    if isinstance(val, str):
        normalized = val.strip().lower()
        if normalized in {"true", "false", "1", "0"}:
            data[key] = normalized in {"true", "1"}
        else:
            # Drop invalid boolean-like strings
            data.pop(key, None)
        return

for _, _, _, data in G_final.edges(keys=True, data=True):
    _sanitize_edge_bool(data, 'reversed')
    _sanitize_edge_bool(data, 'oneway')

# 7. Save the Game-Ready Graph
ox.save_graphml(G_final, 'game_ready_city.graphml')
print("✅ Phase 2 Complete: 'game_ready_city.graphml' and 'hotspots.csv' saved.")