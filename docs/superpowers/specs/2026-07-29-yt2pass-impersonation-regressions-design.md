# yt2pass impersonation-change regressions — design

Date: 2026-07-29
Status: implemented, **partially superseded** — see Correction below
Scope: `yt2pass/yt2pass` (single script), `tests/`

## Correction (2026-08-01): R1 was not a regression

**R1's premise is false. Everything this document says about it is wrong, and
the fix it specifies was implemented and then reverted.** R2 through R7 stand
as written and remain in the code.

The rest of this document is preserved unedited as a record of what was
believed on 2026-07-29. Read the R1 material below as history, not as guidance.

Empirical check against yt-dlp 2026.07 with curl_cffi-0.13.0, running
`player_client=android` with `--cookies-from-browser firefox` against an
age-restricted video:

```
WARNING: [youtube] Skipping client "android" since it does not support cookies
WARNING: Only images are available for download.
```

yt-dlp does not ignore cookies for the `android`/`ios` clients — it **skips the
client entirely**, yielding no formats at all. Three consequences:

1. A cookie-bearing `android`/`ios` rung is strictly worse than its cookieless
   neighbour, not a last-resort chance at a gated video. It cannot ever succeed.
2. These clients cannot serve age-restricted, members-only or private videos
   under any configuration, because cookie authentication is precisely what they
   refuse. The cookie-authenticated clients earlier in the ladder are what handle
   gated content.
3. The direction of the original change was backwards. Before the manual edit
   these rungs carried `--no-cookies`, which clears `--cookies` but never
   `--cookies-from-browser` — so browser cookies were always present and yt-dlp
   was skipping `android`/`ios` on every run. Adding `--no-cookies-from-browser`
   **repaired** those rungs. It never lost gated-video access.

What actually shipped: the four appended rungs were removed in `eb12110`, the
ladders returned to 7 probe / 6 media, and the four rung-ordering tests were
replaced by an inverted guard asserting that *every* `android`/`ios` rung
suppresses browser cookies, so the dead rungs cannot be reintroduced.

Process note: this was caught only because the final whole-branch review flagged
R1's premise as unverifiable in a container without yt-dlp and asked for a check
against the real tool. Every prior review passed it, because nothing in the diff
could reveal it.

## Background

A manual edit to `yt2pass` (version bumped `0.2.5` → `0.2.6`, uncommitted) added
browser-impersonation support, split the yt-dlp client fallback ladders into a
YouTube branch and a generic branch, and fixed a genuine flag bug where
`--no-cookies` never suppressed browser cookies. The edit is broadly correct,
but a review found seven regressions or latent defects.

Three were already repaired before this design was written and are recorded
here only for completeness:

- The alias-symlink `os.utime(..., follow_symlinks=False)` stamp had been
  dropped from `_symlink_media_alias`, silently reverting commit `7f6a734`.
  Restored, along with its docstring and the early `return` on symlink failure.
- The file mode had changed `100755` → `100644`, losing the exec bit on a
  shebang script. Restored with `chmod 755`.
- `_stderr_wants_impersonation` used `bool(s) and s.lower()`, which mypy cannot
  narrow. Changed to `s is not None and ...`, runtime behaviour identical.

After those three, `ruff` and `mypy` error sets are byte-identical to `HEAD`
for this file, and the existing test passes.

This design covers the four remaining regressions (R1–R6, minus the two that
need no code change) plus one new defect found during design (R7).

## Constraints

- `yt-dlp` is **not installed** in the development container. Nothing can be
  verified against real yt-dlp output; all tests must mock `subprocess`.
- The project intentionally excludes `yt2pass/yt2pass` from `ruff`/`mypy`
  enforcement (it carries 155 ruff and 64 mypy findings at `HEAD`). The bar is
  therefore **no new findings relative to `HEAD`**, not zero findings.
- `_base_args` hardcodes `--cookies-from-browser firefox` on every invocation,
  so every rung carries Firefox cookies unless it explicitly opts out.
- Dr. Twinklebrane regularly downloads cookie-gated content (age-restricted,
  members-only, private, purchased). Cookie access is load-bearing.
- Version stays at `0.2.6`; these fixes ride in the same unreleased bump.
- Commits go to the **inner** `/workspace/yt2pass` repo only. The outer
  `/workspace` repo is ignored entirely.

## Regression inventory

| ID | Defect | Resolution |
|----|--------|------------|
| ~~R1~~ | ~~`android`/`ios` rungs lost browser cookies, so a gated video that only those clients can serve now fails~~ | **WITHDRAWN — not a regression; see Correction. Implemented, then reverted in `eb12110`.** |
| R2 | `_generic_argsets()` dropped `--js-runtimes node`, generic yt-dlp infrastructure, for all non-YouTube sites | Hoist node into `_base_args`, gated on `shutil.which` |
| R3 | Non-YouTube fallback depth fell 7 → 3 | No code change; document why |
| R4 | `_impersonation_available()` caches `False` on timeout/exception, disabling impersonation for the whole run | Cache only on a completed subprocess run |
| R5 | `_media_pass` start line logs `_argset_label`, failure lines log `client_name`; the two no longer correlate | Use `client_name` for both `_media_pass` lines, once names are unique |
| R6 | `_check_impersonation()` spawns a yt-dlp subprocess on every invocation, including no-URL runs | Make the probe lazy; delete the eager startup call |
| R7 | `_client_name_for_argset` collides: `[]` and the cookieless generic rung both return `"default"` | Add a `+nocookies` suffix to the name |

> **Superseded.** The paragraph below reasons about a gap that does not exist:
> `android`/`ios` cannot serve gated videos with or without cookies, because
> yt-dlp skips those clients outright when cookies are present. See Correction.

R1's severity is narrower than it first appears. Of the seven YouTube probe
rungs, four (`tv_embedded`, `web`, `mweb`, `tv_html5_embed`) carry cookies both
before and after the manual edit. Gated content therefore still gets four
cookie-bearing attempts. The gap is only the case where `android` or `ios` is
the *only* client that works — which does happen when other clients are
SABR-blocked.

## Design

### 1. Unique rung names (R7, and prerequisite for R1)

`_client_name_for_argset` produces both the human log label and the
`_PREFERRED_YT_CLIENT` reorder key. Colliding names make log lines ambiguous
and make the reorder pull multiple rungs to the front when only one succeeded.
R1 would add two further collisions (cookie-bearing `android` versus cookieless
`android`).

New naming rule:

- Base name: the `youtube:player_client=<x>` value → `<x>`; else
  `--impersonate <t>` → `impersonate:<t>`; else `default`.
- If `--no-cookies-from-browser` appears in the argset, append `+nocookies`.

Resulting names, all distinct within each ladder:

- YouTube probe ladder: `tv_embedded`, `web`, `web+nocookies`, `mweb`,
  `tv_html5_embed`, `android+nocookies`, `ios+nocookies`, `android`, `ios`
- YouTube media ladder: `tv_html5_embed`, `tv_embedded`, `web`, `mweb`,
  `android+nocookies`, `ios+nocookies`, `android`, `ios`
- Generic ladder: `default`, `impersonate:chrome`, `default+nocookies`

Names must stay stable across items in a playlist run, since
`_PREFERRED_YT_CLIENT` persists. They do — the name is a pure function of the
argset.

### 2. Cookie-bearing last-resort rungs (R1) — WITHDRAWN

> **Do not implement this section.** It was built and then reverted in
> `eb12110`. The rungs it specifies can never succeed: yt-dlp skips the
> `android`/`ios` clients entirely when browser cookies are present. See
> Correction. The current code asserts the opposite invariant — every
> `android`/`ios` rung *must* suppress browser cookies.

Append to the YouTube branch of `_probe_client_argsets(url)`, *after* the
existing cookieless `android`/`ios` rungs:

```python
["--extractor-args", "youtube:player_client=android"],
["--extractor-args", "youtube:player_client=ios"],
```

Seven rungs become nine. Append the identical two to the YouTube branch of
`_media_blind_client_overrides(url)`: six become eight.

These carry Firefox cookies via `_base_args`. They are reached only after every
other rung has failed, so healthy videos pay nothing and a gated
android/ios-only video regains the path it had before the manual edit.

The cookieless variants stay *ahead* of the cookie-bearing ones: cookieless is
the better default for these clients, and trying it first preserves current
behaviour for everything that already works.

### 3. Hoist the JS runtime (R2)

- Add `_node_available() -> bool` returning `shutil.which("node") is not None`,
  mirroring the existing `_ffmpeg_available()`.
- `_base_args` appends `["--js-runtimes", "node"]` when `_node_available()`.
- Remove the `"--js-runtimes", "node"` pair from all four rungs that carry it:
  the `web` and `mweb` rungs in `_probe_client_argsets`, and the `web` and
  `mweb` rungs in `_media_blind_client_overrides`.
- Leave `--remote-components ejs:github` on those YouTube rungs. That is
  YouTube's JS-challenge solver, genuinely YouTube-specific, and correctly
  scoped to the YouTube branch.

Non-YouTube sites regain a JS runtime, the flag stops being requested when node
is absent, and the duplication disappears.

`shutil.which` is called once per `_base_args` invocation. That is a handful of
filesystem lookups per download attempt — not worth memoising.

### 4. Lazy impersonation probe with an honest cache (R4, R6)

Delete the `_check_impersonation()` call from `main()` and delete the function.
`_IMPERSONATION_FIX_HINT` stays: the stderr-triggered warning inside
`_probe_info` becomes the sole path that surfaces it, and it fires precisely
when impersonation is both needed and missing.

Rework `_impersonation_available()` so the module-level tri-state
`_IMPERSONATION_AVAILABLE` is written **only after a subprocess run completes**:

- Cache already set (`not None`) → return it.
- `_find_ytdlp_exe()` returns `None` → return `False`, leave the cache unset.
- `subprocess.run` raises, including `TimeoutExpired` → debug-log, return
  `False`, leave the cache unset.
- Run completed (any return code) → parse stdout, store the result, return it.

A completed run with a non-zero return code still caches. The run answered the
question; re-probing per playlist item would cost a subprocess each time for no
new information.

Callers become `_generic_argsets()` and the `_probe_info` warning path. A
YouTube-only run therefore spawns no impersonation subprocess at all, and a
single slow start no longer suppresses `--impersonate` for the rest of the run.

The existing stdout parser is unchanged: skip blank lines and lines starting
with `[`, `-`, or `Client`; any remaining line without `(unavailable)` means at
least one usable target. This survives ANSI colouring, since yt-dlp wraps the
whole `(unavailable)` token rather than splitting it.

### 5. Fallback depth (R3) — documentation only

The generic ladder stays at three rungs. The seven pre-edit rungs were not
seven retries: for a non-YouTube URL the `youtube:player_client` args are inert,
so the ladder issued the same request repeatedly. The real cushion for
transient failures is the outer `probe_max_outer` loop with its cooldown, plus
yt-dlp's own `--retries`/`--extractor-retries` from `_base_args`.

Add a comment in `_generic_argsets()` recording this, so the shorter ladder is
not later mistaken for an oversight. No behaviour change.

### 6. Log-line consistency (R5)

Once names are unique, `_media_pass` reverts its blind-attempt start line from
`_argset_label(override)` back to `client_name`, matching the failure and
debug lines beneath it. The manual edit switched to `_argset_label` because the
empty argset previously logged as a blank string; the `default` base name
removes that reason.

`_argset_label` is retained and still used in the `_probe_info` failure
warnings, where the full flag list aids debugging. The rule is: `client_name`
for "which rung is running" lines, `_argset_label` for failure diagnostics.

## Testing

Two new files, both reusing the `_load_yt2pass()` `SourceFileLoader` helper
already used by `tests/test_symlink_alias.py`. Each call to that helper returns
a freshly executed module, which gives every cache test clean module globals —
a shared fixture must therefore load per-test, not per-session.

### `tests/test_ytdlp_argsets.py` — pure functions, no mocking

| Behaviour under test | Concrete bug that makes it fail |
|---|---|
| Every rung name in the YouTube probe ladder is unique (`len(set(names)) == len(names)`) | R7 collision; R1's cookie-bearing `android` colliding with `android+nocookies` |
| Every rung name in the YouTube media ladder is unique | same, on the second ladder |
| Every rung name in the generic ladder is unique | `[]` and the cookieless rung both returning `default` |
| `_client_name_for_argset` returns `android+nocookies` for the cookieless rung and `android` for the cookie-bearing one | the `+nocookies` suffix rule dropped or inverted |
| ~~The last two YouTube probe rungs contain no `--no-cookies-from-browser`~~ | **WITHDRAWN — the shipped test asserts the exact opposite: every `android`/`ios` rung MUST contain `--no-cookies-from-browser`. See Correction.** |
| ~~The last two YouTube media rungs contain no `--no-cookies-from-browser`~~ | **WITHDRAWN — same inversion.** |
| ~~A cookieless `android` rung appears strictly before the cookie-bearing one~~ | **WITHDRAWN — no cookie-bearing rung exists.** |
| No rung in either ladder contains `--js-runtimes` | section 3 applied to only some rungs |
| Every YouTube `web`/`mweb` rung still contains `--remote-components ejs:github` | the ejs flag removed along with node |
| `_generic_argsets()` contains no `youtube:player_client` token | generic routing regressed to the YouTube ladder |
| `_is_youtube_url`: `youtube.com`, `www.youtube.com`, `music.youtube.com`, `youtu.be`, `youtube-nocookie.com`, and a bare video ID → `True` | subdomain or short-domain handling broken |
| `_is_youtube_url`: `vimeo.com`, `notyoutube.com`, `evil-youtube.com`, `youtube.com.evil.test` → `False` | substring rather than anchored host match, at either end |
| `_stderr_wants_impersonation`: `None` → `False`, `""` → `False`, exact phrase → `True`, upper-cased phrase → `True` | the `None` guard or the `.lower()` dropped |

`_base_args` node gating is tested by monkeypatching `shutil.which` on the
loaded module: truthy → `--js-runtimes node` present; `None` → absent.

### `tests/test_impersonation.py` — mocked `subprocess.run`

| Behaviour under test | Concrete bug that makes it fail |
|---|---|
| A table mixing available rows and `(unavailable)` rows → `True` | parser treats any `(unavailable)` as fatal |
| A table where every row says `(unavailable)` → `False` | parser inverted |
| `[info]` banner, `Client ...` header and `-----` rule are skipped | header row counted as an available target |
| `TimeoutExpired` → returns `False` **and** a second call re-invokes `subprocess.run` (`call_count == 2`) | R4 cache poisoning |
| Completed run → a second call does **not** re-invoke (`call_count == 1`) | caching silently disabled, one subprocess per playlist item |
| `_find_ytdlp_exe()` patched to `None` → `False`, and `subprocess.run` never called | probe runs without an executable |
| `_generic_argsets()` includes `--impersonate chrome` when available and omits it when not | asking yt-dlp for a target it cannot serve, which hard-errors |

Assertions check exact flag sequences and exact name strings, not truthiness.
No test asserts merely that a list is non-empty.

### Existing coverage

`tests/test_symlink_alias.py` stays as-is and must keep passing; it is the
regression guard for the restored `os.utime` stamp.

## Error handling

- **node absent** — flag omitted; yt-dlp behaves exactly as it does today.
- **yt-dlp absent** — `_ensure_ytdlp_available()` is already fatal earlier in
  `main()`, so `_impersonation_available()` cannot be reached without it. The
  `None` guard is defence in depth for direct calls from tests.
- **Impersonation probe times out** — that one call omits the impersonate rung
  and the cache stays unset, so the next call retries.
- **Impersonation genuinely unavailable** — `_generic_argsets()` omits the
  impersonate rung entirely rather than passing a target yt-dlp cannot serve,
  and `_probe_info` prints `_IMPERSONATION_FIX_HINT` once when an extractor
  actually demanded impersonation.

## Verification

- `pixi run test` — all tests green.
- `ruff` and `mypy` findings on `yt2pass/yt2pass` compared against the same
  tools run on `git show HEAD:yt2pass/yt2pass`, aggregated by rule and diffed.
  The diff must be empty; the file is excluded from enforcement, so absolute
  counts are meaningless and only the delta matters.
- `pixi run pre-commit run --all-files` before committing.
- `python -m py_compile` on the script, since it has no `.py` extension and is
  not otherwise imported by the default test run.
- File mode stays `100755`.

## Out of scope

- Reducing the 155 ruff / 64 mypy findings that predate this work.
- Any change to `batch-yt2pass`, `install.sh`, or `README.md`.
- Reworking the impersonation stdout parser beyond what R4 requires.
- Adding a `--impersonate` command-line option for the user; the current design
  only uses impersonation as an automatic generic-site fallback.
