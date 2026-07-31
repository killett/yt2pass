"""Tests for yt2pass's browser-impersonation detection."""

import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "yt2pass"

TABLE_MIXED = """\
[info] Available impersonate targets
Client  Version  OS       Source
------  -------  -------  ---------
chrome  110      windows  curl_cffi
safari  15.5     macos    (unavailable)
"""

TABLE_ALL_UNAVAILABLE = """\
[info] Available impersonate targets
Client  Version  OS       Source
------  -------  -------  ------------
chrome  110      windows  (unavailable)
safari  15.5     macos    (unavailable)
"""

TABLE_HEADER_ONLY = """\
[info] Available impersonate targets
Client  Version  OS       Source
------  -------  -------  ------------
"""


def _load_yt2pass() -> ModuleType:
    """Load the extensionless yt2pass script as a freshly executed module."""
    loader = importlib.machinery.SourceFileLoader(
        "yt2pass_script", str(SCRIPT_PATH)
    )
    spec = importlib.util.spec_from_loader("yt2pass_script", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def yt2pass() -> ModuleType:
    """Fresh module per test, so _IMPERSONATION_AVAILABLE starts unset."""
    return _load_yt2pass()


def _completed(stdout: str) -> subprocess.CompletedProcess[str]:
    """Build a CompletedProcess standing in for a real yt-dlp run."""
    return subprocess.CompletedProcess(
        args=["yt-dlp"], returncode=0, stdout=stdout, stderr=""
    )


def _install_fake_run(yt2pass, monkeypatch, behaviour):
    """Patch subprocess.run with `behaviour` and return a list of call records."""
    calls: list[tuple[object, ...]] = []

    def fake_run(*args, **kwargs):
        calls.append(args)
        return behaviour()

    monkeypatch.setattr(yt2pass, "_find_ytdlp_exe", lambda: "/usr/bin/yt-dlp")
    monkeypatch.setattr(yt2pass.subprocess, "run", fake_run)
    return calls


def test_mixed_table_reports_impersonation_available(yt2pass, monkeypatch):
    _install_fake_run(yt2pass, monkeypatch, lambda: _completed(TABLE_MIXED))
    assert yt2pass._impersonation_available() is True


def test_all_unavailable_table_reports_no_impersonation(yt2pass, monkeypatch):
    _install_fake_run(yt2pass, monkeypatch,
                      lambda: _completed(TABLE_ALL_UNAVAILABLE))
    assert yt2pass._impersonation_available() is False


def test_header_rows_are_not_mistaken_for_targets(yt2pass, monkeypatch):
    _install_fake_run(yt2pass, monkeypatch, lambda: _completed(TABLE_HEADER_ONLY))
    assert yt2pass._impersonation_available() is False


def test_completed_run_is_cached(yt2pass, monkeypatch):
    calls = _install_fake_run(yt2pass, monkeypatch, lambda: _completed(TABLE_MIXED))
    assert yt2pass._impersonation_available() is True
    assert yt2pass._impersonation_available() is True
    assert len(calls) == 1, "a completed probe must be cached, not repeated"


def test_timeout_does_not_poison_the_cache(yt2pass, monkeypatch):
    def blow_up():
        raise subprocess.TimeoutExpired(cmd="yt-dlp", timeout=15)

    calls = _install_fake_run(yt2pass, monkeypatch, blow_up)
    assert yt2pass._impersonation_available() is False
    assert yt2pass._impersonation_available() is False
    assert len(calls) == 2, "a timed-out probe must be retried, not cached"


def test_missing_executable_short_circuits(yt2pass, monkeypatch):
    calls = _install_fake_run(yt2pass, monkeypatch, lambda: _completed(TABLE_MIXED))
    monkeypatch.setattr(yt2pass, "_find_ytdlp_exe", lambda: None)
    assert yt2pass._impersonation_available() is False
    assert calls == [], "no subprocess should run without a yt-dlp executable"


def test_startup_impersonation_check_is_gone(yt2pass):
    assert not hasattr(yt2pass, "_check_impersonation"), (
        "the eager startup probe must be removed; it cost a yt-dlp subprocess "
        "on every invocation, including runs with no URL"
    )


def test_fix_hint_survives_for_the_stderr_triggered_warning(yt2pass):
    assert "curl-cffi" in yt2pass._IMPERSONATION_FIX_HINT


@pytest.mark.parametrize("available,expected", [(True, True), (False, False)])
def test_generic_ladder_offers_impersonate_only_when_usable(
    yt2pass, monkeypatch, available, expected
):
    monkeypatch.setattr(yt2pass, "_impersonation_available", lambda: available)
    names = [yt2pass._client_name_for_argset(a) for a in yt2pass._generic_argsets()]
    assert ("impersonate:chrome" in names) is expected
