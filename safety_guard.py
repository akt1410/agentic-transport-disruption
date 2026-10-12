"""
Deterministic Safety Guard Module
═════════════════════════════════
Pure-Python deterministic verification layer. Evaluates every proposed
assignment card against ground-truth physical constraints before execution.

Checks Performed:
  1. Topological Reachability: Every edge in the route must exist and be OPEN in G_disrupted.
  2. State-of-Charge (SoC) Sufficiency: Vehicle SoC >= travel_time * 1.0 * 1.15 buffer.
  3. Passenger Capacity: Vehicle seats >= passenger party size.
  4. Conflict Resolution: No vehicle assigned to more than one request simultaneously.

Violations increment HCVR (Hard Constraint Violation Rate) and mark assignments as rejected.
"""

from tools import tool_route_travel_time, tool_find_shortest_path

SOC_RATE_PER_MINUTE = 1.0
SOC_SAFETY_BUFFER   = 0.15


def validate_decision(decision, G_ground_truth_disrupted, scenario):
    """
    Validates a DecisionCard against ground-truth network and fleet state.
    Returns: (validated_decision, list_of_violations)
    """
    vehicles_map = {v["id"]: v for v in scenario["vehicles"]}
    requests_map = {r["id"]: r for r in scenario["requests"]}

    all_violations = []
    validated_assignments = []
    assigned_vehicles = set()

    for asgn in decision["assignments"]:
        # Skip unserved assignments
        if asgn["status"] != "served" or not asgn.get("route"):
            validated_assignments.append(asgn)
            continue

        vid = asgn.get("vehicle_id")
        rid = asgn.get("request_id")
        route = asgn.get("route")

        violations = []

        # ── 1. Duplicate Vehicle Assignment Check ─────────────────────────────
        if vid in assigned_vehicles:
            violations.append({
                "type": "duplicate_vehicle_assignment",
                "detail": f"Vehicle {vid} assigned to multiple requests concurrently."
            })
        elif vid:
            assigned_vehicles.add(vid)

        # ── 2. Route Reachability Check ───────────────────────────────────────
        if route and len(route) >= 2:
            for i in range(len(route) - 1):
                u, v = route[i], route[i + 1]
                if not G_ground_truth_disrupted.has_edge(u, v):
                    violations.append({
                        "type": "route_unreachable",
                        "detail": f"Segment ({u} ↔ {v}) is closed or missing in ground-truth network."
                    })
                    break

        # ── 3. Battery State-of-Charge (SoC) Check ────────────────────────────
        if vid in vehicles_map and route:
            actual_time = tool_route_travel_time(G_ground_truth_disrupted, route)
            if actual_time < float("inf"):
                needed_soc = actual_time * SOC_RATE_PER_MINUTE * (1.0 + SOC_SAFETY_BUFFER)
                curr_soc = vehicles_map[vid]["soc"]
                if curr_soc < needed_soc:
                    violations.append({
                        "type": "soc_insufficient",
                        "detail": f"Vehicle {vid} battery ({curr_soc}%) < needed ({needed_soc:.1f}%)."
                    })

        # ── 4. Passenger Capacity Check ───────────────────────────────────────
        if vid in vehicles_map and rid in requests_map:
            cap = vehicles_map[vid]["capacity"]
            pax = requests_map[rid]["passengers"]
            if cap < pax:
                violations.append({
                    "type": "capacity_exceeded",
                    "detail": f"Vehicle {vid} seats ({cap}) < party size ({pax})."
                })

        # ── Verdict ───────────────────────────────────────────────────────────
        if violations:
            all_violations.append({
                "request_id": rid,
                "vehicle_id": vid,
                "violations": violations
            })
            rejected_asgn = dict(asgn)
            rejected_asgn["status"] = "rejected"
            rejected_asgn["violations"] = violations
            validated_assignments.append(rejected_asgn)
        else:
            validated_assignments.append(asgn)

    result = dict(decision)
    result["assignments"] = validated_assignments
    return result, all_violations


def apply_sop_fallback(validated_decision, G_ground_truth_disrupted, scenario):
    """
    Applies deterministic SOP fallback repair for any assignments rejected by the guard.
    """
    used_vids = {
        a["vehicle_id"] for a in validated_decision["assignments"]
        if a["status"] == "served" and a.get("vehicle_id")
    }
    available_fleet = [
        v for v in scenario["vehicles"]
        if v["status"] == "available" and v["id"] not in used_vids
    ]

    repaired_assignments = []

    for asgn in validated_decision["assignments"]:
        if asgn["status"] == "rejected":
            rid = asgn["request_id"]
            req = next((r for r in scenario["requests"] if r["id"] == rid), None)
            if not req:
                repaired_assignments.append({**asgn, "status": "unserved"})
                continue

            # Deterministic Dijkstra shortest path fallback
            path, trip_time = tool_find_shortest_path(G_ground_truth_disrupted, req["origin"], req["destination"])
            if not path:
                repaired_assignments.append({**asgn, "status": "unserved", "reason": "no_physical_path"})
                continue

            # Find closest feasible vehicle
            best_v, best_pr, best_total = None, None, float("inf")
            for v in available_fleet:
                pr, pt = tool_find_shortest_path(G_ground_truth_disrupted, v["position"], req["origin"])
                if pr:
                    total_tt = pt + trip_time
                    soc_needed = total_tt * SOC_RATE_PER_MINUTE * (1.0 + SOC_SAFETY_BUFFER)
                    if v["soc"] >= soc_needed and v["capacity"] >= req["passengers"] and total_tt < best_total:
                        best_v = v
                        best_pr = pr
                        best_total = total_tt

            if best_v:
                used_vids.add(best_v["id"])
                available_fleet = [v for v in available_fleet if v["id"] != best_v["id"]]
                repaired_assignments.append({
                    "request_id": rid,
                    "vehicle_id": best_v["id"],
                    "route": best_pr + path[1:],
                    "estimated_time": best_total,
                    "status": "served",
                    "repaired_by_fallback": True
                })
            else:
                repaired_assignments.append({**asgn, "status": "unserved", "reason": "no_fleet_available"})
        else:
            repaired_assignments.append(asgn)

    out = dict(validated_decision)
    out["assignments"] = repaired_assignments
    return out
