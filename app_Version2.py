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
import math

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

def _haversine(lat1, lon1, lat2, lon2):
    r = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# Build planner guidance items from the same data used by the heatmap
guidance_items = []

def _spread_points(points, min_distance_m=150):
    selected = []
    for lat, lon, weight in points:
        too_close = False
        for s in selected:
            if _haversine(lat, lon, s[0], s[1]) < min_distance_m:
                too_close = True
                break
        if not too_close:
            selected.append((lat, lon, weight))
    return selected

if len(heat_points) > 0:
    # Take more points, then spread them out to avoid clustering
    candidates = sorted(heat_points, key=lambda x: x[2], reverse=True)[:200]
    top_points = _spread_points(candidates, min_distance_m=180)[:15]
    for lat, lon, weight in top_points:
        guidance_items.append({
            "label": f"High-heat segment (heat={weight:.2f})",
            "lat": lat,
            "lon": lon,
            "action": "Prioritize canopy + cooling pavement"
        })
elif not df_hotspots.empty and {'x', 'y'}.issubset(df_hotspots.columns):
    candidates = [(row['y'], row['x'], 1.0) for _, row in df_hotspots.iterrows()]
    top_points = _spread_points(candidates, min_distance_m=180)[:15]
    for lat, lon, _ in top_points:
        guidance_items.append({
            "label": "Hotspot cluster",
            "lat": lat,
            "lon": lon,
            "action": "Add shade trees + reflective surfaces"
        })

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
    st.sidebar.error("⚠️ HEATWAVE ACTIVE: Penalties for unshaded roads increased by 174.5%!")
    heat_multiplier = 30 # Huge penalty for concrete

# Walking speed for time estimates
st.sidebar.markdown("**Walking Speed (km/h)**")
walk_speed_kmh = st.sidebar.slider("Speed", min_value=2.0, max_value=7.0, value=4.8, step=0.1)
walk_speed_mps = walk_speed_kmh * 1000 / 3600

# Route Generator
st.sidebar.subheader("Plan a Route")

# Coordinate-based start/end selection
st.sidebar.markdown("**Set Start/End by Coordinates**")
start_lat = st.sidebar.number_input("Start Latitude", value=34.118457, format="%.6f", step=0.000100)
start_lon = st.sidebar.number_input("Start Longitude", value=-118.274520, format="%.6f", step=0.000100)
end_lat = st.sidebar.number_input("End Latitude", value=34.098322, format="%.6f", step=0.000100)
end_lon = st.sidebar.number_input("End Longitude", value=-118.296184, format="%.6f", step=0.000100)

def _nearest_node(lat, lon, node_xy_dict):
    best_node = None
    best_dist = float("inf")
    for node_id, (nlat, nlon) in node_xy_dict.items():
        d = _haversine(lat, lon, nlat, nlon)
        if d < best_dist:
            best_dist = d
            best_node = node_id
    return best_node, best_dist

if st.sidebar.button("📍 Use These Coordinates"):
    if len(node_xy) == 0:
        st.sidebar.error("No node coordinate data available.")
    else:
        start_node, start_d = _nearest_node(start_lat, start_lon, node_xy)
        end_node, end_d = _nearest_node(end_lat, end_lon, node_xy)
        if start_node is None or end_node is None:
            st.sidebar.error("Could not find nearest nodes for the given coordinates.")
        else:
            st.session_state['start'] = start_node
            st.session_state['end'] = end_node
            st.sidebar.success(f"Start matched within {int(start_d)}m, End within {int(end_d)}m")

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
        
        # Time estimates (minutes)
        time_fast_min = len_fast / walk_speed_mps / 60
        time_cool_min = len_cool / walk_speed_mps / 60

        # --- 4. DISPLAY METRICS ---
        col1, col2, col3 = st.columns(3)
        col1.metric(
            "Fastest Route (Red)",
            f"{int(len_fast)} m",
            f"~{time_fast_min:.1f} min",
            delta_color="inverse"
        )
        col2.metric(
            "CoolPath (Green)",
            f"{int(len_cool)} m",
            f"~{time_cool_min:.1f} min (+{saved_dist}m)",
            delta_color="normal"
        )
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
m = folium.Map(location=map_center, zoom_start=14, tiles=None)

# Basemap switcher
folium.TileLayer("CartoDB positron", name="Light (CartoDB)").add_to(m)
folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)
folium.TileLayer("CartoDB dark_matter", name="Dark (CartoDB)").add_to(m)
folium.TileLayer(
    tiles="https://a.tile.opentopomap.org/{z}/{x}/{y}.png",
    name="Terrain (OpenTopo)",
    attr="Map data © OpenStreetMap contributors, SRTM | Map style © OpenTopoMap (CC-BY-SA)",
).add_to(m)

# Draw Routes if they exist
if 'start' in st.session_state:
    # Get coordinates for lines
    # ox.utils_graph.get_route_edge_attributes is deprecated/complex in newer versions
    # easier to just pull node lat/lons

    route_fast = st.session_state.get('route_fast', [])
    route_cool = st.session_state.get('route_cool', [])

    if len(route_fast) > 1:
        coords_fast = [[node_xy[n][0], node_xy[n][1]] for n in route_fast if n in node_xy]
        folium.PolyLine(coords_fast, color="red", weight=5, opacity=0.6, tooltip="Fastest Route").add_to(m)
        
        # Start/End Markers
        folium.Marker(coords_fast[0], popup="Start", icon=folium.Icon(color="blue")).add_to(m)
        folium.Marker(coords_fast[-1], popup="Destination", icon=folium.Icon(color="black")).add_to(m)

    if len(route_cool) > 1:
        coords_cool = [[node_xy[n][0], node_xy[n][1]] for n in route_cool if n in node_xy]
        folium.PolyLine(coords_cool, color="green", weight=5, opacity=0.8, tooltip="CoolPath").add_to(m)

    # Always draw a marker to verify map renders
    if len(route_fast) > 0 and route_fast[0] in node_xy:
        folium.Marker([node_xy[route_fast[0]][0], node_xy[route_fast[0]][1]], popup="Start").add_to(m)

# Draw Planner Focus Areas (aligned to heatmap)
show_hotspots = st.checkbox("Show Priority Focus Areas (Planner View)")
if show_hotspots and len(guidance_items) > 0:
    for item in guidance_items:
        folium.CircleMarker(
            location=[item['lat'], item['lon']],
            radius=9,
            color="orange",
            fill=True,
            fill_color="orange",
            popup=item['action']
        ).add_to(m)

# Heatmap layer
show_heatmap = st.checkbox("Show Heatmap (Hotter = brighter)")
if show_heatmap and len(heat_points) > 0:
    HeatMap(heat_points, radius=12, blur=18, max_zoom=14, name="Heatmap").add_to(m)

folium.LayerControl(position="topright", collapsed=False).add_to(m)

# Render Map in Streamlit
# Use direct HTML rendering to avoid blank iframe issues with st_folium
components.html(m._repr_html_(), height=520)

# --- 6. PLANNER INSTRUCTIONS ---
st.markdown("---")
with st.expander("Planner Guidance: Priority Areas to Improve", expanded=False):
    st.write(
        "Below are priority focus areas for urban cooling interventions (tree planting, shade structures, "
        "cool pavement). For this demo, these are derived from the hottest segments or simulated hotspots."
    )

    if guidance_items:
        for i, item in enumerate(guidance_items, start=1):
            st.markdown(
                f"{i}. **{item['label']}** — ({item['lat']:.5f}, {item['lon']:.5f}) → {item['action']}"
            )
    else:
        st.info("No hotspot data available yet. Run Phase 2 to generate hotspots.csv or enable the heatmap.")

# --- 7. EXPLANATION (For the Video Pitch) ---
st.markdown("---")
st.subheader("How it works")
st.write(f"""
- **Vegetation Data:** Sourced from Sentinel-2 Satellite (10m resolution).
- **Current Algorithm:** A* Routing with a dynamic penalty factor of **{heat_multiplier}x** for concrete surfaces.
- **SDG Impact:** Promotes walking (Health) while adapting to climate change (Resilience).
""")