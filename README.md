# Agentic AI in Transport Disruption Management

**B.Tech Minor Project — Semester 5, IIIT Naya Raipur**  
**Mentors:** Dr. Alaa DAOUD (INSA Hauts-de-France) & Dr. Srinivasa K G (IIIT Naya Raipur)

---

## 1. Overview & Research Focus

This project benchmarks **Tool-Augmented Multi-Agent LLMs vs. Monolithic Single-LLMs vs. Traditional Rule-Based SOPs** on 2D road networks under graduated disruption complexity ($L_1$ to $L_5$).

### Primary Research Question
> *"When does multi-agent LLM coordination actually improve transport-disruption decisions compared with a single LLM agent or traditional rule-based approach (SOPs) on 2D road networks, and is the improvement worth the additional computational and financial cost?"*

---

## 2. Quick Start

### A. Launch Interactive Web Dashboard (Recommended)

```bash
cd project/
source venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```
Opens the interactive browser dashboard with:
- **Comparative Arena**: Side-by-side simulation of B1, B2, and B3 with instant benchmark replay or live Gemini API inference.
- **2D Manhattan Grid Visualizer**: Interactive Plotly map with color-coded disruptions, EV fleet locations, and route overlays.
- **Benchmark Analytics**: Interactive charts for $RFR_w$, $HCVR$, latency, and API dollar economics.
- **Resume & Portfolio Toolkit**: STAR-method resume bullets and talking points ready for CV/LinkedIn.

### B. Run Command-Line Benchmark Experiments

```bash
source venv/bin/activate
python run_benchmark.py
```
Runs the automated benchmark using Google's Gemini API (`gemini-flash-lite-latest`), prints comparison tables, and saves plots to `results/real_benchmark.png` and `results/RESULTS.md`.

---

## 3. Free 1-Click Public Deployment Guide

You can deploy this dashboard online completely free to share on your resume, LinkedIn, or portfolio:

### Option 1: Streamlit Community Cloud (Recommended)
1. Push this repository to GitHub.
2. Visit [share.streamlit.io](https://share.streamlit.io) and log in with GitHub.
3. Click **"New app"**, select your repository, set the main file path to `app.py`, and click **Deploy**.
4. *(Optional)* Add your Gemini API key under **App settings → Secrets** (`GEMINI_API_KEY = "your-key"`).

### Option 2: Hugging Face Spaces
1. Create a new Space on [huggingface.co/spaces](https://huggingface.co/spaces) and select the **Streamlit** SDK.
2. Push this repo's files to the Space repository. Hugging Face will automatically install `requirements.txt` and serve the dashboard.

---

## 4. Project Architecture

The codebase is organized into modular Python components:

```
project/
├── app.py               # Interactive Streamlit Web Dashboard & Research Arena
├── visualizer.py        # 2D Manhattan grid & benchmark Plotly charts generator
├── network.py           # 4×4 Manhattan urban grid (16 nodes, 24 edges with capacities & travel times)
├── tools.py             # Deterministic Tool API (Dijkstra, K-alternative routes, battery checks)
├── scenarios.py         # Graduated L1–L5 scenarios with natural language incident alerts
├── safety_guard.py      # Deterministic physical safety guard (reachability, battery SoC, capacity)
├── controllers.py       # 3 Controllers: B1 (Rule-Based), B2 (Single-LLM), B3 (Tool-Augmented Multi-Agent)
├── run_benchmark.py     # Main experiment runner (live Gemini API calls, metric calculation, plots)
├── build_report.py      # Generates the academic progress report in DOCX format
├── requirements.txt     # Dependencies (streamlit, plotly, networkx, google-genai, matplotlib, numpy)
├── .streamlit/          # UI theme configuration
└── results/             # Benchmark outputs
    ├── real_benchmark.png   # 4-panel comparison plot
    ├── RESULTS.md           # Markdown results table
    └── raw_logs.json        # Raw per-scenario execution logs
```

---

## 5. Key Scientific Results

1. **Unstructured Incident Alerts:**
   - Classical Rule-Based SOPs (B1) lack natural language processing. When road closures are announced via police text alerts, B1 attempts to route through the closed segment and is intercepted by the Safety Guard (resulting in non-zero HCVR).
   - Generative LLM controllers (B2 and B3) successfully parse the alerts and identify impassable roads.

2. **Emergency Priority Allocation:**
   - At high complexity ($L_4$–$L_5$), Multi-Agent coordination (B3) prioritizes emergency hospital requests ($w=3.0$), achieving **$50.0\% - 58.3\%$** weighted fulfillment, whereas Single-LLM collapses to **$26.9\%$** due to context overload.

3. **Latency & Cost Overhead:**
   - Multi-Agent coordination incurs $\sim 3\times - 4\times$ higher wall-clock latency ($\sim 5.0\text{s}$ vs $\sim 1.6\text{s}$) and consumes $\sim 2.5\times$ more tokens.
   - For simple disruptions ($L_1$), classical algorithms remain optimal. Multi-agent coordination is justified only at compound disruption levels ($L_3+$).
