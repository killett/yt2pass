# yt2pass

`yt-dlp` will silently produce a video file with no subtitles when YouTube rate-limits the subtitle download — you won't get an error, you'll just get a video without subs. `yt2pass` fixes that by doing subtitles first (with patient retries and configurable cooldowns) and only downloading the media once all required subtitle files exist on disk.

## Table of Contents

- [Quickstart](#quickstart)
- [What it does](#what-it-does)
- [Installation](#installation)
- [Usage](#usage)
- [Command cheatsheet](#command-cheatsheet)
- [Subtitle modes explained](#subtitle-modes-explained)
- [Configuration notes](#configuration-notes)
- [Troubleshooting](#troubleshooting)
- [Exit codes](#exit-codes)
- [`batch-yt2pass` output files](#batch-yt2pass-output-files)
- [License](#license)

## Quickstart

```bash
git clone https://github.com/killett/yt2pass.git && cd yt2pass && ./install.sh
yt2pass 'https://youtu.be/VIDEOID'
```

## What it does

`yt-dlp` is a command-line program for downloading videos from YouTube and hundreds of other sites. It handles format selection, subtitle fetching, merging audio and video streams, and embedding subtitles into the output container. Most people use it and it mostly works.

The problem surfaces with subtitles. YouTube will return an HTTP 429 (Too Many Requests) when you ask for subtitle files too quickly — and `yt-dlp` will log the error and continue, producing an MKV with no subtitles. There is also a distinction between human-made subtitles (uploaded by the creator or a professional) and automatically generated captions (machine-generated, often lower quality), and the two are accessed through different mechanisms. Some formats require a PO token (a short-lived credential tied to your browser session) to be fetched at all; YouTube's SABR streaming format has introduced additional instability since 2024.

`yt2pass` solves this with a two-pass approach. Pass 1 probes the video metadata, identifies which subtitle tracks are actually present, and then retries the subtitle download with configurable cooldowns until all required `.srt` files are on disk. Only then does Pass 2 run, downloading the media and embedding the already-confirmed subtitles into the final MKV. If the subtitles cannot be retrieved after the configured number of tries, `yt2pass` stops before downloading any media, so you never end up with a large video file that is silently missing captions.

## Installation

### Prerequisites

#### yt-dlp

`yt2pass` requires `yt-dlp`. Install it with `pipx` so it lives in its own isolated Python environment and is easy to upgrade:

```bash
# 0) Make sure ~/.local/bin is first on PATH for this session and future logins
export PATH="$HOME/.local/bin:$PATH"
grep -q 'export PATH="$HOME/.local/bin:$PATH"' ~/.profile || \
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.profile

# 1) Install pipx
sudo apt-get update
sudo apt-get install -y pipx
pipx ensurepath   # ok to ignore the "restart shell" hint for now

# 2) Install yt-dlp (nightly / pre-release) via pipx and FORCE re-link the shim
pipx install --force --pip-args="--pre" yt-dlp

# 3) Add the impersonation dependency inside THAT venv
pipx runpip yt-dlp install --upgrade "curl_cffi>=0.6.0"
pipx runpip yt-dlp install -U "yt-dlp[default]"

# 4) (Recommended) Install a JS runtime so yt-dlp can solve YouTube's JS challenges
sudo apt-get install -y nodejs

# 5) Verify the right binary is being used and the shim points to the venv
command -v yt-dlp
readlink -f ~/.local/bin/yt-dlp
~/.local/share/pipx/venvs/yt-dlp/bin/yt-dlp -v --ignore-config --version

# You should see in the verbose header:
#   Optional libraries: ... curl_cffi ...
#   JS runtimes: node

TO UPGRADE:
pipx upgrade --pip-args="--pre" yt-dlp

TO INSTALL aria2c (optional downloader):
sudo apt-get update
sudo apt-get install -y aria2
```

To upgrade `yt-dlp` later:

```bash
pipx upgrade --pip-args="--pre" yt-dlp
```

#### ffmpeg

`ffmpeg` is required to convert `.vtt` subtitle files to `.srt` and to embed subtitles into the output MKV. Without it, subtitles may be downloaded as `.vtt` files but will not be embedded.

```bash
# Debian / Ubuntu
sudo apt-get install -y ffmpeg

# macOS (Homebrew)
brew install ffmpeg
```

#### nodejs

A JavaScript runtime lets `yt-dlp` solve YouTube's JS challenges inline. Strongly recommended.

```bash
# Debian / Ubuntu
sudo apt-get install -y nodejs

# macOS (Homebrew)
brew install node
```

#### aria2c (optional)

Only needed if you use the `--aria` flag for multi-connection downloads.

```bash
# Debian / Ubuntu
sudo apt-get install -y aria2

# macOS (Homebrew)
brew install aria2
```

### Install yt2pass

```bash
git clone https://github.com/killett/yt2pass.git
cd yt2pass
./install.sh
```

`install.sh` creates symlinks to `yt2pass` and `batch-yt2pass` in the best writable directory on your `PATH` (defaulting to `~/.local/bin`). Useful flags:

| Flag | Effect |
|---|---|
| `--dry-run` | Print what would be linked without touching anything |
| `--system` | Install into `/usr/local/bin` (uses `sudo` if needed) |
| `--add-to-path` | Automatically append the `PATH` fix to your shell rc without prompting |

### Manual install (alternative)

If you prefer not to run the installer script:

```bash
ln -s "$PWD/yt2pass" ~/.local/bin/yt2pass
ln -s "$PWD/batch-yt2pass" ~/.local/bin/batch-yt2pass
```

Make sure `~/.local/bin` is on your `PATH`. The symlinks resolve to the actual scripts inside the repository, so `git pull` updates take effect immediately.

## Usage

### Single video

```bash
# Download with default subtitle languages (en, fr, orig)
yt2pass 'https://youtu.be/VIDEOID'

# Download with specific subtitle languages
yt2pass --langs en,fr,ja 'https://youtu.be/VIDEOID'

# Require auto-generated captions too, strictly
yt2pass --auto --strict --langs en,orig 'https://youtu.be/VIDEOID'
```

Each run produces a single MKV file in the current directory named after the video title, uploader, and video ID. See [Configuration notes](#configuration-notes) for the filename pattern.

### Playlist

Pass a playlist URL the same way as a single video URL. `yt2pass` iterates the playlist entries in order. If an output MKV already exists for a given video ID, that item is skipped (resume behavior). Filenames include a playlist index prefix when `yt-dlp` provides one.

### Batch from a text file

Use `batch-yt2pass` to process a list of URLs from a text file. The file can be any text (prose, notes, exported bookmarks) — URLs are extracted by regex and deduplicated before processing.

```bash
batch-yt2pass my-watchlist.txt
```

`batch-yt2pass` reads the input file once before starting. It does not live-reread the file during a run; add new URLs to a separate file and start a new `batch-yt2pass` invocation for them. Three output files are written to the current directory as items complete:

- `<stamp>-yt2pass-successes-<base>` — one URL per line for each successful download
- `<stamp>-yt2pass-failures-<base>` — failed URLs with the captured stdout/stderr from `yt2pass`
- `<stamp>-yt2pass-retry-<base>` — failed URLs only (no output), suitable to re-feed directly to `batch-yt2pass`

### Hotkeys during download (POSIX only)

While `yt2pass` is running in a terminal on Linux or macOS, you can press:

| Key | Action |
|---|---|
| `q`, `n`, `Esc` | Cancel the current download |
| `p` | Pause `yt-dlp` (sends SIGSTOP) |
| `r` | Resume `yt-dlp` (sends SIGCONT) |

These hotkeys are not available on Windows.

## Command cheatsheet

### yt2pass

| Flag | Default | What it does |
|---|---|---|
| `-v`, `--version` | — | Print version and exit |
| `-d`, `--debug` | false | Enable debug logging |
| `--langs` | `en,fr,orig` | Comma-separated subtitle language codes to fetch. `orig` means the video's original language |
| `--print-langs` | — | Print all known language codes and names, then exit |
| `--cooldown-between-passes` | 90 | Seconds to sleep between the subtitle pass and the media pass |
| `--cooldown-between-tries` | 180 | Seconds to sleep between subtitle retry attempts |
| `--max-tries` | 5 | Maximum subtitle attempts before failing hard |
| `--rate-limit` | 0 | Download rate cap in kB/s; 0 means no limit |
| `--nosubs` | false | Skip the subtitle pass entirely (still embeds any existing `.srt` files) |
| `--onlysubs` | false | Download subtitles only, then exit without fetching media |
| `--auto` | false | Also consider auto-generated captions, not just human-made subtitles |
| `--strict` | false | Treat all requested subtitle languages as hard requirements; use very long exponential backoff on 429s |
| `--720p` | false | Prefer 720p video quality when choosing formats |
| `--smallest` | false | Prefer the smallest available resolution |
| `--go-low` | false | Allow download when only the low-quality `mp4-low` format is available |
| `--po-token` | `$YT_PO_TOKEN` | YouTube PO token in `CLIENT.CONTEXT+TOKEN` format |
| `--aria` | false | Use `aria2c` as an external downloader for improved performance |
| `url` | — | Video or playlist URL (omit to check `yt-dlp` status and exit) |
| `extra` | — | Additional arguments forwarded verbatim to `yt-dlp` (rarely needed) |

`--720p` and `--smallest` cannot be used together.

### batch-yt2pass

| Flag | Default | What it does |
|---|---|---|
| `file` | — | Input text file to scan for `http`/`https` URLs |
| `-d`, `--debug` | false | Enable debug logging |
| `-v`, `--version` | — | Print version and exit |

## Subtitle modes explained

| Mode | Human subs | Auto subs | On 429 with missing subs |
|---|---|---|---|
| default | Required if available, else skipped | Ignored | Retry up to `--max-tries`, then proceed |
| `--auto` | Required if available | Best-effort; `orig` auto-track also required | Retry; persistent 429 → skip with warning |
| `--auto --strict` | Required | Required (including translated tracks) | Very long exponential backoff; fail if still missing after max tries |

"Required" means `yt2pass` will not proceed to the media pass unless those subtitles exist on disk. "Best-effort" means `yt2pass` retries but will proceed even if those subtitles could not be retrieved.

## Configuration notes

### Firefox cookies

`yt2pass` always passes `--cookies-from-browser firefox` to `yt-dlp`. This is hardcoded in `_base_args` (`yt2pass:535`). You must have Firefox installed on your system and be logged into YouTube in Firefox for cookie-dependent formats to work. Future versions may expose this as a command-line flag; for now, Firefox is the only supported browser.

### PO tokens

Some YouTube content requires a PO token (a session credential tied to your browser). You can supply one via the `--po-token` flag or by setting the `YT_PO_TOKEN` environment variable. The format is `CLIENT.CONTEXT+TOKEN`. PO tokens are short-lived; regenerate one from your browser if downloads start failing with format-availability errors.

### Filename pattern

Downloaded files are named using the `yt-dlp` output template:

```text
%(title)s - %(uploader)s - ID %(id)s.%(ext)s
```

This is not currently configurable from the command line.

### yt-dlp auto-update

`yt2pass` attempts to update `yt-dlp` at most once per 24 hours (via `pipx upgrade` or `--update-to nightly` depending on your install method). The timestamp of the last update attempt is stored in `~/.cache/yt2pass/` on Linux/macOS or `%LOCALAPPDATA%\yt2pass\` on Windows.

## Troubleshooting

### yt-dlp is not installed or not on PATH

`yt2pass` will print installation instructions and exit with code 2 if `yt-dlp` is not found. Follow the pipx install dance in the [Prerequisites](#prerequisites) section above. Make sure `~/.local/bin` is on your `PATH` before running `yt2pass`.

### HTTP 429 storms

YouTube rate-limits subtitle downloads more aggressively than video downloads. If you are seeing repeated 429 errors, try adding `--strict` to force longer exponential backoffs (combined with `--auto` if you need auto-generated captions). You can also increase `--max-tries` beyond the default of 5 and raise `--cooldown-between-tries` above 180 seconds. Expect waits of several minutes per retry in worst cases.

### Only mp4-low available

If `yt-dlp` can only see the low-quality `mp4-low` format — a transient condition that often resolves after a few hours — `yt2pass` will treat it as an error by default and retry. If you want to proceed anyway (for example, to grab a lower-quality copy now), pass `--go-low`.

### Subs come out as .vtt instead of .srt

`ffmpeg` is required for the `.vtt` to `.srt` conversion and for embedding subtitles into MKV. Install it with `sudo apt-get install -y ffmpeg` (Linux) or `brew install ffmpeg` (macOS) and re-run.

### Terminal is weird after Ctrl-C

`yt2pass` tries to restore terminal state on exit, but if that fails (for example, if you kill it with `kill -9`), your terminal may be left in raw mode. Run `reset` or `stty sane` to recover.

### aria2c was requested but disabled

If `yt2pass` reports that `aria2c` is not available, either install it (`sudo apt-get install -y aria2` / `brew install aria2`) or remove the `--aria` flag from your command.

### Cookies / SABR / why Firefox?

YouTube restricts certain formats and subtitle tracks to authenticated sessions. `yt-dlp` can read cookies directly from your browser's profile, and `yt2pass` hardcodes Firefox as the source. If you do not have Firefox installed or are not logged into YouTube in Firefox, you may see 403 errors or be offered only low-quality or format-stripped results. SABR (YouTube's newer streaming format, introduced in 2024) can behave differently from the older `/videoplayback` endpoint; keeping `yt-dlp` up to date (via the auto-update or `pipx upgrade`) is the most reliable mitigation.

### Playlist item was skipped — how do I force re-download?

`yt2pass` uses `yt-dlp`'s `--no-overwrites` flag, so any video whose output MKV already exists in the current directory is skipped. To force a re-download, delete the existing MKV file whose name contains the video ID, then re-run `yt2pass` with the same playlist URL.

### Batch run created a `*-retry-*` file — what do I do with it?

Feed it back to `batch-yt2pass`:

```bash
batch-yt2pass <stamp>-yt2pass-retry-<original-file>
```

The retry file contains only the URLs that failed in the previous run, one per line. Running `batch-yt2pass` on it will attempt those downloads again and produce a fresh set of success/failure/retry output files.

## Exit codes

| Code | Source | Meaning |
|---|---|---|
| 0 | — | All requested work completed successfully |
| 1 | `batch-yt2pass` | At least one URL in the batch failed |
| 2 | `yt2pass` | `yt-dlp` missing, `--720p`+`--smallest` conflict, or invalid filename pattern |
| 3 | `yt2pass` | Probe failed or playlist had no entries |
| 126 | `batch-yt2pass` | Could not exec `yt2pass` |
| 127 | `batch-yt2pass` | `yt2pass` not found on PATH |
| 130 | `yt2pass` | KeyboardInterrupt / cancel key pressed |
| non-zero | `yt2pass` | `yt-dlp` returned non-zero for an individual item (passed through) |

## `batch-yt2pass` output files

When `batch-yt2pass` finishes, three files are written in the current directory. `<stamp>` is a timestamp prefix and `<base>` is derived from the input filename.

- `<stamp>-yt2pass-successes-<base>` — one line per URL that downloaded successfully
- `<stamp>-yt2pass-failures-<base>` — one entry per failed URL, with the captured stdout and stderr from the `yt2pass` invocation embedded inline, so you can read the error without re-running
- `<stamp>-yt2pass-retry-<base>` — failed URLs only, no diagnostic output, suitable to pass directly to `batch-yt2pass` for a retry run

These files are written incrementally as each item completes, not at the end of the run. If you interrupt a batch, the files up to that point are intact and the retry file can be used to resume.

## License

This project is released under the terms in the `LICENSE` file at the root of the repository.
