# tmux-quota

Account-budget bars for tmux, powered by [ccswap](https://github.com/errhythm/ccswap).
Bars show **quota consumed**; colors show consumption relative to elapsed time.
Runs on Linux and macOS with command-line tools only.

```text
Claude work* 5h [━━────] 25% W [━━━━──] 60% / home W [━━────] 35% │ Codex* W [━─────] 20%
```

The example is fictional. There are no built-in work/personal account mappings,
slot numbers, email addresses, or plan-specific rules. Configure as many accounts
as you need in ccswap. Only the 5-hour and weekly windows it actually reports are
shown; a missing 5-hour window never becomes an invented 0% bar.

- `*` after an account label marks the active login **within that provider**.
- `~` means the account has last-known, stale, or unavailable measurements.
- `?` inside a bar means that particular measurement is unknown or expired.
- `unavailable` means an account/provider has no quota windows to display.
- A single account without a custom label is abbreviated, for example `Codex*`.

This is an initial alpha targeting ccswap **0.47.0**. Tests use synthetic fixtures
and a fake CLI. Local checks exercised live error responses on macOS; successful
authenticated end-to-end fetching and the Linux CI matrix still need validation.
Windows is not supported (the cache uses POSIX file locks).

## Install

Requires Python 3.11+, tmux, and the ccswap CLI. ccswap itself requires Python
3.12+. No desktop app, CodexBar, jq, or background service is needed.

From a checkout, using [uv](https://docs.astral.sh/uv/):

```sh
uv tool install --python 3.13 ccswap==0.47.0
uv tool install --python 3.13 .
tmux-quota --version
```

Alternatively, install ccswap separately and run `pipx install .` with a compatible
Python interpreter. tmux-quota is not yet published to PyPI. ccswap is an external
executable, not a Python library dependency; it is not installed or upgraded by
installing tmux-quota.

Follow ccswap's [account setup](https://github.com/errhythm/ccswap#quick-start).
With accounts already registered, verify its two usage commands in your terminal:

```sh
ccswap list --provider claude --json
ccswap codex usage --json
tmux-quota --format plain
```

For a single provider, use `tmux-quota --provider claude` or `--provider codex`.
This tool never runs login, add, switch, auto, or reset commands. ccswap owns
credentials and can refresh them during usage collection according to its own
behavior. Migrating from another account manager is a separate task; consult
ccswap's documentation before letting two managers operate on the same store.

To upgrade a local installation after pulling changes, run:

```sh
uv tool install --force --python 3.13 .
```

## Add to tmux

Find both executable paths:

```sh
command -v tmux-quota
command -v ccswap
```

This minimal, reloadable configuration assumes both are in `~/.local/bin`;
substitute the actual paths from the commands above:

```tmux
set -g status-interval 5
set -g status-right-length 240
set -g status-right '#(~/.local/bin/tmux-quota --ccswap ~/.local/bin/ccswap --quiet)'
```

To keep existing widgets, insert the `#(...)` segment into your existing
`status-right` value with a separator. The explicit ccswap path handles tmux
servers whose PATH differs from the interactive shell. The configuration can be
reloaded without appending duplicate segments:

```sh
tmux source-file ~/.tmux.conf
```

See [examples/tmux.conf](examples/tmux.conf) for theme and sizing options. A font
with Unicode box-drawing characters renders the default thin bars. `--ascii`
uses `[==----]` bars and `|` separators instead.

## Terminal colors

The default `--theme terminal` uses the terminal's ANSI palette for pace: green
(slot 2), blue (4), yellow (3), and red (1). Labels, unknown readings, brackets,
and tracks inherit tmux's configured status style. No background or hex colors
are forced, and no light/dark background detection is attempted.

ANSI color appearance and contrast depend on your terminal palette. Override any
role to suit your status line; colors can be `default`, `colour0` through
`colour255`, or a quoted `#RRGGBB` value:

```sh
tmux-quota --color blue=colour6 --color track=colour8
tmux-quota --color 'green=#22aa55' --color text=default
```

Roles are `green`, `blue`, `amber`, `red`, `unknown`, `track`, and `text`.
Overrides apply after the selected palette. `default` restores the tmux status
style. The old `--theme dark` and `--theme light` Tokyo Night palettes remain
explicit opt-in presets. Plain and JSON output do not use color palettes.

## Pace colors

| Color | Consumed percentage / elapsed percentage | Halfway through a period |
| --- | --- | --- |
| Green | ≤0.8× | ≤40% consumed |
| Blue | >0.8× to 1.1× | >40–55% consumed |
| Amber | >1.1× to 1.4× | >55–70% consumed |
| Red | >1.4×, or 100% consumed | >70% consumed |
| Neutral | Missing reset time, untrusted reading, or stale data | No pace judgment |

Each bar is evaluated independently. The filled portion always represents
consumed quota; it does not represent pace. Colors are applied to the fill and
percentage. The empty track and brackets use the configured track style. Unknown pace still shows a
readable percentage when its measurement is recent enough to display.

Elapsed time is inferred from the reset timestamp and a fixed 5-hour or 7-day
period. The first **2% of a period** is treated as 2% elapsed to reduce noisy
colors just after a reset: 6 minutes for a 5-hour window, about 3 hours 22 minutes
for a weekly window. Those durations are a source-format assumption; other window
durations are not supported by this release.

Past resets, missing measurement ages, readings over `--max-age`, and measurements
more than 60 seconds in the future are unavailable. A reset more than one full
period ahead (plus 60 seconds of clock tolerance) gives neutral pace. Last-known
readings with a trustworthy age may retain a percentage but always stay neutral.
Codex error responses without a measurement age are unknown unless a previous
local measurement can be retained.

Pace assumes future usage resembles the average so far. It is a planning signal,
not a forecast guarantee, and does not distinguish work hours from idle time.
Per-model quotas, credit balances, and money spent are outside this release.

## Options

| Option | Default | Purpose |
| --- | --- | --- |
| `--provider all/claude/codex` | `all` | Providers to fetch or render |
| `--format tmux/plain/json` | `tmux` | Styled tmux text, plain text, or normalized JSON |
| `--theme terminal/dark/light` | `terminal` | Inherit terminal colors, or opt into a Tokyo Night preset |
| `--color ROLE=COLOR` | none | Override a foreground role; repeat for multiple roles |
| `--width 1..32` | `6` | Cells inside each bar |
| `--ascii` | off | ASCII bars and separators |
| `--active-only` | off | Show only the active account per provider |
| `--label PROVIDER:SLOT=NAME` | none | Override a label; repeat for multiple accounts |
| `--ccswap PATH` | `ccswap` | Executable path, not a shell command |
| `--timeout SECONDS` | `20` | Maximum runtime per provider command |
| `--cache-ttl SECONDS` | `60` | Minimum interval between fetch attempts |
| `--max-age SECONDS` | `600` | Maximum measurement age for displayed percentages |
| `--cache-dir PATH` | see below | Cache directory |
| `--no-cache` | off | Fetch each invocation without reading/writing cache |
| `--stdin` | off | Read source JSON without fetching or caching |
| `--quiet` | off | Suppress diagnostics on stderr |
| `--version` | | Show version |
| `--help` | | Show CLI help |

Example label overrides (replace slots with your actual ccswap numbers):

```sh
tmux-quota --label claude:7=work --label claude:12=home --label codex:4=lab
```

Labels default to ccswap aliases or slot numbers. They are truncated to 24
characters and sanitized in text output; no email field is used as a label.
JSON output preserves the full label, along with normalized window timestamps,
availability, pace, and diagnostics. Do not put private information in aliases
if you intend to share the output or cache.

## JSON input

Render provider JSON directly, without fetching or touching the cache:

```sh
ccswap list --provider claude --json | tmux-quota --stdin --provider claude
ccswap codex usage --json | tmux-quota --stdin --provider codex
```

A combined object keyed by `claude` and `codex` is also accepted; see the
[synthetic fixture](tests/fixtures/combined.json). Input without a provider field
is treated as Claude's list schema. `--provider` also selects which parts of
combined input to render.

**ccswap's combined `list --json` provides Codex metadata without quota values.**
To render Codex bars, use the `codex usage --json` payload. ccswap uses camelCase
window keys for Claude and snake_case keys for Codex; the adapter handles both
provider-specific formats. Other top-level providers are ignored. Unknown extra
fields are ignored; unsupported explicit schema versions are rejected.

`--stdin` expects ccswap source JSON, not tmux-quota's normalized `--format json`
output. Codex's usage command lacks measurement timestamps, so error-free piped
Codex readings are assumed to have been collected now. Avoid replaying old Codex
JSON as though it were live. Claude's supplied measurement ages remain respected.

## Caching and failures

The live adapter invokes these independently, in parallel:

```sh
ccswap list --provider claude --json
ccswap codex usage --json
```

Normalized measurements live in `$XDG_CACHE_HOME/tmux-quota`, defaulting to
`~/.cache/tmux-quota`. Data and lock files have mode 0600; newly created cache
directories have mode 0700. Atomic writes and per-provider locks prevent partial
files and overlapping fetches. Executable paths, account-home overrides, and
`XDG_DATA_HOME` scope caches independently. No daemon is required.

The cache contains labels, slot numbers, active flags, timestamps, quota values,
an opaque account-ownership hash, and generic diagnostics. Raw provider responses,
email fields, and credentials are not stored. The hash is derived from account
identity for cache matching; it is not an anonymization guarantee and is omitted
from public JSON output. User-chosen aliases may still contain private information.

Failures back off for the cache TTL. A failed command or an individual account's
missing quota response preserves the same account's previous measurements without
resetting their original age. Retained readings are neutral; they become `?`
after `--max-age`. Ownership must match before per-account fallback is used, so
reusing a slot does not transfer another login's measurements. Deleted accounts
are removed when the source returns a new account list. One failing provider
does not hide the other.

An account/provider without windows displays `unavailable`; an empty account list
does too. With `--active-only`, a provider with registered accounts but no active
login displays `no active account`. Account changes can take up to the cache TTL
to appear. Unwritable cache directories produce diagnostics; use another
`--cache-dir` or fix permissions. `--no-cache` is for debugging, not frequent tmux
polling. The normalized JSON format is schema version 1 and may gain fields.

Diagnostics go to stderr. Exit status is 0 when accounts were returned (including
partial/account-level usage failures), or sources successfully returned empty
account lists; 1 when
source/input errors leave no accounts; and 2 for invalid arguments. Do not use
exit status alone to judge freshness: inspect JSON `available`, `pace`, and
`errors`. `--quiet` only suppresses stderr; JSON diagnostics remain present.

## Troubleshooting

- **Command not found in tmux:** use explicit executable paths for both tools.
- **Neutral bars or `~`:** inspect the underlying ccswap commands above. Check
  credential access, network/DNS, clock accuracy, and measurement age. Neutral is
  intentional when pace cannot be trusted.
- **Codex unavailable:** confirm `ccswap codex usage --json` reports quota windows.
  A Codex account list alone is insufficient. API-key logins do not supply the
  subscription windows this tool renders.
- **Fetch failure:** test `tmux-quota --no-cache --format json` in your own terminal.
  Sandboxed shells can have different network and credential access. To avoid
  replacing a normal terminal's cache during experiments, pass a separate
  `--cache-dir`.
- **Crowded status line:** use `--active-only`, `--provider`, or a smaller `--width`.
- **Font rendering:** use `--ascii` if box-drawing characters render poorly.

## Development

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Use a Python 3.11+ interpreter. The package has no runtime Python dependencies;
packaging uses setuptools. Tests need no live accounts, credentials, or network.
See [CONTRIBUTING.md](CONTRIBUTING.md) for packaging and contribution instructions.

## License

[MIT](LICENSE). This independent project integrates through ccswap's public CLI
and is not affiliated with ccswap, Anthropic, or OpenAI.
