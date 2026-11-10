# Contributing

Use Python 3.11+ on Linux or macOS. No live accounts are needed to develop or test.

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m pip install -e .
tmux-quota --help
```

With uv:

```sh
uv run --python 3.13 python -m unittest discover -s tests -v
uv build
```

Keep provider JSON parsing in `source.py`, pace calculations in `model.py`, and
presentation in `render.py`. The ccswap integration must use public CLI commands,
not private Python APIs or account credential files. New schema handling needs a
synthetic fixture and a test. Never commit real emails, tokens, account exports,
or usage caches.

The cache stores normalized display measurements, not raw provider responses.
Tests should exercise failures, time boundaries, and public CLI behavior without
contacting providers or changing logins. CI targets Linux and macOS; it has not
run until the repository is pushed to GitHub.
