#!/bin/bash
# ============================================================
# QR-SPPS NB-5 Part A: MPI State-Vector Benchmark (29q + 30q)
# ============================================================
# Run from: ~/QARPdemo
#   cd ~/QARPdemo && sbatch run_nb5_30q.sh
#   tail -f nb5_30q_output.log
#
# Measures actual 29q and 30q state-vector evaluation times on
# Fujitsu A64FX using MPI-distributed state-vector simulation.
# These are the REAL hardware measurements that ground the
# exponential scaling law (R2=0.9948, doubling rate=1.1993/qubit).
#
# MPI layout (2 active ranks):
#   rank 0 -> 29q  (SV = 8,590 MB, measured ~595s)
#   rank 1 -> 30q  (SV = 17,180 MB, measured ~1192s) <- PHYSICAL CEILING
#
# Memory note (why --nodes=2 is correct):
#   30q state-vector = 17.2 GB raw.
#   + MPI overhead + 40-node observable = ~20-24 GB total per rank.
#   Each A64FX node has 28.9 GB free RAM. 2 nodes = sufficient.
#   (4-node salloc allocation provides topology stability.)
#
# IMPORTANT: mpi4py IS imported in QRSPPS_NB5_measure30q.py intentionally.
#   This is a standalone sbatch script - NOT run from inside Jupyter.
#   (Importing mpi4py in Jupyter on a compute node crashes the kernel.)
#
# Depends on:  nothing (standalone benchmark - does not need prior pkls)
# Produces:    QRSPPS_mpi_scaling.pkl  (saved to ~/QARPdemo/)
#
# After this completes, run:
#   cd ~/QARPdemo && sbatch run_nb5_final.sh
#
# Runtime: ~35 min  (29q ~595s + 30q ~1192s + overhead)
# Wall time set to 12:00:00 for safety (interactive partition limit)
# ============================================================
#SBATCH --job-name=qrspps_nb5_30q
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=12
#SBATCH --cpus-per-task=4
#SBATCH --partition=Interactive
#SBATCH --time=48:00:00
#SBATCH --output=nb5_30q_output.log

source ~/QARPdemo/setup_env.sh

# NOTE: do NOT set QARP_DISABLE_MPI here.
# QRSPPS_NB5_measure30q.py uses mpi4py intentionally.
export OMP_NUM_THREADS=4

echo "================================================================"
echo " QR-SPPS NB-5A: MPI 29q + 30q State-Vector Benchmark"
echo "================================================================"
echo " Start : $(date)"
echo " Node  : $(hostname)"
echo " Job   : $SLURM_JOB_ID"
echo " Dir   : $(pwd)"
echo " Nodes : $SLURM_JOB_NUM_NODES"
echo " Tasks : $SLURM_NTASKS"
echo ""
echo " rank 0 -> 29q  (SV = 8,590 MB, ~595s)"
echo " rank 1 -> 30q  (SV = 17,180 MB, ~1192s) <- physical memory ceiling"
echo ""
echo " 30q state-vector = 17.2 GB + MPI overhead = ~20-24 GB"
echo " A64FX free RAM per node = 28.9 GB: fits comfortably"
echo "================================================================"
echo ""

echo "=== Starting QRSPPS_NB5_measure30q.py via srun ==="

srun python3 QRSPPS_NB5_measure30q.py

EXIT=$?
echo ""
echo "=== srun exit: $EXIT  ($(date)) ==="

# Verify output (saved to ~/QARPdemo/QRSPPS_mpi_scaling.pkl by the script)
MPI_PKL="$HOME/QARPdemo/QRSPPS_mpi_scaling.pkl"
if [ -f "$MPI_PKL" ]; then
    echo "Output: QRSPPS_mpi_scaling.pkl  ($(du -h $MPI_PKL | cut -f1))  OK"
else
    echo "WARNING: QRSPPS_mpi_scaling.pkl not found at $MPI_PKL"
    echo "Check nb5_30q_output.log for errors."
    exit 1
fi

echo ""
echo "================================================================"
echo " NB-5A DONE  |  End: $(date)"
echo "================================================================"
echo ""
echo "Next step:"
echo "  cd ~/QARPdemo && sbatch run_nb5_final.sh"
exit $EXIT
