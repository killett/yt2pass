"""Tests for yt2pass's yt-dlp argset ladders and URL routing helpers."""

import importlib.machinery
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "yt2pass"


def _load_yt2pass() -> ModuleType:
    """Load the extensionless yt2pass script as a module.

    Returns:
        A freshly executed module object. Each call re-executes the script, so
        module-level caches (notably _IMPERSONATION_AVAILABLE) start unset.
    """
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
    """Fresh yt2pass module per test, so module globals never leak."""
    return _load_yt2pass()


@pytest.fixture
def yt_url() -> str:
    """A representative YouTube watch URL."""
    return "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.mark.parametrize("url", [
    "https://youtube.com/watch?v=abc123",
    "https://www.youtube.com/watch?v=abc123",
    "https://music.youtube.com/watch?v=abc123",
    "https://youtu.be/abc123",
    "https://www.youtube-nocookie.com/embed/abc123",
    "dQw4w9WgXcQ",
])
def test_youtube_urls_route_to_the_youtube_ladder(yt2pass, url):
    assert yt2pass._is_youtube_url(url) is True


@pytest.mark.parametrize("url", [
    "https://vimeo.com/123456",
    "https://notyoutube.com/watch?v=abc123",
    "https://evil-youtube.com/watch?v=abc123",
    "https://youtube.com.evil.test/watch?v=abc123",
])
def test_non_youtube_urls_route_to_the_generic_ladder(yt2pass, url):
    assert yt2pass._is_youtube_url(url) is False


def test_stderr_wants_impersonation_ignores_missing_stderr(yt2pass):
    assert yt2pass._stderr_wants_impersonation(None) is False
    assert yt2pass._stderr_wants_impersonation("") is False


def test_stderr_wants_impersonation_matches_regardless_of_case(yt2pass):
    lower = "ERROR: no impersonate target is available"
    upper = "ERROR: No Impersonate Target Is Available"
    assert yt2pass._stderr_wants_impersonation(lower) is True
    assert yt2pass._stderr_wants_impersonation(upper) is True


def test_stderr_wants_impersonation_ignores_unrelated_errors(yt2pass):
    assert yt2pass._stderr_wants_impersonation("ERROR: Video unavailable") is False
