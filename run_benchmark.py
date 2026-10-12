#!/usr/bin/env python3
"""
Unified Experiment Runner & Benchmark
═════════════════════════════════════
Executes the Transport Disruption Benchmark comparing:
  • B1: Rule-Based SOP (Blind to text alerts, greedy dispatch)
  • B2: Single-LLM Agent (Monolithic Gemini API call)
  • B3: Tool-Augmented Multi-Agent System (Traffic, Fleet, Routing Tool, Coordinator)

Measures:
  1. RFR (%): Request Fulfillment Rate
  2. RFR_weighted (%): Priority-Weighted Fulfillment (Emergency trips = 3× weight)
  3. HCVR (%): Hard Constraint Violation Rate (Pre-guard infeasibility)
  4. Real Latency (s): Measured decision time
  5. Real Token Usage & Cost ($)

Generates:
  • Console results tables
  • results/real_benchmark.png
  • results/RESULTS.md
"""

import os
import sys
import time
import json
import random
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from google import genai

from network import create_network, apply_disruptions
from scenarios import generate_scenarios
from safety_guard import validate_decision, apply_sop_fallback
from controllers import (
    controller_b1_rule_based,
    controller_b2_single_llm,
    controller_b3_multi_agent
)

# ── Pricing: Gemini 2.5 Flash / Flash Lite ───────────────────────────────────
COST_PER_1M_INPUT  = 0.10     # $0.10 per 1M input tokens
COST_PER_1M_OUTPUT = 0.40     # $0.40 per 1M output tokens
API_CALL_DELAY     = 2.0      # Safety delay between calls


def compute_scenario_metrics(decision, violations, scenario, G_original, G_disrupted,
                             latency, prompt_tokens, candidate_tokens):
    """Computes all quantitative evaluation metrics for one decision card."""
    asgns = decision["assignments"]
    requests_map = {r["id"]: r for r in scenario["requests"]}

    n_proposed = sum(1 for a in asgns if a["status"] in ("served", "rejected"))
    n_violations = len(violations)
    n_served = sum(1 for a in asgns if a["status"] == "served")
    n_total_req = len(scenario["requests"])

    # 1. Standard RFR
    rfr = (n_served / n_total_req * 100.0) if n_total_req > 0 else 100.0

    # 2. Priority-Weighted RFR (Emergency = 3x, Standard = 1x)
    total_weight = 0.0
    served_weight = 0.0
    for r in scenario["requests"]:
        w = 3.0 if r.get("priority") == "emergency" else 1.0
        total_weight += w
    for a in asgns:
        if a["status"] == "served":
            req = requests_map.get(a["request_id"])
            w = 3.0 if req and req.get("priority") == "emergency" else 1.0
            served_weight += w
    rfr_weighted = (served_weight / total_weight * 100.0) if total_weight > 0 else 100.0

    # 3. HCVR (Hard Constraint Violation Rate)
    hcvr = (n_violations / n_proposed * 100.0) if n_proposed > 0 else 0.0

    # 4. Token Cost
    cost_usd = (prompt_tokens / 1_000_000.0 * COST_PER_1M_INPUT) + \
               (candidate_tokens / 1_000_000.0 * COST_PER_1M_OUTPUT)

    return {
        "rfr": rfr,
        "rfr_weighted": rfr_weighted,
        "hcvr": hcvr,
        "latency_s": latency,
        "prompt_tokens": prompt_tokens,
        "candidate_tokens": candidate_tokens,
        "total_tokens": prompt_tokens + candidate_tokens,
        "cost_usd": cost_usd
    }


def aggregate_results(results):
    """Aggregates metrics into mean and standard deviation per level and controller."""
    controllers = ["B1_RuleBased", "B2_SingleLLM", "B3_MultiAgent"]
    agg = {}
    for lv in range(1, 6):
        agg[lv] = {}
        for c in controllers:
            agg[lv][c] = {}
            for metric in ("rfr", "rfr_weighted", "hcvr", "latency_s", "total_tokens", "cost_usd"):
                vals = [m[metric] for m in results[lv][c]]
                agg[lv][c][metric] = {
                    "mean": float(np.mean(vals)) if vals else 0.0,
                    "std":  float(np.std(vals))  if vals else 0.0
                }
    return agg


def print_comparison_tables(agg):
    """Prints clean terminal summary tables."""
    controllers = ["B1_RuleBased", "B2_SingleLLM", "B3_MultiAgent"]
    labels = {
        "B1_RuleBased": "B1 Rule-Based SOP",
        "B2_SingleLLM": "B2 Single-LLM",
        "B3_MultiAgent": "B3 Multi-Agent"
    }

    metrics = [
        ("rfr",          "Request Fulfillment Rate (RFR)",             "%   ↑ higher is better"),
        ("rfr_weighted", "Priority-Weighted RFR (Emergency=3×)",       "%   ↑ higher is better"),
        ("hcvr",         "Hard Constraint Violation Rate (HCVR)",      "%   ↓ lower is better"),
        ("latency_s",    "Real Execution Latency",                     "s   ↓ lower is better"),
        ("total_tokens", "Total Tokens Used",                          "    measured"),
        ("cost_usd",     "Real API Monetary Cost",                     "$   measured"),
    ]

    for key, title, unit in metrics:
        print(f"\n{'─'*76}")
        print(f"  {title}  ({unit})")
        print(f"{'─'*76}")
        hdr = f"  {'Level':>5} │"
        for c in controllers:
            hdr += f"  {labels[c]:>19} │"
        print(hdr)
        print(f"  {'─'*5} │" + f"  {'─'*19} │" * 3)

        for lv in range(1, 6):
            row = f"    L{lv} │"
            for c in controllers:
                m = agg[lv][c][key]["mean"]
                s = agg[lv][c][key]["std"]
                if key == "cost_usd":
                    row += f"   ${m:.6f}±{s:.5f} │"
                elif key == "latency_s":
                    row += f"    {m:>6.2f} ± {s:>4.2f} │"
                elif key == "total_tokens":
                    row += f"    {m:>6.0f} ± {s:>4.0f} │"
                else:
                    row += f"    {m:>5.1f} ± {s:>4.1f} │"
            print(row)
    print()


def plot_benchmark_figures(agg, out_dir="results"):
    """Generates a 4-panel publication-grade comparison figure."""
    os.makedirs(out_dir, exist_ok=True)
    levels = list(range(1, 6))
    controllers = ["B1_RuleBased", "B2_SingleLLM", "B3_MultiAgent"]
    labels = {
        "B1_RuleBased": "B1 Rule-Based SOP (Blind to Alerts)",
        "B2_SingleLLM": "B2 Single-LLM (Monolithic)",
        "B3_MultiAgent": "B3 Multi-Agent (Tool-Augmented)"
    }
    colors = {
        "B1_RuleBased": "#1F77B4",
        "B2_SingleLLM": "#FF7F0E",
        "B3_MultiAgent": "#2CA02C"
    }

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("Transport Disruption Benchmark (Real Google Gemini API)\n"
                 "Tool-Augmented Multi-Agent vs Single-LLM vs Rule-Based SOP",
                 fontsize=14, fontweight="bold", y=0.99)

    # 1. Priority-Weighted Fulfillment Rate
    ax = axes[0, 0]
    for c in controllers:
        ms = [agg[lv][c]["rfr_weighted"]["mean"] for lv in levels]
        ss = [agg[lv][c]["rfr_weighted"]["std"]  for lv in levels]
        ax.errorbar(levels, ms, yerr=ss, marker="o", capsize=4,
                    color=colors[c], label=labels[c], lw=2)
    ax.set(xlabel="Complexity Level", ylabel="Weighted RFR (%)",
           title="Priority-Weighted Fulfillment (Emergency=3×)  [↑]")
    ax.set_xticks(levels); ax.set_xticklabels([f"L{l}" for l in levels])
    ax.set_ylim(-2, 108); ax.legend(fontsize=8.5); ax.grid(alpha=0.3)

    # 2. Hard Constraint Violation Rate (HCVR)
    ax = axes[0, 1]
    x = np.arange(len(levels)); w = 0.26
    for i, c in enumerate(controllers):
        ms = [agg[lv][c]["hcvr"]["mean"] for lv in levels]
        ax.bar(x + i*w, ms, w, label=labels[c], color=colors[c], alpha=0.85)
    ax.set(xlabel="Complexity Level", ylabel="HCVR (%)",
           title="Hard Constraint Violations (Pre-Guard)  [↓]")
    ax.set_xticks(x + w); ax.set_xticklabels([f"L{l}" for l in levels])
    ax.legend(fontsize=8.5); ax.grid(alpha=0.3, axis="y")

    # 3. Real Latency
    ax = axes[1, 0]
    for c in controllers:
        ms = [agg[lv][c]["latency_s"]["mean"] for lv in levels]
        ss = [agg[lv][c]["latency_s"]["std"]  for lv in levels]
        ax.errorbar(levels, ms, yerr=ss, marker="D", capsize=4,
                    color=colors[c], label=labels[c], lw=2)
    ax.set(xlabel="Complexity Level", ylabel="Latency (s)",
           title="Real Execution Latency  [↓]")
    ax.set_xticks(levels); ax.set_xticklabels([f"L{l}" for l in levels])
    ax.legend(fontsize=8.5); ax.grid(alpha=0.3)

    # 4. Token Usage
    ax = axes[1, 1]
    for c in controllers:
        ms = [agg[lv][c]["total_tokens"]["mean"] for lv in levels]
        ax.plot(levels, ms, marker="s", color=colors[c], label=labels[c], lw=2)
    ax.set(xlabel="Complexity Level", ylabel="Tokens Consumed",
           title="Real Token Consumption per Scenario")
    ax.set_xticks(levels); ax.set_xticklabels([f"L{l}" for l in levels])
    ax.legend(fontsize=8.5); ax.grid(alpha=0.3)

    plt.tight_layout()
    out_path = os.path.join(out_dir, "real_benchmark.png")
    fig.savefig(out_path, dpi=160, bbox_inches="tight")
    plt.close()
    print(f"  📊 Saved figure to: {out_path}")


def save_markdown_report(agg, raw_logs, out_dir="results"):
    """Saves a comprehensive markdown report with tables."""
    os.makedirs(out_dir, exist_ok=True)
    controllers = ["B1_RuleBased", "B2_SingleLLM", "B3_MultiAgent"]

    lines = [
        "# Real Gemini API Benchmark Results",
        "",
        "## Experimental Configuration",
        "- **Network:** 4×4 Manhattan urban grid (16 nodes, 24 edges with capacities and travel times).",
        "- **Complexity Spectrum:** L1 to L5 graduated scenarios.",
        "- **Unstructured Text Advisories:** Tested on police/traffic incident alerts that rule-based SOPs cannot parse.",
        "- **Controllers Evaluated:**",
        "  1. `B1_RuleBased`: Rigid classical Dijkstra SOP (blind to natural language alerts).",
        "  2. `B2_SingleLLM`: Monolithic Gemini call with full context.",
        "  3. `B3_MultiAgent`: 4-Agent collaborative system (Traffic, Fleet, Routing Tool, Coordinator).",
        "- **Foundation Model:** `gemini-flash-lite-latest` via Google GenAI SDK.",
        ""
    ]

    for key, title in [
        ("rfr_weighted", "Priority-Weighted Fulfillment Rate (RFR_w %)"),
        ("rfr",          "Standard Request Fulfillment Rate (RFR %)"),
        ("hcvr",         "Hard Constraint Violation Rate (HCVR %)"),
        ("latency_s",    "Real Execution Latency (seconds)"),
        ("total_tokens", "Total Tokens Consumed"),
        ("cost_usd",     "Real API Monetary Cost ($)")
    ]:
        lines += [
            f"### {title}",
            "",
            "| Level | B1 Rule-Based SOP | B2 Single-LLM | B3 Multi-Agent |",
            "| :---: | :---: | :---: | :---: |"
        ]
        for lv in range(1, 6):
            row = f"| L{lv} |"
            for c in controllers:
                m = agg[lv][c][key]["mean"]
                s = agg[lv][c][key]["std"]
                if key == "cost_usd":
                    row += f" ${m:.6f} |"
                elif key in ("latency_s", "rfr", "rfr_weighted", "hcvr"):
                    row += f" {m:.1f} ± {s:.1f} |"
                else:
                    row += f" {m:.0f} |"
            lines.append(row)
        lines.append("")

    lines += [
        "## Embedded Plot",
        "",
        "![Benchmark Figure](real_benchmark.png)",
        ""
    ]

    with open(os.path.join(out_dir, "RESULTS.md"), "w") as f:
        f.write("\n".join(lines))
    print(f"  📄 Saved markdown report to: {out_dir}/RESULTS.md")

    with open(os.path.join(out_dir, "raw_logs.json"), "w") as f:
        json.dump(raw_logs, f, indent=2, default=str)
    print(f"  💾 Saved raw execution logs to: {out_dir}/raw_logs.json")


def main():
    print("=" * 76)
    print("  TRANSPORT DISRUPTION BENCHMARK (REAL GEMINI API)")
    print("  Tool-Augmented Multi-Agent  vs  Single-LLM  vs  Rule-Based SOP")
    print("=" * 76, "\n")

    # Read API Key
    key_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_key.txt")
    api_key = open(key_file).read().strip() if os.path.exists(key_file) else os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("❌ Missing API key! Ensure api_key.txt is present.")
        sys.exit(1)

    model_name = "gemini-flash-lite-latest"
    client = genai.Client(api_key=api_key)
    print(f"  🔑 Gemini Client initialized (Model: {model_name})")

    # Setup network & scenarios
    G_original = create_network()
    # 2 scenarios per level = 10 scenarios total across L1 to L5 (balanced for speed & statistics)
    scenarios = generate_scenarios(per_level=2, base_seed=100)
    print(f"  Network  : 4×4 Grid (16 nodes, 24 edges)")
    print(f"  Scenarios: {len(scenarios)} total (2 per level × 5 levels)\n")

    results = {lv: {"B1_RuleBased": [], "B2_SingleLLM": [], "B3_MultiAgent": []} for lv in range(1, 6)}
    raw_logs = []

    for i, sc in enumerate(scenarios):
        lv = sc["level"]
        sid = sc["scenario_id"]
        G_disrupted, closed_edges = apply_disruptions(G_original, sc["disruptions"])
        print(f"  [{i+1:>2}/{len(scenarios)}] Processing {sid} (Complexity Level {lv})...")

        # ── 1. B1 Rule-Based SOP ──────────────────────────────────────────────
        t0 = time.time()
        dec1 = controller_b1_rule_based(sc, G_original)
        lat1 = time.time() - t0
        val1, viol1 = validate_decision(dec1, G_disrupted, sc)
        fin1 = apply_sop_fallback(val1, G_disrupted, sc)
        m1 = compute_scenario_metrics(fin1, viol1, sc, G_original, G_disrupted, lat1, 0, 0)
        results[lv]["B1_RuleBased"].append(m1)
        print(f"       B1 SOP         : RFR_w={m1['rfr_weighted']:5.1f}%  HCVR={m1['hcvr']:4.1f}%  lat={m1['latency_s']:.3f}s")

        # ── 2. B2 Single-LLM ──────────────────────────────────────────────────
        dec2, lat2, pt2, ct2 = controller_b2_single_llm(client, model_name, sc, G_original)
        val2, viol2 = validate_decision(dec2, G_disrupted, sc)
        fin2 = apply_sop_fallback(val2, G_disrupted, sc)
        m2 = compute_scenario_metrics(fin2, viol2, sc, G_original, G_disrupted, lat2, pt2, ct2)
        results[lv]["B2_SingleLLM"].append(m2)
        print(f"       B2 Single-LLM  : RFR_w={m2['rfr_weighted']:5.1f}%  HCVR={m2['hcvr']:4.1f}%  lat={m2['latency_s']:.2f}s  tokens={m2['total_tokens']}")
        time.sleep(API_CALL_DELAY)

        # ── 3. B3 Multi-Agent ─────────────────────────────────────────────────
        dec3, lat3, pt3, ct3 = controller_b3_multi_agent(client, model_name, sc, G_original, call_delay=API_CALL_DELAY)
        val3, viol3 = validate_decision(dec3, G_disrupted, sc)
        fin3 = apply_sop_fallback(val3, G_disrupted, sc)
        m3 = compute_scenario_metrics(fin3, viol3, sc, G_original, G_disrupted, lat3, pt3, ct3)
        results[lv]["B3_MultiAgent"].append(m3)
        print(f"       B3 Multi-Agent : RFR_w={m3['rfr_weighted']:5.1f}%  HCVR={m3['hcvr']:4.1f}%  lat={m3['latency_s']:.2f}s  tokens={m3['total_tokens']}")
        time.sleep(API_CALL_DELAY)

        raw_logs.append({
            "scenario": sid,
            "level": lv,
            "B1_metrics": m1,
            "B2_metrics": m2,
            "B3_metrics": m3,
            "B2_raw": dec2.get("raw_response", ""),
            "B3_logs": dec3.get("agent_logs", {})
        })

    # Aggregate & Display
    agg = aggregate_results(results)
    print_comparison_tables(agg)
    plot_benchmark_figures(agg)
    save_markdown_report(agg, raw_logs)

    print("\n" + "=" * 76)
    print("  ✅ BENCHMARK COMPLETE — Real data saved to results/ folder")
    print("=" * 76)


if __name__ == "__main__":
    main()
