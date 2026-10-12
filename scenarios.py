"""
Scenario Generator Module
═════════════════════════
Generates reproducible, graduated disruption scenarios (L1–L5).

Key Realistic Features:
  1. Graduated Complexity Spectrum: L1 (1 closure) to L5 (3 closures, 2 congestions, 2 breakdowns).
  2. Unstructured Natural Language Incident Alerts: Text advisories describing dynamic
     closures that rule-based SOPs (without NLP) fail to parse.
  3. Priority Demand: Passenger requests categorized as 'emergency' (weighted 3× in RFR_w)
     or 'standard' commute.
"""

import random

# All 24 edges in the 4×4 network
ALL_EDGES = [
    # Horizontal
    ("N0", "N1"), ("N1", "N2"), ("N2", "N3"),
    ("N4", "N5"), ("N5", "N6"), ("N6", "N7"),
    ("N8", "N9"), ("N9", "N10"), ("N10", "N11"),
    ("N12", "N13"), ("N13", "N14"), ("N14", "N15"),
    # Vertical
    ("N0", "N4"), ("N1", "N5"), ("N2", "N6"), ("N3", "N7"),
    ("N4", "N8"), ("N5", "N9"), ("N6", "N10"), ("N7", "N11"),
    ("N8", "N12"), ("N9", "N13"), ("N10", "N14"), ("N11", "N15"),
]

STREET_LOOKUP = {
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

DEFAULT_FLEET_POSITIONS = ["N0", "N3", "N4", "N7", "N12", "N8"]
DEFAULT_FLEET_CAPACITY  = [4, 6, 4, 6, 4, 6]

# Candidate OD pairs across town
OD_CANDIDATES = [
    ("N0", "N15", "emergency"),   # Cross-town trip to Central Hospital
    ("N4", "N15", "emergency"),   # West Station to Central Hospital
    ("N8", "N3",  "standard"),    # Financial District to East Gate
    ("N12", "N2", "standard"),    # South Terminal to City Center
    ("N1", "N14", "standard"),    # North Ave to Park View
    ("N5", "N11", "emergency"),   # Medical transport to Civic Center
    ("N0", "N10", "standard"),    # North Depot to University
    ("N13", "N3", "standard"),    # River Crossing to East Gate
]

LEVEL_CONFIG = {
    1: {"closures": 1, "congestions": 0, "breakdowns": 0, "n_requests": 3, "has_text_alert": False},
    2: {"closures": 1, "congestions": 1, "breakdowns": 0, "n_requests": 4, "has_text_alert": True},
    3: {"closures": 1, "congestions": 1, "breakdowns": 1, "n_requests": 5, "has_text_alert": True},
    4: {"closures": 2, "congestions": 1, "breakdowns": 1, "n_requests": 6, "has_text_alert": True},
    5: {"closures": 3, "congestions": 2, "breakdowns": 2, "n_requests": 7, "has_text_alert": True},
}


def generate_scenarios(per_level=3, base_seed=42):
    """
    Generates reproducible benchmark scenarios across levels L1–L5.
    Returns: list of scenario dictionaries.
    """
    scenarios = []

    for level in range(1, 6):
        cfg = LEVEL_CONFIG[level]
        for idx in range(per_level):
            seed = base_seed + level * 1000 + idx
            rng = random.Random(seed)

            disruptions = []
            text_alerts = []
            used_edges = set()

            # ── 1. Road Closures ──────────────────────────────────────────────
            candidates = [e for e in ALL_EDGES if e not in used_edges]
            closure_edges = rng.sample(candidates, min(cfg["closures"], len(candidates)))
            
            for i, edge in enumerate(closure_edges):
                u, v = edge
                street = STREET_LOOKUP.get((u, v), STREET_LOOKUP.get((v, u), f"{u}-{v}"))
                used_edges.add(edge)
                
                # In L2-L5, at least one closure is an UNSTRUCTURED TEXT ALERT (simulating a sudden real-time incident)
                is_text_alert_closure = (cfg["has_text_alert"] and i == 0)
                
                disruptions.append({
                    "type": "road_closure",
                    "edge": list(edge),
                    "street_name": street,
                    "reported_via_text_only": is_text_alert_closure
                })
                
                if is_text_alert_closure:
                    text_alerts.append(
                        f"🚨 URGENT POLICE DISPATCH: Major water main break on {street} "
                        f"between {u} and {v}. Road segment is completely BLOCKED to all traffic. "
                        f"All dispatch units must avoid {u} ↔ {v} immediately."
                    )
                else:
                    text_alerts.append(
                        f"ℹ️ TRAFFIC ADVISORY: Scheduled maintenance on {street} between {u} and {v}. "
                        f"Segment closed to public transit."
                    )

            # ── 2. Congestion Events ──────────────────────────────────────────
            candidates = [e for e in ALL_EDGES if e not in used_edges]
            for edge in rng.sample(candidates, min(cfg["congestions"], len(candidates))):
                u, v = edge
                street = STREET_LOOKUP.get((u, v), STREET_LOOKUP.get((v, u), f"{u}-{v}"))
                factor = round(rng.uniform(2.5, 4.0), 1)
                used_edges.add(edge)
                disruptions.append({
                    "type": "congestion",
                    "edge": list(edge),
                    "street_name": street,
                    "factor": factor,
                    "reported_via_text_only": False
                })
                text_alerts.append(
                    f"⚠️ TRAFFIC NOTICE: Severe bottleneck on {street} ({u} ↔ {v}). "
                    f"Travel times are delayed by {factor}× normal speed."
                )

            # ── 3. Vehicle Breakdowns ─────────────────────────────────────────
            broken_vids = [f"V{v}" for v in rng.sample(range(6), min(cfg["breakdowns"], 6))]
            for vid in broken_vids:
                disruptions.append({
                    "type": "vehicle_breakdown",
                    "vehicle_id": vid
                })
                text_alerts.append(f"🔧 FLEET ALERT: Vehicle {vid} experienced mechanical failure and is OUT OF SERVICE.")

            # ── 4. Electric Vehicle Fleet ─────────────────────────────────────
            broken_set = set(broken_vids)
            soc_lo = 35 if level <= 3 else 25
            soc_hi = 95 if level <= 3 else 80
            
            fleet = []
            for v in range(6):
                vid = f"V{v}"
                fleet.append({
                    "id": vid,
                    "position": DEFAULT_FLEET_POSITIONS[v],
                    "soc": rng.randint(soc_lo, soc_hi),
                    "capacity": DEFAULT_FLEET_CAPACITY[v],
                    "status": "broken" if vid in broken_set else "available"
                })

            # ── 5. Passenger Requests with Priorities ─────────────────────────
            n_req = cfg["n_requests"]
            req_samples = rng.sample(OD_CANDIDATES, min(n_req, len(OD_CANDIDATES)))
            requests = []
            for j, (o, d, prio) in enumerate(req_samples):
                # Ensure higher levels have clear emergency priority requests
                effective_prio = prio
                if level >= 3 and j == 0:
                    effective_prio = "emergency"
                    
                requests.append({
                    "id": f"R{j}",
                    "origin": o,
                    "destination": d,
                    "passengers": rng.randint(1, 4),
                    "priority": effective_prio,
                    "description": f"{effective_prio.upper()} trip: {o} → {d}"
                })

            scenarios.append({
                "scenario_id": f"L{level}_{idx:03d}",
                "level": level,
                "disruptions": disruptions,
                "text_alerts": text_alerts,
                "vehicles": fleet,
                "requests": requests,
                "seed": seed
            })

    return scenarios
