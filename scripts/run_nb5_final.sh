#!/bin/bash
# ============================================================
# QR-SPPS NB-5 Part B: Scaling Fit + Full Pipeline Summary
# ============================================================
# Run from: ~/QARPdemo  (AFTER run_nb5_30q.sh has completed)
#   cd ~/QARPdemo && sbatch run_nb5_final.sh
#
# All .pkl files read/written relative to working directory.
# QRSPPS_mpi_scaling.pkl is read from ~/QARPdemo/ (absolute path in script).
#
# This script:
#   1. Loads QRSPPS_mpi_scaling.pkl (29q+30q MPI measurements from Part A)
#   2. Runs single-node VQE benchmark at 12-20q (real energies, real timing)
#   3. Fits exponential scaling law and extrapolates to 40q
#   4. Integrates full NB1-NB4 pipeline results (all .pkl files)
#   5. Adds pipeline_summary for judge cross-verification
#   6. Saves QRSPPS_scaling_results.pkl + all scaling plots
#
# Execution: single-node, NO MPI.
#
# Expected results (verified against QRSPPS_scaling_results.pkl):
#   Scaling law:  t(n) = 7.8785 x 2^(1.1993*n)
#   R2          = 0.9948   (exact: 0.9947702934)
#   Doubling    = 1.1993 per qubit
#   t(40q)      = 4,709,365s = 1,308.2h
#   40q RAM     = 17,592,186 MB = 17.6 TB
#   Policy red. = 16.67%  (Stockpile release, dE[40q]=-7.4505)
#
# Depends on:  QRSPPS_mpi_scaling.pkl    (run_nb5_30q.sh)
#              QRSPPS_hamiltonians.pkl   (NB1)
#              QRSPPS_vqe_results.pkl    (NB2)
#              QRSPPS_policy_results.pkl (NB3)
#              QRSPPS_dosqpe_results.pkl (NB4)
# Produces:    QRSPPS_scaling_results.pkl
#              QRSPPS_qubit_scaling_full.png
#              QRSPPS_qubit_scaling.png
#
# Runtime: ~15-20 min
# ============================================================
#SBATCH --job-name=qrspps_nb5_final
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=12
#SBATCH --partition=Interactive
#SBATCH --time=48:00:00
#SBATCH --output=log_nb5_final.txt

source ~/QARPdemo/setup_env.sh

export QARP_DISABLE_MPI=1
export OMP_NUM_THREADS=48

echo "================================================================"
echo " QR-SPPS NB-5B: Scaling Fit + Pipeline Summary"
echo "================================================================"
echo " Start : $(date)"
echo " Node  : $(hostname)"
echo " Job   : $SLURM_JOB_ID"
echo " Dir   : $(pwd)"
echo ""
echo " Expected: R2=0.9948 | rate=1.1993/q | t(40q)=1308.2h | 17.6TB"
echo "================================================================"

# Dependency check (NB5_Scaling reads mpi_scaling.pkl from ~/QARPdemo/
# and all others as relative paths from cwd)
MISSING=0

MPI_PKL="$HOME/QARPdemo/QRSPPS_mpi_scaling.pkl"
if [ -f "$MPI_PKL" ]; then
    echo "Found : QRSPPS_mpi_scaling.pkl  ($(du -h $MPI_PKL | cut -f1))"
else
    echo "MISSING: $MPI_PKL"
    echo "Run 'sbatch run_nb5_30q.sh' first and wait for it to complete."
    MISSING=$((MISSING+1))
fi

for PKL in QRSPPS_hamiltonians.pkl QRSPPS_vqe_results.pkl \
           QRSPPS_policy_results.pkl QRSPPS_dosqpe_results.pkl; do
    if [ -f "$PKL" ]; then
        echo "Found : $PKL  ($(du -h $PKL | cut -f1))"
    else
        echo "MISSING: $PKL in $(pwd)"
        MISSING=$((MISSING+1))
    fi
done

if [ $MISSING -gt 0 ]; then
    echo ""
    echo "ERROR: $MISSING required file(s) missing. Pipeline order:"
    echo "  NB1: Run QRSPPS_NB1_Hamiltonian_40q.ipynb in Jupyter"
    echo "  NB2: cd ~/QARPdemo && sbatch run_nb2_vqe.sh"
    echo "  NB3+4: cd ~/QARPdemo && sbatch run_nb3_nb4.sh"
    echo "  NB5A: cd ~/QARPdemo && sbatch run_nb5_30q.sh"
    echo "  NB5B: cd ~/QARPdemo && sbatch run_nb5_final.sh  (this script)"
    exit 1
fi
echo ""

echo "=== Starting QRSPPS_NB5_Scaling.py ==="

python3 QRSPPS_NB5_Scaling.py

EXIT=$?
echo ""
echo "=== NB5 scaling exit: $EXIT  ($(date)) ==="

if [ ! -f "QRSPPS_scaling_results.pkl" ]; then
    echo "ERROR: QRSPPS_scaling_results.pkl not created. Check log_nb5_final.txt."
    exit 1
fi
echo "Output: QRSPPS_scaling_results.pkl  ($(du -h QRSPPS_scaling_results.pkl | cut -f1))  OK"

# Verify the three key numbers
python3 - << 'PYEOF'
import pickle, sys
try:
    with open('QRSPPS_scaling_results.pkl', 'rb') as f:
        s = pickle.load(f)
    print("")
    print("  Scaling law verification (vs .pkl):")
    print(f"    R2            = {s['r_squared']:.4f}   (expected 0.9948)")
    print(f"    Doubling rate = {s['doubling_rate']:.4f} (expected 1.1993)")
    print(f"    t(40q)        = {s['t_40q_predicted']:.0f}s = {s['t_40q_predicted']/3600:.1f}h  (expected 1308.2h)")
    print(f"    Policy E-red  = {s['policy_energy_reduction_pct']:.2f}%  (expected 16.67%)")
except Exception as e:
    print(f"  Verify failed: {e}", file=sys.stderr)
PYEOF

echo ""
echo "================================================================"
echo " FULL QR-SPPS PIPELINE COMPLETE"
echo " End: $(date)"
echo "================================================================"
echo ""
echo "All .pkl files for judge cross-verification:"
for PKL in QRSPPS_hamiltonians.pkl QRSPPS_vqe_results.pkl \
           QRSPPS_policy_results.pkl QRSPPS_dosqpe_results.pkl \
           QRSPPS_scaling_results.pkl; do
    if [ -f "$PKL" ]; then
        echo "  OK  $PKL  ($(du -h $PKL | cut -f1))"
    else
        echo "  --  $PKL  MISSING"
    fi
done
echo ""
echo "Run dashboard:"
echo "  cd ~/QARPdemo && streamlit run dashboard.py"
exit $EXIT
