#!/bin/zsh
set -e
cd "${0:A:h}"
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python app.py --open
else
  exec /usr/bin/env python3 app.py --open
fi
