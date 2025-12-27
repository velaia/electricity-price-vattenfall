#!/bin/zsh
cd /Users/daniel/git/energiepreis-vattenfall-api
source /Users/daniel/git/energiepreis-vattenfall-api/.venv/bin/activate
/opt/homebrew/bin/uv run /Users/daniel/git/energiepreis-vattenfall-api/main.py
open -gj /Users/daniel/git/energiepreis-vattenfall-api/dual_timeline_plot.png