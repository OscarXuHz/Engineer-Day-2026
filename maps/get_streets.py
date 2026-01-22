import osmnx as ox

from config import DIST, PLACE_POINT

# 1. Download the graph (drive + walk)
print("Downloading street network...")
G = ox.graph_from_point(PLACE_POINT, dist=DIST, network_type='walk')

# 2. Project to UTM (Meters) - CRITICAL for merging with satellite data
G_proj = ox.project_graph(G)

# 3. Save as GraphML (This is your checkpoint)
ox.save_graphml(G_proj, filepath='city_network.graphml')
print("Street network saved to city_network.graphml")