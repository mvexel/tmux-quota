"""tmux styling and plain terminal output from the same measurements."""

from .model import Account, Window

PALETTES = {
    # ANSI slots use the terminal's configured palette, independent of whether
    # its background is light or dark. Non-pace text inherits tmux's status style.
    "terminal": {"green": "colour2", "blue": "colour4", "amber": "colour3",
                 "red": "colour1", "unknown": "default", "track": "default", "text": "default"},
    "dark": {"green": "#9ece6a", "blue": "#7aa2f7", "amber": "#e0af68",
             "red": "#f7768e", "unknown": "#737da8", "track": "#565f89", "text": "#c0caf5"},
    "light": {"green": "#587539", "blue": "#2e7de9", "amber": "#8c6c3e",
              "red": "#f52a65", "unknown": "#8990b3", "track": "#8990b3", "text": "#343b58"},
}


def style(color: str) -> str:
    return "#[default]" if color == "default" else f"#[fg={color}]"


def safe_label(value: str) -> str:
    # '#' introduces tmux formats/styles/commands; strip it from untrusted labels.
    return "".join(c for c in value if c.isprintable() and c != "#")[:24] or "?"


def bar(window: Window, now: float, max_age: float, width: int,
        ascii_only: bool, palette: dict[str, str] | None) -> str:
    known = window.available(now, max_age)
    pct = window.consumed if known else None
    filled = int(pct * width / 100 + 0.5) if pct is not None else 0
    # Thin lines avoid terminal-specific full-cell shading of block glyphs.
    full, empty = ("=", "-") if ascii_only else ("━", "─")
    percent = f"{pct:.0f}%" if pct is not None else "?"
    if palette is None:
        return "[" + full * filled + empty * (width - filled) + "] " + percent
    pace = window.pace(now, max_age)
    color = palette[pace]
    percent_color = palette["text"] if pace == "unknown" else color
    return (style(palette["track"]) + "[" + style(color) + full * filled +
            style(palette["track"]) + empty * (width - filled) + "]" +
            style(percent_color) + " " + percent + style(palette["text"]))


def render(accounts: list[Account], *, now: float, theme: str = "terminal",
           format: str = "tmux", width: int = 6, ascii_only: bool = False,
           max_age: float = 600, labels: dict[str, str] | None = None,
           active_only: bool = False, scoped_providers: tuple[str, ...] = (),
           colors: dict[str, str] | None = None) -> str:
    palette = {**PALETTES[theme], **(colors or {})} if format == "tmux" else None
    groups = []
    for provider in ("claude", "codex"):
        members = [a for a in accounts if a.provider == provider and
                   (not active_only or a.active)]
        compact = (len(members) == 1 and members[0].label == members[0].number and
                   f"{provider}:{members[0].number}" not in (labels or {}))
        title = provider.title()
        segments = []
        for account in members:
            label = (labels or {}).get(f"{provider}:{account.number}", account.label)
            unavailable = not account.windows or any(
                w.last_known or not w.available(now, max_age) for w in account.windows
            )
            marker = ("*" if account.active else "") + ("~" if unavailable and account.windows else "")
            windows = " ".join(
                w.label + " " + bar(w, now, max_age, width, ascii_only, palette)
                for w in account.windows
            ) or "unavailable"
            if compact:
                title += marker
                segments.append(windows)
            else:
                segments.append(safe_label(label) + marker + " " + windows)
        if segments:
            groups.append(title + " " + " / ".join(segments))
        elif provider in scoped_providers:
            has_accounts = any(a.provider == provider for a in accounts)
            status = "no active account" if active_only and has_accounts else "unavailable"
            groups.append(provider.title() + " " + status)
    separator = " | " if ascii_only else " │ "
    text = separator.join(groups)
    return style(palette["text"]) + text + "#[default]" if palette and text else text
