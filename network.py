"""
Road Network Module
═══════════════════
Defines a 4×4 Manhattan urban grid with named intersections, named streets,
travel times, and capacity attributes.

Intersections (16 nodes):
    N0 (North Depot)       — N1 (North Ave)       — N2 (City Center)     — N3 (East Gate)
    |                         |                         |                         |
    N4 (West Station)      — N5 (Elm Square)      — N6 (Market Crossing) — N7 (Tech Park)
    |                         |                         |                         |
    N8 (Financial Dist)    — N9 (Main & 2nd)      — N10 (University)     — N11 (Civic Center)
    |                         |                         |                         |
    N12 (South Terminal)   — N13 (River Crossing) — N14 (Park View)      — N15 (Central Hospital)

Each edge has:
  • street_name (e.g., "1st Avenue", "Elm Street")
  • travel_time (minutes to traverse under free-flow)
  • capacity    (vehicles per hour)
"""

import copy
import networkx as nx

NODE_NAMES = {
    "N0": "North Depot",        "N1": "North Avenue",     "N2": "City Center",        "N3": "East Gate",
    "N4": "West Station",       "N5": "Elm Square",       "N6": "Market Crossing",    "N7": "Tech Park",
    "N8": "Financial District", "N9": "Main & 2nd",       "N10": "University",        "N11": "Civic Center",
    "N12": "South Terminal",    "N13": "River Crossing",  "N14": "Park View",         "N15": "Central Hospital"
}

# Named street segments for realistic text alerts
STREET_NAMES = {
    ("N0", "N1"): "North Boulevard",
    ("N1", "N2"): "Grand Avenue",
    ("N2", "N3"): "East Promenade",
    ("N4", "N5"): "Elm Street",
    ("N5", "N6"): "Pine Avenue",
    ("N6", "N7"): "Oak Way",
    ("N8", "N9"): "Market Street",
    ("N9", "N10"): "University Way",
    ("N10", "N11"): "Civic Highway",
    ("N12", "N13"): "River Road",
    ("N13", "N14"): "South Parkway",
    ("N14", "N15"): "Hospital Boulevard",
    
    # Verticals
    ("N0", "N4"): "West Ring Road",
    ("N1", "N5"): "1st Avenue",
    ("N2", "N6"): "Central Avenue",
    ("N3", "N7"): "East Ring Road",
    ("N4", "N8"): "Industrial Parkway",
    ("N5", "N9"): "2nd Avenue",
    ("N6", "N10"): "3rd Avenue",
    ("N7", "N11"): "Express Link",
    ("N8", "N12"): "Harbor Boulevard",
    ("N9", "N13"): "4th Avenue",
    ("N10", "N14"): "5th Avenue",
    ("N11", "N15"): "Emergency Access Route",
}


def create_network():
    """Create the base 4×4 Manhattan urban road network."""
    G = nx.Graph()

    # Add 16 nodes with positions and human names
    for i in range(16):
        node_id = f"N{i}"
        row, col = divmod(i, 4)
        G.add_node(node_id, pos=(col, 3 - row), name=NODE_NAMES[node_id])

    # Add 24 bidirectional edges with travel times & street names
    for (u, v), street in STREET_NAMES.items():
        row_u, col_u = divmod(int(u[1:]), 4)
        row_v, col_v = divmod(int(v[1:]), 4)
        is_horizontal = (row_u == row_v)
        
        # Base free-flow travel time (minutes)
        base_tt = 5.0 + (int(u[1:]) + int(v[1:])) % 3 if is_horizontal else 6.0 + (int(u[1:]) + int(v[1:])) % 3
        G.add_edge(u, v, travel_time=base_tt, free_flow_time=base_tt,
                   capacity=40, street_name=street)

    return G


def apply_disruptions(G_original, disruptions):
    """
    Apply active disruptions to create a disrupted network state.
    Returns: (G_disrupted, set_of_closed_edges)
    """
    G = copy.deepcopy(G_original)
    closed_edges = set()

    for d in disruptions:
        if d["type"] == "road_closure":
            u, v = d["edge"]
            if G.has_edge(u, v):
                G.remove_edge(u, v)
                closed_edges.add((u, v))
                closed_edges.add((v, u))
        elif d["type"] == "congestion":
            u, v = d["edge"]
            if G.has_edge(u, v):
                G[u][v]["travel_time"] *= d["factor"]

    return G, closed_edges
