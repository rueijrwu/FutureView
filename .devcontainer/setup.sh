#!/usr/bin/env bash
set -euo pipefail

python --version
python -m pip install --upgrade pip
python -m pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.4"
python -m pip install "numpy>=1.26" "pandas>=2.2" "yfinance>=0.2.54"
python -m pip install -e . --no-deps

python - <<'PY'
import torch
print(f"torch={torch.__version__}")
print(f"device={'cuda' if torch.cuda.is_available() else 'cpu'}")
PY
