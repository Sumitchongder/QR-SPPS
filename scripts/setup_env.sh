#!/bin/bash
# ============================================================
# QR-SPPS Environment Setup Script
# Fujitsu Quantum Simulator Challenge 2025-26, Group A (g140-user1)
# MUST be run on a compute node (after salloc), NOT on loginvm
# Usage: source ~/QARPdemo/setup_env.sh
# ============================================================

# --- Guard: refuse to run on the login node ---
HOSTNAME=$(hostname)
if [[ "$HOSTNAME" == loginvm* ]]; then
    echo "ERROR: This script must run on a compute node (fx-*), not on $HOSTNAME."
    echo "Run: salloc -N 4 -p Interactive --time=48:00:00"
    echo "Then: source ~/QARPdemo/setup_env.sh"
    return 1 2>/dev/null || exit 1
fi

# --- Python virtual environment ---
source ~/QARPdemo/venv/bin/activate

# --- Boost library path (required for QARP) ---
export LD_LIBRARY_PATH=/home/share/developer/boost-1.90.0/lib:/usr/local/lib
export BOOST_ROOT=/home/share/developer/boost-1.90.0

# --- OpenMP: single-threaded per MPI rank (prevents floating-point errors) ---
export OMP_NUM_THREADS=1

# --- Qulacs thread count: use all 48 A64FX cores per node ---
export QULACS_NUM_THREADS=48

# --- glibc bug workaround (Fujitsu QSim v1.6.2 docs, Troubleshooting 10.2.2) ---
if [ -z "${LD_PRELOAD}" ]; then
    export LD_PRELOAD=/lib64/libgomp.so.1
else
    export LD_PRELOAD=/lib64/libgomp.so.1:$LD_PRELOAD
fi

# --- Confirmation ---
QARP_VER=$(python3 -c 'import qarp; print(qarp.__version__)' 2>/dev/null || echo 'not found')
echo "================================================"
echo " QR-SPPS environment ready"
echo " QARP version : $QARP_VER"
echo " Python       : $(python3 --version 2>&1)"
echo " Node         : $HOSTNAME"
echo " OMP threads  : $OMP_NUM_THREADS"
echo " Qulacs threads: $QULACS_NUM_THREADS"
echo "================================================"
