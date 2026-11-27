#!/bin/bash
# install-macos.sh: install Via's toolchain on macOS, for your own user.
#
# Usage:
#   ./install-macos.sh            install or update every engine, then run `workcenter doctor`
#   ./install-macos.sh --dry-run  print every step and every command; run none, write nothing
#   ./install-macos.sh --yes      answer yes to the questions (sudo, when a step needs it)
#   ./install-macos.sh --check    run `workcenter doctor` only
#
# Written for the bash macOS ships (3.2) and its own tools (shasum, hdiutil, ditto, plutil).
# Apple Silicon is the target; an Intel Mac is best effort. Every address and checksum comes from
# toolchain/desktop.json. Each step skips work already done, so the script is safe to run again.
#
# Environment overrides:
#   WORKCENTER_ROOT   install root     (default ~/Library/Application Support/via)
#   WORKCENTER_LINK   the command      (default ~/.local/bin/workcenter)
#   KICAD_DIR         KiCad's folder   (default /Applications/KiCad)

DRY=0
YES=0
CHECK=0
STEPS=8

case "${BASH_SOURCE[0]}" in
  */*) SRC_DIR="${BASH_SOURCE[0]%/*}" ;;
  *) SRC_DIR="." ;;
esac
SRC_DIR="$(cd "$SRC_DIR" && pwd)"
PINS="${SRC_DIR}/toolchain/desktop.json"
ROOT="${WORKCENTER_ROOT:-${HOME}/Library/Application Support/via}"
LINK="${WORKCENTER_LINK:-${HOME}/.local/bin/workcenter}"
KICAD_DIR="${KICAD_DIR:-/Applications/KiCad}"
BREW_PREFIX=""
ARCH=""
JAVA_KEY=""
MNT=""
MARK="# Via (install-macos.sh)"

usage() {
  printf '%s\n' "Usage: ./install-macos.sh [--dry-run] [--yes] [--check]" \
    "  --dry-run  print every step and every command; run none, write nothing" \
    "  --yes      answer yes to the questions (sudo, when a step needs it)" \
    "  --check    run \`workcenter doctor\` only" \
    "  -h, --help this text"
}

say() { printf '[via] %s\n' "$*"; }
die() {
  printf '[via] ERROR: %s\n' "$*" >&2
  exit 1
}

# 1 step's first line: its number, its name, what it does.
header() { say "step $1/${STEPS}: $2: $3"; }

# A command as a shell reads it: each word quoted where it needs it (the root's path holds a blank).
quoted() {
  local out="" a
  for a in "$@"; do
    out="${out}${out:+ }$(printf '%q' "$a")"
  done
  printf '%s\n' "$out"
}

# Runs a command, after printing it; a dry run prints it only.
run() {
  if [ "$DRY" = 1 ]; then
    say "would run: $(quoted "$@")"
    return 0
  fi
  say "run: $(quoted "$@")"
  "$@"
}

# Writes a file (its text is the second argument), after naming it; a dry run names it only.
write_file() {
  if [ "$DRY" = 1 ]; then
    say "would write: $1"
    return 0
  fi
  say "write: $1"
  printf '%s\n' "$2" > "$1"
}

# 1 value of toolchain/desktop.json by its dotted key: macOS's plutil, else python3 (Linux, for tests).
pin() {
  local v=""
  if command -v plutil > /dev/null 2>&1; then
    v="$(plutil -extract "$1" raw -o - "$PINS" 2> /dev/null)" || v=""
  else
    v="$(python3 -c 'import json, sys
d = json.load(open(sys.argv[1]))
for k in sys.argv[2].split("."):
    d = d[k]
print(d)' "$PINS" "$1" 2> /dev/null)" || v=""
  fi
  if [ -z "$v" ]; then
    die "toolchain/desktop.json names no ${1}"
  fi
  printf '%s\n' "$v"
}

# A step that needs sudo says so and asks first; --yes answers yes; with no terminal and no --yes the
# run stops and says how to go on.
as_admin() {
  local why="$1" answer=""
  shift
  say "this step needs sudo to ${why}: sudo $(quoted "$@")"
  if [ "$DRY" = 1 ]; then
    say "would ask first, then run: sudo $(quoted "$@")"
    return 0
  fi
  if [ "$YES" != 1 ]; then
    if [ ! -t 0 ]; then
      die "no terminal to ask on: run ./install-macos.sh in a terminal, or pass --yes to let it run sudo"
    fi
    read -r -p "[via] Run it now? [y/N] " answer
    case "$answer" in
      y | Y | yes | YES) ;;
      *) die "stopped: sudo was not allowed. Nothing was copied." ;;
    esac
  fi
  run sudo "$@"
}

sha_of() {
  local got
  got="$(shasum -a 256 "$1")"
  printf '%s\n' "${got%% *}"
}

check_sha() {
  local got
  got="$(sha_of "$1")"
  if [ "$got" != "$2" ]; then
    die "checksum mismatch for ${1}: expected ${2}, got ${got}"
  fi
}

# Downloads a pinned file to dest and checks its SHA256; a file already there with that SHA256 is kept.
# The mirror (may be empty) is tried when the first address fails.
fetch() {
  local url="$1" mirror="$2" sha="$3" bytes="$4" dest="$5" got
  if [ "$DRY" != 1 ] && [ -s "$dest" ] && [ "$(sha_of "$dest")" = "$sha" ]; then
    say "already downloaded: ${dest} (SHA256 ${sha})"
    return 0
  fi
  run mkdir -p "${dest%/*}"
  say "download: ${url} (${bytes} bytes)"
  if ! run curl -fL --retry 3 --connect-timeout 20 -C - -o "${dest}.part" "$url"; then
    if [ -z "$mirror" ]; then
      die "download failed: ${url}. Run the script again; it goes on where it stopped."
    fi
    run rm -f "${dest}.part"
    run curl -fL --retry 3 --connect-timeout 20 -o "${dest}.part" "$mirror" \
      || die "download failed from both ${url} and ${mirror}. Run the script again."
  fi
  if [ "$DRY" = 1 ]; then
    say "would check: shasum -a 256 ${dest}.part is ${sha}"
    run mv "${dest}.part" "$dest"
    return 0
  fi
  got="$(sha_of "${dest}.part")"
  if [ "$got" != "$sha" ]; then
    rm -f "${dest}.part"
    die "checksum mismatch for ${url}: expected ${sha}, got ${got}. The file was removed; run the script again."
  fi
  say "checksum ok: ${sha}"
  run mv "${dest}.part" "$dest"
}

preflight() {
  local system v major min brew_min kver pyver translated
  system="$(uname -s)"
  ARCH="$(uname -m)"
  if [ "$system" != Darwin ]; then
    if [ "$DRY" != 1 ]; then
      die "install-macos.sh is for macOS; this is ${system}. On Ubuntu 24.04 run: sudo ./install.sh"
    fi
    say "dry run on ${system}: the steps a Mac would run"
  fi
  if [ ! -f "$PINS" ]; then
    die "no pins file at ${PINS}: run the script from a checkout of Via"
  fi
  min="$(pin kicad.macos.min_macos)"
  brew_min="$(pin homebrew.min_macos)"
  kver="$(pin kicad.version)"
  pyver="$(pin python.version)"
  if command -v sw_vers > /dev/null 2>&1; then
    v="$(sw_vers -productVersion)"
    major="${v%%.*}"
    if [ "$major" -lt "$min" ] 2> /dev/null; then
      if [ "$DRY" != 1 ]; then
        die "this is macOS ${v}; KiCad ${kver} needs macOS ${min} or newer"
      fi
      say "the real run stops here: this is macOS ${v}; KiCad needs macOS ${min} or newer"
    elif [ "$major" -lt "$brew_min" ] 2> /dev/null; then
      say "this is macOS ${v}: Homebrew supports macOS ${brew_min} and newer, so Python ${pyver} builds from source here, which is slow and may fail."
    fi
  fi
  case "$ARCH" in
    arm64) JAVA_KEY="macos_arm64" ;;
    x86_64)
      translated="$(sysctl -n sysctl.proc_translated 2> /dev/null || printf '0')"
      if [ "$translated" = 1 ]; then
        if [ "$DRY" != 1 ]; then
          die "this shell runs under Rosetta on an Apple Silicon Mac: open Terminal without Rosetta and run the script again"
        fi
        say "the real run stops here: this shell runs under Rosetta"
      fi
      say "Intel Mac: best effort; Via targets Apple Silicon. It needs a Homebrew already installed: Homebrew's installer no longer supports Intel, and Python ${pyver} builds from source."
      JAVA_KEY="macos_x64"
      ;;
    *) die "unknown processor ${ARCH}: Via installs on arm64 (Apple Silicon) and x86_64 (Intel)" ;;
  esac
  say "Via for macOS. Root: ${ROOT}. Command: ${LINK}. KiCad: ${KICAD_DIR}."
  say "${STEPS} steps: Homebrew, Python and ngspice from it, KiCad, Java, FreeRouting, the venv, the command, doctor."
  say "Nothing here runs sudo, unless ${KICAD_DIR%/*} is not writable for you: then it asks first."
}

step_brew() {
  local pyver install
  pyver="$(pin python.version)"
  install="$(pin homebrew.install)"
  header 1 Homebrew "find brew; Python ${pyver} and ngspice come from it"
  if command -v brew > /dev/null 2>&1; then
    :
  elif [ -x /opt/homebrew/bin/brew ]; then
    PATH="/opt/homebrew/bin:${PATH}"
  elif [ -x /usr/local/bin/brew ]; then
    PATH="/usr/local/bin:${PATH}"
  elif [ "$ARCH" != arm64 ]; then
    # Homebrew's own installer aborts on an Intel Mac: never send the user to it.
    if [ "$DRY" != 1 ]; then
      die "Homebrew is not installed, and on an Intel Mac Via cannot install it: Homebrew's installer no longer supports Intel. Via needs a Homebrew already installed there."
    fi
    say "dry run: the real run stops here: Homebrew is not installed, and Homebrew's installer no longer supports Intel"
    BREW_PREFIX="/usr/local"
    return 0
  else
    say "Homebrew is not installed. Install it with this 1 command, then run ./install-macos.sh again:"
    printf '  %s\n' "$install"
    if [ "$DRY" != 1 ]; then
      exit 1
    fi
    say "dry run: the real run stops here until Homebrew is installed"
    if [ "$ARCH" = arm64 ]; then BREW_PREFIX="/opt/homebrew"; else BREW_PREFIX="/usr/local"; fi
    return 0
  fi
  BREW_PREFIX="$(brew --prefix)"
  say "Homebrew at ${BREW_PREFIX}"
  if [ "$EUID" = 0 ]; then
    if [ "$DRY" != 1 ]; then
      die "run ./install-macos.sh as your own user, not as root: Homebrew refuses root, and the root folder is under your home. The script asks for sudo when a step needs it."
    fi
    say "the real run stops here: it runs as your own user, not as root"
  fi
}

# Homebrew installs the ngspice it has today, not the pin: say which one it is, and warn when it differs.
check_ngspice() {
  local formula="$1" want got
  want="$(pin ngspice.version)"
  if [ "$DRY" = 1 ]; then
    say "would check: brew list --versions ${formula} names ${want}"
    return 0
  fi
  got="$(brew list --versions "$formula" 2> /dev/null || true)"
  got="${got#"${formula}" }"
  got="${got%% *}"
  if [ "$got" = "$want" ]; then
    say "ngspice ${got} from Homebrew, as pinned"
  else
    say "WARNING: Homebrew installed ngspice ${got:-of no version it names}; Via pins ${want}. The simulations may differ."
  fi
}

step_formulae() {
  local pyf ngf pyver
  pyf="$(pin python.macos_formula)"
  ngf="$(pin ngspice.macos_formula)"
  pyver="$(pin python.version)"
  header 2 "Python ${pyver} and ngspice" "brew installs ${pyf} and ${ngf}, then checks ngspice's version against the pin; one already there is kept"
  run brew install "$pyf" "$ngf"
  PY312="${BREW_PREFIX}/opt/${pyf}/bin/python${pyver}"
  if [ "$DRY" != 1 ]; then
    [ -x "$PY312" ] || die "no ${PY312} after brew install ${pyf}"
    [ -x "${BREW_PREFIX}/bin/ngspice" ] || die "no ${BREW_PREFIX}/bin/ngspice after brew install ${ngf}"
  fi
  check_ngspice "$ngf"
}

kicad_cli() { printf '%s\n' "${KICAD_DIR}/KiCad.app/Contents/MacOS/kicad-cli"; }

# Whether you may write in a folder: the 1 test of it, in a real run and in a dry run alike.
can_write() { [ -w "$1" ]; }

# The nearest folder that exists, from a path that may not exist yet.
nearest_dir() {
  local d="$1"
  while [ ! -d "$d" ]; do
    case "$d" in
      */*) d="${d%/*}" ;;
      *) d="." ;;
    esac
    [ -n "$d" ] || d="/"
  done
  printf '%s\n' "$d"
}

# Detaches the KiCad DMG and removes its mount folder. It is the EXIT trap while the DMG is mounted,
# so a stop at any point after the mount leaves nothing mounted.
detach_dmg() {
  if [ -n "$MNT" ]; then
    say "run: $(quoted hdiutil detach "$MNT")"
    hdiutil detach "$MNT" > /dev/null 2>&1 || true
    rmdir "$MNT" 2> /dev/null || true
    MNT=""
  fi
}

# Copies KiCad's folder from the mounted DMG to KICAD_DIR. A folder under your home is yours: it is
# made with mkdir -p, never with sudo. Elsewhere sudo is asked for only when the nearest folder that
# exists is not writable for you.
place_kicad() {
  local from="$1" parent="${KICAD_DIR%/*}"
  case "${parent}/" in
    "${HOME}/"*)
      run mkdir -p "$parent" || return 1
      run ditto "$from" "$KICAD_DIR" || return 1
      return 0
      ;;
  esac
  if can_write "$(nearest_dir "$parent")"; then
    run mkdir -p "$parent" || return 1
    run ditto "$from" "$KICAD_DIR" || return 1
  else
    as_admin "copy KiCad into ${parent}" ditto "$from" "$KICAD_DIR" || return 1
  fi
}

step_kicad() {
  local ver cli have="" dmg mnt folder file url mirror sha bytes
  ver="$(pin kicad.version)"
  cli="$(kicad_cli)"
  folder="$(pin kicad.macos.folder)"
  file="$(pin kicad.macos.file)"
  url="$(pin kicad.macos.url)"
  mirror="$(pin kicad.macos.mirror)"
  sha="$(pin kicad.macos.sha256)"
  bytes="$(pin kicad.macos.bytes)"
  header 3 KiCad "KiCad ${ver} from its pinned DMG, checked by SHA256, copied to ${KICAD_DIR}"
  if [ "$DRY" != 1 ] && [ -x "$cli" ]; then
    have="$("$cli" version 2> /dev/null || true)"
    if [ "$have" = "$ver" ]; then
      say "KiCad ${have} is already at ${KICAD_DIR}"
      return 0
    fi
  fi
  if [ "$DRY" != 1 ] && [ -e "$KICAD_DIR" ]; then
    die "${KICAD_DIR} holds another KiCad (${have:-no kicad-cli that answers}). Install KiCad ${ver} beside it, with no sudo: KICAD_DIR=\"\$HOME/Applications/KiCad\" ./install-macos.sh. The KiCad in ${KICAD_DIR} belongs to you: ask before moving it."
  fi
  dmg="${ROOT}/downloads/${file}"
  fetch "$url" "$mirror" "$sha" "$bytes" "$dmg"
  if [ "$DRY" = 1 ]; then
    mnt="<a new temporary folder>"
  else
    mnt="$(mktemp -d "${TMPDIR:-/tmp}/via-kicad.XXXXXX")"
  fi
  run hdiutil attach -nobrowse -readonly -noautoopen -mountpoint "$mnt" "$dmg"
  if [ "$DRY" != 1 ]; then
    MNT="$mnt"
    trap detach_dmg EXIT
  fi
  if ! place_kicad "${mnt}/${folder}"; then
    die "the copy of KiCad to ${KICAD_DIR} failed"
  fi
  if [ "$DRY" = 1 ]; then
    run hdiutil detach "$mnt"
    say "would check: $(kicad_cli) version prints ${ver}"
  else
    detach_dmg
    trap - EXIT
    have="$("$cli" version 2> /dev/null || true)"
    [ "$have" = "$ver" ] || die "${cli} version printed '${have}', not ${ver}"
    say "KiCad ${have} at ${KICAD_DIR}"
  fi
  # Kept, as install.ps1 keeps its downloads: a run again uses it after its SHA256 check, and CI keeps
  # this folder between runs (ee-agent-kit/CI.md, "Windows and macOS").
  say "kept for a run again: ${dmg} (${bytes} bytes; delete it to free the space)"
}

step_java() {
  local dir="${ROOT}/java21" tgz sha new top java jver file url bytes
  sha="$(pin "java.${JAVA_KEY}.sha256")"
  jver="$(pin java.version)"
  file="$(pin "java.${JAVA_KEY}.file")"
  url="$(pin "java.${JAVA_KEY}.url")"
  bytes="$(pin "java.${JAVA_KEY}.bytes")"
  java="${dir}/Contents/Home/bin/java"
  header 4 "Java 21" "Eclipse Temurin JRE ${jver} for FreeRouting, into ${dir}"
  if [ "$DRY" != 1 ] && [ -x "$java" ] && [ "$(cat "${dir}/.sha256" 2> /dev/null)" = "$sha" ]; then
    say "Temurin ${jver} is already at ${dir}"
  else
    tgz="${ROOT}/downloads/${file}"
    fetch "$url" "" "$sha" "$bytes" "$tgz"
    new="${ROOT}/java21.new"
    run rm -rf "$new"
    run mkdir -p "$new"
    run tar -xzf "$tgz" -C "$new"
    top="${new}/<the 1 folder in it>"
    if [ "$DRY" != 1 ]; then
      for top in "$new"/*; do break; done
      [ -x "${top}/Contents/Home/bin/java" ] || die "no Contents/Home/bin/java in ${tgz}"
    fi
    run rm -rf "$dir"
    run mv "$top" "$dir"
    run rm -rf "$new"
    write_file "${dir}/.sha256" "$sha"
    say "kept for a run again: ${tgz}"
  fi
  # tools/routers.py runs the java this file names (install.sh writes it the same way).
  write_file "${ROOT}/java.path" "$java"
  if [ "$DRY" != 1 ]; then
    say "java: $("$java" -version 2>&1 | head -1)"
  fi
}

step_freerouting() {
  local ver dir jar url sha bytes
  ver="$(pin freerouting.version)"
  url="$(pin freerouting.url)"
  sha="$(pin freerouting.sha256)"
  bytes="$(pin freerouting.bytes)"
  dir="${ROOT}/freerouting"
  jar="${dir}/freerouting-${ver}.jar"
  header 5 FreeRouting "the FreeRouting ${ver} jar, checked by SHA256, into ${dir}"
  fetch "$url" "" "$sha" "$bytes" "$jar"
  run ln -sfn "$jar" "${dir}/freerouting.jar"
}

step_venv() {
  local venv="${ROOT}/venv" want have=""
  want="$(pin python.version)"
  header 6 "the venv" "Python ${want} venv at ${venv} with requirements.txt"
  if [ "$DRY" != 1 ]; then
    [ -x "$PY312" ] || die "no ${PY312}: step 2 did not install Python ${want}"
    if [ -x "${venv}/bin/python" ]; then
      have="$("${venv}/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2> /dev/null || true)"
    fi
  fi
  if [ "$have" = "$want" ]; then
    say "venv present: ${venv} (Python ${have})"
  else
    run "$PY312" -m venv --clear "$venv"
  fi
  # `python -m pip`: the same pip as the venv's Python, whatever its path.
  run "${venv}/bin/python" -m pip install -q --upgrade pip
  run "${venv}/bin/python" -m pip install -q -r "${SRC_DIR}/requirements.txt"
}

# The text of the `workcenter` command: every path Via reads, then the venv's Python on tools/workcenter.
# A variable set before the command wins.
launcher_text() {
  local app="${KICAD_DIR}/KiCad.app/Contents" name value
  printf '%s\n' "#!/bin/bash" \
    "# Made by install-macos.sh: run it again to rewrite this file. A variable set before the command wins."
  for name in WORKCENTER_ROOT WORKCENTER_SRC KICAD_CLI NGSPICE FREEROUTING_JAR KICAD_SYMBOL_DIR \
    KICAD_FOOTPRINT_DIR KICAD10_3DMODEL_DIR; do
    case "$name" in
      WORKCENTER_ROOT) value="$ROOT" ;;
      WORKCENTER_SRC) value="$SRC_DIR" ;;
      KICAD_CLI) value="${app}/MacOS/kicad-cli" ;;
      NGSPICE) value="${BREW_PREFIX}/bin/ngspice" ;;
      FREEROUTING_JAR) value="${ROOT}/freerouting/freerouting.jar" ;;
      KICAD_SYMBOL_DIR) value="${app}/SharedSupport/symbols" ;;
      KICAD_FOOTPRINT_DIR) value="${app}/SharedSupport/footprints" ;;
      KICAD10_3DMODEL_DIR) value="${app}/SharedSupport/3dmodels" ;;
    esac
    # The $ is the written file's: it expands when the command runs, not here.
    # shellcheck disable=SC2016
    printf 'if [ -z "${%s:-}" ]; then %s=%q; fi\n' "$name" "$name" "$value"
  done
  # shellcheck disable=SC2016
  printf '%s\n' "export WORKCENTER_ROOT WORKCENTER_SRC KICAD_CLI NGSPICE FREEROUTING_JAR KICAD_SYMBOL_DIR" \
    "export KICAD_FOOTPRINT_DIR KICAD10_3DMODEL_DIR" \
    'exec "$WORKCENTER_ROOT/venv/bin/python" "$WORKCENTER_SRC/tools/workcenter" "$@"'
}

step_link() {
  local bin="${LINK%/*}" profile line
  header 7 "the workcenter command" "write ${LINK}, which runs tools/workcenter with Via's paths"
  run mkdir -p "$bin" "$ROOT"
  write_file "$LINK" "$(launcher_text)"
  run chmod 0755 "$LINK"
  run cp "${SRC_DIR}/WORKCENTER.md" "${ROOT}/WORKCENTER.md"
  case ":${PATH}:" in
    *":${bin}:"*)
      say "${bin} is on PATH"
      return 0
      ;;
  esac
  case "${SHELL:-}" in
    */bash) profile="${HOME}/.bash_profile" ;;
    *) profile="${HOME}/.zprofile" ;;
  esac
  line="export PATH=$(printf '%q' "$bin"):\"\$PATH\"  ${MARK}"
  if [ "$DRY" != 1 ] && [ -f "$profile" ] && grep -qF "$MARK" "$profile"; then
    say "${profile} already puts ${bin} on PATH; a new terminal finds workcenter"
    return 0
  fi
  say "${bin} is not on PATH: adding 1 line to ${profile}: ${line}"
  if [ "$DRY" != 1 ]; then
    printf '%s\n' "$line" >> "$profile"
  fi
  say "open a new terminal, or run: export PATH=$(printf '%q' "$bin"):\"\$PATH\""
}

step_doctor() {
  local code=0
  header 8 "workcenter doctor" "the last step: doctor names each engine and says ok, degraded or missing"
  if [ "$DRY" = 1 ]; then
    say "would run: $(quoted "$LINK" doctor)"
    return 0
  fi
  say "run: $(quoted "$LINK" doctor)"
  "$LINK" doctor || code=$?
  return "$code"
}

main() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --dry-run) DRY=1 ;;
      --yes | -y) YES=1 ;;
      --check) CHECK=1 ;;
      -h | --help)
        usage
        exit 0
        ;;
      *)
        printf '[via] unknown argument: %s\n' "$1" >&2
        usage >&2
        exit 2
        ;;
    esac
    shift
  done
  if [ "$CHECK" = 1 ]; then
    [ -x "$LINK" ] || die "no ${LINK}: run ./install-macos.sh first"
    exec "$LINK" doctor
  fi
  preflight
  step_brew
  step_formulae
  step_kicad
  step_java
  step_freerouting
  step_venv
  step_link
  if [ "$DRY" = 1 ]; then
    step_doctor
    say "dry run: nothing was installed, written or downloaded"
    return 0
  fi
  step_doctor
}

# The steps run when the script is executed, not when a test sources it to call 1 function.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  set -euo pipefail
  main "$@"
fi
