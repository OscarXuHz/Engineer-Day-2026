import osmnx as ox
import rasterio
import pandas as pd
from shapely.geometry import Point

print("Loading data...")
# 1. Load the Street Network (from Step 2)
G = ox.load_graphml('city_network.graphml')

# 2. Load the NDVI Image
ndvi_src = rasterio.open('ndvi_final.tiff')

# 3. Convert Graph to GeoDataFrames (Nodes and Edges)
gdf_nodes, gdf_edges = ox.graph_to_gdfs(G)

# --- CRITICAL PROJECTION FIX ---
# We must project the streets to match the satellite image's CRS
target_crs = ndvi_src.crs
print(f"Reprojecting streets to match satellite CRS: {target_crs}")
gdf_edges = gdf_edges.to_crs(target_crs)

# 4. Sampling Function
def get_greenness_score(geometry):
    """
    Samples the NDVI image at the midpoint of the street.
    Returns a score: 0.0 (Concrete) to 1.0 (Lush Forest)
    """
    try:
        # Get the midpoint of the street segment
        midpoint = geometry.interpolate(0.5, normalized=True)
        
        # Get pixel coordinates (row, col) in the image
        row, col = ndvi_src.index(midpoint.x, midpoint.y)
        
        # Read the value at that pixel
        # usage: read(band_index, window=Window(col, row, 1, 1))
        # Note: rasterio uses ((row, row+1), (col, col+1)) for windows usually, 
        # but direct read by index is easier via reading the full array if small, 
        # or using the generator. 
        # Let's use the simplest robust method: sample the array we loaded.
        
        # Safe read using the window method is best for performance, 
        # but let's just read the whole small crop since we cropped it!
        data = ndvi_src.read(1)
        value = data[row, col]
        
        return float(value)
    except Exception as e:
        return 0.0 # Default to concrete if something fails

# 5. Apply the function to every street
print("Sampling vegetation data for all streets...")
gdf_edges['ndvi'] = gdf_edges['geometry'].apply(get_greenness_score)

print("Applying contrast stretching to fix East Hollywood scores...")

# 6. CLIP NEGATIVES
# Anything below 0 (water, shadows) is effectively dead concrete for our purpose.
# We set the floor to 0.0.
gdf_edges['ndvi_clean'] = gdf_edges['ndvi'].clip(lower=0.0)

# 7. SQUARING (The "Gamma Correction")
# This is the magic trick. Squaring a decimal makes small numbers MUCH smaller.
# Highway (0.1) -> 0.1 * 0.1 = 0.01 (Very Low score)
# Park (0.7)    -> 0.7 * 0.7 = 0.49 (Still decent)
gdf_edges['contrast_score'] = gdf_edges['ndvi_clean'] ** 2

# 8. MIN-MAX SCALING (Re-normalize to 0-1 range)
# We find the greenest street in East Hollywood and call that "1.0"
max_val = gdf_edges['contrast_score'].max()
min_val = gdf_edges['contrast_score'].min()

# Protect against divide by zero if your area is uniform
if max_val - min_val > 0:
    gdf_edges['green_score'] = (gdf_edges['contrast_score'] - min_val) / (max_val - min_val)
else:
    gdf_edges['green_score'] = gdf_edges['contrast_score']

# 9. (Optional) HARD THRESHOLDING
# If highways are still too high, force a penalty on main roads.
# 'highway' is a standard OSM tag.
def penalize_highways(row):
    # List of big road types
    highways = ['primary', 'secondary', 'tertiary', 'motorway', 'trunk']
    
    # Check if the 'highway' tag (road type) is in our list
    # Note: sometimes 'highway' is a list (e.g. ['primary', 'trunk']), so we convert to string
    road_type = str(row['highway'])
    
    if any(h in road_type for h in highways):
        return row['green_score'] * 0.5 # Penalty: Cut score in half
    return row['green_score']

# Apply the penalty
gdf_edges['green_score'] = gdf_edges.apply(penalize_highways, axis=1)

# Result Check
print("Data Fixed.")
print("Sample Highway Score:", gdf_edges[gdf_edges['highway'].astype(str).str.contains('primary')]['green_score'].mean())
# Should be closer to 0.1 or 0.2 now.


current_max = gdf_edges['green_score'].max()

if current_max > 0:
    # Divide everyone by the max score.
    # If the max was 0.3, then 0.3 / 0.3 becomes 1.0.
    # The highway (0.0001) / 0.3 becomes 0.0003 (still near zero).
    gdf_edges['green_score'] = gdf_edges['green_score'] / current_max

print(f"Scores Re-Normalized. Max is now: {gdf_edges['green_score'].max()}")
# Save again...


# 10. Save the enriched data
# Convert back to graph so we can use it for routing later
# Note: Saving directly as GeoJSON is often easier for Streamlit visualization
gdf_edges.to_file("final_city_streets_v2.geojson", driver="GeoJSON")

print("✅ Success: 'final_city_streets_v2.geojson' saved.")
print("   - This file contains your streets + their green scores.")
print("   - Use this file for Phase 2 (Routing).")