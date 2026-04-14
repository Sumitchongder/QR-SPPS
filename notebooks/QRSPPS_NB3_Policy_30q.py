"""
QR-SPPS Notebook 3: ADAPT-VQE Policy Optimization
===================================================
Run in: Jupyter (python3 kernel, no MPI needed)
Depends on: QRSPPS_hamiltonians.pkl, QRSPPS_vqe_results.pkl
Produces:
  QRSPPS_policy_results.pkl
  QRSPPS_policy_effectiveness.png
  QRSPPS_policy_heatmap.png
  QRSPPS_policy_map.png
  QRSPPS_policy_roi.png
Time: ~15 min

30q EXECUTION ARCHITECTURE
===========================
NB1 encoded a 40-node supply chain into a 40-qubit Hamiltonian.
NB2 ran VQE on a 30-qubit sub-network (Tier 0+1+2 full + top-10 Retail).

This notebook (NB3) runs ADAPT-VQE policy optimization on the SAME 30-qubit
sub-network, using the index map stored in QRSPPS_vqe_results.pkl to correctly
apply policy perturbations to the 30q qubit indices.

Translation used throughout:
  - vqe['idx_map_40_to_30']  : {40q_node_idx -> 30q_qubit_idx}
  - vqe['idx_map_30_to_40']  : {30q_qubit_idx -> 40q_node_idx}
  - n_vqe_q = 30             : actual execution qubit count
  - n_nodes  = 40            : full network size (for energy scaling & output)

Policy operators are constructed in 30q qubit space, VQE runs on 30q,
results are mapped back to 40q for business metrics and visualisation.
"""
import os, sys, time, pickle
import numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from scipy.optimize import minimize
from datetime import datetime

sys.path.insert(0, os.path.expanduser('~/QARPdemo'))
os.environ['QARP_DISABLE_MPI'] = '1'

from openfermion import QubitOperator
from qulacs import QuantumState, QuantumCircuit, Observable
from qulacs.gate import RY, CNOT

T0 = time.time()
def log(msg): print(f"[{time.time()-T0:6.1f}s] {msg}", flush=True)

log("=" * 60)
log("QR-SPPS NB-3: ADAPT-VQE Policy Optimization")
log(f"  {datetime.now()}")
log("=" * 60)

# ── 1. Load data ──────────────────────────────────────────────────────────────
with open('QRSPPS_hamiltonians.pkl', 'rb') as f:
    ham = pickle.load(f)
with open('QRSPPS_vqe_results.pkl', 'rb') as f:
    vqe = pickle.load(f)

n_nodes          = ham['n_nodes']          # 40 — full network
NODE_LABELS      = ham['NODE_LABELS']      # length-40
TIER             = ham['TIER']             # {node_40q: tier}
SUPPLY_EDGES     = ham['SUPPLY_EDGES']     # 40q original edges
SHOCK_A          = ham['SHOCK_SCENARIO_A'] # 40q shock indices

vqe_E0_A         = float(vqe['vqe_E0_A'])          # 30q raw VQE energy
vqe_params_sub_A = np.array(vqe['vqe_params_sub_A'])# 30q ansatz params
n_vqe_q          = int(vqe['n_vqe_q'])              # 30

# 30q ↔ 40q index maps (saved by NB2)
idx_map_40_to_30 = vqe.get('idx_map_40_to_30', {i: i for i in range(n_vqe_q)})
idx_map_30_to_40 = vqe.get('idx_map_30_to_40', {i: i for i in range(n_vqe_q)})
top10_retail     = vqe.get('top10_retail', list(range(20, 30)))

# 30q sub-network metadata (reconstructed from maps)
TIER_30          = {q30: TIER[q40] for q30, q40 in idx_map_30_to_40.items()}
NODE_LABELS_30   = vqe.get('NODE_LABELS_30',
                            [NODE_LABELS[idx_map_30_to_40[i]] for i in range(n_vqe_q)])
SUPPLY_EDGES_30  = vqe.get('SUPPLY_EDGES_30',
                            [(idx_map_40_to_30[s], idx_map_40_to_30[d], J)
                             for s, d, J in SUPPLY_EDGES
                             if s in idx_map_40_to_30 and d in idx_map_40_to_30])
SHOCK_A_30       = [(idx_map_40_to_30[nd], lam)
                    for nd, lam in SHOCK_A if nd in idx_map_40_to_30]

# 40q stress from NB2 (direct 30q + mean-field extrapolated for q30–q39)
stress_vqe_A_40  = np.array(vqe.get('stress_vqe_A_40q',
                                     np.tile(np.array(vqe['stress_vqe_A']),
                                             n_nodes // n_vqe_q + 1)[:n_nodes]))
stress_vqe_A_30  = np.array(vqe['stress_vqe_A'])   # raw 30q output

log(f"Loaded: n_nodes={n_nodes}  n_vqe_q={n_vqe_q}  vqe_E0_A(30q)={vqe_E0_A:.4f}")
log(f"        idx_map covers {len(idx_map_40_to_30)} of {n_nodes} nodes in 30q space")
log(f"        30q sub-net: {n_vqe_q} qubits  "
    f"(Tier0+1+2 full + top-10 retail: {top10_retail})")

# ── 2. Helpers ────────────────────────────────────────────────────────────────
def build_H(supply_edges, tier, shocks, n_q):
    """Ising Hamiltonian on n_q qubits."""
    tb = {0: 0.1, 1: 0.15, 2: 0.20, 3: 0.25}
    H  = sum((QubitOperator(f'Z{i}', tb.get(tier.get(i, 3), 0.25))
              for i in range(n_q)), QubitOperator())
    H += sum((QubitOperator(f'Z{s} Z{d}', -J)
              for s, d, J in supply_edges if s < n_q and d < n_q), QubitOperator())
    for nd, lam in shocks:
        if nd < n_q:
            H += QubitOperator(f'X{nd}', -lam)
    return H


def build_obs(H, nq):
    obs = Observable(nq)
    for term, coeff in H.terms.items():
        if abs(coeff) < 1e-12: continue
        if len(term) == 0:
            obs.add_operator(coeff.real, "")
        else:
            obs.add_operator(coeff.real,
                             " ".join(f"{op} {idx}" for idx, op in term))
    return obs


def build_ansatz(nq, params):
    """Depth-1 HEA: RY + CNOT + RY  (2*nq params)."""
    c = QuantumCircuit(nq)
    for q in range(nq):      c.add_gate(RY(q, params[q]))
    for q in range(0, nq-1, 2): c.add_CNOT_gate(q, q + 1)
    for q in range(1, nq-1, 2): c.add_CNOT_gate(q, q + 1)
    for q in range(nq):      c.add_gate(RY(q, params[nq + q]))
    return c


def cost_fn(obs, nq):
    def cost(p):
        st = QuantumState(nq)
        build_ansatz(nq, p).update_quantum_state(st)
        return float(obs.get_expectation_value(st))
    return cost


def stress_from_wf(params, nq):
    """Extract per-qubit stress from ansatz wavefunction (30q space)."""
    st  = QuantumState(nq)
    build_ansatz(nq, params).update_quantum_state(st)
    psi = st.get_vector()
    N   = 2 ** nq
    idx = np.arange(N, dtype=np.int64)
    return np.array([np.abs(psi[((idx >> q) & 1).astype(bool)])**2 .sum()
                     for q in range(nq)])


def map_stress_30_to_40(stress_30, retail_stress_mean=None):
    """Map 30q stress vector → 40q.  Excluded retail → mean-field value."""
    s40 = np.zeros(n_nodes)
    for q30, q40 in idx_map_30_to_40.items():
        s40[q40] = stress_30[q30]
    # Mean-field fill for excluded Tier-3 retail nodes
    if retail_stress_mean is None:
        retail_30_idx = [idx_map_40_to_30[r] for r in top10_retail
                         if r in idx_map_40_to_30]
        retail_stress_mean = float(np.mean(stress_30[retail_30_idx])) if retail_30_idx else 0.5
    excluded = [i for i in range(n_nodes)
                if TIER[i] == 3 and i not in idx_map_40_to_30]
    for node in excluded:
        s40[node] = retail_stress_mean
    return s40


# ── 3. 30q policy operators (built in 30q qubit space) ───────────────────────
# Node sets in 30q qubit indices
retail_30    = [i for i in range(n_vqe_q) if TIER_30.get(i, 3) == 3]
supplier_30  = [i for i in range(n_vqe_q) if TIER_30.get(i, 3) == 1]
dist_30      = [i for i in range(n_vqe_q) if TIER_30.get(i, 3) == 2]

log(f"  30q Tier-3 (retail)     : {retail_30}")
log(f"  30q Tier-1 (suppliers)  : {supplier_30}")
log(f"  30q Tier-2 (distrib.)   : {dist_30}")


def policy_op(name):
    """Return QubitOperator perturbation in 30q qubit space."""
    if name == "No intervention":
        return QubitOperator()

    if name == "Rate hike":
        # Raise energy cost for stressed retail nodes → Z penalty on retail qubits
        return sum((QubitOperator(f"Z{q}", 0.4) for q in retail_30), QubitOperator())

    if name == "Supplier subsidy":
        # X-field on supplier qubits: encourages superposition (resilience boost)
        return sum((QubitOperator(f"X{q}", -0.6) for q in supplier_30), QubitOperator())

    if name == "Stockpile release":
        # Z penalty relief on distributors + reduced ZZ coupling to retail
        H = sum((QubitOperator(f"Z{q}", 0.5) for q in dist_30), QubitOperator())
        if dist_30 and retail_30:
            H += QubitOperator(f"Z{dist_30[0]} Z{retail_30[0]}", 0.2)
        return H

    if name == "Trade diversion":
        # Re-route: strengthen alternate Tier-0 → Tier-1 couplings
        # Use actual 30q qubit indices for RM-A (q0) and suppliers (q2, q3)
        rm_a_30   = idx_map_40_to_30.get(0, 0)
        sup2_30   = idx_map_40_to_30.get(2, 2)
        sup3_30   = idx_map_40_to_30.get(3, 3)
        rm_b_30   = idx_map_40_to_30.get(1, 1)
        return (QubitOperator(f"Z{rm_a_30} Z{sup2_30}", 0.5)
                + QubitOperator(f"Z{rm_a_30} Z{sup3_30}", 0.4)
                + QubitOperator(f"X{rm_b_30}", -0.3))

    if name == "Combined optimal":
        # Best blend: retail Z-penalty + supplier X-field + RM-A re-routing
        H  = sum((QubitOperator(f"Z{q}", 0.3) for q in retail_30[:4]),    QubitOperator())
        H += sum((QubitOperator(f"X{q}", -0.4) for q in supplier_30[:2]), QubitOperator())
        rm_a_30 = idx_map_40_to_30.get(0, 0)
        sup2_30 = idx_map_40_to_30.get(2, 2)
        H += QubitOperator(f"Z{rm_a_30} Z{sup2_30}", 0.3)
        return H

    return QubitOperator()


POLICY_NAMES = ["No intervention", "Rate hike", "Supplier subsidy",
                "Stockpile release", "Trade diversion", "Combined optimal"]
PAL          = ["#64748b", "#4f8ef7", "#10d9a0", "#f59e0b", "#8b5cf6", "#ef4444"]
POLICY_COSTS = {
    "No intervention":   0,
    "Rate hike":         2.0,
    "Supplier subsidy":  5.0,
    "Stockpile release": 3.0,
    "Trade diversion":   1.5,
    "Combined optimal":  8.0,
}

# ── 4. ADAPT gradient screening (30q) ────────────────────────────────────────
log("\nADAPT gradient screening on 30q sub-network ...")
H_base_30  = build_H(SUPPLY_EDGES_30, TIER_30, SHOCK_A_30, n_vqe_q)
obs_base_30 = build_obs(H_base_30, n_vqe_q)

gradients = {}
eps = 0.1

for name in POLICY_NAMES:
    if name == "No intervention":
        gradients[name] = 0.0
        continue
    P = policy_op(name)
    if not any(t != () for t in P.terms):
        gradients[name] = len(list(P.terms)) * 0.05
        continue
    cf_p = cost_fn(build_obs(H_base_30 + P * eps,  n_vqe_q), n_vqe_q)
    cf_m = cost_fn(build_obs(H_base_30 + P * (-eps), n_vqe_q), n_vqe_q)
    Ep   = cf_p(vqe_params_sub_A)
    Em   = cf_m(vqe_params_sub_A)
    gradients[name] = abs((Ep - Em) / (2 * eps))
    log(f"  {name:22s}: grad={gradients[name]:.4f}")

ranked = sorted(gradients.items(), key=lambda x: x[1], reverse=True)
log(f"  Top policy by ADAPT: {ranked[0][0]}")

# ── 5. Policy VQE (serial, 30q warm-started from NB2 params) ─────────────────
log("\nRunning policy VQE (6 policies, 30q, warm-started from NB2) ...")
policy_results = {}

for name in POLICY_NAMES:
    t0 = time.time()

    if name == "No intervention":
        stress_30 = stress_from_wf(vqe_params_sub_A, n_vqe_q)
        stress_40 = map_stress_30_to_40(stress_30)
        policy_results[name] = {
            "E0":            vqe_E0_A / n_vqe_q * n_nodes,  # scale to 40q
            "E0_30q":        vqe_E0_A,
            "params_sub":    vqe_params_sub_A,
            "history":       [],
            "stress_30q":    stress_30,
            "stress":        stress_40,
            "delta_E":       0.0,
            "delta_stress":  np.zeros(n_nodes),
            "nodes_relieved":0,
            "gradient":      0.0,
            "time":          0.0,
        }
        log(f"  {name:22s}: analytical baseline (30q→40q mapped)")
        continue

    P        = policy_op(name)
    H_pol    = H_base_30 + P
    obs_pol  = build_obs(H_pol, n_vqe_q)

    np.random.seed(hash(name) % 2 ** 31)
    p0   = vqe_params_sub_A + np.random.randn(len(vqe_params_sub_A)) * 0.05
    hist = []
    cf   = cost_fn(obs_pol, n_vqe_q)

    def cb(p):
        hist.append(cf(p))

    res = minimize(cf, p0, method='COBYLA', callback=cb,
                   options={'maxiter': 25, 'rhobeg': 0.3})
    dt  = time.time() - t0

    # 30q energy → 40q scaled
    E0_30q = res.fun
    E0_40q = E0_30q / n_vqe_q * n_nodes
    dE     = E0_40q - (vqe_E0_A / n_vqe_q * n_nodes)

    # Stress: direct from wavefunction, then mapped to 40q
    stress_30 = stress_from_wf(res.x, n_vqe_q)
    stress_40 = map_stress_30_to_40(stress_30)
    delta_s   = stress_40 - stress_vqe_A_40
    nr        = int(np.sum(delta_s < -0.01))

    policy_results[name] = {
        "E0":            E0_40q,
        "E0_30q":        E0_30q,
        "params_sub":    res.x,
        "history":       hist,
        "stress_30q":    stress_30,
        "stress":        stress_40,
        "delta_E":       dE,
        "delta_stress":  delta_s,
        "nodes_relieved":nr,
        "gradient":      gradients[name],
        "time":          dt,
    }
    log(f"  {name:22s}: E0_30q={E0_30q:.3f}  E0_40q={E0_40q:.3f}  "
        f"dE={dE:+.3f}  relief={nr}  ({dt:.1f}s)")

# ── 6. Business metrics ───────────────────────────────────────────────────────
log("\nComputing business metrics ...")
baseline_stress = np.mean(policy_results["No intervention"]["stress"])
for name in POLICY_NAMES:
    dE   = policy_results[name]["delta_E"]
    cost = POLICY_COSTS[name]
    roi  = abs(dE) / cost if cost > 0 else 0.0
    mean_s = np.mean(policy_results[name]["stress"])
    resil  = max(0.0, 100.0 * (1.0 - mean_s / baseline_stress))
    tput   = policy_results[name]["nodes_relieved"] * 0.12
    policy_results[name]["roi"]                   = roi
    policy_results[name]["resilience_score"]      = resil
    policy_results[name]["throughput_recovered"]  = tput
    policy_results[name]["cost_units"]            = cost

delta_matrix = np.array([policy_results[n]["delta_stress"] for n in POLICY_NAMES])

# ── 7. Figure 1: Policy effectiveness ────────────────────────────────────────
log("Plotting figures ...")
names = POLICY_NAMES
dEs   = [policy_results[n]["delta_E"]        for n in names]
nrs   = [policy_results[n]["nodes_relieved"]  for n in names]
grads = [policy_results[n]["gradient"]        for n in names]

fig, axes = plt.subplots(1, 3, figsize=(18, 6))
for ax, vals, xlabel, title in [
    (axes[0], dEs,   "ΔE0 (40q scaled)",    "Energy reduction (lower=better)"),
    (axes[1], nrs,   "Nodes relieved",       "Network relief (higher=better)"),
    (axes[2], grads, "ADAPT |∂E/∂λ| (30q)", "Policy priority (ADAPT gradient)"),
]:
    ax.barh(names, vals, color=PAL)
    if ax is axes[0]:
        ax.axvline(x=0, color='black', lw=0.8)
    ax.set_xlabel(xlabel)
    ax.set_title(title, fontsize=11)
    ax.grid(True, axis='x', alpha=0.3)

plt.suptitle(
    f"QR-SPPS Policy Effectiveness — ADAPT-VQE\n"
    f"30q execution → 40q mapped  |  n_vqe_q={n_vqe_q}  n_nodes={n_nodes}",
    fontsize=12, fontweight='bold')
plt.tight_layout()
plt.savefig('QRSPPS_policy_effectiveness.png', dpi=150, bbox_inches='tight')
log("Saved: QRSPPS_policy_effectiveness.png")

# ── 8. Figure 2: Policy heatmap (40q full network) ───────────────────────────
fig, ax = plt.subplots(figsize=(20, 5))
vmax = max(0.3, float(np.abs(delta_matrix).max()))
im   = ax.imshow(delta_matrix, cmap='RdYlGn', aspect='auto',
                 vmin=-vmax, vmax=vmax)
plt.colorbar(im, ax=ax, label='Δ stress (green=relief, red=worsened)')
ax.set_xticks(range(n_nodes))
ax.set_xticklabels(
    [f"{NODE_LABELS[i]}\n[T{TIER[i]}]" for i in range(n_nodes)],
    fontsize=5.5, ha='center')
ax.set_yticks(range(len(names)))
ax.set_yticklabels(names, fontsize=9)

# Tier boundary lines
tier_starts = {}
for i in range(n_nodes):
    t = TIER[i]
    if t not in tier_starts:
        tier_starts[t] = i
for t, boundary in sorted(tier_starts.items())[1:]:
    ax.axvline(x=boundary - 0.5, color='gray', lw=1.5, ls=':')

# Mark which nodes are extrapolated vs direct VQE
for i in range(n_nodes):
    if i not in idx_map_40_to_30:
        ax.axvline(x=i, color='white', lw=0.4, alpha=0.3)

ax.set_title(
    f"Policy Relief Heatmap — 30q exec → 40q  |  Green=relief\n"
    f"(faint white bars = mean-field extrapolated nodes q30–q39)",
    fontsize=11, fontweight='bold')
plt.tight_layout()
plt.savefig('QRSPPS_policy_heatmap.png', dpi=150, bbox_inches='tight')
log("Saved: QRSPPS_policy_heatmap.png")

# ── 9. Figure 3: Per-policy stress map (40q) ─────────────────────────────────
fig, axes = plt.subplots(2, 3, figsize=(22, 10))
axes = axes.flatten()
for ax, name, col in zip(axes, names, PAL):
    stress_40 = policy_results[name]["stress"]
    bar_colors = [
        "#8B0000" if s >= 0.85 else
        ("#C63030" if s >= 0.5 else
         ("#E87070" if s >= 0.25 else "#B5EAD7"))
        for s in stress_40
    ]
    ax.bar(range(n_nodes), stress_40, color=bar_colors, edgecolor='white', lw=0.3)
    ax.step(list(range(n_nodes)) + [n_nodes - 1],
            list(stress_vqe_A_40) + [stress_vqe_A_40[-1]],
            where='mid', color='#334155', ls='--', lw=1, alpha=0.6,
            label='Baseline (NB2)')
    # Mark boundary between direct VQE and extrapolated nodes
    ax.axvline(x=n_vqe_q - 0.5, color='navy', lw=1.2, ls=':', alpha=0.7,
               label=f'30q/40q boundary')
    ax.set_ylim(0, 1.15)
    ax.set_xticks(range(0, n_nodes, max(1, n_nodes // 8)))
    ax.set_xticklabels(
        [NODE_LABELS[i] for i in range(0, n_nodes, max(1, n_nodes // 8))],
        rotation=45, ha='right', fontsize=7)
    dE = policy_results[name]["delta_E"]
    nr = policy_results[name]["nodes_relieved"]
    rs = policy_results[name]["resilience_score"]
    ax.set_title(
        f"{name}\nΔE={dE:+.3f}  relief={nr}  resilience={rs:.0f}/100",
        fontsize=9, fontweight='bold')
    ax.legend(fontsize=7)
    ax.grid(True, axis='y', alpha=0.3)

plt.suptitle(
    f"QR-SPPS Policy Map — 30q ADAPT-VQE → 40q network\n"
    f"(left of dashed line: direct VQE | right: mean-field extrapolated)",
    fontsize=12, fontweight='bold')
plt.tight_layout()
plt.savefig('QRSPPS_policy_map.png', dpi=150, bbox_inches='tight')
log("Saved: QRSPPS_policy_map.png")

# ── 10. Figure 4: ROI / Business applicability ────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(18, 6))
rois   = [policy_results[n]["roi"]                  for n in names]
resils = [policy_results[n]["resilience_score"]     for n in names]
tputs  = [policy_results[n]["throughput_recovered"] for n in names]
for ax, vals, xlabel, title, fmt in [
    (axes[0], rois,   "ROI (ΔE/cost)",           "Policy ROI",          "{:.3f}"),
    (axes[1], resils, "Resilience score (0–100)", "Supply Resilience",   "{:.1f}"),
    (axes[2], tputs,  "Throughput recovery",      "Throughput Recovery", "{:.1%}"),
]:
    bars = ax.barh(names, vals, color=PAL)
    ax.set_xlabel(xlabel)
    ax.set_title(title, fontsize=10, fontweight='bold')
    ax.grid(True, axis='x', alpha=0.3)
    for bar, v in zip(bars, vals):
        ax.text(bar.get_width() + max(vals) * 0.01,
                bar.get_y() + bar.get_height() / 2,
                fmt.format(v), va='center', fontsize=8)

plt.suptitle(
    f"QR-SPPS Business Impact — 30q ADAPT-VQE Policy Analysis\n"
    f"(energies scaled to 40q full network for business comparability)",
    fontsize=12, fontweight='bold')
plt.tight_layout()
plt.savefig('QRSPPS_policy_roi.png', dpi=150, bbox_inches='tight')
log("Saved: QRSPPS_policy_roi.png")

# ── 11. Save pkl (all keys NB4 expects) ──────────────────────────────────────
best_dE = min(POLICY_NAMES, key=lambda k: policy_results[k]["delta_E"])

with open('QRSPPS_policy_results.pkl', 'wb') as f:
    pickle.dump({
        # Core results
        'policy_results':   policy_results,
        'policy_names':     POLICY_NAMES,
        'gradients':        gradients,
        'ranked_policies':  ranked,
        'delta_matrix':     delta_matrix,
        # Stress arrays (both 30q and 40q)
        'stress_vqe_A':     stress_vqe_A_40,   # 40q (NB4 expects n_nodes length)
        'stress_vqe_A_30q': stress_vqe_A_30,   # 30q raw
        'vqe_E0_A':         vqe_E0_A / n_vqe_q * n_nodes,  # 40q scaled
        'vqe_E0_A_30q':     vqe_E0_A,           # 30q raw
        # Network metadata
        'n_nodes':          n_nodes,             # 40
        'n_vqe_q':          n_vqe_q,             # 30
        'NODE_LABELS':      NODE_LABELS,         # length-40
        'NODE_LABELS_30':   NODE_LABELS_30,
        'TIER':             TIER,
        'TIER_30':          TIER_30,
        'SUPPLY_EDGES':     SUPPLY_EDGES,
        'SUPPLY_EDGES_30':  SUPPLY_EDGES_30,
        # Index maps for NB4
        'idx_map_40_to_30': idx_map_40_to_30,
        'idx_map_30_to_40': idx_map_30_to_40,
        'top10_retail':     top10_retail,
        # Temperature grid for NB4 tail-risk
        'temperatures':     np.logspace(-2, 1, 60),
    }, f)
log("Saved: QRSPPS_policy_results.pkl")

# ── 12. Final summary ─────────────────────────────────────────────────────────
log("")
log("=" * 60)
log("=== NB-3 Complete ===")
log(f"  Execution   : {n_vqe_q}q ADAPT-VQE → {n_nodes}q network (mapped)")
log(f"  Best policy : {best_dE}  (ΔE={policy_results[best_dE]['delta_E']:+.4f}, 40q scaled)")
log(f"  Top ADAPT   : {ranked[0][0]}  (grad={ranked[0][1]:.4f})")
log(f"  Total time  : {time.time()-T0:.0f}s")
log("=" * 60)
