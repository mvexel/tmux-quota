from contextlib import redirect_stdout, redirect_stderr
from dataclasses import asdict, replace
import fcntl
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from tmux_quota.cache import cached_fetch, collect, fetch
from tmux_quota.cli import main
from tmux_quota.model import Account, Window
from tmux_quota.source import SourceError


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.account = Account("codex", "1", "1", True, (
            Window("W", 17, 604800, time.time() + 300000, time.time()),), "test-owner")

    def test_cache_throttles_calls_and_preserves_observation_time(self):
        with patch("tmux_quota.cache.fetch", return_value=[self.account]) as source:
            first = cached_fetch("codex", "ccswap", 1, self.directory, 60)
            second = cached_fetch("codex", "ccswap", 1, self.directory, 60)
        self.assertEqual(source.call_count, 1)
        self.assertEqual(first.accounts, second.accounts)
        self.assertEqual(next(self.directory.glob("*.json")).stat().st_mode & 0o777, 0o600)

    def test_failure_keeps_last_good_without_refreshing_its_age(self):
        with patch("tmux_quota.cache.fetch", return_value=[self.account]):
            cached_fetch("codex", "ccswap", 1, self.directory, 60)
        with patch("tmux_quota.cache.fetch", side_effect=SourceError("offline")):
            later = cached_fetch("codex", "ccswap", 1, self.directory, 0)
        self.assertEqual(later.accounts[0].windows[0].observed_at,
                         self.account.windows[0].observed_at)
        self.assertTrue(later.accounts[0].windows[0].last_known)
        self.assertEqual(later.error, "offline")
        with patch("tmux_quota.cache.fetch") as source:
            self.assertEqual(cached_fetch("codex", "ccswap", 1, self.directory, 60).error, "offline")
            source.assert_not_called()

    def test_corrupt_and_future_checked_cache_are_refetched(self):
        with patch("tmux_quota.cache.fetch", return_value=[self.account]):
            cached_fetch("codex", "ccswap", 1, self.directory, 60)
        path = next(self.directory.glob("*.json"))
        for content in ("{broken", "[]", json.dumps({"version": 1, "checked_at": time.time() + 1000,
                                                    "accounts": [asdict(self.account)]})):
            path.write_text(content)
            with patch("tmux_quota.cache.fetch", return_value=[self.account]) as source:
                cached_fetch("codex", "ccswap", 1, self.directory, 60)
                source.assert_called_once()

    def test_lock_contention_serves_cache_without_starting_another_fetch(self):
        with patch("tmux_quota.cache.fetch", return_value=[self.account]):
            cached_fetch("codex", "ccswap", 1, self.directory, 60)
        with next(self.directory.glob("*.lock")).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch("tmux_quota.cache.fetch") as source:
                result = cached_fetch("codex", "ccswap", 1, self.directory, 0)
                source.assert_not_called()
                self.assertEqual(result.accounts, [self.account])

    def test_different_account_homes_get_different_caches(self):
        with patch("tmux_quota.cache.fetch", return_value=[self.account]) as source:
            for home in ("/first", "/second"):
                with patch.dict(os.environ, {"CODEX_HOME": home}):
                    cached_fetch("codex", "ccswap", 1, self.directory, 60)
        self.assertEqual(source.call_count, 2)

    def test_exit_zero_account_failure_retains_usage_and_new_active_flag(self):
        with patch("tmux_quota.cache.fetch", return_value=[self.account]):
            cached_fetch("codex", "ccswap", 1, self.directory, 60)
        unavailable = replace(self.account, active=False, windows=())
        with patch("tmux_quota.cache.fetch", return_value=[unavailable]):
            result = cached_fetch("codex", "ccswap", 1, self.directory, 0)
        account = result.accounts[0]
        self.assertFalse(account.active)
        self.assertEqual(account.windows[0].observed_at, self.account.windows[0].observed_at)
        self.assertEqual(account.windows[0].consumed, 17)
        self.assertTrue(account.windows[0].last_known)
        self.assertEqual(result.error, "usage unavailable for account 1")
        with patch("tmux_quota.cache.fetch", return_value=[self.account]):
            recovered = cached_fetch("codex", "ccswap", 1, self.directory, 0)
        self.assertIsNone(recovered.error)
        self.assertFalse(recovered.accounts[0].windows[0].last_known)

    def test_missing_new_account_does_not_inherit_another_accounts_usage(self):
        with patch("tmux_quota.cache.fetch", return_value=[self.account]):
            cached_fetch("codex", "ccswap", 1, self.directory, 60)
        different = replace(self.account, number="9", windows=())
        with patch("tmux_quota.cache.fetch", return_value=[different]):
            result = cached_fetch("codex", "ccswap", 1, self.directory, 0)
        self.assertEqual(result.accounts, [different])

    def test_reused_slot_does_not_inherit_another_logins_measurements(self):
        with patch("tmux_quota.cache.fetch", return_value=[self.account]):
            cached_fetch("codex", "ccswap", 1, self.directory, 60)
        for identity in ("different-owner", None):
            different = replace(self.account, identity=identity, windows=())
            with patch("tmux_quota.cache.fetch", return_value=[different]):
                result = cached_fetch("codex", "ccswap", 1, self.directory, 0)
            self.assertEqual(result.accounts[0].windows, ())

    def test_xdg_data_homes_get_distinct_caches(self):
        with patch("tmux_quota.cache.fetch", return_value=[self.account]) as source:
            for home in ("/first", "/second"):
                with patch.dict(os.environ, {"XDG_DATA_HOME": home}):
                    cached_fetch("codex", "ccswap", 1, self.directory, 60)
        self.assertEqual(source.call_count, 2)

    def test_partial_provider_failure_preserves_other_provider(self):
        def provider(name, executable, timeout):
            if name == "claude":
                raise SourceError("timeout")
            return [self.account]
        with patch("tmux_quota.cache.fetch", side_effect=provider):
            accounts, errors = collect(("claude", "codex"), "ccswap", 1, None, 60)
        self.assertEqual(accounts, [self.account])
        self.assertEqual(errors, ["claude: timeout"])

    def test_subprocess_contract_errors_and_no_stderr_leak(self):
        with patch("tmux_quota.cache.subprocess.run", return_value=subprocess.CompletedProcess(
                [], 0, '{"provider":"codex","accounts":[]}', "")) as run:
            self.assertEqual(fetch("codex", "/path with spaces/ccswap", 7), [])
            self.assertEqual(run.call_args.args[0], ["/path with spaces/ccswap", "codex", "usage", "--json"])
            self.assertEqual(run.call_args.kwargs["timeout"], 7)
        for result in [subprocess.CompletedProcess([], 1, "private account data", "secret"),
                       subprocess.CompletedProcess([], 0, "not JSON", "secret")]:
            with patch("tmux_quota.cache.subprocess.run", return_value=result):
                with self.assertRaises(SourceError) as error:
                    fetch("claude", "ccswap", 1)
                self.assertNotIn("secret", str(error.exception))
                self.assertNotIn("private", str(error.exception))
        for error in [FileNotFoundError(), subprocess.TimeoutExpired("ccswap", 1)]:
            with patch("tmux_quota.cache.subprocess.run", side_effect=error):
                with self.assertRaises(SourceError):
                    fetch("claude", "ccswap", 1)


class CliTests(unittest.TestCase):
    def invoke(self, args, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), patch("sys.stdin", io.StringIO(stdin)):
            status = main(args)
        return status, out.getvalue(), err.getvalue()

    def test_stdin_json_and_label_override(self):
        data = '{"provider":"codex","accounts":[{"number":1,"active":true,"usage":{"weekly":{"pct":17}}}]}'
        status, out, err = self.invoke(["--stdin", "--format", "json", "--label", "codex:1=home"], data)
        self.assertEqual(status, 0)
        row = json.loads(out)["accounts"][0]
        self.assertEqual(row["label"], "home")
        self.assertEqual(row["windows"][0]["pace"], "unknown")
        self.assertEqual(err, "")

    def test_invalid_stdin_and_quiet_failure(self):
        status, out, err = self.invoke(["--stdin", "--format", "plain", "--quiet"], "[]")
        self.assertEqual(status, 1)
        self.assertEqual(out.strip(), "Claude unavailable │ Codex unavailable")
        self.assertEqual(err, "")

    def test_reject_invalid_options(self):
        for args in [["--width", "0"], ["--timeout", "nan"], ["--cache-ttl", "-1"],
                     ["--label", "oops"], ["--max-age", "inf"]]:
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(args)
            self.assertEqual(error.exception.code, 2)

    def test_real_cli_process_with_fake_ccswap_and_cached_second_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / "fake ccswap"
            counter = root / "calls"
            fake.write_text(f'''#!{sys.executable}
import json, sys, time
from pathlib import Path
with Path({str(counter)!r}).open('a') as out:
    out.write(' '.join(sys.argv[1:]) + '\\n')
if sys.argv[1:] == ['list', '--provider', 'claude', '--json']:
    data = {{'accounts': [{{'number': 1, 'alias': 'team', 'active': True,
        'usageStatus': 'ok', 'usageAgeSeconds': 0,
        'usage': {{'sevenDay': {{'pct': 54}}}}}}]}}
elif sys.argv[1:] == ['codex', 'usage', '--json']:
    data = {{'provider':'codex', 'accounts':[{{'number':1, 'active':True,
        'usage':{{'weekly':{{'pct':17}}}}}}]}}
else:
    sys.exit(23)
print(json.dumps(data))
''')
            fake.chmod(0o755)
            command = [sys.executable, "-m", "tmux_quota", "--ccswap", str(fake),
                       "--cache-dir", str(root / "cache"), "--format", "plain"]
            for _ in range(2):
                result = subprocess.run(command, text=True, capture_output=True, check=True)
                self.assertEqual(result.stdout.strip(), "Claude team* W [━━━───] 54% │ Codex* W [━─────] 17%")
            self.assertCountEqual(counter.read_text().splitlines(),
                                  ["list --provider claude --json", "codex usage --json"])


if __name__ == "__main__":
    unittest.main()
