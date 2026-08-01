"""Tests for yt2pass's yt-dlp argset ladders and URL routing helpers."""

import importlib.machinery
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

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


def test_cookieless_and_cookie_bearing_android_get_distinct_names(yt2pass):
    cookieless = ["--extractor-args", "youtube:player_client=android",
                  "--no-cookies-from-browser", "--no-cookies"]
    cookie_bearing = ["--extractor-args", "youtube:player_client=android"]
    assert yt2pass._client_name_for_argset(cookieless) == "android+nocookies"
    assert yt2pass._client_name_for_argset(cookie_bearing) == "android"


def test_generic_default_and_cookieless_rungs_get_distinct_names(yt2pass):
    assert yt2pass._client_name_for_argset([]) == "default"
    assert yt2pass._client_name_for_argset(
        ["--no-cookies-from-browser", "--no-cookies"]) == "default+nocookies"


def test_impersonate_argset_is_named_for_its_target(yt2pass):
    assert yt2pass._client_name_for_argset(
        ["--impersonate", "chrome"]) == "impersonate:chrome"


def test_argset_label_still_describes_the_empty_argset(yt2pass):
    assert yt2pass._argset_label([]) == "<default client>"
    assert yt2pass._argset_label(["--impersonate", "chrome"]) == "--impersonate chrome"


def test_every_probe_rung_has_a_unique_name(yt2pass, yt_url):
    ladder = yt2pass._probe_client_argsets(yt_url)
    names = [yt2pass._client_name_for_argset(a) for a in ladder]
    assert len(set(names)) == len(names), f"duplicate rung names: {names}"


def test_every_media_rung_has_a_unique_name(yt2pass, yt_url):
    ladder = yt2pass._media_blind_client_overrides(yt_url)
    names = [yt2pass._client_name_for_argset(a) for a in ladder]
    assert len(set(names)) == len(names), f"duplicate rung names: {names}"


@pytest.mark.parametrize("impersonation", [True, False])
def test_every_generic_rung_has_a_unique_name(yt2pass, monkeypatch, impersonation):
    monkeypatch.setattr(yt2pass, "_impersonation_available", lambda: impersonation)
    ladder = yt2pass._generic_argsets()
    names = [yt2pass._client_name_for_argset(a) for a in ladder]
    assert len(set(names)) == len(names), f"duplicate rung names: {names}"


def test_every_android_and_ios_rung_suppresses_browser_cookies(yt2pass, yt_url):
    # yt-dlp refuses to run the android/ios clients when cookies are present:
    #   WARNING: [youtube] Skipping client "android" since it does not support
    #   cookies
    # and then finds no formats at all. _base_args always passes
    # --cookies-from-browser, so a rung that omits --no-cookies-from-browser is
    # not a last-resort chance at gated videos -- it is a guaranteed dead rung.
    checked = 0
    for ladder in (yt2pass._probe_client_argsets(yt_url),
                   yt2pass._media_blind_client_overrides(yt_url)):
        for argset in ladder:
            name = yt2pass._client_name_for_argset(argset)
            if name.startswith(("android", "ios")):
                assert "--no-cookies-from-browser" in argset, (
                    f"{name} rung does not suppress browser cookies; yt-dlp "
                    "will skip the client entirely and find no formats")
                checked += 1
    assert checked == 4, f"expected 4 android/ios rungs, checked {checked}"


def test_generic_ladder_has_no_youtube_player_client(yt2pass, monkeypatch):
    monkeypatch.setattr(yt2pass, "_impersonation_available", lambda: True)
    for argset in yt2pass._generic_argsets():
        for part in argset:
            assert not part.startswith("youtube:player_client=")


class _StubOptions:
    """Minimal stand-in for Options, covering the fast=True path of _base_args."""

    def __init__(self) -> None:
        self.args = SimpleNamespace(rate_limit=0, aria=False)

    def output_template(self) -> str:
        return "%(title)s.%(ext)s"


def test_node_available_follows_shutil_which(yt2pass, monkeypatch):
    monkeypatch.setattr(yt2pass.shutil, "which",
                        lambda name: "/usr/bin/node" if name == "node" else None)
    assert yt2pass._node_available() is True
    monkeypatch.setattr(yt2pass.shutil, "which", lambda name: None)
    assert yt2pass._node_available() is False


def test_base_args_requests_node_when_present(yt2pass, monkeypatch):
    monkeypatch.setattr(yt2pass, "_node_available", lambda: True)
    args = yt2pass._base_args(_StubOptions(), fast=True)
    assert "--js-runtimes" in args
    assert args[args.index("--js-runtimes") + 1] == "node"


def test_base_args_omits_node_when_absent(yt2pass, monkeypatch):
    monkeypatch.setattr(yt2pass, "_node_available", lambda: False)
    args = yt2pass._base_args(_StubOptions(), fast=True)
    assert "--js-runtimes" not in args


def test_no_ladder_rung_names_a_js_runtime(yt2pass, yt_url):
    for ladder in (yt2pass._probe_client_argsets(yt_url),
                   yt2pass._media_blind_client_overrides(yt_url)):
        for argset in ladder:
            assert "--js-runtimes" not in argset


def test_web_and_mweb_rungs_keep_the_ejs_component(yt2pass, yt_url):
    checked = 0
    for ladder in (yt2pass._probe_client_argsets(yt_url),
                   yt2pass._media_blind_client_overrides(yt_url)):
        for argset in ladder:
            name = yt2pass._client_name_for_argset(argset)
            if name.startswith(("web", "mweb")):
                assert "--remote-components" in argset
                assert argset[argset.index("--remote-components") + 1] == "ejs:github"
                checked += 1
    assert checked == 5, f"expected 5 web/mweb rungs, checked {checked}"


# --- YouTube/generic routing wiring ---------------------------------------
#
# _probe_client_argsets(url) and _media_blind_client_overrides(url) each start
# with `if not _is_youtube_url(url): return _generic_argsets()`. Every ladder
# test above uses the yt_url fixture, so it never exercises that guard, and
# test_generic_ladder_has_no_youtube_player_client calls _generic_argsets()
# directly, bypassing the routing entirely. These tests pin the guard itself:
# delete either `if not _is_youtube_url(url): ...` line and one of the tests
# below must fail.

_NON_YOUTUBE_URL = "https://vimeo.com/123456"


@pytest.mark.parametrize("impersonation", [True, False])
def test_probe_argsets_route_non_youtube_url_to_generic_ladder(
        yt2pass, monkeypatch, impersonation):
    monkeypatch.setattr(yt2pass, "_impersonation_available", lambda: impersonation)
    assert (yt2pass._probe_client_argsets(_NON_YOUTUBE_URL)
            == yt2pass._generic_argsets())


@pytest.mark.parametrize("impersonation", [True, False])
def test_media_argsets_route_non_youtube_url_to_generic_ladder(
        yt2pass, monkeypatch, impersonation):
    monkeypatch.setattr(yt2pass, "_impersonation_available", lambda: impersonation)
    assert (yt2pass._media_blind_client_overrides(_NON_YOUTUBE_URL)
            == yt2pass._generic_argsets())


def test_probe_argsets_do_not_route_youtube_url_to_generic_ladder(yt2pass, yt_url):
    ladder = yt2pass._probe_client_argsets(yt_url)
    assert any(
        isinstance(part, str) and part.startswith("youtube:player_client=")
        for argset in ladder for part in argset
    ), f"expected a youtube:player_client rung, got {ladder!r}"


def test_media_argsets_do_not_route_youtube_url_to_generic_ladder(yt2pass, yt_url):
    ladder = yt2pass._media_blind_client_overrides(yt_url)
    assert any(
        isinstance(part, str) and part.startswith("youtube:player_client=")
        for argset in ladder for part in argset
    ), f"expected a youtube:player_client rung, got {ladder!r}"
