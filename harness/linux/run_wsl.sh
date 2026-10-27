#!/usr/bin/env bash
# run_netem.sh without Docker: in a WSL2 distro, as root for tc (wsl -d <distro> -u root -- bash run_wsl.sh).
# Peers must be Linux builds: PQQUIC_RS_BIN / PQQUIC_GO_BIN. Pass PQQUIC_DISABLE_GSO=1 and
# QUIC_GO_DISABLE_GSO=true: with GSO on, netem on lo keeps or drops a GSO batch as one unit (see
# notes/prediction-netem.md). Other env as for run_netem.sh (STACKS, LOSSES, PAIRS, SEED, TAG).
set -u
cd "$(dirname "$0")/.."
: "${PQQUIC_RS_BIN:?Linux rust-pair build}" "${PQQUIC_GO_BIN:?Linux gopair build}"
export OUT=${OUT:-$(pwd)/../data/bench}
bash linux/run_netem.sh
