"""
Deterministic Tool API Layer
════════════════════════════
Provides exact, verified algorithmic tools for agents and controllers.
Agents invoke these tools rather than predicting node paths in raw text.

Core Tools:
  • tool_find_shortest_path       — Dijkstra shortest path on active graph
  • tool_get_k_diverse_routes     — K loop-free alternative routes for detour spreading
  • tool_route_travel_time        — Computes exact traversal duration along a path
  • tool_check_battery            — Verifies SoC >= travel_time * 1.15 buffer
  • tool_filter_available_fleet   — Filters operational vehicles with adequate range
"""

import networkx as nx
from itertools import islice

SOC_RATE_PER_MINUTE = 1.0   # 1.0% battery consumed per minute of driving
SOC_SAFETY_MARGIN   = 0.15  # 15% safety buffer


def tool_find_shortest_path(G, origin, destination):
    """
    Computes exact Dijkstra shortest path between origin and destination.
    Returns: (path_node_list, travel_time_minutes) or (None, inf)
    """
    try:
        path = nx.shortest_path(G, origin, destination, weight="travel_time")
        travel_time = sum(
            G[path[i]][path[i + 1]]["travel_time"] for i in range(len(path) - 1)
        )
        return path, travel_time
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None, float("inf")


def tool_get_k_diverse_routes(G, origin, destination, k=3):
    """
    Computes up to k diverse loop-free routes between origin and destination.
    Enables multi-agent coordination to spread detour traffic across multiple streets.
    Returns: list of (path_node_list, travel_time_minutes)
    """
    try:
        generator = nx.shortest_simple_paths(G, origin, destination, weight="travel_time")
        routes = []
        for path in islice(generator, k):
            tt = sum(G[path[i]][path[i + 1]]["travel_time"] for i in range(len(path) - 1))
            routes.append((path, tt))
        return routes
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []


def tool_route_travel_time(G, route):
    """
    Calculates exact travel time along a specified route on graph G.
    Returns: travel_time_minutes (float) or inf if any edge is missing/closed.
    """
    if not route or len(route) < 2:
        return float("inf")
    total_time = 0.0
    for i in range(len(route) - 1):
        u, v = route[i], route[i + 1]
        if G.has_edge(u, v):
            total_time += G[u][v]["travel_time"]
        else:
            return float("inf")
    return total_time


def tool_check_battery(vehicle, route_minutes):
    """
    Verifies if vehicle battery SoC is sufficient to complete the route.
    Formula: required_soc = route_minutes * 1.0% * (1 + 0.15)
    Returns: (is_feasible: bool, required_soc: float, remaining_soc: float)
    """
    required_soc = route_minutes * SOC_RATE_PER_MINUTE * (1.0 + SOC_SAFETY_MARGIN)
    current_soc = vehicle.get("soc", 0.0)
    is_feasible = (current_soc >= required_soc)
    return is_feasible, round(required_soc, 1), round(current_soc - required_soc, 1)


def tool_filter_available_fleet(fleet, min_soc=20):
    """
    Filters operational, non-broken vehicles with SoC above min_soc.
    """
    return [v for v in fleet if v["status"] == "available" and v["soc"] >= min_soc]
