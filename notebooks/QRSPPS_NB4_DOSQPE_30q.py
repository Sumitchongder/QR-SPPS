"""
QR-SPPS Notebook 4: DOS-QPE + Cascade Dynamics + Tail Risk
============================================================
Run in: Jupyter (python3 kernel, no MPI needed)
Depends on: QRSPPS_hamiltonians.pkl, QRSPPS_vqe_results.pkl,
            QRSPPS_policy_results.pkl
Produces:
  QRSPPS_dosqpe_results.pkl
  QRSPPS_dosqpe_full.png
Time: ~20–30 min

30q EXECUTION ARCHITECTURE
===========================
NB1: 40-qubit Hamiltonian encoding of full 40-node supply chain.
NB2: VQE on 30-qubit sub-network (Tier 0+1+2 full + top-10 Retail).
NB3: ADAPT-VQE policy optimization on same 30q sub-network.
NB4 (this):
  - DOS-QPE   : Trotter evolution on 30q, FFT → density of states
  - Cascade   : 30q real-time dynamics snapshots (→ 40q mapped output)
  - Tail risk : Quantum Boltzmann on 40q-scaled energies from NB3

All energies output by this notebook are scaled to 40q equivalents
via the linear extensive relation: E_40q = E_30q × (40/30).
All stress arrays are mapped back to 40q via idx_map_30_to_40 + mean-field
extrapolation for the excluded retail nodes (q30–q39 in 40q space).
"""
import os, sys, time, pickle
import numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from datetime import datetime

sys.path.insert(0, os.path.expanduser('~/QARPdemo'))
os.environ['QARP_DISABLE_MPI'] = '1'

from openfermion import QubitOperator
from qulacs import QuantumState, QuantumCircuit, Observable
from qulacs.gate import RY, CNOT
from qulacs.state import inner_product

T0 = time.time()
def log(msg): print(f"[{time.time()-T0:6.1f}s] {msg}", flush=True)

log("=" * 60)
log("QR-SPPS NB-4: DOS-QPE + Cascade + Tail Risk")
log(f"  {datetime.now()}")
log("=" * 60)

# ── 1. Load data ──────────────────────────────────────────────────────────────
with open('QRSPPS_hamiltonians.pkl',   'rb') as f: ham = pickle.load(f)
with open('QRSPPS_vqe_results.pkl',    'rb') as f: vqe = pickle.load(f)
with open('QRSPPS_policy_results.pkl', 'rb') as f: pol = pickle.load(f)

# Full network metadata (40q)
n_nodes      = ham['n_nodes']          # 40
NODE_LABELS  = ham['NODE_LABELS']      # length-40
TIER         = ham['TIER']
SUPPLY_EDGES = ham['SUPPLY_EDGES']
SHOCK_A      = ham['SHOCK_SCENARIO_A']
E0_extrap_A  = ham['exact_E0_A']       # NB1 40q extrapolated reference
gap_A        = ham.get('spectral_gap_A', 2.1)

# NB2 VQE outputs (30q)
vqe_E0_A_30q     = float(vqe['vqe_E0_A'])           # raw 30q energy
vqe_params_sub_A = np.array(vqe['vqe_params_sub_A']) # 30q ansatz params
n_vqe_q          = int(vqe['n_vqe_q'])               # 30

# 30q ↔ 40q index maps
idx_map_40_to_30 = vqe.get('idx_map_40_to_30', {i: i for i in range(n_vqe_q)})
idx_map_30_to_40 = vqe.get('idx_map_30_to_40', {i: i for i in range(n_vqe_q)})
top10_retail     = vqe.get('top10_retail', list(range(20, 30)))

# 30q sub-network metadata
TIER_30         = {q30: TIER[q40] for q30, q40 in idx_map_30_to_40.items()}
NODE_LABELS_30  = vqe.get('NODE_LABELS_30',
                           [NODE_LABELS[idx_map_30_to_40[i]] for i in range(n_vqe_q)])
SUPPLY_EDGES_30 = vqe.get('SUPPLY_EDGES_30',
                           [(idx_map_40_to_30[s], idx_map_40_to_30[d], J)
                            for s, d, J in SUPPLY_EDGES
                            if s in idx_map_40_to_30 and d in idx_map_40_to_30])
SHOCK_A_30      = [(idx_map_40_to_30[nd], lam)
                   for nd, lam in SHOCK_A if nd in idx_map_40_to_30]

# NB3 policy outputs (energies already 40q-scaled inside pkl)
policy_results  = pol['policy_results']
policy_names    = pol['policy_names']
temperatures    = pol.get('temperatures', np.logspace(-2, 1, 60))

# 40q-scaled VQE baseline (for energy plots)
vqe_E0_A_40q    = vqe_E0_A_30q / n_vqe_q * n_nodes

log(f"Loaded: n_nodes={n_nodes}  n_vqe_q={n_vqe_q}")
log(f"        vqe_E0_A (30q)={vqe_E0_A_30q:.4f}  → (40q scaled)={vqe_E0_A_40q:.4f}")
log(f"        NB1 E0_A (40q extrap)={E0_extrap_A:.4f}")

# ── 2. Helpers ────────────────────────────────────────────────────────────────
def build_H_30(n_q):
    """Ising Hamiltonian on 30q sub-network."""
    tb = {0: 0.1, 1: 0.15, 2: 0.20, 3: 0.25}
    H  = sum((QubitOperator(f'Z{i}', tb.get(TIER_30.get(i, 3), 0.25))
              for i in range(n_q)), QubitOperator())
    H += sum((QubitOperator(f'Z{s} Z{d}', -J)
              for s, d, J in SUPPLY_EDGES_30 if s < n_q and d < n_q),
             QubitOperator())
    for nd, lam in SHOCK_A_30:
        if nd < n_q:
            H += QubitOperator(f'X{nd}', -lam)
    return H


def build_ansatz_d1(nq, params):
    """Depth-1 HEA: RY + CNOT + RY  (2*nq params)."""
    c = QuantumCircuit(nq)
    for q in range(nq):         c.add_gate(RY(q, params[q]))
    for q in range(0, nq-1, 2): c.add_CNOT_gate(q, q + 1)
    for q in range(1, nq-1, 2): c.add_CNOT_gate(q, q + 1)
    for q in range(nq):         c.add_gate(RY(q, params[nq + q]))
    return c


def build_trotter(H, nq, dt):
    """First-order Trotter circuit for e^{-iHdt}."""
    c = QuantumCircuit(nq)
    for term, coeff in H.terms.items():
        if abs(coeff) < 1e-12 or len(term) == 0: continue
        angle = 2.0 * float(coeff.real) * dt
        ops   = list(term)
        if len(ops) == 1:
            idx, op = ops[0]
            if   op == "Z": c.add_RZ_gate(idx, -angle)
            elif op == "X": c.add_RX_gate(idx, -angle)
            elif op == "Y": c.add_RY_gate(idx, -angle)
        elif len(ops) == 2:
            (i0, op0), (i1, op1) = ops
            if op0 == "Z" and op1 == "Z":
                c.add_CNOT_gate(i0, i1)
                c.add_RZ_gate(i1, -angle)
                c.add_CNOT_gate(i0, i1)
    return c


def make_stress_fn(nq):
    """Return function: QuantumState → per-qubit stress vector."""
    N    = 2 ** nq
    idx  = np.arange(N, dtype=np.int64)
    masks = [((idx >> q) & 1).astype(bool) for q in range(nq)]
    def fn(psi_state):
        probs = np.abs(psi_state.get_vector()) ** 2
        return np.array([probs[masks[q]].sum() for q in range(nq)])
    return fn


def map_stress_30_to_40(stress_30):
    """Map 30q stress → 40q, filling excluded retail with mean-field."""
    s40 = np.zeros(n_nodes)
    for q30, q40 in idx_map_30_to_40.items():
        s40[q40] = stress_30[q30]
    retail_30_idx = [idx_map_40_to_30[r] for r in top10_retail
                     if r in idx_map_40_to_30]
    rm = float(np.mean(stress_30[retail_30_idx])) if retail_30_idx else 0.5
    for node in range(n_nodes):
        if TIER[node] == 3 and node not in idx_map_40_to_30:
            s40[node] = rm
    return s40


# ── 3. DOS-QPE — 30q Trotter evolution ───────────────────────────────────────
N_STEPS = 64
T_MAX   = 15.0
log(f"\nDOS-QPE: {N_STEPS} Trotter steps  T_max={T_MAX}  n_vqe_q={n_vqe_q}")

H_A_30  = build_H_30(n_vqe_q)
times   = np.linspace(0, T_MAX, N_STEPS)
dt      = times[1] - times[0]
trotter = build_trotter(H_A_30, n_vqe_q, dt)

# Initial state from NB2 VQE params
psi0 = QuantumState(n_vqe_q)
build_ansatz_d1(n_vqe_q, vqe_params_sub_A).update_quantum_state(psi0)

amplitudes    = np.zeros(N_STEPS, dtype=complex)
amplitudes[0] = 1.0 + 0j

psi_t = QuantumState(n_vqe_q)
psi_t.load(psi0)
for t_idx in range(1, N_STEPS):
    trotter.update_quantum_state(psi_t)
    amplitudes[t_idx] = complex(inner_product(psi0, psi_t))
    if t_idx % 16 == 0:
        log(f"  step {t_idx}/{N_STEPS}  |A|={abs(amplitudes[t_idx]):.3f}")

del psi_t, psi0
log(f"DOS-QPE done | |A|=[{np.abs(amplitudes).min():.3f}, "
    f"{np.abs(amplitudes).max():.3f}]")

# FFT → DOS
window  = np.hanning(N_STEPS)
dos_fft = np.abs(np.fft.fft(amplitudes * window))
freqs   = np.fft.fftfreq(N_STEPS, d=dt) * 2 * np.pi
pos_mask  = freqs >= 0
freqs_pos = freqs[pos_mask]
dos_pos   = dos_fft[pos_mask]
order     = np.argsort(freqs_pos)
energies_A_30q = freqs_pos[order]
dos_A          = dos_pos[order]

# Scale energy axis to 40q for labelling
energy_scale = n_nodes / n_vqe_q  # 40/30
energies_A_40q = energies_A_30q * energy_scale

log(f"  DOS peak energy (30q): {energies_A_30q[np.argmax(dos_A)]:.3f}")
log(f"  DOS peak energy (40q scaled): {energies_A_40q[np.argmax(dos_A)]:.3f}")

# ── 4. Cascade failure dynamics (30q → 40q mapped) ───────────────────────────
N_SNAP  = 10
T_CASC  = 6.0
dt_casc = T_CASC / N_SNAP
log(f"\nCascade dynamics: {N_SNAP} snapshots  T={T_CASC}  on {n_vqe_q}q")

trotter_c = build_trotter(H_A_30, n_vqe_q, dt_casc)
sfn       = make_stress_fn(n_vqe_q)

psi_c = QuantumState(n_vqe_q)
build_ansatz_d1(n_vqe_q, vqe_params_sub_A).update_quantum_state(psi_c)

# 30q cascade matrix
cascade_30 = np.zeros((N_SNAP, n_vqe_q))
for snap in range(N_SNAP):
    trotter_c.update_quantum_state(psi_c)
    cascade_30[snap] = sfn(psi_c)
del psi_c

# Map each snapshot to 40q
cascade_40 = np.zeros((N_SNAP, n_nodes))
for snap in range(N_SNAP):
    cascade_40[snap] = map_stress_30_to_40(cascade_30[snap])

log(f"Cascade done: 30q={cascade_30.shape}  40q={cascade_40.shape}")

# ── 5. Tail risk (quantum Boltzmann on 40q-scaled energies) ──────────────────
log("Computing tail risks ...")

# Spectral width estimated from NB1 gap scaled to 40q
spectral_width = gap_A * (n_nodes / n_vqe_q)
E_cutoff       = vqe_E0_A_40q + 0.85 * spectral_width

def tail_risk(E0_40q, width, temps):
    """P(catastrophe) vs temperature using Gaussian DOS model."""
    Eg    = np.linspace(E0_40q, E0_40q + width, 400)
    sigma = width / 6
    dos   = np.exp(-((Eg - (E0_40q + width / 2)) ** 2) / (2 * sigma ** 2))
    cat   = Eg >= (E0_40q + 0.85 * width)
    tr    = np.zeros(len(temps))
    for i, T in enumerate(temps):
        bw = np.exp(-(Eg - E0_40q) / T) * dos
        Z  = bw.sum()
        tr[i] = bw[cat].sum() / Z if Z > 0 else 0.0
    return tr


policy_tail_risks = {}
for name in policy_names:
    # policy_results[name]["E0"] is already 40q-scaled (set in NB3)
    E0_pol = float(policy_results[name]["E0"])
    policy_tail_risks[name] = tail_risk(E0_pol, spectral_width, temperatures)

cat_overlaps = {n: float(policy_tail_risks[n][30]) for n in policy_names}
log("Tail risks done")

# ── 6. Full DOS-QPE dashboard ─────────────────────────────────────────────────
log("Plotting full dashboard ...")
COLS = ["#64748b", "#4f8ef7", "#10d9a0", "#f59e0b", "#8b5cf6", "#ef4444"]

fig = plt.figure(figsize=(24, 13))
gs  = gridspec.GridSpec(2, 3, figure=fig, hspace=0.45, wspace=0.36)

# Panel 1: DOS (energy axis in 40q-scaled units)
ax1 = fig.add_subplot(gs[0, 0])
mask = (energies_A_40q >= 0) & (energies_A_40q < 20 * energy_scale)
ax1.plot(energies_A_40q[mask], dos_A[mask], color="#7F77DD", lw=1.5)
ax1.axvline(x=abs(vqe_E0_A_40q) / n_nodes,
            color='#D85A30', ls='--', lw=1.5,
            label=f'E0 density={vqe_E0_A_40q/n_nodes:.3f}')
ax1.set_xlabel("Energy (40q-scaled units)")
ax1.set_ylabel("DOS (arbitrary units)")
ax1.set_title(
    f"Density of States via QPE\n"
    f"{n_vqe_q}q Trotter  |  {N_STEPS} steps  →  40q scaled",
    fontsize=10)
ax1.legend(fontsize=8)
ax1.grid(True, alpha=0.3)

# Panel 2: Survival amplitude A(t)
ax2 = fig.add_subplot(gs[0, 1])
ax2.plot(times, np.real(amplitudes), color="#534AB7", lw=1.5, label="Re[A(t)]")
ax2.plot(times, np.imag(amplitudes), color="#D85A30", lw=1.0,  label="Im[A(t)]")
ax2.plot(times, np.abs(amplitudes),  color="#1D9E75", lw=1.0,
         ls="--", label="|A(t)|")
ax2.set_xlabel("Time t")
ax2.set_ylabel("Amplitude")
ax2.set_title(
    f"Survival amplitude ⟨ψ|e⁻ⁱᴴᵗ|ψ⟩\n"
    f"H = 30q sub-network  |  T_max={T_MAX}",
    fontsize=10)
ax2.legend(fontsize=8)
ax2.grid(True, alpha=0.3)

# Panel 3: Cascade matrix (40q full network)
ax3 = fig.add_subplot(gs[0, 2])
im3 = ax3.imshow(cascade_40.T, cmap="RdYlGn_r", aspect="auto", vmin=0, vmax=1)
ts  = max(1, n_nodes // 8)
ax3.set_yticks(range(0, n_nodes, ts))
ax3.set_yticklabels([NODE_LABELS[i] for i in range(0, n_nodes, ts)], fontsize=6)
ax3.axhline(y=n_vqe_q - 0.5, color='white', lw=1.5, ls='--',
            alpha=0.8)
ax3.set_xlabel("Snapshot")
ax3.set_ylabel("Node (40q full network)")
ax3.set_title(
    f"Cascade failure dynamics\n"
    f"30q Trotter → 40q mapped  |  {N_SNAP} snapshots  |  dashed=30q/40q boundary",
    fontsize=9)
plt.colorbar(im3, ax=ax3, label="P(|1⟩)")

# Panel 4: Tail risk curves
ax4 = fig.add_subplot(gs[1, 0])
for (name, tr), col in zip(policy_tail_risks.items(), COLS):
    ax4.semilogx(temperatures, np.array(tr) * 100, color=col, lw=1.5,
                 label=name, ls="--" if name == "No intervention" else "-")
ax4.set_xlabel("Temperature (market volatility)")
ax4.set_ylabel("P(catastrophe) %")
ax4.set_title(
    "Tail risk vs market volatility\n"
    "(Quantum Boltzmann, 40q-scaled energies)",
    fontsize=10)
ax4.legend(fontsize=7)
ax4.grid(True, alpha=0.3)

# Panel 5: Policy ground-state energies (40q)
ax5 = fig.add_subplot(gs[1, 1])
pol_E = [float(policy_results[n]["E0"]) for n in policy_names]
ax5.barh(policy_names, pol_E, color=COLS)
ax5.axvline(x=vqe_E0_A_40q, color="red", ls="--", lw=1.5,
            label=f"VQE baseline={vqe_E0_A_40q:.3f}")
ax5.axvline(x=E0_extrap_A, color="navy", ls=":", lw=1.5,
            label=f"NB1 extrap={E0_extrap_A:.3f}")
ax5.set_xlabel("E0 (40q scaled)")
ax5.set_title(
    "Policy ground-state energy\n"
    "(30q VQE → ×(40/30) scaling)",
    fontsize=10)
ax5.legend(fontsize=7)
ax5.grid(True, axis="x", alpha=0.3)

# Panel 6: Tail risk at unit volatility
ax6 = fig.add_subplot(gs[1, 2])
tr_T1 = [policy_tail_risks[n][30] * 100 for n in policy_names]
bars6 = ax6.barh(policy_names, tr_T1, color=COLS)
ax6.set_xlabel("P(catastrophe) % at T=1")
ax6.set_title(
    "Tail risk at unit volatility\n"
    "(catastrophe = E > E0 + 0.85·ΔE_spectral)",
    fontsize=10)
ax6.grid(True, axis="x", alpha=0.3)
for bar, v in zip(bars6, tr_T1):
    ax6.text(bar.get_width() + max(tr_T1) * 0.01,
             bar.get_y() + bar.get_height() / 2,
             f"{v:.1f}%", va='center', fontsize=8)

plt.suptitle(
    f"QR-SPPS DOS-QPE + Cascade Dynamics + Tail Risk\n"
    f"30q execution  →  40q full network (n={n_nodes} nodes)",
    fontsize=13, fontweight="bold")
plt.savefig("QRSPPS_dosqpe_full.png", dpi=150, bbox_inches="tight")
log("Saved: QRSPPS_dosqpe_full.png")

# ── 7. Save pkl ───────────────────────────────────────────────────────────────
with open("QRSPPS_dosqpe_results.pkl", "wb") as f:
    pickle.dump({
        # DOS-QPE (30q execution, energy axis in both 30q and 40q units)
        "energies_A":          energies_A_30q,    # 30q raw frequencies
        "energies_A_40q":      energies_A_40q,    # 40q scaled
        "dos_A":               dos_A,
        "survival_A":          amplitudes,
        "times_A":             times,
        # Cascade (both 30q raw and 40q mapped)
        "cascade_matrix_30q":  cascade_30,
        "cascade_matrix":      cascade_40,        # 40q (NB5/downstream expects this)
        "stress_dynamics":     cascade_40,
        "times_dynamics":      np.linspace(0, T_CASC, N_SNAP),
        # Tail risk
        "temperatures":        temperatures,
        "policy_tail_risks":   policy_tail_risks,
        "tail_risks":          policy_tail_risks,
        "cat_overlaps":        cat_overlaps,
        "E_cutoff":            E_cutoff,
        "spectral_width_est":  spectral_width,
        # Reference energies
        "vqe_E0_A_30q":        vqe_E0_A_30q,
        "vqe_E0_A":            vqe_E0_A_40q,     # 40q scaled (downstream compat)
        "E0_extrap_40q":       E0_extrap_A,
        "evals_A":             ham.get('eigs_A', energies_A_30q[:20]),
        # Metadata
        "n_nodes":             n_nodes,           # 40
        "n_vqe_q":             n_vqe_q,           # 30
        "N_STEPS":             N_STEPS,
        "idx_map_40_to_30":    idx_map_40_to_30,
        "idx_map_30_to_40":    idx_map_30_to_40,
    }, f)
log("Saved: QRSPPS_dosqpe_results.pkl")

# ── 8. Final summary ──────────────────────────────────────────────────────────
best_policy = min(policy_names, key=lambda n: policy_tail_risks[n][30])
log("")
log("=" * 60)
log("=== NB-4 Complete ===")
log(f"  Execution      : {n_vqe_q}q Trotter → {n_nodes}q network (mapped)")
log(f"  DOS steps      : {N_STEPS}")
log(f"  Cascade snaps  : {N_SNAP}")
log(f"  Lowest tail risk policy: {best_policy}  "
    f"({policy_tail_risks[best_policy][30]*100:.1f}%)")
log(f"  Total time     : {time.time()-T0:.0f}s")
log("=" * 60)
