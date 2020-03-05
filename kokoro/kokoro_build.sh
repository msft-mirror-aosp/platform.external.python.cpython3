#!/bin/bash

# Fail on any error.
set -e

DEST="${KOKORO_ARTIFACTS_DIR}/dest"
OUT="${KOKORO_ARTIFACTS_DIR}/out"
PYTHON_SRC=${KOKORO_ARTIFACTS_DIR}/git/cpython3

BASEDIR=$(dirname "$0")

python3 --version
python3 ${BASEDIR}/build.py "${PYTHON_SRC}" "${OUT}" "${DEST}" "${KOKORO_BUILD_ID}"
