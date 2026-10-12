"""
Three Disruption Controllers
════════════════════════════
B1 — Rule-Based SOP Controller (Deterministic, Blind to Unstructured Text Alerts)
B2 — Single-LLM Agent with Tool-Calling (Monolithic Gemini 2.5 Flash / Flash Lite)
B3 — Tool-Augmented Multi-Agent System (Traffic, Fleet, Routing, Coordinator)

All LLM controllers use real Google Gemini API calls with measured latency and tokens.
"""

import json
import re
import time
from google import genai
from google.genai import types

from tools import (
    tool_find_shortest_path,
    tool_get_k_diverse_routes,
    tool_route_travel_time,
    tool_check_battery,
    tool_filter_available_fleet,
)
from network import apply_disruptions


# ═══════════════════════════════════════════════════════════════════════════════
#  LLM Helper Functions
# ═══════════════════════════════════════════════════════════════════════════════

def _call_gemini(client, model_name, prompt, max_retries=3):
    """
    Executes a real call to Gemini API.
    Returns: (text_response, latency_seconds, prompt_tokens, completion_tokens)
    """
    for attempt in range(max_retries):
        try:
            t0 = time.time()
            resp = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.1),
            )
            lat = time.time() - t0
            text = resp.text or ""
            
            try:
                pt = resp.usage_metadata.prompt_token_count or 0
                ct = resp.usage_metadata.candidates_token_count or 0
            except Exception:
                pt = len(prompt) // 4
                ct = len(text) // 4
                
            return text, lat, pt, ct
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                wait_time = 15 * (attempt + 1)
                time.sleep(wait_time)
            elif attempt < max_retries - 1:
                time.sleep(3)
            else:
                return "", 0.0, 0, 0


def _extract_json(text):
    """Extracts first valid JSON object or array from LLM response text."""
    if not text:
        return None
    # Remove markdown code fences
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        text = m.group(1)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch in ("{", "["):
            if depth == 0:
                start = i
            depth += 1
        elif ch in ("}", "]"):
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    start = None
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  B1: Rule-Based SOP Controller (Blind to Unstructured Text Alerts)
# ═══════════════════════════════════════════════════════════════════════════════

def controller_b1_rule_based(scenario, G_original):
    """
    Simulates a traditional municipal SOP.
    Limitation: Only accesses structured pre-scheduled database records.
    It CANNOT read unstructured police/weather text alerts.
    If a road closure was announced via text alert only, B1 naively routes through it.
    """
    # B1 only sees non-text disruptions
    known_disruptions = [
        d for d in scenario["disruptions"]
        if not d.get("reported_via_text_only", False)
    ]
    G_known, _ = apply_disruptions(G_original, known_disruptions)

    available_fleet = [v.copy() for v in scenario["vehicles"] if v["status"] == "available"]
    used_vids = set()
    assignments = []

    # Sequential greedy dispatch (ignores emergency priority)
    for req in scenario["requests"]:
        path, trip_time = tool_find_shortest_path(G_known, req["origin"], req["destination"])
        if not path:
            assignments.append({"request_id": req["id"], "vehicle_id": None, "route": None,
                                "estimated_time": None, "status": "unserved", "reason": "no_path"})
            continue

        best_v, best_pr, best_total = None, None, float("inf")
        for v in available_fleet:
            if v["id"] in used_vids:
                continue
            pr, pt = tool_find_shortest_path(G_known, v["position"], req["origin"])
            if pr:
                total_tt = pt + trip_time
                is_feasible, needed_soc, _ = tool_check_battery(v, total_tt)
                if is_feasible and v["capacity"] >= req["passengers"] and total_tt < best_total:
                    best_v = v
                    best_pr = pr
                    best_total = total_tt

        if best_v:
            used_vids.add(best_v["id"])
            full_route = best_pr + path[1:]
            assignments.append({
                "request_id": req["id"],
                "vehicle_id": best_v["id"],
                "route": full_route,
                "estimated_time": best_total,
                "status": "served"
            })
        else:
            assignments.append({"request_id": req["id"], "vehicle_id": None, "route": None,
                                "estimated_time": None, "status": "unserved", "reason": "no_vehicle"})

    return {
        "scenario_id": scenario["scenario_id"],
        "controller": "B1_RuleBased_SOP",
        "assignments": assignments
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  B2: Single-LLM Agent with Tool-Calling
# ═══════════════════════════════════════════════════════════════════════════════

_B2_PROMPT_TEMPLATE = """You are an Autonomous Transport Disruption Controller for a 4×4 city road network (nodes N0 to N15).
You must analyze live text incident alerts, identify closed road segments, and assign available electric vehicles to passenger requests.

## LIVE INCIDENT TEXT ALERTS
{alerts}

## PASSENGER REQUESTS
{requests}

## AVAILABLE ELECTRIC FLEET
{vehicles}

## INSTRUCTIONS
1. Read all incident alerts carefully to identify any road segments that are completely closed or impassable.
2. For each request, pick an available vehicle and provide a sequence of nodes connecting:
   [Vehicle Position] -> ... -> [Request Origin] -> ... -> [Request Destination]
3. Avoid all closed segments identified in the alerts.
4. Give high priority to 'EMERGENCY' requests.
5. Do NOT assign the same vehicle to multiple requests.

Output strictly valid JSON:
{{
  "identified_closed_edges": [["N4", "N5"]],
  "assignments": [
    {{"request_id": "R0", "vehicle_id": "V0", "route": ["N0", "N1", "N2", "N15"]}},
    {{"request_id": "R1", "vehicle_id": null, "route": null}}
  ]
}}"""


def controller_b2_single_llm(client, model_name, scenario, G_original):
    """
    Monolithic Single-LLM Agent.
    Sends all alerts, fleet, and requests in one prompt.
    """
    alerts_text = "\n".join(f"• {a}" for a in scenario["text_alerts"]) or "None"
    reqs_text = "\n".join(
        f"• {r['id']}: {r['origin']} → {r['destination']} ({r['passengers']} passengers, Priority: {r['priority']})"
        for r in scenario["requests"]
    )
    veh_text = "\n".join(
        f"• {v['id']}: At {v['position']}, Battery {v['soc']}%, Seats {v['capacity']}, Status: {v['status']}"
        for v in scenario["vehicles"]
    )

    prompt = _B2_PROMPT_TEMPLATE.format(
        alerts=alerts_text,
        requests=reqs_text,
        vehicles=veh_text
    )

    raw_text, lat, pt, ct = _call_gemini(client, model_name, prompt)
    data = _extract_json(raw_text)

    # Convert LLM plan to standardized DecisionCard
    req_ids = {r["id"] for r in scenario["requests"]}
    parsed_assignments = []
    
    if data and "assignments" in data and isinstance(data["assignments"], list):
        for item in data["assignments"]:
            rid = item.get("request_id")
            vid = item.get("vehicle_id")
            route = item.get("route")
            if rid in req_ids:
                if vid and route and isinstance(route, list) and len(route) >= 2:
                    tt = tool_route_travel_time(G_original, route)
                    parsed_assignments.append({
                        "request_id": rid,
                        "vehicle_id": vid,
                        "route": route,
                        "estimated_time": tt,
                        "status": "served"
                    })
                else:
                    parsed_assignments.append({
                        "request_id": rid,
                        "vehicle_id": None,
                        "route": None,
                        "estimated_time": None,
                        "status": "unserved"
                    })

    # Fill any requests missed by LLM
    covered = {a["request_id"] for a in parsed_assignments}
    for r in scenario["requests"]:
        if r["id"] not in covered:
            parsed_assignments.append({
                "request_id": r["id"],
                "vehicle_id": None,
                "route": None,
                "estimated_time": None,
                "status": "unserved",
                "reason": "llm_omitted"
            })

    decision = {
        "scenario_id": scenario["scenario_id"],
        "controller": "B2_SingleLLM",
        "assignments": parsed_assignments,
        "raw_response": raw_text
    }
    return decision, lat, pt, ct


# ═══════════════════════════════════════════════════════════════════════════════
#  B3: Tool-Augmented Multi-Agent System (Traffic, Fleet, Routing, Coordinator)
# ═══════════════════════════════════════════════════════════════════════════════

_TRAFFIC_PROMPT = """You are the TRAFFIC AGENT in a Multi-Agent Transport Control System.
Your SOLE task: Read these real-time incident alerts and extract ALL impassable/closed road segments.

## INCIDENT ALERTS
{alerts}

Output strictly valid JSON:
{{
  "closed_edges": [["N4", "N5"]],
  "reasoning": "brief summary of closures"
}}"""


_FLEET_PROMPT = """You are the FLEET AGENT in a Multi-Agent Transport Control System.
Your SOLE task: Audit the vehicle fleet and allocate vehicles based on battery range and passenger priority.

## FLEET STATUS
{vehicles}

## PASSENGER REQUESTS TO BE SERVED
{requests}

Reserve the highest-SoC vehicles for 'EMERGENCY' requests.
Output strictly valid JSON:
{{
  "emergency_reservations": [{{"request_id": "R0", "recommended_vehicle": "V1", "rationale": "High SoC for emergency"}}],
  "standard_allocations": [{{"request_id": "R1", "recommended_vehicle": "V0"}}]
}}"""


_COORDINATOR_PROMPT = """You are the COORDINATOR AGENT in a Multi-Agent Transport Control System.
Your task: Synthesize reports from the Traffic Agent and Fleet Agent to finalize vehicle-to-route assignments.

## TRAFFIC AGENT REPORT (Closed Roads)
{traffic_report}

## FLEET AGENT REPORT (Vehicle Allocations)
{fleet_report}

## CANDIDATE VERIFIED DETOUR ROUTES GENERATED BY ROUTING TOOL
{candidate_routes}

## RULES
1. Never assign a route that uses any closed edge.
2. Prioritize emergency requests.
3. No vehicle may be assigned to more than one request.

Output strictly valid JSON:
{{
  "assignments": [
    {{"request_id": "R0", "vehicle_id": "V1", "selected_route": ["N0", "N1", "N2", "N15"]}},
    {{"request_id": "R1", "vehicle_id": "V0", "selected_route": ["N8", "N9", "N10", "N11"]}}
  ]
}}"""


def controller_b3_multi_agent(client, model_name, scenario, G_original, call_delay=2.0):
    """
    Tool-Augmented Multi-Agent System.
    4 Specialized Agents: Traffic -> Fleet -> Routing Tool -> Coordinator.
    """
    total_lat = 0.0
    total_pt = 0
    total_ct = 0
    agent_logs = {}

    # ── Agent 1: Traffic Agent (Call 1) ───────────────────────────────────────
    alerts_text = "\n".join(f"• {a}" for a in scenario["text_alerts"]) or "None"
    p1 = _TRAFFIC_PROMPT.format(alerts=alerts_text)
    t1_text, lat1, pt1, ct1 = _call_gemini(client, model_name, p1)
    total_lat += lat1; total_pt += pt1; total_ct += ct1
    agent_logs["traffic"] = t1_text
    time.sleep(call_delay)

    traffic_data = _extract_json(t1_text) or {}
    closed_from_traffic = traffic_data.get("closed_edges", [])
    
    # Tool invocation: Construct verified open graph avoiding extracted closures
    closed_set = set()
    for edge in closed_from_traffic:
        if isinstance(edge, list) and len(edge) == 2:
            closed_set.add((edge[0], edge[1]))
            closed_set.add((edge[1], edge[0]))
            
    G_verified = G_original.copy()
    for (u, v) in closed_set:
        if G_verified.has_edge(u, v):
            G_verified.remove_edge(u, v)

    # ── Agent 2: Fleet Agent (Call 2) ─────────────────────────────────────────
    veh_text = "\n".join(
        f"• {v['id']}: At {v['position']}, Battery {v['soc']}%, Seats {v['capacity']}, Status: {v['status']}"
        for v in scenario["vehicles"]
    )
    reqs_text = "\n".join(
        f"• {r['id']}: {r['origin']} → {r['destination']} ({r['passengers']} passengers, Priority: {r['priority']})"
        for r in scenario["requests"]
    )
    p2 = _FLEET_PROMPT.format(vehicles=veh_text, requests=reqs_text)
    t2_text, lat2, pt2, ct2 = _call_gemini(client, model_name, p2)
    total_lat += lat2; total_pt += pt2; total_ct += ct2
    agent_logs["fleet"] = t2_text
    time.sleep(call_delay)

    # ── Step 3: Routing Tool Execution (Algorithmic Tool) ─────────────────────
    # Generate verified alternative routes using Dijkstra / K-shortest paths tool
    candidate_routes_map = {}
    for r in scenario["requests"]:
        routes = tool_get_k_diverse_routes(G_verified, r["origin"], r["destination"], k=2)
        candidate_routes_map[r["id"]] = [path for path, tt in routes]

    candidate_text = json.dumps(candidate_routes_map, indent=2)

    # ── Agent 4: Coordinator Agent (Call 4) ───────────────────────────────────
    p4 = _COORDINATOR_PROMPT.format(
        traffic_report=t1_text,
        fleet_report=t2_text,
        candidate_routes=candidate_text
    )
    t4_text, lat4, pt4, ct4 = _call_gemini(client, model_name, p4)
    total_lat += lat4; total_pt += pt4; total_ct += ct4
    agent_logs["coordinator"] = t4_text

    coord_data = _extract_json(t4_text) or {}
    assignments_raw = coord_data.get("assignments", [])

    # Synthesize verified final assignments with tool checks
    final_assignments = []
    used_vids = set()
    req_ids = {r["id"] for r in scenario["requests"]}

    for item in assignments_raw:
        rid = item.get("request_id")
        vid = item.get("vehicle_id")
        route = item.get("selected_route")

        if rid in req_ids and vid and vid not in used_vids:
            used_vids.add(vid)
            veh = next((v for v in scenario["vehicles"] if v["id"] == vid), None)
            
            # Combine vehicle pickup path with trip route
            if veh and route and len(route) >= 2:
                pickup_path, pt = tool_find_shortest_path(G_verified, veh["position"], route[0])
                full_route = (pickup_path + route[1:]) if pickup_path else route
                tt = tool_route_travel_time(G_verified, full_route)
                
                final_assignments.append({
                    "request_id": rid,
                    "vehicle_id": vid,
                    "route": full_route,
                    "estimated_time": tt,
                    "status": "served"
                })
            else:
                final_assignments.append({"request_id": rid, "vehicle_id": None, "route": None,
                                         "estimated_time": None, "status": "unserved"})

    # Ensure every request is covered
    covered = {a["request_id"] for a in final_assignments}
    for r in scenario["requests"]:
        if r["id"] not in covered:
            final_assignments.append({
                "request_id": r["id"],
                "vehicle_id": None,
                "route": None,
                "estimated_time": None,
                "status": "unserved",
                "reason": "unassigned"
            })

    decision = {
        "scenario_id": scenario["scenario_id"],
        "controller": "B3_MultiAgent_ToolAugmented",
        "assignments": final_assignments,
        "agent_logs": agent_logs
    }
    return decision, total_lat, total_pt, total_ct
