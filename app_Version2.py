import streamlit as st
import osmnx as ox
import networkx as nx
import folium
from streamlit_folium import st_folium
import pandas as pd
import random
import streamlit.components.v1 as components
import geopandas as gpd
from folium.plugins import HeatMap

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="CoolPath: Urban Heat Navigator", layout="wide")

st.title("🌡️ CoolPath: AI-Powered Urban Heat Navigator")
st.markdown("**Challenge 1: Sustainable Cities (SDG 11)** | *Routes for comfort, not just speed.*")

# --- 1. LOAD DATA (CACHED) ---
# We use @st.cache_resource so the graph only loads ONCE (speedy!)
@st.cache_resource
def load_data():
    # Load the Phase 2 Graph
    G = ox.load_graphml('game_ready_city.graphml')

    # Ensure CRS exists; if missing, infer from GeoJSON
    if 'crs' not in G.graph or G.graph['crs'] is None:
        try:
            gdf_scored = gpd.read_file('maps/final_city_streets_v2.geojson')
            if gdf_scored.crs is not None:
                G.graph['crs'] = gdf_scored.crs
        except Exception:
            try:
                gdf_scored = gpd.read_file('final_city_streets_v2.geojson')
                if gdf_scored.crs is not None:
                    G.graph['crs'] = gdf_scored.crs
            except Exception:
                pass

    # Build a lat/lon node lookup for mapping (Folium expects EPSG:4326)
    node_xy = {}
    try:
        edges_gdf = gpd.read_file('maps/final_city_streets_v2.geojson')
        if edges_gdf.crs is not None:
            edges_gdf = edges_gdf.to_crs(epsg=4326)
        for _, row in edges_gdf.iterrows():
            try:
                u = row.get('u')
                v = row.get('v')
                geom = row.get('geometry')
                if geom is None:
                    continue
                coords = list(geom.coords)
                if u is not None and len(coords) > 0:
                    node_xy[int(u)] = (coords[0][1], coords[0][0])
                if v is not None and len(coords) > 0:
                    node_xy[int(v)] = (coords[-1][1], coords[-1][0])
            except Exception:
                continue
    except Exception:
        node_xy = {}
    
    # Load Hotspots (if they exist)
    try:
        hotspots = pd.read_csv('hotspots.csv')
    except Exception:
        hotspots = pd.DataFrame()

    # Build heatmap points from edges GeoJSON (lat, lon, weight)
    heat_points = []
    try:
        edges_gdf = gpd.read_file('maps/final_city_streets_v2.geojson')
        if edges_gdf.crs is not None:
            edges_gdf = edges_gdf.to_crs(epsg=4326)
        for _, row in edges_gdf.iterrows():
            geom = row.get('geometry')
            if geom is None:
                continue
            centroid = geom.centroid
            # Use HEI-like weight (hotter = higher); fallback to 0.5
            green_score = row.get('green_score', 0.5)
            try:
                green_score = float(green_score)
            except Exception:
                green_score = 0.5
            heat = 1.0 - green_score
            heat_points.append([centroid.y, centroid.x, heat])
    except Exception:
        heat_points = []

    # Compute a safe map center (lat/lon)
    map_center = None
    try:
        gdf_center = gpd.read_file('maps/final_city_streets_v2.geojson')
        if gdf_center.crs is not None:
            gdf_center = gdf_center.to_crs(epsg=4326)
            centroid = gdf_center.unary_union.centroid
            map_center = [centroid.y, centroid.x]
    except Exception:
        try:
            gdf_center = gpd.read_file('final_city_streets_v2.geojson')
            if gdf_center.crs is not None:
                gdf_center = gdf_center.to_crs(epsg=4326)
                centroid = gdf_center.unary_union.centroid
                map_center = [centroid.y, centroid.x]
        except Exception:
            pass

    return G, node_xy, hotspots, map_center, heat_points

with st.spinner("Loading City Digital Twin..."):
    G, node_xy, df_hotspots, safe_center, heat_points = load_data()
    nodes_list = list(G.nodes())

# --- 2. SIDEBAR CONTROLS ---
st.sidebar.header("🕹️ Simulation Controls")

# Scenario Selector (The "Wizard of Oz" Demo Feature)
scenario = st.sidebar.radio(
    "Select Scenario:",
    ["Standard Day (25°C)", "Heatwave Alert (40°C)"]
)

# Simulation Logic: If Heatwave, we increase penalty
heat_multiplier = 10 # Default
if "Heatwave" in scenario:
    st.sidebar.error("⚠️ HEATWAVE ACTIVE: Penalties for unshaded roads increased by 200%!")
    heat_multiplier = 30 # Huge penalty for concrete

# Route Generator
st.sidebar.subheader("Plan a Route")
if st.sidebar.button("🎲 Generate Random Route"):
    # Pick random points from the largest connected component
    try:
        largest_comp = max(nx.weakly_connected_components(G), key=len)
        comp_nodes = list(largest_comp)
        start_node = random.choice(comp_nodes)
        end_node = random.choice(comp_nodes)
    except Exception:
        # Fallback: any nodes
        start_node = random.choice(nodes_list)
        end_node = random.choice(nodes_list)
    st.session_state['start'] = start_node
    st.session_state['end'] = end_node

# --- 3. MAIN LOGIC (ROUTING) ---
if 'start' in st.session_state:
    start = st.session_state['start']
    end = st.session_state['end']

    # Update weights dynamically based on Scenario
    # (We iterate slightly to adjust the 'cool_cost' for the current user setting)
    for u, v, k, data in G.edges(keys=True, data=True):
        # Ensure numeric types
        try:
            length = float(data.get('length', 10))
        except Exception:
            length = 10.0

        try:
            hei = float(data.get('hei', 0.5))
        except Exception:
            hei = 0.5

        # Recalculate cost based on sidebar slider
        data['current_cost'] = length * (1 + (hei * heat_multiplier))

    # Calculate Routes
    try:
        # 1. Fastest Path (Minimize Length)
        route_fast = nx.shortest_path(G, start, end, weight='length')
        len_fast = nx.path_weight(G, route_fast, weight='length')
        
        # 2. Coolest Path (Minimize 'current_cost')
        route_cool = nx.shortest_path(G, start, end, weight='current_cost')
        len_cool = nx.path_weight(G, route_cool, weight='length')

        # Persist routes for rendering
        st.session_state['route_fast'] = route_fast
        st.session_state['route_cool'] = route_cool
        
        # Calculate Stats
        saved_dist = int(len_cool - len_fast)
        
        # --- 4. DISPLAY METRICS ---
        col1, col2, col3 = st.columns(3)
        col1.metric("Fastest Route (Red)", f"{int(len_fast)} m", "High Heat Exposure", delta_color="inverse")
        col2.metric("CoolPath (Green)", f"{int(len_cool)} m", f"+{saved_dist}m longer", delta_color="normal")
        col3.metric("Current Condition", scenario)

    except Exception as e:
        st.error(f"Routing Error: {e}")
        route_fast = []
        route_cool = []
        st.session_state['route_fast'] = []
        st.session_state['route_cool'] = []

    if len(route_fast) < 2 or len(route_cool) < 2:
        st.warning("No valid route found for this random pair. Click Generate Random Route again.")

# --- 5. MAP RENDERING ---
# Get center of the map
if safe_center is not None:
    map_center = safe_center
elif 'start' in st.session_state and st.session_state['start'] in node_xy:
    map_center = [node_xy[st.session_state['start']][0], node_xy[st.session_state['start']][1]]
elif len(node_xy) > 0:
    first_node = next(iter(node_xy.values()))
    map_center = [first_node[0], first_node[1]]
else:
    map_center = [34.05, -118.25]

# --- 5. MAP RENDERING ---
m = folium.Map(location=map_center, zoom_start=15, tiles=None)

# Basemap switcher
folium.TileLayer("CartoDB positron", name="Light (CartoDB)").add_to(m)
folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)
folium.TileLayer("CartoDB dark_matter", name="Dark (CartoDB)").add_to(m)
folium.TileLayer(
    tiles="https://a.tile.opentopomap.org/{z}/{x}/{y}.png",
    name="Terrain (OpenTopo)",
    attr="Map data © OpenStreetMap contributors, SRTM | Map style © OpenTopoMap (CC-BY-SA)",
).add_to(m)

# Debug panel
with st.expander("Debug Map Data", expanded=False):
    st.write("Map center:", map_center)
    try:
        sample_key = next(iter(node_xy.keys())) if len(node_xy) > 0 else None
        st.write("Sample node:", sample_key, node_xy.get(sample_key))
    except Exception as e:
        st.write("Sample node error:", e)

# Draw Routes if they exist
if 'start' in st.session_state:
    # Get coordinates for lines
    # ox.utils_graph.get_route_edge_attributes is deprecated/complex in newer versions
    # easier to just pull node lat/lons

    route_fast = st.session_state.get('route_fast', [])
    route_cool = st.session_state.get('route_cool', [])

    if len(route_fast) > 1:
        coords_fast = [[node_xy[n][0], node_xy[n][1]] for n in route_fast if n in node_xy]
        with st.expander("Debug Routes", expanded=False):
            st.write("Fast coords sample:", coords_fast[:3])
        folium.PolyLine(coords_fast, color="red", weight=5, opacity=0.6, tooltip="Fastest Route").add_to(m)
        
        # Start/End Markers
        folium.Marker(coords_fast[0], popup="Start", icon=folium.Icon(color="blue")).add_to(m)
        folium.Marker(coords_fast[-1], popup="Destination", icon=folium.Icon(color="black")).add_to(m)

    if len(route_cool) > 1:
        coords_cool = [[node_xy[n][0], node_xy[n][1]] for n in route_cool if n in node_xy]
        with st.expander("Debug Routes", expanded=False):
            st.write("Cool coords sample:", coords_cool[:3])
        folium.PolyLine(coords_cool, color="green", weight=5, opacity=0.8, tooltip="CoolPath").add_to(m)

    # Always draw a marker to verify map renders
    if len(route_fast) > 0 and route_fast[0] in node_xy:
        folium.Marker([node_xy[route_fast[0]][0], node_xy[route_fast[0]][1]], popup="Start").add_to(m)

# Draw Hotspots (For the 'Planner' view)
# Toggle to show/hide
show_hotspots = st.checkbox("Show Priority Planting Zones (Planner View)")
if show_hotspots and not df_hotspots.empty:
    for idx, row in df_hotspots.iterrows():
        folium.CircleMarker(
            location=[row['y'], row['x']],
            radius=10,
            color="orange",
            fill=True,
            fill_color="orange",
            popup="🔥 High Heat / Low Canopy"
        ).add_to(m)

# Heatmap layer
show_heatmap = st.checkbox("Show Heatmap (Hotter = brighter)")
if show_heatmap and len(heat_points) > 0:
    HeatMap(heat_points, radius=12, blur=18, max_zoom=14, name="Heatmap").add_to(m)

folium.LayerControl(position="topright", collapsed=False).add_to(m)

# Render Map in Streamlit
# Use direct HTML rendering to avoid blank iframe issues with st_folium
components.html(m._repr_html_(), height=520)

# --- 6. EXPLANATION (For the Video Pitch) ---
st.markdown("---")
st.subheader("How it works")
st.write(f"""
- **Vegetation Data:** Sourced from Sentinel-2 Satellite (10m resolution).
- **Current Algorithm:** A* Routing with a dynamic penalty factor of **{heat_multiplier}x** for concrete surfaces.
- **SDG Impact:** Promotes walking (Health) while adapting to climate change (Resilience).
""")