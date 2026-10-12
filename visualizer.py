"""
Interactive Visualization Module for Agentic Transport Disruption
══════════════════════════════════════════════════════════════════
Provides rich Plotly figures for:
  1. The 4×4 Manhattan Road Network (nodes, edges, disruptions, fleet, route overlays)
  2. Multi-controller benchmark comparison charts (RFR, RFR_w, HCVR, Latency, Cost)
"""

import plotly.graph_objects as go
from network import NODE_NAMES, STREET_NAMES

# 4×4 Manhattan Grid Coordinates:
# Row 0 (top): N0, N1, N2, N3 (y = 3)
# Row 1:      N4, N5, N6, N7 (y = 2)
# Row 2:      N8, N9, N10, N11 (y = 1)
# Row 3 (bot): N12, N13, N14, N15 (y = 0)
NODE_POSITIONS = {
    f"N{i * 4 + j}": (float(j), float(3 - i))
    for i in range(4)
    for j in range(4)
}

CONTROLLER_COLORS = {
    "B1_RuleBased": "#3b82f6",   # Blue
    "B2_SingleLLM": "#f59e0b",   # Amber / Orange
    "B3_MultiAgent": "#10b981",  # Emerald Green
    "B1": "#3b82f6",
    "B2": "#f59e0b",
    "B3": "#10b981"
}


def create_network_figure(
    G_disrupted=None,
    closed_edges=None,
    bottleneck_edges=None,
    fleet_states=None,
    requests=None,
    active_routes=None,
    selected_controller=None,
    title="2D Urban Road Network (4×4 Manhattan Grid)"
):
    """
    Renders an interactive Plotly map of the 4×4 Manhattan road network.
    
    Args:
        G_disrupted: NetworkX DiGraph after disruptions
        closed_edges: List of closed (u, v) tuples
        bottleneck_edges: List of congested (u, v) tuples
        fleet_states: List or dict of EV objects: [{"id": "V0", "loc": "N0", "soc": 80, "capacity": 4}]
        requests: List of requests [{"id": "R0", "origin": "N8", "dest": "N3", "priority": "emergency"}]
        active_routes: Dict or list of routes, e.g.:
                       {"B1": [["N0", "N4", "N8"]], "B2": [...], "B3": [...]}
                       or [{"controller": "B3", "request_id": "R0", "route": [...]}]
        selected_controller: Optional filter ('All', 'B1', 'B2', 'B3')
    """
    closed_set = set()
    if closed_edges:
        for u, v in closed_edges:
            closed_set.add((u, v))
            closed_set.add((v, u))

    congested_set = set()
    if bottleneck_edges:
        for u, v in bottleneck_edges:
            congested_set.add((u, v))
            congested_set.add((v, u))

    fig = go.Figure()

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Base Road Segments (Edges)
    # ─────────────────────────────────────────────────────────────────────────
    drawn_edges = set()
    for (u, v), street in STREET_NAMES.items():
        edge_key = tuple(sorted((u, v)))
        if edge_key in drawn_edges:
            continue
        drawn_edges.add(edge_key)

        x0, y0 = NODE_POSITIONS[u]
        x1, y1 = NODE_POSITIONS[v]

        is_closed = (u, v) in closed_set or (v, u) in closed_set
        is_congested = (u, v) in congested_set or (v, u) in congested_set

        # Determine edge styling
        if is_closed:
            color = "#ef4444"  # Red
            width = 5
            dash = "dash"
            status_desc = "⛔ CLOSED / IMPASSABLE"
        elif is_congested:
            color = "#f97316"  # Orange
            width = 4
            dash = "dot"
            status_desc = "⚠️ SEVERE CONGESTION (3× Travel Time)"
        else:
            color = "#94a3b8"  # Slate
            width = 3
            dash = "solid"
            status_desc = "✅ Normal Flow"

        # Edge line trace
        fig.add_trace(go.Scatter(
            x=[x0, x1],
            y=[y0, y1],
            mode="lines",
            line=dict(color=color, width=width, dash=dash),
            hoverinfo="text",
            hovertext=f"<b>{street}</b> ({u} ↔ {v})<br>Status: {status_desc}",
            showlegend=False
        ))

        # Midpoint marker for disruption badges
        if is_closed or is_congested:
            mid_x = (x0 + x1) / 2.0
            mid_y = (y0 + y1) / 2.0
            badge_symbol = "x" if is_closed else "triangle-up"
            fig.add_trace(go.Scatter(
                x=[mid_x],
                y=[mid_y],
                mode="markers",
                marker=dict(symbol=badge_symbol, size=14, color=color, line=dict(width=2, color="#ffffff")),
                hoverinfo="text",
                hovertext=f"<b>Disruption Alert</b>: {street}<br>{status_desc}",
                showlegend=False
            ))

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Overlay Vehicle / Request Routes
    # ─────────────────────────────────────────────────────────────────────────
    if active_routes:
        # Normalize active_routes into a list of dicts
        route_items = []
        if isinstance(active_routes, dict):
            for ctrl, r_list in active_routes.items():
                for item in r_list:
                    if isinstance(item, list):
                        route_items.append({"controller": ctrl, "route": item, "label": ctrl})
                    elif isinstance(item, dict):
                        item["controller"] = ctrl
                        route_items.append(item)
        elif isinstance(active_routes, list):
            route_items = active_routes

        # Filter by selected_controller if specified
        if selected_controller and selected_controller != "All":
            route_items = [r for r in route_items if r.get("controller") == selected_controller]

        # Shift offsets so multiple routes on same edge don't completely overlap
        offset_map = {"B1": -0.04, "B1_RuleBased": -0.04, "B2": 0.0, "B2_SingleLLM": 0.0, "B3": 0.04, "B3_MultiAgent": 0.04}

        for r_info in route_items:
            path = r_info.get("route", [])
            if not path or len(path) < 2:
                continue

            ctrl = r_info.get("controller", "Route")
            req_id = r_info.get("request_id", "")
            veh_id = r_info.get("vehicle_id", "")
            color = CONTROLLER_COLORS.get(ctrl, "#6366f1")
            offset = offset_map.get(ctrl, 0.0)

            xs, ys = [], []
            for n in path:
                if n in NODE_POSITIONS:
                    px, py = NODE_POSITIONS[n]
                    xs.append(px + offset)
                    ys.append(py + offset)

            label = f"{ctrl}: Req {req_id} (Veh {veh_id})" if req_id else f"{ctrl} Path"
            fig.add_trace(go.Scatter(
                x=xs,
                y=ys,
                mode="lines+markers",
                line=dict(color=color, width=4),
                marker=dict(size=8, color=color),
                hoverinfo="text",
                hovertext=f"<b>{label}</b><br>Route: {' → '.join(path)}",
                name=label,
                showlegend=True
            ))

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Intersections (Nodes)
    # ─────────────────────────────────────────────────────────────────────────
    node_x, node_y, node_text, node_hover, node_colors = [], [], [], [], []
    for node_id, (x, y) in NODE_POSITIONS.items():
        node_x.append(x)
        node_y.append(y)
        node_text.append(node_id)
        name = NODE_NAMES.get(node_id, node_id)
        
        # Color coding special nodes
        if node_id == "N15":  # Central Hospital
            c = "#ef4444"     # Emergency red
            hover = f"🏥 <b>{name} ({node_id})</b><br>Central Emergency Hospital (Critical Triage Destination)"
        elif node_id == "N0":   # North Depot
            c = "#3b82f6"     # Blue
            hover = f"🏢 <b>{name} ({node_id})</b><br>Primary Transit Operations Depot"
        elif node_id in ("N3", "N4", "N7", "N12"): # Transit hubs
            c = "#8b5cf6"     # Purple
            hover = f"🚏 <b>{name} ({node_id})</b><br>Major Passenger Transit Station"
        else:
            c = "#1e293b"     # Slate dark
            hover = f"📍 <b>{name} ({node_id})</b><br>Manhattan Grid Intersection"
        
        node_colors.append(c)
        node_hover.append(hover)

    fig.add_trace(go.Scatter(
        x=node_x,
        y=node_y,
        mode="markers+text",
        marker=dict(size=26, color=node_colors, line=dict(width=2, color="#ffffff")),
        text=node_text,
        textfont=dict(color="#ffffff", size=11, family="Arial Black"),
        textposition="middle center",
        hoverinfo="text",
        hovertext=node_hover,
        showlegend=False
    ))

    # ─────────────────────────────────────────────────────────────────────────
    # 4. EV Fleet Status Markers
    # ─────────────────────────────────────────────────────────────────────────
    if fleet_states:
        fleet_list = fleet_states if isinstance(fleet_states, list) else fleet_states.values()
        for veh in fleet_list:
            v_id = veh.get("id") or veh.get("vehicle_id", "V")
            loc = veh.get("loc") or veh.get("current_node", "N0")
            soc = veh.get("soc", 100)
            cap = veh.get("capacity", 4)
            is_operable = veh.get("operable", True)

            if loc in NODE_POSITIONS:
                px, py = NODE_POSITIONS[loc]
                # Offset slightly from node center so node ID remains readable
                vx = px - 0.18
                vy = py + 0.18
                
                status_icon = "⚡" if is_operable else "❌"
                status_desc = f"SoC: {soc}% | Cap: {cap} seats" if is_operable else "BREAKDOWN (Non-operable)"
                marker_color = "#10b981" if (is_operable and soc >= 50) else ("#f59e0b" if is_operable else "#ef4444")

                fig.add_trace(go.Scatter(
                    x=[vx],
                    y=[vy],
                    mode="markers+text",
                    marker=dict(symbol="square", size=18, color=marker_color, line=dict(width=1.5, color="#ffffff")),
                    text=[v_id],
                    textfont=dict(color="#ffffff", size=9, family="Arial Bold"),
                    textposition="middle center",
                    hoverinfo="text",
                    hovertext=f"<b>EV Fleet: {v_id}</b> {status_icon}<br>Location: {loc} ({NODE_NAMES.get(loc, '')})<br>{status_desc}",
                    showlegend=False
                ))

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Passenger Requests (Origin & Destination)
    # ─────────────────────────────────────────────────────────────────────────
    if requests:
        for req in requests:
            r_id = req.get("id", "R")
            orig = req.get("origin")
            dest = req.get("dest")
            priority = req.get("priority", "standard")
            is_emer = (priority == "emergency")

            # Origin marker
            if orig in NODE_POSITIONS:
                ox, oy = NODE_POSITIONS[orig]
                fig.add_trace(go.Scatter(
                    x=[ox + 0.18],
                    y=[oy - 0.18],
                    mode="markers",
                    marker=dict(symbol="star" if is_emer else "circle", size=14, color="#ef4444" if is_emer else "#3b82f6", line=dict(width=1.5, color="#ffffff")),
                    hoverinfo="text",
                    hovertext=f"<b>Request {r_id} (Origin)</b><br>Priority: {priority.upper()}<br>Pickup: {orig} → Dropoff: {dest}",
                    showlegend=False
                ))

    # Layout styling
    fig.update_layout(
        title=dict(text=title, font=dict(size=16, color="#0f172a")),
        margin=dict(l=20, r=20, t=50, b=20),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, range=[-0.4, 3.4]),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, range=[-0.4, 3.4], scaleanchor="x", scaleratio=1),
        plot_bgcolor="#f8fafc",
        paper_bgcolor="#ffffff",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.15,
            xanchor="center",
            x=0.5,
            font=dict(size=11)
        ),
        height=520,
    )

    return fig


def create_benchmark_bar_chart(metric_key, metric_title, y_label, higher_is_better=True):
    """
    Renders an interactive comparative bar chart comparing B1, B2, and B3 across levels L1–L5.
    Uses the real empirical results obtained in the benchmark.
    """
    levels = ["L1 (Simple)", "L2 (Moderate)", "L3 (Compound)", "L4 (Cascading)", "L5 (Extreme)"]

    # Empirical dataset from real_benchmark / RESULTS.md
    data = {
        "rfr_weighted": {
            "B1": [100.0, 100.0, 83.3, 41.7, 61.5],
            "B2": [100.0, 100.0, 94.4, 58.3, 26.9],
            "B3": [100.0, 81.2, 77.8, 58.3, 50.0],
        },
        "rfr": {
            "B1": [100.0, 100.0, 70.0, 50.0, 42.9],
            "B2": [100.0, 100.0, 90.0, 50.0, 21.4],
            "B3": [100.0, 87.5, 80.0, 50.0, 35.7],
        },
        "hcvr": {
            "B1": [0.0, 12.5, 29.2, 33.3, 16.7],
            "B2": [50.0, 62.5, 35.0, 116.7, 50.0],
            "B3": [0.0, 33.3, 33.3, 116.7, 116.7],
        },
        "latency_s": {
            "B1": [0.001, 0.001, 0.001, 0.001, 0.001],
            "B2": [2.6, 1.6, 4.5, 1.6, 1.6],
            "B3": [6.1, 3.9, 5.6, 5.1, 4.7],
        },
        "tokens": {
            "B1": [0, 0, 0, 0, 0],
            "B2": [753, 859, 964, 1040, 1122],
            "B3": [1708, 2124, 2332, 2680, 2736],
        },
        "cost_usd": {
            "B1": [0.0, 0.0, 0.0, 0.0, 0.0],
            "B2": [0.000155, 0.000173, 0.000205, 0.000220, 0.000222],
            "B3": [0.000321, 0.000410, 0.000447, 0.000520, 0.000491],
        }
    }

    metric_values = data.get(metric_key, data["rfr_weighted"])

    fig = go.Figure()

    fig.add_trace(go.Bar(
        name="B1: Rule-Based SOP",
        x=levels,
        y=metric_values["B1"],
        marker_color="#3b82f6",
        text=[f"{v:.1f}" if metric_key != "cost_usd" else f"${v:.5f}" for v in metric_values["B1"]],
        textposition="auto"
    ))

    fig.add_trace(go.Bar(
        name="B2: Single-LLM (Monolithic)",
        x=levels,
        y=metric_values["B2"],
        marker_color="#f59e0b",
        text=[f"{v:.1f}" if metric_key != "cost_usd" else f"${v:.5f}" for v in metric_values["B2"]],
        textposition="auto"
    ))

    fig.add_trace(go.Bar(
        name="B3: Tool-Augmented Multi-Agent",
        x=levels,
        y=metric_values["B3"],
        marker_color="#10b981",
        text=[f"{v:.1f}" if metric_key != "cost_usd" else f"${v:.5f}" for v in metric_values["B3"]],
        textposition="auto"
    ))

    fig.update_layout(
        title=dict(text=f"<b>{metric_title}</b>", font=dict(size=16, color="#0f172a")),
        barmode="group",
        xaxis_title="Disruption Complexity Tier",
        yaxis_title=y_label,
        plot_bgcolor="#f8fafc",
        paper_bgcolor="#ffffff",
        margin=dict(l=40, r=20, t=60, b=40),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5
        ),
        height=400
    )

    return fig
