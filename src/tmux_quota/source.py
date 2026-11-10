"""Adapters for ccswap 0.47's public CLI JSON (no private Python imports)."""

import hashlib
import json

from .model import Account, Window, number, timestamp

PROVIDERS = ("claude", "codex")
COMMANDS = {
    "claude": ("list", "--provider", "claude", "--json"),
    "codex": ("codex", "usage", "--json"),
}


class SourceError(ValueError):
    pass


def validate(payload: object) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("accounts"), list):
        raise SourceError("Expected ccswap JSON containing an accounts array")
    if "error" in payload:
        raise SourceError("ccswap reported an error")
    if payload.get("schemaVersion", 1) != 1:
        raise SourceError("Unsupported ccswap schema version")
    if any(not isinstance(row, dict) for row in payload["accounts"]):
        raise SourceError("Invalid ccswap account row")
    return payload


def parse(payload: object, provider: str, collected_at: float) -> list[Account]:
    data = validate(payload)
    accounts = []
    for row in data["accounts"]:
        slot = row.get("number")
        if isinstance(slot, bool) or not isinstance(slot, (int, str)):
            raise SourceError("Missing ccswap account number")
        slot = str(slot)
        # Do not use email as a display label or persist it in our cache.
        alias = row.get("alias")
        label = alias if isinstance(alias, str) and alias else slot
        usage = row.get("usage")
        last_known = False
        if provider == "claude":
            last_known = not isinstance(usage, dict) or row.get("usageStatus", "ok") != "ok"
            if not isinstance(usage, dict):
                usage = row.get("lastGoodUsage")
            prefix = "lastGood" if row.get("usage") is None else "usage"
            # lastGoodFetchedAt vs usageFetchedAt; lastGoodAgeSeconds vs usageAgeSeconds.
            age = number(row.get(prefix + "AgeSeconds"))
            observed = timestamp(row.get(prefix + "FetchedAt"))
            if age is not None:
                from_age = collected_at - max(0, age)
                observed = min(observed, from_age) if observed is not None else from_age
            # Missing measurement age must never make stale data appear fresh.
            windows_spec = (("fiveHour", "5h", 18000), ("sevenDay", "W", 604800))
        else:
            # codex usage makes a fresh request per invocation; on errors it can
            # return last-good usage, which must not receive a confident pace color.
            last_known = bool(row.get("error") or row.get("status"))
            observed = None if last_known else collected_at
            windows_spec = (("five_hour", "5h", 18000), ("weekly", "W", 604800))
            if isinstance(usage, dict) and "weekly" not in usage:
                windows_spec = (("five_hour", "5h", 18000), ("seven_day", "W", 604800))
        usage = usage if isinstance(usage, dict) else {}
        windows = []
        for key, name, duration in windows_spec:
            raw = usage.get(key)
            if not isinstance(raw, dict):
                continue
            consumed = number(raw.get("pct"))
            if consumed is not None:
                consumed = max(0, min(100, consumed))
            reset = timestamp(raw.get("resetsAt", raw.get("resets_at")))
            windows.append(Window(name, consumed, duration, reset, observed, last_known))
        active = row.get("active") is True or (
            "active" not in row and str(data.get("activeAccountNumber")) == slot
        )
        # A slot can be moved or reused. An opaque ownership tag prevents fallback
        # measurements crossing logins, without persisting raw email/organization.
        email = row.get("email")
        identity = None
        if isinstance(email, str) and email:
            owner = json.dumps([provider, email, row.get("organizationUuid", "")])
            identity = hashlib.sha256(owner.encode()).hexdigest()
        accounts.append(Account(provider, slot, label, active, tuple(windows), identity))
    return accounts


def parse_input(payload: object, providers: tuple[str, ...], now: float) -> list[Account]:
    if not isinstance(payload, dict):
        raise SourceError("Expected a JSON object")
    if "accounts" in payload:
        provider = payload.get("provider", "claude")
        if provider not in PROVIDERS:
            raise SourceError("Unknown provider in JSON input")
        return parse(payload, provider, now) if provider in providers else []
    if not any(provider in payload for provider in PROVIDERS):
        raise SourceError("Expected a provider-keyed object or an accounts array")
    result = []
    for provider in providers:
        if provider in payload:
            result.extend(parse(payload[provider], provider, now))
    return result
