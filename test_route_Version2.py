import osmnx as ox
import networkx as nx
import ast

print("Loading Engine...")
G = ox.load_graphml('game_ready_city.graphml')

# Sanity check: ensure every edge has a numeric cool_cost
missing_cool = 0
fixed_cool = 0
for _, _, _, data in G.edges(keys=True, data=True):
    if 'cool_cost' not in data or data['cool_cost'] is None:
        missing_cool += 1
        data['cool_cost'] = float(data.get('length', 10.0))
        continue

    val = data.get('cool_cost')
    try:
        data['cool_cost'] = float(val)
    except Exception:
        # Try to parse list-like strings (e.g., "[1.2]") and extract first value
        try:
            parsed = ast.literal_eval(val) if isinstance(val, str) else val
            if isinstance(parsed, (list, tuple)) and len(parsed) > 0:
                data['cool_cost'] = float(parsed[0])
            else:
                data['cool_cost'] = float(data.get('length', 10.0))
        except Exception:
            data['cool_cost'] = float(data.get('length', 10.0))
        fixed_cool += 1

if missing_cool > 0 or fixed_cool > 0:
    print(f"⚠️ Added fallback cool_cost to {missing_cool} edges, fixed {fixed_cool} invalid values.")

# Diagnostics: graph connectivity and weight health
print("Running diagnostics...")

# 1) Check for NaN/invalid cool_cost
invalid_cool = 0
for _, _, _, data in G.edges(keys=True, data=True):
    val = data.get('cool_cost', None)
    if val is None or not isinstance(val, (int, float)):
        invalid_cool += 1
    else:
        try:
            if val != val:  # NaN check
                invalid_cool += 1
        except Exception:
            invalid_cool += 1

print(f"Cool_cost invalid on {invalid_cool} edges.")

# 2) Ensure start/end nodes are in the same weakly connected component
components = list(nx.weakly_connected_components(G))
print(f"Weakly connected components: {len(components)}")

largest_comp = max(components, key=len) if components else set()
print(f"Largest component size: {len(largest_comp)}")

# Re-pick nodes from the largest component to ensure a path exists
if largest_comp:
    comp_nodes = list(largest_comp)
    start_node = comp_nodes[0]
    end_node = comp_nodes[min(50, len(comp_nodes) - 1)]

# Pick two random nodes (Source and Target)
nodes = list(G.nodes())
start_node = nodes[40]
end_node = nodes[90] # Pick one slightly far away

print(f"Routing from {start_node} to {end_node}...")

# 1. Calculate Fastest Path (Minimize 'length')
try:
    route_fast = nx.shortest_path(G, start_node, end_node, weight='length')
    len_fast = nx.path_weight(G, route_fast, weight='length')
    print(f"🏎️ Fastest Route: {int(len_fast)} meters")
except:
    print("No fast route found.")

# 2. Calculate Cool Path (Minimize 'cool_cost')
try:
    route_cool = nx.shortest_path(G, start_node, end_node, weight='cool_cost')
    len_cool_actual = nx.path_weight(G, route_cool, weight='length') # Actual walking distance
    print(f"🌳 Cool Route: {int(len_cool_actual)} meters (Might be longer, but cooler)")
except:
    print("No cool route found.")

# Comparison
if 'route_fast' in locals() and 'route_cool' in locals():
    if route_fast == route_cool:
        print("⚠️ Warning: Routes are identical. Increase the penalty factor in phase2_processing.py")
    else:
        print("✅ SUCCESS: The logic works! The Cool Route is different from the Fast Route.")