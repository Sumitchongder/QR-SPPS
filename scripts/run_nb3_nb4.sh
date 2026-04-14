#!/bin/bash
# ============================================================
# QR-SPPS NB-3 + NB-4: ADAPT-VQE Policy + DOS-QPE
# ============================================================
# Run from: ~/QARPdemo
#   cd ~/QARPdemo && sbatch run_nb3_nb4.sh
#
# All .pkl files are read/written relative to the working directory.
#
# NB-3 (ADAPT-VQE Policy Optimisation):
#   6 counterfactual policies ranked by gradient screening.
#   Warm-starts from NB2 vqe_params_sub_A (30q ansatz parameters).
#   Each policy runs in ~0.7s (O(1) expectation values, no re-opt).
#   Runtime: ~15 min total.
#
# NB-4 (DOS-QPE Spectral Reconstruction + Cascade Dynamics):
#   64 Trotter steps, T_max=15.0, dt=0.2381, Nyquist=2.10 (no aliasing).
#   Cascade: 10 snapshots, T_casc=6.0, dt_casc=0.6.
#   Tail risk: 6 policies x 60 temperature values.
#   Runtime: ~20-30 min.
#
# Both scripts set QARP_DISABLE_MPI=1 internally.
# Execution: single-node, NO MPI for either notebook.
#
# Depends on: QRSPPS_hamiltonians.pkl  (NB1)
#             QRSPPS_vqe_results.pkl   (NB2)
# Produces:   QRSPPS_policy_results.pkl
#             QRSPPS_dosqpe_results.pkl
#             QRSPPS_policy_effectiveness.png
#             QRSPPS_policy_heatmap.png
#             QRSPPS_policy_map.png
#             QRSPPS_policy_roi.png
#             QRSPPS_dosqpe_full.png
#
# Expected key results (verifiable against .pkl files):
#   NB3: Stockpile release best dE[40q] = -7.4505 (16.67% reduction)
#        Supplier subsidy top ADAPT gradient g = 4.1955
#   NB4: |A(0)| = 1.0000  |A(T_max)| = 0.0746
#        E_cutoff = -43.2197  spectral_width = 1.7333
#        cascade final mean stress = 0.7945
# ============================================================
#SBATCH --job-name=qrspps_nb3nb4
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=12
#SBATCH --partition=Interactive
#SBATCH --time=48:00:00
#SBATCH --output=log_nb3_nb4.txt

source ~/QARPdemo/setup_env.sh

export QARP_DISABLE_MPI=1
export OMP_NUM_THREADS=48

echo "================================================================"
echo " QR-SPPS NB-3 + NB-4: ADAPT-VQE + DOS-QPE"
echo "================================================================"
echo " Start : $(date)"
echo " Node  : $(hostname)"
echo " Job   : $SLURM_JOB_ID"
echo " Dir   : $(pwd)"
echo "================================================================"

# Dependency check
for PKL in QRSPPS_hamiltonians.pkl QRSPPS_vqe_results.pkl; do
    if [ ! -f "$PKL" ]; then
        echo "ERROR: $PKL not found in $(pwd)"
        echo "Ensure NB1 (Jupyter) and NB2 (run_nb2_vqe.sh) completed."
        exit 1
    fi
    echo "Found : $PKL  ($(du -h $PKL | cut -f1))"
done
echo ""

# NB-3
echo "=== Starting NB-3: QRSPPS_NB3_Policy_30q.py ==="
echo "    6 policies via ADAPT-VQE gradient screening"
echo "    Baseline E0[30q]=-33.5198 | E0[40q]=-44.6931"
echo "    Start: $(date)"

python3 QRSPPS_NB3_Policy_30q.py

NB3_EXIT=$?
echo "NB3 exit: $NB3_EXIT  ($(date))"

if [ $NB3_EXIT -ne 0 ]; then
    echo "ERROR: NB-3 failed (exit $NB3_EXIT). NB-4 will not run."
    exit $NB3_EXIT
fi

if [ ! -f "QRSPPS_policy_results.pkl" ]; then
    echo "ERROR: QRSPPS_policy_results.pkl not created. Check log_nb3_nb4.txt."
    exit 1
fi
echo "Output: QRSPPS_policy_results.pkl  ($(du -h QRSPPS_policy_results.pkl | cut -f1))  OK"
echo ""

# NB-4
echo "=== Starting NB-4: QRSPPS_NB4_DOSQPE_30q.py ==="
echo "    64 Trotter steps | T_max=15.0 | dt=0.2381 | Nyquist=2.10"
echo "    Cascade: 10 snapshots | T_casc=6.0"
echo "    Start: $(date)"

python3 QRSPPS_NB4_DOSQPE_30q.py

NB4_EXIT=$?
echo "NB4 exit: $NB4_EXIT  ($(date))"

if [ $NB4_EXIT -ne 0 ]; then
    echo "ERROR: NB-4 failed (exit $NB4_EXIT). Check log_nb3_nb4.txt."
    exit $NB4_EXIT
fi

if [ ! -f "QRSPPS_dosqpe_results.pkl" ]; then
    echo "ERROR: QRSPPS_dosqpe_results.pkl not created. Check log_nb3_nb4.txt."
    exit 1
fi
echo "Output: QRSPPS_dosqpe_results.pkl  ($(du -h QRSPPS_dosqpe_results.pkl | cut -f1))  OK"

echo ""
echo "================================================================"
echo " NB-3 + NB-4 ALL DONE"
echo " End: $(date)"
echo "================================================================"
echo ""
echo "Next steps:"
echo "  Step A: cd ~/QARPdemo && sbatch run_nb5_30q.sh    (12h MPI benchmark)"
echo "  Step B: cd ~/QARPdemo && sbatch run_nb5_final.sh  (after Step A)"
exit 0
