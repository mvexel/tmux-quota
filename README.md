# tmux-quota

Small account-budget bars for tmux, powered by [ccswap](https://github.com/errhythm/ccswap).
Shows how much quota you have **consumed** and colors each bar by your pace through
its usage period. Command-line tools only, on Linux and macOS.

```text
Claude *team 5h █░░░░░ 11% W ███░░░ 54% / personal W ███░░░ 47% │ Codex *1 W █░░░░░ 17%
```

`*` marks the active account **within each provider**. `~` marks last-known,
stale, or unavailable usage. Unknown measurements show `?`, never an invented 0%.
Account labels default to ccswap aliases or slot numbers; emails are never used.

This is an initial alpha. The adapters are based on ccswap 0.47's documented
commands and source, and tested with synthetic fixtures and a fake CLI. They
have not yet been exercised against a live ccswap account store.

## Install

Requires Python 3.11+, tmux, and the `ccswap` CLI (which requires Python 3.12+).
No CodexBar, desktop app, jq, or background service is needed.

From this checkout:

```sh
uv tool install ccswap==0.47.0
uv tool install .
tmux-quota --format plain
```

Alternatively use `pipx install .` after installing ccswap separately. The project
is not yet published to PyPI. ccswap is an external executable, not a Python
library dependency; upgrading it is an explicit choice.

Use ccswap's [setup documentation](https://github.com/errhythm/ccswap#quick-start)
to register accounts. tmux-quota never runs login, add, switch, auto, or reset
commands. ccswap remains responsible for credentials and may refresh them while
collecting usage, according to its own behavior.

## Add to tmux

Check `command -v tmux-quota` and use that absolute path if it differs:

```tmux
set -g status-interval 5
set -g status-right-length 240
set -ag status-right ' │ #(~/.local/bin/tmux-quota --quiet)'
```

Append the segment once to your existing status line. Repeatedly sourcing
`set -ag` appends duplicate segments; for a reloadable config, include the command
inside your existing `set -g status-right '...'` instead. See
[examples/tmux.conf](examples/tmux.conf) for account labels and sizing.

## Pace colors

| Color | Consumption / elapsed portion of period | At halfway through a period |
| --- | --- | --- |
| Green | ≤ 0.8× | ≤40% consumed |
| Blue | >0.8× to 1.1× | >40–55% consumed |
| Amber | >1.1× to 1.4× | >55–70% consumed |
| Red | >1.4×, or 100% consumed | >70% consumed |
| Neutral | Missing reset time, untrusted reading, or stale data | No pace judgment |

Each bar is independent. A personal account with only a weekly window gets no
5-hour bar. Codex's `weekly` window is also handled independently of a 5-hour
window. Per-model quotas and credit balances are outside this initial release.

Elapsed time is inferred from the reset timestamp and the window duration
(5 hours or 7 days), with a **2%-of-period grace floor** immediately after a
reset. That floor is 6 minutes for 5-hour windows and about 3 hours 22 minutes
for weekly windows. A reading whose reset has passed becomes unknown until
ccswap supplies a new one. Last-known readings may retain a percentage while
remaining neutral; after ten minutes they become `?`.

Pace assumes future usage resembles the average so far. It is a planning signal,
not a forecast guarantee, and it does not distinguish work hours from idle time.

## Options

```sh
tmux-quota --theme light
tmux-quota --active-only --width 4
tmux-quota --label claude:1=team --label claude:2=personal --label codex:1=work
tmux-quota --provider codex --format plain --ascii
tmux-quota --format json
tmux-quota --ccswap /absolute/path/to/ccswap
```

Labels are shortened to 24 characters and sanitized for tmux. Provider selection
is `all` (default), `claude`, or `codex`. Plain output contains no colors or tmux
format strings; JSON output includes normalized windows, availability, and pace.

Use `--stdin` to render without running ccswap or touching the cache:

```sh
ccswap list --provider claude --json | tmux-quota --stdin --provider claude
ccswap codex usage --json | tmux-quota --stdin --provider codex
```

A combined object keyed by `claude` and `codex` is also accepted. **ccswap's
ordinary combined `list --json` includes Codex metadata without usage.** To render
Codex bars, supply the `codex usage --json` payload, not just its account list.
See [the synthetic combined fixture](tests/fixtures/combined.json) for the shape.
Input without a provider field is treated as Claude's list schema.

## Fetching and failures

The live adapter invokes these two commands independently and in parallel:

```sh
ccswap list --provider claude --json
ccswap codex usage --json
```

Normalized measurements are cached in `$XDG_CACHE_HOME/tmux-quota` (default
`~/.cache/tmux-quota`). Files have mode 0600, new cache directories 0700, and writes
are atomic. Separate provider locks prevent overlapping tmux redraws from
launching duplicate fetches. Account-home overrides and different executables
get independent cache files. The cache contains labels, slot numbers, active
flags, timestamps and quota values; no raw responses, emails, or credentials
(unless you explicitly put sensitive text in an alias).

Defaults: `--cache-ttl 60`, `--timeout 20` per provider, `--max-age 600`.
Failed refreshes back off for the cache TTL and keep existing measurements
without resetting their original observation time. A failed provider does not
hide the other. With no data, a provider displays `?`. An empty account list also
displays `?`; register accounts in ccswap first. Account changes can take up to
the cache TTL to appear. If the cache directory is unwritable, the provider
reports an error; fix permissions or select another `--cache-dir`.

Diagnostics go to stderr; `--quiet` suppresses them for tmux. Exit status is 0
when data is available (including partial provider failures), 1 on total source
failure, and 2 for invalid CLI arguments. `--no-cache` is useful for debugging,
but avoid it in a frequently refreshed status line.

## Development

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The package uses only Python's standard library at runtime. Tests need no live
accounts or network. Packaging uses setuptools. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. This independent project integrates with ccswap through its public CLI.
It is not affiliated with ccswap, Anthropic, or OpenAI.
