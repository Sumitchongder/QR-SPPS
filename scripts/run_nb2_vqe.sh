#!/bin/bash
# ============================================================
# QR-SPPS NB-2: VQE Ground State — 30-Qubit Execution
# ============================================================
# Run from: ~/QARPdemo
#   cd ~/QARPdemo && sbatch run_nb2_vqe.sh
#
# All .pkl files are read/written relative to the working directory.
# Architecture: 40q encoded (NB1) -> 30q VQE executed (this script)
#   Tier 0+1+2 fully retained + top-10 retail by coupling strength.
#   E0[30q raw] = -33.5198  ->  E0[40q scaled] = -44.6931 (zero error)
#   Ansatz: RY+CNOT, depth=3, 120 params, 5 restarts, COBYLA maxiter=2000
#
# Execution: single-node, NO MPI.
#   QARP_DISABLE_MPI=1 prevents QulacsEngine wrapper segfault on ARM A64FX.
#   Script uses qulacs Observable API directly, not QulacsEngine.
#
# Depends on: QRSPPS_hamiltonians.pkl  (NB1 Jupyter notebook)
# Produces:   QRSPPS_vqe_results.pkl
#             QRSPPS_vqe_convergence.png
#             QRSPPS_quantum_vs_classical.png
#             QRSPPS_vqe_depth_scaling.png
#
# Runtime: ~60-90 min
#   5 restarts x 2 scenarios x ~8 min (30q, depth=3)
#   + depth study ~15 min (depths 1-5, 1 restart each)
# ============================================================
#SBATCH --job-name=qrspps_nb2_vqe
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=12
#SBATCH --cpus-per-task=48
#SBATCH --partition=Interactive
#SBATCH --time=48:00:00
#SBATCH --output=log_nb2_vqe.txt

source ~/QARPdemo/setup_env.sh

# Disable QulacsEngine MPI wrapper - segfaults on ARM A64FX.
# NB2 uses qulacs Observable API directly (not QulacsEngine).
export QARP_DISABLE_MPI=1
export OMP_NUM_THREADS=48

echo "================================================================"
echo " QR-SPPS NB-2: VQE Ground State (30q Execution)"
echo "================================================================"
echo " Start : $(date)"
echo " Node  : $(hostname)"
echo " Job   : $SLURM_JOB_ID"
echo " Dir   : $(pwd)"
echo ""
echo " 40q encoded  | 30q executed"
echo " E0[30q] target: -33.5198"
echo " E0[40q] target: -44.6931 = -33.5198 x (40/30)"
echo "================================================================"

# Dependency check
if [ ! -f "QRSPPS_hamiltonians.pkl" ]; then
    echo "ERROR: QRSPPS_hamiltonians.pkl not found in $(pwd)"
    echo "Run NB1 Jupyter notebook first, then cd ~/QARPdemo before sbatch."
    exit 1
fi

echo "Input : QRSPPS_hamiltonians.pkl  ($(du -h QRSPPS_hamiltonians.pkl | cut -f1))"
echo ""
echo "=== Starting QRSPPS_NB2_VQE_30q.py ==="

python3 QRSPPS_NB2_VQE_30q.py

EXIT=$?
echo ""
echo "=== NB2 finished --- exit: $EXIT  ($(date)) ==="

if [ -f "QRSPPS_vqe_results.pkl" ]; then
    echo "Output: QRSPPS_vqe_results.pkl  ($(du -h QRSPPS_vqe_results.pkl | cut -f1))  OK"
else
    echo "ERROR: QRSPPS_vqe_results.pkl not created. Check log_nb2_vqe.txt."
    exit 1
fi

echo ""
echo "Next step:"
echo "  cd ~/QARPdemo && sbatch run_nb3_nb4.sh"
exit $EXIT
