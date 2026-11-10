"""Bounded CLI calls, private atomic caches, and a lock per provider."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from .model import Account, Window, number
from .source import COMMANDS, SourceError, parse, validate


@dataclass
class Result:
    accounts: list[Account]
    error: str | None = None


def fetch(provider: str, executable: str, timeout: float) -> list[Account]:
    started = time.time()
    try:
        process = subprocess.run(
            [executable, *COMMANDS[provider]], capture_output=True,
            text=True, encoding="utf-8", timeout=timeout,
        )
    except FileNotFoundError:
        raise SourceError("ccswap not found; install it or pass --ccswap /path/to/ccswap") from None
    except subprocess.TimeoutExpired:
        raise SourceError(f"ccswap timed out after {timeout:g}s") from None
    except (OSError, UnicodeError):
        raise SourceError("Could not execute ccswap") from None
    if process.returncode:
        # Do not leak account identities, credentials, or arbitrary provider output.
        raise SourceError(f"ccswap exited with status {process.returncode}")
    try:
        data = json.loads(process.stdout)
    except ValueError:
        raise SourceError("ccswap returned invalid JSON") from None
    # Age Codex results from request start, rather than pretending slow requests
    # completed with a brand new measurement. Claude has its own measurement age.
    return parse(validate(data), provider, started)


def read_cache(path: Path, provider: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != 1 or number(data.get("checked_at")) is None:
            return {}
        accounts = []
        for row in data["accounts"]:
            if row["provider"] != provider or not isinstance(row["label"], str):
                return {}
            windows = []
            for w in row["windows"]:
                if w["label"] not in ("5h", "W") or number(w["duration"]) is None:
                    return {}
                for key in ("consumed", "resets_at", "observed_at"):
                    if w[key] is not None and number(w[key]) is None:
                        return {}
                if w["consumed"] is not None and not 0 <= w["consumed"] <= 100:
                    return {}
                windows.append(Window(**w))
            accounts.append(Account(provider, str(row["number"]), row["label"],
                                    row["active"] is True, tuple(windows), row.get("identity")))
        data["parsed"] = accounts
        return data
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {}


def write_cache(path: Path, data: dict) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".quota-", delete=False) as handle:
            temporary = Path(handle.name)
            # NamedTemporaryFile starts at 0600 on POSIX, even with a loose umask.
            json.dump(data, handle, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def usage_error(accounts: list[Account]) -> str | None:
    slots = [a.number for a in accounts if not a.windows or any(w.last_known for w in a.windows)]
    return "usage unavailable for account " + ", ".join(slots) if slots else None


def retain_usage(accounts: list[Account], previous: list[Account]) -> list[Account]:
    """A successful CLI exit can still contain per-account quota failures."""
    old = {a.number: a for a in previous}
    result = []
    for account in accounts:
        missing = not account.windows or all(w.observed_at is None for w in account.windows)
        previous = old.get(account.number)
        if (missing and previous is not None and previous.windows and
                account.identity is not None and account.identity == previous.identity):
            windows = tuple(replace(w, last_known=True) for w in previous.windows)
            # Use the new active-account flag; only retain the measurements.
            account = replace(account, windows=windows)
        result.append(account)
    return result


def cached_fetch(provider: str, executable: str, timeout: float, cache_dir: Path,
                 ttl: float) -> Result:
    # Keep distinct ccswap installations and account-home overrides independent.
    scope = {k: v for k, v in os.environ.items()
             if k in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "XDG_DATA_HOME") or
             k.startswith(("CCSWAP_", "CSWAP_"))}
    scope["executable"] = shutil.which(executable) or executable
    key = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()[:16]
    path = cache_dir / f"{provider}-{key}.json"
    cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (cache_dir / f"{provider}-{key}.lock").open("a") as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            saved = read_cache(path, provider)
            return Result(saved.get("parsed", []), "refresh in progress")
        saved = read_cache(path, provider)
        checked = saved.get("checked_at", 0)
        if saved and 0 <= time.time() - checked < ttl:
            return Result(saved["parsed"], saved.get("error"))
        try:
            accounts = fetch(provider, executable, timeout)
            error = usage_error(accounts)
            accounts = retain_usage(accounts, saved.get("parsed", []))
        except SourceError as exc:
            accounts = [replace(a, windows=tuple(replace(w, last_known=True) for w in a.windows))
                        for a in saved.get("parsed", [])]
            error = str(exc)
        write_cache(path, {"version": 1, "checked_at": time.time(), "error": error,
                           "accounts": [asdict(a) for a in accounts]})
        return Result(accounts, error)


def collect(providers: tuple[str, ...], executable: str, timeout: float,
            cache_dir: Path | None, ttl: float) -> tuple[list[Account], list[str]]:
    def one(provider: str) -> Result:
        try:
            if cache_dir is not None:
                return cached_fetch(provider, executable, timeout, cache_dir, ttl)
            accounts = fetch(provider, executable, timeout)
            return Result(accounts, usage_error(accounts))
        except (SourceError, OSError) as exc:
            return Result([], str(exc))

    # Providers are independent and each has its own timeout and cache lock.
    with ThreadPoolExecutor(max_workers=len(providers)) as pool:
        results = list(pool.map(one, providers))
    accounts, errors = [], []
    for provider, result in zip(providers, results):
        accounts.extend(result.accounts)
        if result.error:
            errors.append(f"{provider}: {result.error}")
    return accounts, errors
