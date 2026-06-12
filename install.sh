#!/usr/bin/env bash
#
# install.sh — Symlink yt2pass and batch-yt2pass onto your PATH.
#
# Modeled on the install logic from killett/utilities/clean-caches.sh.
#
# Usage:
#   ./install.sh                      Install (symlink into the best writable PATH dir).
#   ./install.sh --dry-run            Show what would happen; touch nothing.
#   ./install.sh --add-to-path        Non-interactive: append PATH-fix line without prompting.
#   ./install.sh --system             Install into /usr/local/bin (uses sudo unless root).
#   ./install.sh --help               Show usage.

set -euo pipefail

# Scripts shipped in this repo. Each is installed under its own name (no
# extension stripping) into the chosen PATH directory.
SCRIPTS=( yt2pass batch-yt2pass )

prog=${0##*/}

# Filled in by compute_path_fix.
PATH_FIX_KIND=""
PATH_FIX_FILE=""

err() { printf '%s: %s\n\n' "$prog" "$1" >&2; usage >&2; exit 2; }
die() { printf '%s: %s\n' "$prog" "$1" >&2; exit "${2:-1}"; }

usage() {
    cat <<EOF
Usage: $prog [OPTION]...

Symlink the yt2pass scripts (${SCRIPTS[*]}) into the best writable directory
on your PATH. If that directory is not already on PATH, you will be asked
whether to add it (interactive shells only; declined automatically when
non-interactive).

Options:
  -n, --dry-run     Show what would be installed and any PATH fix, then exit.
      --add-to-path Add the install dir to PATH without prompting (use this
                    for non-interactive runs such as CI).
      --system      Install into /usr/local/bin instead. Uses sudo unless
                    already running as root.
  -h, --help        Show this help and exit.
EOF
}

# --- Helpers (ported verbatim from clean-caches.sh) ------------------------

# Is $1 a directory currently on $PATH? (normalises trailing slashes)
dir_on_path() {
    local target="${1%/}" entry found=1 IFS=:
    set -f
    for entry in $PATH; do
        [[ -z "$entry" ]] && entry=.
        if [[ "${entry%/}" == "$target" ]]; then found=0; break; fi
    done
    set +f
    return "$found"
}

# Can we write into $1, creating it (and any missing parents) if needed?
dir_usable() {
    local d="$1" p
    if [[ -d "$d" ]]; then
        [[ -w "$d" ]]
    elif [[ -e "$d" ]]; then
        return 1
    else
        p="$d"
        while [[ ! -e "$p" ]]; do
            local parent; parent=$(dirname -- "$p")
            [[ "$parent" == "$p" ]] && break
            p="$parent"
        done
        [[ -d "$p" && -w "$p" ]]
    fi
}

compute_path_fix() {
    local shell_base
    shell_base=$(basename -- "${SHELL:-}" 2>/dev/null || true)
    case "$shell_base" in
        zsh)
            PATH_FIX_KIND="file"; PATH_FIX_FILE="$HOME/.zshrc" ;;
        bash)
            PATH_FIX_KIND="file"
            if [[ "$(uname -s 2>/dev/null || true)" == Darwin ]]; then
                PATH_FIX_FILE="$HOME/.bash_profile"
            else
                PATH_FIX_FILE="$HOME/.bashrc"
            fi ;;
        fish)
            PATH_FIX_KIND="fish"; PATH_FIX_FILE="" ;;
        *)
            PATH_FIX_KIND="unknown"; PATH_FIX_FILE="" ;;
    esac
}

warn_path() {
    printf '%s is not on your PATH. Add it (then restart your shell), e.g.:\n' "$1" >&2
    # shellcheck disable=SC2016
    printf '  echo '\''export PATH="%s:$PATH"'\'' >> ~/.zshrc   # zsh; ~/.bashrc for bash\n' "$1" >&2
    printf 'or re-run with --add-to-path to do it automatically.\n' >&2
}

write_path_entry() {
    local dir="$1" rcfile="$PATH_FIX_FILE"
    if [[ -f "$rcfile" ]] && grep -qF -- "\"$dir:" "$rcfile"; then
        printf 'PATH entry for %s already present in %s\n' "$dir" "$rcfile" >&2
    else
        {
            printf '\n# Added by %s\n' "$prog"
            # shellcheck disable=SC2016
            printf 'export PATH="%s:$PATH"\n' "$dir"
        } >> "$rcfile" || die "could not write to $rcfile"
        printf 'Added %s to PATH in %s\n' "$dir" "$rcfile" >&2
    fi
    printf 'Restart your shell or run:  source %s\n' "$rcfile" >&2
}

path_fix_dry() {
    local dir="$1"
    compute_path_fix
    case "$PATH_FIX_KIND" in
        file)
            if [[ "$add_to_path_flag" == true ]]; then
                printf 'Would add %s to PATH in %s\n' "$dir" "$PATH_FIX_FILE" >&2
            elif [[ -t 0 ]]; then
                printf 'Would ask whether to add %s to PATH in %s\n' "$dir" "$PATH_FIX_FILE" >&2
            else
                warn_path "$dir"
            fi ;;
        fish)
            printf 'Would suggest: fish_add_path %s\n' "$dir" >&2 ;;
        *)
            warn_path "$dir" ;;
    esac
}

handle_path() {
    local dir="$1" onp="$2" mode="$3" reply
    [[ "$onp" == true ]] && return 0
    if [[ "$mode" == dry ]]; then
        path_fix_dry "$dir"
        return 0
    fi
    compute_path_fix
    case "$PATH_FIX_KIND" in
        fish)
            printf 'To add %s to PATH in fish, run:  fish_add_path %s\n' "$dir" "$dir" >&2
            return 0 ;;
        unknown)
            warn_path "$dir"
            return 0 ;;
    esac
    if [[ "$add_to_path_flag" == true ]]; then
        write_path_entry "$dir"
    elif [[ -t 0 ]]; then
        printf 'Add %s to your PATH by editing %s? [y/N] ' "$dir" "$PATH_FIX_FILE" >&2
        read -r reply || reply=""
        case "$reply" in
            [Yy]|[Yy][Ee][Ss]) write_path_entry "$dir" ;;
            *) printf 'Left PATH unchanged. Re-run with --add-to-path to add it later.\n' >&2 ;;
        esac
    else
        warn_path "$dir"
    fi
}

# Directory containing this script (the repo root). Resolves one symlink hop
# (a prior install of this script), then canonicalises via pwd -P.
script_dir() {
    local src="$0" tgt dir
    if [[ "$src" != */* ]]; then
        local found; found=$(command -v -- "$src" 2>/dev/null || true)
        [[ -n "$found" ]] && src="$found"
    fi
    if [[ -L "$src" ]]; then
        tgt=$(readlink "$src" 2>/dev/null || true)
        case "$tgt" in
            /*) src="$tgt" ;;
            ?*) src="$(dirname -- "$src")/$tgt" ;;
        esac
    fi
    dir=$(cd -P -- "$(dirname -- "$src")" 2>/dev/null && pwd -P) || return 1
    printf '%s\n' "$dir"
}

# Pick the best writable directory for installation, plus whether it's on PATH.
# Echoes "dir|on_path" where on_path is 'true' or 'false'.
pick_install_dir() {
    local on_path=false chosen="" dir
    local -a candidates=()

    if [[ "$system_flag" == true ]]; then
        chosen="/usr/local/bin"
        on_path=true; dir_on_path "$chosen" || on_path=false
        printf '%s|%s\n' "$chosen" "$on_path"
        return 0
    fi

    local os; os=$(uname -s 2>/dev/null || echo unknown)
    if [[ "$(id -u)" -eq 0 ]]; then
        candidates+=(/usr/local/bin /usr/bin)
    else
        [[ -n "${HOME:-}" ]] && candidates+=("$HOME/.local/bin" "$HOME/bin")
        case "$os" in
            Darwin) candidates+=(/opt/homebrew/bin /usr/local/bin) ;;
            *)      candidates+=(/usr/local/bin) ;;
        esac
    fi
    [[ ${#candidates[@]} -gt 0 ]] || die "no candidate install directories for this system."

    # Prefer a dir that's already on PATH and writable.
    for dir in "${candidates[@]}"; do
        if dir_on_path "$dir" && dir_usable "$dir"; then chosen="$dir"; on_path=true; break; fi
    done
    if [[ -z "$chosen" ]]; then
        for dir in "${candidates[@]}"; do
            if dir_usable "$dir"; then chosen="$dir"; on_path=false; break; fi
        done
    fi
    if [[ -z "$chosen" ]]; then
        printf '%s: no writable install directory found. Tried:\n' "$prog" >&2
        printf '  %s\n' "${candidates[@]}" >&2
        die "create one (e.g. mkdir -p ~/.local/bin), put it on PATH, or use --system."
    fi
    printf '%s|%s\n' "$chosen" "$on_path"
}

# Install ONE script. Returns 0 on success, 1 on per-script failure.
install_one() {
    local name="$1" chosen="$2" sudo_prefix="$3" mode="$4"
    local repo_dir script_path link_path

    repo_dir=$(script_dir) || die "cannot determine script directory."
    script_path="$repo_dir/$name"
    [[ -f "$script_path" ]] || { printf '%s: missing script: %s\n' "$prog" "$script_path" >&2; return 1; }

    link_path="$chosen/$name"

    if [[ -L "$link_path" ]]; then
        local cur; cur=$(readlink "$link_path" 2>/dev/null || true)
        if [[ "$cur" == "$script_path" ]]; then
            printf 'Already installed: %s -> %s\n' "$link_path" "$script_path" >&2
            return 0
        fi
        printf '%s: %s already exists (link to %s); remove it or install elsewhere.\n' \
            "$prog" "$link_path" "$cur" >&2
        return 1
    elif [[ -e "$link_path" ]]; then
        printf '%s: %s already exists and is not a symlink; refusing to overwrite.\n' \
            "$prog" "$link_path" >&2
        return 1
    fi

    if [[ "$mode" == dry ]]; then
        if [[ -n "$sudo_prefix" ]]; then
            printf 'Would install (with sudo): %s -> %s\n' "$link_path" "$script_path" >&2
        else
            printf 'Would install: %s -> %s\n' "$link_path" "$script_path" >&2
        fi
        return 0
    fi

    if [[ ! -d "$chosen" ]]; then
        $sudo_prefix mkdir -p -- "$chosen" || { printf '%s: could not create %s\n' "$prog" "$chosen" >&2; return 1; }
    fi
    if [[ ! -x "$script_path" ]]; then
        chmod +x -- "$script_path" 2>/dev/null \
            || printf '%s: note: could not chmod +x %s; do so manually if needed.\n' "$prog" "$script_path" >&2
    fi
    $sudo_prefix ln -s -- "$script_path" "$link_path" \
        || { printf '%s: failed to create symlink %s\n' "$prog" "$link_path" >&2; return 1; }
    printf 'Installed: %s -> %s\n' "$link_path" "$script_path" >&2
    return 0
}

install_all() {
    local mode="apply"; [[ "$dry_run" == true ]] && mode="dry"

    local pick chosen on_path sudo_prefix=""
    pick=$(pick_install_dir)
    chosen="${pick%|*}"
    on_path="${pick##*|}"

    if [[ "$system_flag" == true && "$(id -u)" -ne 0 ]]; then
        if command -v sudo >/dev/null 2>&1; then
            sudo_prefix="sudo"
        else
            die "--system needs sudo (not found) or running as root."
        fi
    fi

    local any_fail=false name
    for name in "${SCRIPTS[@]}"; do
        if ! install_one "$name" "$chosen" "$sudo_prefix" "$mode"; then
            any_fail=true
        fi
    done

    handle_path "$chosen" "$on_path" "$mode"

    if [[ "$any_fail" == true ]]; then
        return 1
    fi
    return 0
}

# --- Argument parsing ------------------------------------------------------

dry_run=false
add_to_path_flag=false
system_flag=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        -n|--dry-run)   dry_run=true ;;
        --add-to-path)  add_to_path_flag=true ;;
        --system)       system_flag=true ;;
        -h|--help)      usage; exit 0 ;;
        --)             shift; break ;;
        -*)             err "unknown option: $1" ;;
        *)              err "unexpected positional argument: $1" ;;
    esac
    shift
done
if [[ $# -gt 0 ]]; then
    err "unexpected positional argument: $1"
fi

install_all
