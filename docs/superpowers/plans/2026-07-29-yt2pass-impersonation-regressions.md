# yt2pass Impersonation-Change Regressions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the four behavioural regressions and one latent naming defect introduced by the uncommitted 0.2.6 impersonation edit to `yt2pass`, with unit tests covering each.

**Architecture:** All production changes land in the single script `/workspace/yt2pass/yt2pass`. Rung names are made unique first, because the R1 fix would otherwise introduce two more name collisions. Then cookie-bearing last-resort rungs are appended, the JS-runtime flag is hoisted from four rungs into `_base_args`, and the impersonation probe becomes lazy with a cache that only records completed subprocess runs. Tests are pure-function plus mocked `subprocess`; nothing touches the network.

**Tech Stack:** Python 3.13, pytest, pixi, ruff, mypy. No new dependencies.

**Global Constraints:**
- `__version__` stays `"0.2.6"`. Do not bump it in any task.
- Commit **only** to the inner `/workspace/yt2pass` repo, on branch `fix/impersonation-regressions`. Never `git add` or `git commit` in the outer `/workspace` repo. Run every git command as `cd /workspace/yt2pass && git ...`.
- New tests go in `/workspace/yt2pass/tests/` (inside the inner repo), **not** `/workspace/tests/` (outer repo, where the pre-existing `test_symlink_alias.py` lives and must stay). Verified: pytest run from `/workspace` discovers both locations, and no `__init__.py` is needed in the inner `tests/` dir.
- Test file basenames must be unique across both `tests/` directories, or pytest errors on duplicate module names. `test_symlink_alias.py` is taken.
- The script is excluded from ruff/mypy enforcement and carries 155 ruff and 64 mypy findings at `HEAD`. The bar is **zero new findings versus HEAD**, not zero findings.
- File mode of `yt2pass` must stay `100755`.
- `yt-dlp` is not installed in this container. No test may invoke it; mock `subprocess.run`.
- Do not reintroduce the `ruff` or `ruff-format` pre-commit hooks, and never run `ruff format` / `pixi run format`.

**User decisions (already made):**
- "keep 0.2.6" — version is not bumped by this work.
- "commit to the inner yt2pass repo" — outer repo is ignored entirely.
- R1 shape: "Append cookie-bearing android/ios rungs at the end" of both ladders, after the cookieless variants.
- R2 shape: "Hoist node into `_base_args`, guarded" by `shutil.which("node")`; `--remote-components ejs:github` stays YouTube-only.
- R4/R6 shape: "Fully lazy, cache only completed probes" — the eager `main()` check is deleted.
- Test scope: "Pure functions + mocked subprocess". No fake yt-dlp shim on PATH.
- Cookie-gated content is downloaded regularly, which is why R1 needs a real fix rather than acceptance.

**Spec:** `docs/superpowers/specs/2026-07-29-yt2pass-impersonation-regressions-design.md`

**Already done before this plan (do not redo):** the `_symlink_media_alias` `os.utime` restore, the `chmod 755`, and the `_stderr_wants_impersonation` mypy fix are all applied in the working tree.

---

### Task 1: Characterisation tests for URL routing and stderr classification

**Goal:** Create the inner-repo test module with a fresh-module fixture and lock in the current behaviour of `_is_youtube_url` and `_stderr_wants_impersonation` before anything else changes.

**Files:**
- Create: `/workspace/yt2pass/tests/test_ytdlp_argsets.py`
- Test: `/workspace/yt2pass/tests/test_ytdlp_argsets.py`

**Acceptance Criteria:**
- [ ] `_load_yt2pass()` returns a freshly executed module, so module-level caches never leak between tests
- [ ] `_is_youtube_url` returns True for `youtube.com`, `www.youtube.com`, `music.youtube.com`, `youtu.be`, `youtube-nocookie.com`, and a bare video ID
- [ ] `_is_youtube_url` returns False for `vimeo.com`, `notyoutube.com`, `evil-youtube.com`, and `youtube.com.evil.test`
- [ ] `_stderr_wants_impersonation` handles `None`, `""`, the exact phrase, and an upper-cased phrase
- [ ] No test invokes `subprocess` or the network

**Verify:** `cd /workspace && pixi run python -m pytest yt2pass/tests/test_ytdlp_argsets.py -v` → all pass

**Steps:**

- [ ] **Step 1: Write the test module**

Create `/workspace/yt2pass/tests/test_ytdlp_argsets.py`:

```python
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
```

- [ ] **Step 2: Run the tests and confirm they pass**

```bash
cd /workspace && pixi run python -m pytest yt2pass/tests/test_ytdlp_argsets.py -v
```

Expected: 13 passed. These are characterisation tests over code that already exists, so they pass immediately. If `test_non_youtube_urls_route_to_the_generic_ladder` fails on `evil-youtube.com` or `youtube.com.evil.test`, the host regex is not anchored — stop and report, because that changes Task 3's assumptions.

- [ ] **Step 3: Confirm the outer test still runs from the same invocation**

```bash
cd /workspace && pixi run test
```

Expected: 14 passed total (13 new + `test_alias_symlink_has_fresh_mtime`).

- [ ] **Step 4: Commit**

```bash
cd /workspace/yt2pass && git add tests/test_ytdlp_argsets.py && git commit -m "test: characterise yt2pass URL routing and stderr classification"
```

---

### Task 2: Give every ladder rung a unique name (R7)

**Goal:** Add a `+nocookies` suffix to `_client_name_for_argset` so cookieless and cookie-bearing variants of the same client stop colliding in log lines and in the `_PREFERRED_YT_CLIENT` reorder key.

**Files:**
- Modify: `/workspace/yt2pass/yt2pass` — `_client_name_for_argset`
- Test: `/workspace/yt2pass/tests/test_ytdlp_argsets.py`

**Acceptance Criteria:**
- [ ] `_client_name_for_argset` returns `android+nocookies` for a cookieless android rung and `android` for a cookie-bearing one
- [ ] `[]` returns `default`; `["--no-cookies-from-browser", "--no-cookies"]` returns `default+nocookies`
- [ ] `["--impersonate", "chrome"]` still returns `impersonate:chrome`
- [ ] Every rung in the YouTube probe ladder, the YouTube media ladder, and the generic ladder has a unique name
- [ ] `_argset_label` is unchanged

**Verify:** `cd /workspace && pixi run python -m pytest yt2pass/tests/test_ytdlp_argsets.py -v` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Append to `/workspace/yt2pass/tests/test_ytdlp_argsets.py`:

```python
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
```

- [ ] **Step 2: Run the tests and confirm they fail**

```bash
cd /workspace && pixi run python -m pytest yt2pass/tests/test_ytdlp_argsets.py -v
```

Expected: FAIL. `test_cookieless_and_cookie_bearing_android_get_distinct_names` fails with `assert 'android' == 'android+nocookies'`. `test_generic_default_and_cookieless_rungs_get_distinct_names` fails with `assert 'default' == 'default+nocookies'`. `test_every_probe_rung_has_a_unique_name` fails with duplicate `web`. `test_every_generic_rung_has_a_unique_name` fails with duplicate `default`.

- [ ] **Step 3: Replace `_client_name_for_argset`**

In `/workspace/yt2pass/yt2pass`, replace the whole function with:

```python
def _client_name_for_argset(argset: Sequence[str]) -> str:
    """
    Short identifying name for a yt-dlp argset: the youtube:player_client value,
    an 'impersonate:<target>' tag, or 'default' when neither is present, with a
    '+nocookies' suffix when the argset suppresses browser cookies.

    The name is both the log label and the _PREFERRED_YT_CLIENT reorder key, so
    it must be unique within a ladder. Without the suffix the cookieless and
    cookie-bearing variants of a client collide, which makes log lines ambiguous
    and makes the reorder pull both rungs to the front when only one succeeded.

    Args:
        argset: Sequence of yt-dlp arguments.

    Returns:
        A string like 'tv_embedded', 'web', 'android+nocookies',
        'impersonate:chrome', 'default', or 'default+nocookies'.
    """
    base = "default"
    for i, part in enumerate(argset):
        if not isinstance(part, str):
            continue
        if part.startswith("youtube:player_client="):
            base = part.split("=", 1)[1]
            break
        if part == "--impersonate" and i + 1 < len(argset):
            base = f"impersonate:{argset[i + 1]}"
            break
    if "--no-cookies-from-browser" in argset:
        base += "+nocookies"
    return base
```

- [ ] **Step 4: Run the tests and confirm they pass**

```bash
cd /workspace && pixi run test
```

Expected: 22 passed.

- [ ] **Step 5: Commit**

```bash
cd /workspace/yt2pass && git add yt2pass tests/test_ytdlp_argsets.py && git commit -m "fix: give every yt-dlp ladder rung a unique name"
```

---

### Task 3: Add cookie-bearing android/ios last-resort rungs (R1)

**Goal:** Restore access to gated videos that only the android or ios client can serve, by appending cookie-bearing variants of those two clients to the end of both YouTube ladders.

**Files:**
- Modify: `/workspace/yt2pass/yt2pass` — `_probe_client_argsets`, `_media_blind_client_overrides`
- Test: `/workspace/yt2pass/tests/test_ytdlp_argsets.py`

**Acceptance Criteria:**
- [ ] The YouTube probe ladder has 9 rungs; the last two are android and ios with no `--no-cookies-from-browser`
- [ ] The YouTube media ladder has 8 rungs; the last two are android and ios with no `--no-cookies-from-browser`
- [ ] In both ladders the cookieless variant of each client is tried strictly before the cookie-bearing one
- [ ] The uniqueness tests from Task 2 still pass over the longer ladders
- [ ] The generic ladder is unaffected

**Verify:** `cd /workspace && pixi run test` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Append to `/workspace/yt2pass/tests/test_ytdlp_argsets.py`:

```python
def test_probe_ladder_ends_with_cookie_bearing_android_and_ios(yt2pass, yt_url):
    ladder = yt2pass._probe_client_argsets(yt_url)
    names = [yt2pass._client_name_for_argset(a) for a in ladder]
    assert names[-2:] == ["android", "ios"]
    for argset in ladder[-2:]:
        assert "--no-cookies-from-browser" not in argset


def test_media_ladder_ends_with_cookie_bearing_android_and_ios(yt2pass, yt_url):
    ladder = yt2pass._media_blind_client_overrides(yt_url)
    names = [yt2pass._client_name_for_argset(a) for a in ladder]
    assert names[-2:] == ["android", "ios"]
    for argset in ladder[-2:]:
        assert "--no-cookies-from-browser" not in argset


def test_probe_ladder_tries_cookieless_before_cookie_bearing(yt2pass, yt_url):
    names = [yt2pass._client_name_for_argset(a)
             for a in yt2pass._probe_client_argsets(yt_url)]
    assert names.index("android+nocookies") < names.index("android")
    assert names.index("ios+nocookies") < names.index("ios")


def test_media_ladder_tries_cookieless_before_cookie_bearing(yt2pass, yt_url):
    names = [yt2pass._client_name_for_argset(a)
             for a in yt2pass._media_blind_client_overrides(yt_url)]
    assert names.index("android+nocookies") < names.index("android")
    assert names.index("ios+nocookies") < names.index("ios")


def test_generic_ladder_has_no_youtube_player_client(yt2pass, monkeypatch):
    monkeypatch.setattr(yt2pass, "_impersonation_available", lambda: True)
    for argset in yt2pass._generic_argsets():
        for part in argset:
            assert not part.startswith("youtube:player_client=")
```

- [ ] **Step 2: Run the tests and confirm they fail**

```bash
cd /workspace && pixi run python -m pytest yt2pass/tests/test_ytdlp_argsets.py -v
```

Expected: FAIL. `test_probe_ladder_ends_with_cookie_bearing_android_and_ios` and `test_media_ladder_ends_with_cookie_bearing_android_and_ios` both fail with `assert ['android+nocookies', 'ios+nocookies'] == ['android', 'ios']`. The two ordering tests fail with `ValueError: 'android' is not in list`. `test_generic_ladder_has_no_youtube_player_client` passes already — it is a guard against Task 4 regressing the routing.

- [ ] **Step 3: Append the rungs to the probe ladder**

In `_probe_client_argsets`, after the existing `ios` cookieless rung and before the closing `]`:

```python
        ["--extractor-args", "youtube:player_client=ios",
         "--no-cookies-from-browser", "--no-cookies"],
        # Same two clients again, this time WITH the browser cookies that
        # _base_args always supplies. Cookieless is the better default for
        # these clients, so it goes first; but a gated video (age-restricted,
        # members-only, private) may be servable only here, and this ladder is
        # reached only after everything above has already failed.
        ["--extractor-args", "youtube:player_client=android"],
        ["--extractor-args", "youtube:player_client=ios"],
    ]
```

- [ ] **Step 4: Append the rungs to the media ladder**

In `_media_blind_client_overrides`, after the existing `ios` cookieless rung and before the closing `]`:

```python
        ["--extractor-args", "youtube:player_client=ios",
         "--no-cookies-from-browser", "--no-cookies"],
        # Cookie-bearing last resort; see the note in _probe_client_argsets.
        ["--extractor-args", "youtube:player_client=android"],
        ["--extractor-args", "youtube:player_client=ios"],
    ]
```

- [ ] **Step 5: Run the tests and confirm they pass**

```bash
cd /workspace && pixi run test
```

Expected: 27 passed. In particular `test_every_probe_rung_has_a_unique_name` must still pass over 9 rungs — that is the assertion proving Task 2 was a genuine prerequisite.

- [ ] **Step 6: Commit**

```bash
cd /workspace/yt2pass && git add yt2pass tests/test_ytdlp_argsets.py && git commit -m "fix: restore cookie-bearing android/ios fallback rungs"
```

---

### Task 4: Hoist the JS runtime into `_base_args` (R2)

**Goal:** Give non-YouTube sites a JS runtime again by moving `--js-runtimes node` out of four YouTube-only rungs into `_base_args`, gated on node actually being installed.

**Files:**
- Modify: `/workspace/yt2pass/yt2pass` — new `_node_available`, `_base_args`, `_probe_client_argsets`, `_media_blind_client_overrides`
- Test: `/workspace/yt2pass/tests/test_ytdlp_argsets.py`

**Acceptance Criteria:**
- [ ] `_node_available()` returns True iff `shutil.which("node")` is not None
- [ ] `_base_args` includes `--js-runtimes node` when node is available and omits it when not
- [ ] No rung in either YouTube ladder contains `--js-runtimes`
- [ ] Every `web` and `mweb` rung still carries `--remote-components ejs:github`
- [ ] The generic ladder still contains no `youtube:player_client`

**Verify:** `cd /workspace && pixi run test` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Append to `/workspace/yt2pass/tests/test_ytdlp_argsets.py`. The `_StubOptions` class supplies only the attributes `_base_args(..., fast=True)` actually reads, so the test does not depend on the full CLI:

```python
from types import SimpleNamespace


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
```

- [ ] **Step 2: Run the tests and confirm they fail**

```bash
cd /workspace && pixi run python -m pytest yt2pass/tests/test_ytdlp_argsets.py -v
```

Expected: FAIL. `test_node_available_follows_shutil_which` fails with `AttributeError: module 'yt2pass_script' has no attribute '_node_available'`. `test_no_ladder_rung_names_a_js_runtime` fails on the first `web` rung.

- [ ] **Step 3: Add `_node_available` next to `_ffmpeg_available`**

In `/workspace/yt2pass/yt2pass`, immediately after `_ffmpeg_available`:

```python
def _node_available() -> bool:
    """Check if a Node.js runtime is available on PATH."""
    return shutil.which("node") is not None
```

- [ ] **Step 4: Add the flag to `_base_args`**

In `_base_args`, immediately after the initial `args = [...]` literal and before the `if not fast:` block:

```python
    if _node_available():
        # Generic yt-dlp infrastructure, not a YouTube-specific knob: name the
        # JS interpreter once, globally, whenever one is installed. Naming it
        # per-rung meant non-YouTube sites never got a runtime at all, and it
        # was requested even on machines with no node.
        args += ["--js-runtimes", "node"]
```

- [ ] **Step 5: Strip the flag from the three probe rungs**

In `_probe_client_argsets`, the `web`, cookieless `web`, and `mweb` rungs become:

```python
        # web with Node+EJS (can solve signatures but may hit SABR URLs)
        ["--extractor-args", "youtube:player_client=web",
         "--remote-components", "ejs:github"],
        ["--extractor-args", "youtube:player_client=web",
         "--no-cookies-from-browser", "--no-cookies",
         "--remote-components", "ejs:github"],
        # mweb (may want PO tokens, but sometimes gives playable HLS without SABR)
        ["--extractor-args", "youtube:player_client=mweb",
         "--remote-components", "ejs:github"],
```

- [ ] **Step 6: Strip the flag from the two media rungs**

In `_media_blind_client_overrides`, the `web` and `mweb` rungs become:

```python
        ["--extractor-args", "youtube:player_client=web",
         "--remote-components", "ejs:github"],
        ["--extractor-args", "youtube:player_client=mweb",
         "--remote-components", "ejs:github"],
```

- [ ] **Step 7: Run the tests and confirm they pass**

```bash
cd /workspace && pixi run test
```

Expected: 32 passed.

- [ ] **Step 8: Commit**

```bash
cd /workspace/yt2pass && git add yt2pass tests/test_ytdlp_argsets.py && git commit -m "fix: hoist --js-runtimes node into _base_args"
```

---

### Task 5: Make the impersonation probe lazy with an honest cache (R4, R6)

**Goal:** Stop spawning a yt-dlp subprocess on every invocation, and stop a single timeout from disabling impersonation for the rest of the run.

**Files:**
- Modify: `/workspace/yt2pass/yt2pass` — `_impersonation_available`, delete `_check_impersonation`, remove its call in `main()`
- Create: `/workspace/yt2pass/tests/test_impersonation.py`

**Acceptance Criteria:**
- [ ] A completed subprocess run is cached: a second call does not re-invoke `subprocess.run`
- [ ] A `TimeoutExpired` is not cached: a second call does re-invoke `subprocess.run`
- [ ] A missing yt-dlp executable returns False without invoking `subprocess.run`
- [ ] A table mixing usable rows and `(unavailable)` rows returns True; an all-`(unavailable)` table returns False
- [ ] The `[info]` banner, the `Client ...` header row and the `-----` rule row are never counted as targets
- [ ] `_check_impersonation` no longer exists and `main()` does not call it
- [ ] `_generic_argsets()` includes `--impersonate chrome` only when impersonation is available

**Verify:** `cd /workspace && pixi run python -m pytest yt2pass/tests/test_impersonation.py -v` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Create `/workspace/yt2pass/tests/test_impersonation.py`:

```python
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


def _completed(stdout: str) -> subprocess.CompletedProcess:
    """Build a CompletedProcess standing in for a real yt-dlp run."""
    return subprocess.CompletedProcess(
        args=["yt-dlp"], returncode=0, stdout=stdout, stderr=""
    )


def _install_fake_run(yt2pass, monkeypatch, behaviour):
    """Patch subprocess.run with `behaviour` and return a list of call records."""
    calls: list[tuple] = []

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
```

- [ ] **Step 2: Run the tests and confirm they fail**

```bash
cd /workspace && pixi run python -m pytest yt2pass/tests/test_impersonation.py -v
```

Expected: FAIL. `test_timeout_does_not_poison_the_cache` fails with `assert 1 == 2` — the current code sets `_IMPERSONATION_AVAILABLE = False` before running the subprocess, so the timeout is cached. `test_startup_impersonation_check_is_gone` fails because `_check_impersonation` still exists.

- [ ] **Step 3: Replace `_impersonation_available`**

In `/workspace/yt2pass/yt2pass`, replace the whole function with:

```python
def _impersonation_available() -> bool:
    """
    Return True if yt-dlp reports at least one usable impersonate target.

    Parses `yt-dlp --list-impersonate-targets`: every known target is listed
    whether or not it works, and unusable ones are tagged "(unavailable)".

    The result is cached for the lifetime of the process, but only when the
    subprocess actually ran to completion. A missing executable or a timeout
    leaves the cache unset so a later call retries; caching those would let one
    slow start suppress --impersonate for the rest of the run.
    """
    global _IMPERSONATION_AVAILABLE
    if _IMPERSONATION_AVAILABLE is not None:
        return _IMPERSONATION_AVAILABLE

    exe = _find_ytdlp_exe()
    if not exe:
        return False
    try:
        cp = subprocess.run([exe, "--ignore-config", "--list-impersonate-targets"],
                            check=False, capture_output=True, text=True, timeout=15)
    except Exception as e:
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            logging.debug("Could not list impersonate targets: %s", e)
        return False

    available = False
    for line in (cp.stdout or "").splitlines():
        s = line.strip()
        # Skip yt-dlp's "[info]" banner, the column header and the rule line.
        if not s or s.startswith(("[", "-", "Client")):
            continue
        if "(unavailable)" not in s:
            available = True
            break

    _IMPERSONATION_AVAILABLE = available
    return available
```

- [ ] **Step 4: Delete `_check_impersonation`**

Remove this function entirely from `/workspace/yt2pass/yt2pass`:

```python
def _check_impersonation() -> None:
    """Log impersonation status once at startup, with repair steps if broken."""
    if _impersonation_available():
        logging.info("Browser impersonation available (curl_cffi loaded).")
    else:
        logging.warning("%s", _IMPERSONATION_FIX_HINT)
```

Leave `_IMPERSONATION_FIX_HINT` in place — the stderr-triggered warning inside `_probe_info` still uses it, and that is now the only path that surfaces it.

- [ ] **Step 5: Remove the call in `main()`**

In `main()`, delete the `_check_impersonation()` line so the two lines:

```python
    _check_impersonation()
    _check_ytdlp_version(options)
```

become:

```python
    _check_ytdlp_version(options)
```

- [ ] **Step 6: Run the tests and confirm they pass**

```bash
cd /workspace && pixi run test
```

Expected: 42 passed.

- [ ] **Step 7: Commit**

```bash
cd /workspace/yt2pass && git add yt2pass tests/test_impersonation.py && git commit -m "fix: probe impersonation lazily and cache only completed runs"
```

---

### Task 6: Restore log-line correlation and document the generic ladder depth (R5, R3)

**Goal:** Make the blind-attempt start line use the same identifier as the failure lines below it, and record why the generic ladder is deliberately shorter than the YouTube one.

**Files:**
- Modify: `/workspace/yt2pass/yt2pass` — `_media_pass` blind-attempt log line, `_generic_argsets` docstring

**Acceptance Criteria:**
- [ ] The blind-attempt start line logs `client_name`, matching the failure and debug lines in the same loop
- [ ] `_argset_label` is still used in the two `_probe_info` failure warnings
- [ ] `_generic_argsets` documents why three rungs is correct and where the retry cushion actually comes from
- [ ] No behavioural change beyond the log string

**Verify:** `cd /workspace && pixi run test` → all pass, and `rg -n '_argset_label' yt2pass/yt2pass` shows exactly the definition plus the two `_probe_info` call sites

**Steps:**

- [ ] **Step 1: Fix the log line**

In `_media_pass`, inside the blind-override loop, change:

```python
                logging.info("Blind attempt using client: %s", _argset_label(override))
```

to:

```python
                logging.info("Blind attempt using client: %s", client_name)
```

This is safe now: the reason the manual edit switched to `_argset_label` was that the empty argset logged as a blank string, and Task 2's `default` / `default+nocookies` base names removed that problem. There is no unit test for this step — it is a log format string, and `_media_pass` needs the full download pipeline to exercise. The uniqueness tests from Task 2 are what guarantee `client_name` is unambiguous.

- [ ] **Step 2: Document the generic ladder depth**

Replace the `_generic_argsets` docstring:

```python
def _generic_argsets() -> list[list[str]]:
    """
    Fallback ladder for non-YouTube sites, where youtube:player_client args are
    inert and would otherwise mean issuing the identical request N times.

    Three rungs is deliberate, not an oversight. The seven-rung YouTube ladder
    is not seven retries for a non-YouTube URL: the extractor-args are ignored,
    so it would issue the same request repeatedly. The cushion for transient
    failures comes from the outer probe_max_outer loop with its cooldown, and
    from --retries/--extractor-retries in _base_args.
    """
```

- [ ] **Step 3: Verify the label helper is used only where intended**

```bash
cd /workspace && rg -n '_argset_label' yt2pass/yt2pass
```

Expected: exactly three hits — the `def _argset_label` line, and the two `logging.warning("Probe failed ...")` / `"Probe failed with do_not_retry error ..."` call sites in `_probe_info`.

- [ ] **Step 4: Run the tests**

```bash
cd /workspace && pixi run test
```

Expected: 42 passed, unchanged.

- [ ] **Step 5: Commit**

```bash
cd /workspace/yt2pass && git add yt2pass && git commit -m "fix: log a consistent client name for blind download attempts"
```

---

### Task 7: Full verification sweep

**Goal:** Confirm the finished script introduces no new lint or type findings versus `HEAD`, still compiles, keeps its exec bit, and passes every test.

**Files:**
- Modify: none

**Acceptance Criteria:**
- [ ] `pixi run test` passes with 42 tests
- [ ] The ruff finding set for the script is identical to `HEAD`'s
- [ ] The mypy finding set for the script is identical to `HEAD`'s
- [ ] The script byte-compiles
- [ ] The file mode is `100755`
- [ ] `__version__` is still `"0.2.6"`
- [ ] `pixi run pre-commit run --all-files` passes
- [ ] The outer `/workspace` repo has no new commits

**Verify:** every command below produces its stated expected output

**Steps:**

- [ ] **Step 1: Run the full test suite**

```bash
cd /workspace && pixi run test
```

Expected: `42 passed`.

- [ ] **Step 2: Diff the ruff and mypy finding sets against HEAD**

Findings are aggregated by rule and compared as sets, because absolute counts are meaningless for a file that is excluded from enforcement and already carries 155 ruff / 64 mypy findings.

```bash
S=/tmp/claude-1000/-workspace/f326462c-97fe-4cce-94b4-4f022cc41474/scratchpad/verify
mkdir -p "$S/head" "$S/cur"
git -C /workspace/yt2pass show HEAD:yt2pass > "$S/head/yt2pass"
cp /workspace/yt2pass/yt2pass "$S/cur/yt2pass"
cd /workspace
for d in head cur; do
  pixi run python -m ruff check --force-exclude --output-format=concise "$S/$d/yt2pass" 2>/dev/null \
    | sed 's/^[^ ]*yt2pass:[0-9]*:[0-9]*: //' | sort | uniq -c | sort -rn > "$S/ruff-$d.txt"
  pixi run python -m mypy --scripts-are-modules --no-error-summary "$S/$d/yt2pass" 2>&1 \
    | sed 's/^[^ ]*yt2pass:[0-9]*: //' | sort | uniq -c | sort -rn > "$S/mypy-$d.txt"
done
echo "=== RUFF delta ==="; diff "$S/ruff-head.txt" "$S/ruff-cur.txt" && echo "(none)"
echo "=== MYPY delta ==="; diff "$S/mypy-head.txt" "$S/mypy-cur.txt" && echo "(none)"
```

Expected: both deltas print `(none)`.

Note: `HEAD` here is the inner repo's `HEAD`, whose copy of the script predates the whole 0.2.6 impersonation edit. That is the correct baseline — the bar is "no new findings versus the last committed script".

- [ ] **Step 3: Byte-compile and check the file mode**

```bash
cd /workspace && pixi run python -c "import py_compile; py_compile.compile('yt2pass/yt2pass', doraise=True); print('compile ok')"
test -x /workspace/yt2pass/yt2pass && echo "exec bit ok" || echo "EXEC BIT MISSING - run chmod 755"
git -C /workspace/yt2pass ls-files --stage yt2pass
```

Expected: `compile ok`, `exec bit ok`, and a stage line beginning `100755`.

- [ ] **Step 4: Confirm the version was not bumped**

```bash
cd /workspace && rg -n '^__version__' yt2pass/yt2pass
```

Expected: `__version__: str = "0.2.6"`.

- [ ] **Step 5: Run pre-commit**

```bash
cd /workspace && pixi run pre-commit run --all-files
```

Expected: all hooks pass. If `trailing-whitespace` or `end-of-file-fixer` modifies files, re-run the test suite and amend the relevant commit — do not run `ruff format`.

- [ ] **Step 6: Confirm the outer repo was never committed to**

```bash
git -C /workspace log --oneline -1
git -C /workspace/yt2pass log --oneline -8
```

Expected: the outer repo's latest commit is still `408721c docs: mark yt2pass symlink-mtime task completed`. The inner repo shows the spec commit, the plan commit, and the six commits from Tasks 1–6.
