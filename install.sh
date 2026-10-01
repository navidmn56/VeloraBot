#!/usr/bin/env bash
# ============================================================
# VeloraBot — Universal Installer / Updater / Repairer
# ============================================================
# Source of truth: https://github.com/navidmn56/VeloraBot (main)
#
# Design:
#   * FD 3 on /dev/tty for prompts → curl|bash safe.
#   * config.py from release is applied, then user's values are
#     re-applied on top (comments & structure from release kept).
#   * data/ and *.log are never touched by any operation.
#   * .version written ONLY after successful health check.
#   * ZIP download pinned to exact commit SHA.
#   * Non-root service user + systemd sandboxing.
#   * Interactive management panel shown in `auto` mode.
# ============================================================

set -Eeuo pipefail
IFS=$'\n\t'

# ============================================================
# Terminal handling (FD 3)
# ============================================================

open_tty() {
    if [[ ! -r /dev/tty || ! -w /dev/tty ]]; then
        printf '%s\n' "ERROR: An interactive terminal is required." >&2
        exit 1
    fi
    exec 3< /dev/tty
}

close_tty() {
    { exec 3<&-; } 2>/dev/null || true
    return 0
}

# ============================================================
# Colors
# ============================================================

readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly MAGENTA='\033[0;35m'
readonly CYAN='\033[0;36m'
readonly BOLD='\033[1m'
readonly DIM='\033[2m'
readonly NC='\033[0m'

# ============================================================
# Constants
# ============================================================

readonly APP_NAME="VeloraBot"
readonly OWNER="navidmn56"
readonly REPO="VeloraBot"
readonly REPO_FULL="${OWNER}/${REPO}"
readonly BRANCH="main"

readonly REPO_URL="https://github.com/${REPO_FULL}"
readonly COMMITS_API="https://api.github.com/repos/${REPO_FULL}/commits/${BRANCH}"

readonly INSTALL_DIR="/opt/VeloraBot"
readonly VENV_DIR="${INSTALL_DIR}/.venv"
readonly CONFIG_FILE="${INSTALL_DIR}/config.py"
readonly DATA_DIR="${INSTALL_DIR}/data"
readonly VERSION_FILE="${INSTALL_DIR}/.version"

readonly SERVICE_NAME="velorabot"
readonly SERVICE_USER="velorabot"
readonly SERVICE_GROUP="velorabot"
readonly SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
readonly SERVICE_OVERRIDE_DIR="/etc/systemd/system/${SERVICE_NAME}.service.d"

readonly BACKUP_ROOT="/opt/VeloraBot-backups"
readonly BACKUP_KEEP=5

LOG_FILE="/var/log/velorabot-installer.log"
LOG_FILE_PRIMARY="/var/log/velorabot-installer.log"

SENSITIVE_PLACEHOLDER_KEYS=(
    "BOT_TOKEN" "ADMIN_ID" "LOG_BOT_TOKEN"
    "BANK_CARD_NUMBER" "BANK_CARD_HOLDER" "BANK_NAME"
    "SENAI_PANEL_URL" "SENAI_PANEL_USERNAME" "SENAI_PANEL_PASSWORD"
    "SENAI_SUB_URL" "SUPPORT_USERNAME" "GEMINI_API_KEY"
)

# All keys that the panel and update flow will preserve/restore.
CONFIG_EDITABLE_KEYS=(
    "BOT_TOKEN" "ADMIN_ID" "LOG_BOT_TOKEN" "LOG_CHANNEL_ID"
    "BANK_CARD_NUMBER" "BANK_CARD_HOLDER" "BANK_NAME"
    "SENAI_PANEL_URL" "SENAI_PANEL_USERNAME" "SENAI_PANEL_PASSWORD"
    "SENAI_SUB_URL" "SUPPORT_USERNAME"
    "GEMINI_ENABLED" "GEMINI_API_KEY" "GEMINI_MODEL"
    "GEMINI_TEMPERATURE" "GEMINI_MAX_TOKENS" "GEMINI_DAILY_LIMIT"
)

# ============================================================
# Runtime state
# ============================================================

SCRIPT_MODE="auto"
CURRENT_VERSION="unknown"
LATEST_VERSION="unknown"
LATEST_COMMIT_SHA=""
LATEST_COMMIT_DATE=""
TEMP_ROOT=""
RELEASE_ROOT=""
BACKUP_DIR=""
BACKUP_READY=0
SERVICE_WAS_ACTIVE=0
UPDATE_IN_PROGRESS=0
VENV_CREATED=0
FORCE_UPDATE=0
SKIP_CONFIG=0
REPAIR_ONLY=0
SERVICE_BACKUP_EXISTS=0
STTY_SAVED_STATE=""

# ============================================================
# Configuration state
# ============================================================

BOT_TOKEN=""
ADMIN_ID=""
LOG_BOT_TOKEN=""
LOG_CHANNEL_ID=""
BANK_CARD_NUMBER=""
BANK_CARD_HOLDER=""
BANK_NAME=""
SENAI_PANEL_URL=""
SENAI_PANEL_USERNAME=""
SENAI_PANEL_PASSWORD=""
SENAI_SUB_URL=""
SUPPORT_USERNAME=""
GEMINI_ENABLED="False"
GEMINI_API_KEY=""
GEMINI_MODEL="gemini-2.5-flash"
GEMINI_TEMPERATURE="0.7"
GEMINI_MAX_TOKENS="90"
GEMINI_DAILY_LIMIT="3"

# ============================================================
# Logging
# ============================================================

initialize_logging() {
    local fallback
    fallback="$(mktemp -t velorabot-installer.XXXXXX.log 2>/dev/null \
        || echo "/tmp/velorabot-installer.$$.log")"
    LOG_FILE="${fallback}"
    : > "${LOG_FILE}" 2>/dev/null || true
    chmod 600 "${LOG_FILE}" 2>/dev/null || true

    if [[ "$(id -u)" -eq 0 ]]; then
        local dir
        dir="$(dirname "${LOG_FILE_PRIMARY}")"
        if mkdir -p "${dir}" 2>/dev/null; then
            if [[ -w "${LOG_FILE_PRIMARY}" ]] || \
               touch "${LOG_FILE_PRIMARY}" 2>/dev/null; then
                LOG_FILE="${LOG_FILE_PRIMARY}"
                chmod 600 "${LOG_FILE}" 2>/dev/null || true
            fi
        fi
    fi
}

timestamp() { date '+%Y-%m-%d %H:%M:%S'; }

write_log() {
    local level="$1"; shift
    printf '[%s] [%s] %s\n' "$(timestamp)" "${level}" "$*" \
        >> "${LOG_FILE}" 2>/dev/null || true
}

log_info()    { printf '%b[INFO]%b %s\n' "${CYAN}"   "${NC}" "$*"; write_log "INFO" "$*"; }
log_success() { printf '%b[ OK ]%b %s\n' "${GREEN}"  "${NC}" "$*"; write_log "OK"   "$*"; }
log_warning() { printf '%b[WARN]%b %s\n' "${YELLOW}" "${NC}" "$*" >&2; write_log "WARN" "$*"; }
log_error()   { printf '%b[FAIL]%b %s\n' "${RED}"    "${NC}" "$*" >&2; write_log "FAIL" "$*"; }
log_command() { printf '%b[CMD ]%b %s\n' "${DIM}"    "${NC}" "$*"; write_log "CMD" "$*"; }

die() {
    log_error "$*"
    printf '\n%s\n  %s\n' "Installer log:" "${LOG_FILE}"
    exit 1
}

# ============================================================
# UI
# ============================================================

draw_line() {
    printf '%b%s%b\n' "${BLUE}" \
        '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━' \
        "${NC}"
}

draw_header() {
    printf '\n'; draw_line
    printf '%b  %s%b\n' "${BOLD}${CYAN}" "$1" "${NC}"
    draw_line; printf '\n'
}

draw_step() {
    printf '\n'
    printf '%b%s%b\n' "${MAGENTA}${BOLD}" \
        '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━' \
        "${NC}"
    printf '%b  %s%b\n' "${MAGENTA}${BOLD}" "$1" "${NC}"
    printf '%b%s%b\n' "${MAGENTA}${BOLD}" \
        '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━' \
        "${NC}"
    printf '\n'
}

# ============================================================
# Cleanup / rollback
# ============================================================

cleanup_temp() {
    if [[ -n "${TEMP_ROOT}" && -d "${TEMP_ROOT}" ]]; then
        rm -rf -- "${TEMP_ROOT}"
    fi
}

# Excludes for the rollback restore (we want to KEEP the user's config.py).
rsync_excludes() {
    printf '%s\n' \
        '--exclude=/config.py' \
        '--exclude=/data/' \
        '--exclude=/.venv/' \
        '--exclude=/.version' \
        '--exclude=/.git/' \
        '--exclude=/.env' \
        '--exclude=/*.log'
}

# Excludes for the update sync (we WANT config.py from the release here).
rsync_excludes_update() {
    printf '%s\n' \
        '--exclude=/data/' \
        '--exclude=/.venv/' \
        '--exclude=/.version' \
        '--exclude=/.git/' \
        '--exclude=/.env' \
        '--exclude=/*.log'
}

restore_application_backup() {
    [[ "${BACKUP_READY}" -eq 1 ]] || return 1
    [[ -n "${BACKUP_DIR}" ]] || return 1
    [[ -f "${BACKUP_DIR}/application.tar.gz" ]] || return 1

    local rollback_root="${TEMP_ROOT}/rollback"
    rm -rf -- "${rollback_root}"
    mkdir -p "${rollback_root}"

    log_info "Restoring application files from backup..."
    if ! tar -xzf "${BACKUP_DIR}/application.tar.gz" \
        -C "${rollback_root}" 2>>"${LOG_FILE}"; then
        log_error "Failed to extract backup archive."
        return 1
    fi

    if [[ ! -f "${rollback_root}/main.py" ]]; then
        log_error "Backup archive is incomplete (main.py missing)."
        return 1
    fi

    mkdir -p "${INSTALL_DIR}"

    local excludes=()
    while IFS= read -r line; do excludes+=("${line}"); done < <(rsync_excludes)

    rsync -a --delete "${excludes[@]}" \
        "${rollback_root}/" "${INSTALL_DIR}/"

    if [[ -f "${BACKUP_DIR}/data.tar.gz" ]]; then
        log_info "Restoring data/ from backup..."
        if tar -xzf "${BACKUP_DIR}/data.tar.gz" \
            -C "${INSTALL_DIR}" 2>>"${LOG_FILE}"; then
            chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${DATA_DIR}" 2>/dev/null || true
            chmod -R 700 "${DATA_DIR}" 2>/dev/null || true
        else
            log_warning "Could not restore data/ from backup."
        fi
    fi

    if [[ "${SERVICE_BACKUP_EXISTS}" -eq 1 && -f "${BACKUP_DIR}/service" ]]; then
        cp -a "${BACKUP_DIR}/service" "${SERVICE_FILE}"
    fi

    systemctl daemon-reload >/dev/null 2>&1 || true
    return 0
}

rollback_update() {
    log_warning "Attempting to roll back the failed update..."

    if ! restore_application_backup; then
        log_error "Application rollback failed."
        return 1
    fi

    if [[ -f "${BACKUP_DIR}/freeze.txt" && -x "${VENV_DIR}/bin/python" ]]; then
        log_info "Restoring previous Python dependencies (pinned freeze)..."
        if ! "${VENV_DIR}/bin/python" -m pip install \
            --force-reinstall --no-deps \
            -r "${BACKUP_DIR}/freeze.txt" >>"${LOG_FILE}" 2>&1; then
            log_warning "Previous Python dependencies could not be fully restored."
        fi
    elif [[ -f "${BACKUP_DIR}/requirements.txt" && -x "${VENV_DIR}/bin/python" ]]; then
        log_info "Restoring previous Python dependencies (requirements.txt)..."
        if ! "${VENV_DIR}/bin/python" -m pip install \
            -r "${BACKUP_DIR}/requirements.txt" >>"${LOG_FILE}" 2>&1; then
            log_warning "Previous Python dependencies could not be fully restored."
        fi
    fi

    systemctl daemon-reload >/dev/null 2>&1 || true
    log_success "Application rollback completed."
    return 0
}

on_exit() {
    local exit_code=$?

    if [[ -n "${STTY_SAVED_STATE}" ]]; then
        stty "${STTY_SAVED_STATE}" < /dev/tty 2>/dev/null || \
            stty echo < /dev/tty 2>/dev/null || true
        STTY_SAVED_STATE=""
    fi

    if (( exit_code != 0 )) && \
       (( UPDATE_IN_PROGRESS == 1 )) && \
       (( BACKUP_READY == 1 )); then

        printf '\n'
        log_error "The update failed with exit code ${exit_code}."

        if rollback_update; then
            if (( SERVICE_WAS_ACTIVE == 1 )); then
                log_info "Starting the previous service version..."
                systemctl start "${SERVICE_NAME}" >/dev/null 2>&1 || true
            fi
            log_warning "The previous application version has been restored."
        else
            log_error "Automatic rollback was not fully successful."
            log_error "Manual recovery may be required."
        fi
    fi

    close_tty
    cleanup_temp
    exit "${exit_code}"
}

trap on_exit EXIT
trap '' HUP

# ============================================================
# Input helpers (FD 3)
# ============================================================

read_tty() {
    local _rt_prompt="$1"
    local _rt_target="$2"
    local _rt_value=""

    printf '%s' "${_rt_prompt}" > /dev/tty

    if ! IFS= read -r _rt_value <&3; then
        return 1
    fi

    printf -v "${_rt_target}" '%s' "${_rt_value}"
}

read_secret_tty() {
    local _rs_prompt="$1"
    local _rs_target="$2"
    local _rs_value=""
    local _rs_stty_state=""
    local _rs_rc=0

    printf '%s' "${_rs_prompt}" > /dev/tty

    _rs_stty_state="$(stty -g < /dev/tty 2>/dev/null || true)"
    STTY_SAVED_STATE="${_rs_stty_state}"
    stty -echo < /dev/tty 2>/dev/null || true

    IFS= read -r _rs_value <&3 || _rs_rc=1

    if [[ -n "${_rs_stty_state}" ]]; then
        stty "${_rs_stty_state}" < /dev/tty 2>/dev/null || true
    else
        stty echo < /dev/tty 2>/dev/null || true
    fi
    STTY_SAVED_STATE=""
    printf '\n' > /dev/tty

    (( _rs_rc == 0 )) || return 1

    printf -v "${_rs_target}" '%s' "${_rs_value}"
}

ask_yes_no() {
    local prompt="$1"
    local default="$2"
    local answer=""

    while true; do
        if ! read_tty "${prompt}" answer; then
            return 1
        fi

        answer="${answer,,}"
        [[ -z "${answer}" ]] && answer="${default}"

        case "${answer}" in
            y|yes) return 0 ;;
            n|no)  return 1 ;;
            *)     log_warning "Please answer yes or no." ;;
        esac
    done
}

# ============================================================
# Arguments
# ============================================================

show_help() {
    cat <<EOF
VeloraBot Installer / Updater / Repairer

Usage:
  sudo bash $0
  sudo bash $0 --install
  sudo bash $0 --update
  sudo bash $0 --force-update
  sudo bash $0 --skip-config
  sudo bash $0 --repair
  sudo bash $0 --help

Options:
  --install         Force a fresh installation.
  --update          Force an update of an existing installation.
  --force-update    Re-sync even when the installed commit is current.
  --skip-config     Skip config prompts during a fresh install.
  --repair          Validate and repair the current installation.
  --help, -h        Show this help message.

Running without arguments opens the interactive management panel.

Source of truth:
  ${REPO_URL} (branch: ${BRANCH})
EOF
}

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --install)       SCRIPT_MODE="install" ;;
            --update)        SCRIPT_MODE="update" ;;
            --force-update)  FORCE_UPDATE=1 ;;
            --skip-config)   SKIP_CONFIG=1 ;;
            --repair)        REPAIR_ONLY=1 ;;
            --help|-h)       show_help; exit 0 ;;
            *)               die "Unknown argument: $1" ;;
        esac
        shift
    done
}

# ============================================================
# Environment checks
# ============================================================

check_root() {
    if [[ "$(id -u)" -ne 0 ]]; then
        die "This installer must be run as root."
    fi
    log_success "Running with root privileges."
}

check_operating_system() {
    [[ -f /etc/os-release ]] || die "Cannot detect the operating system."
    # shellcheck disable=SC1091
    source /etc/os-release

    printf 'Operating System : %s\n' "${PRETTY_NAME:-Unknown}"
    printf 'Architecture     : %s\n' "$(uname -m)"
    printf 'Kernel           : %s\n' "$(uname -r)"
    printf '\n'

    local id="${ID:-}"
    local id_like="${ID_LIKE:-}"

    if [[ "${id}" == "debian" || "${id}" == "ubuntu" || \
          "${id_like}" == *"debian"* || "${id_like}" == *"ubuntu"* ]]; then
        log_success "Detected an apt-based distribution."
        return 0
    fi

    log_warning "This installer is designed for apt-based distributions."
    log_warning "Detected: ${PRETTY_NAME:-Unknown}"

    if ! ask_yes_no "Continue anyway? [y/N]: " "n"; then
        exit 0
    fi
}

install_system_dependencies() {
    draw_step "Installing System Dependencies"
    export DEBIAN_FRONTEND=noninteractive

    log_command "apt-get update"
    apt-get -o DPkg::Lock::Timeout=120 update -qq

    log_command "Installing required packages"
    apt-get -o DPkg::Lock::Timeout=120 install -y -qq \
        ca-certificates curl unzip rsync python3 python3-pip \
        python3-venv python3-dev build-essential libssl-dev libffi-dev \
        libjpeg-dev zlib1g-dev

    for cmd in python3 curl unzip rsync; do
        command -v "${cmd}" >/dev/null 2>&1 || die "${cmd} is not available."
    done

    log_success "System dependencies are installed."
}

check_python_version() {
    local version
    version="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"
    printf 'Python version: %s\n' "${version}"

    if ! python3 -c \
        'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)'; then
        die "VeloraBot requires Python 3.10 or newer."
    fi
    log_success "Python version is supported."
}

check_github_connectivity() {
    draw_step "Checking GitHub Connectivity"
    if curl --fail --silent --show-error --location \
        --connect-timeout 10 --max-time 30 \
        "https://github.com" >/dev/null; then
        log_success "GitHub is reachable."
    else
        die "Unable to connect to GitHub."
    fi
}

# ============================================================
# GitHub main branch
# ============================================================

fetch_latest_commit() {
    draw_step "Checking Latest GitHub Commit (${BRANCH})"
    local metadata_file="${TEMP_ROOT}/commit.json"

    log_info "Requesting latest commit information from GitHub..."

    curl --fail --silent --show-error --location \
        --retry 4 --retry-delay 2 \
        --connect-timeout 15 --max-time 60 \
        -H "Accept: application/vnd.github+json" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        "${COMMITS_API}" -o "${metadata_file}"

    local parsed
    parsed="$(
        python3 - "${metadata_file}" <<'PY'
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)
if data.get("message"):
    raise SystemExit(f"GitHub API error: {data['message']}")
sha = data.get("sha", "")
if not sha:
    raise SystemExit("No SHA.")
commit = data.get("commit", {}) or {}
author = commit.get("author", {}) or {}
print(sha)
print(author.get("date", ""))
PY
    )" || die "Failed to parse GitHub commit information."

    LATEST_COMMIT_SHA="$(printf '%s\n' "${parsed}" | sed -n '1p')"
    LATEST_COMMIT_DATE="$(printf '%s\n' "${parsed}" | sed -n '2p')"
    [[ -n "${LATEST_COMMIT_SHA}" ]] || die "Latest commit SHA could not be determined."

    LATEST_VERSION="${LATEST_COMMIT_SHA:0:12}"

    printf '\nLatest commit : %s\n' "${LATEST_VERSION}"
    printf 'Commit date   : %s\n\n' "${LATEST_COMMIT_DATE}"
    log_success "Latest commit detected."
}

download_latest_commit() {
    draw_step "Downloading ${BRANCH} branch"
    local archive="${TEMP_ROOT}/main.zip"
    local extract_dir="${TEMP_ROOT}/main"
    mkdir -p "${extract_dir}"

    local zip_url="https://codeload.github.com/${REPO_FULL}/zip/${LATEST_COMMIT_SHA}"

    log_info "Downloading commit ${LATEST_VERSION}..."
    log_command "curl ${zip_url}"

    curl --fail --silent --show-error --location \
        --retry 4 --retry-delay 2 \
        --connect-timeout 15 --max-time 300 \
        "${zip_url}" -o "${archive}"

    [[ -s "${archive}" ]] || die "The downloaded archive is empty."

    log_info "Extracting archive..."
    rm -rf -- "${extract_dir}"
    mkdir -p "${extract_dir}"

    if ! unzip -q "${archive}" -d "${extract_dir}"; then
        die "Failed to extract the archive."
    fi

    RELEASE_ROOT=""
    while IFS= read -r -d '' directory; do
        if [[ -f "${directory}/main.py" && \
              -f "${directory}/requirements.txt" ]]; then
            RELEASE_ROOT="${directory}"
            break
        fi
    done < <(find "${extract_dir}" -mindepth 1 -maxdepth 2 -type d -print0)

    [[ -n "${RELEASE_ROOT}" ]] || \
        die "Invalid structure. main.py and requirements.txt were not found."

    log_success "${BRANCH} branch extracted successfully."
}

validate_release_for_install() {
    [[ -f "${RELEASE_ROOT}/main.py" ]] || die "main.py is missing from the release."
    [[ -f "${RELEASE_ROOT}/requirements.txt" ]] || die "requirements.txt is missing."
    [[ -f "${RELEASE_ROOT}/config.py" ]] || die "config.py is missing from the release."
    log_success "Release structure is valid for installation."
}

validate_release_for_update() {
    [[ -f "${RELEASE_ROOT}/main.py" ]] || die "main.py is missing from the release."
    [[ -f "${RELEASE_ROOT}/requirements.txt" ]] || die "requirements.txt is missing."
    log_success "Release structure is valid for update."
}

# ============================================================
# Version
# ============================================================

read_current_version() {
    if [[ -f "${VERSION_FILE}" ]]; then
        CURRENT_VERSION="$(tr -d '\r\n' < "${VERSION_FILE}")"
        [[ -n "${CURRENT_VERSION}" ]] || CURRENT_VERSION="unknown"
    else
        CURRENT_VERSION="unknown"
    fi
}

write_version_file() {
    printf '%s\n' "${LATEST_VERSION}" > "${VERSION_FILE}"
    chmod 644 "${VERSION_FILE}"
}

versions_equal() { [[ "$1" == "$2" ]]; }

# ============================================================
# Backup
# ============================================================

prune_old_backups() {
    [[ -d "${BACKUP_ROOT}" ]] || return 0
    local dirs
    mapfile -t dirs < <(
        find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d \
            -printf '%T@ %p\n' 2>/dev/null \
            | sort -rn | awk -v k="${BACKUP_KEEP}" 'NR>k {print $2}'
    )
    local d
    for d in "${dirs[@]}"; do
        [[ -n "${d}" ]] || continue
        log_info "Pruning old backup: ${d}"
        rm -rf -- "${d}"
    done
}

create_backup() {
    local ts
    ts="$(date '+%Y%m%d_%H%M%S')"
    BACKUP_DIR="${BACKUP_ROOT}/${ts}_from-${CURRENT_VERSION}_to-${LATEST_VERSION}"
    mkdir -p "${BACKUP_DIR}"
    chmod 700 "${BACKUP_ROOT}" 2>/dev/null || true
    chmod 700 "${BACKUP_DIR}"

    draw_step "Creating Update Backup"

    log_info "Backing up application source (excluding data/, .venv/, *.log)..."
    tar -czf "${BACKUP_DIR}/application.tar.gz" \
        --exclude='./.venv' \
        --exclude='./data' \
        --exclude='./.git' \
        --exclude='./*.log' \
        -C "${INSTALL_DIR}" . 2>>"${LOG_FILE}" || {
        log_error "Failed to create application backup."
        return 1
    }

    if [[ -d "${DATA_DIR}" ]]; then
        log_info "Backing up data/ (users, orders, configs)..."
        tar -czf "${BACKUP_DIR}/data.tar.gz" \
            -C "${INSTALL_DIR}" data 2>>"${LOG_FILE}" || {
            log_error "Failed to back up data/."
            return 1
        }
    fi

    if [[ -f "${INSTALL_DIR}/requirements.txt" ]]; then
        cp -a "${INSTALL_DIR}/requirements.txt" "${BACKUP_DIR}/requirements.txt"
    fi

    if [[ -x "${VENV_DIR}/bin/python" ]]; then
        "${VENV_DIR}/bin/python" -m pip freeze \
            > "${BACKUP_DIR}/freeze.txt" 2>/dev/null || true
    fi

    if [[ -f "${SERVICE_FILE}" ]]; then
        cp -a "${SERVICE_FILE}" "${BACKUP_DIR}/service"
        SERVICE_BACKUP_EXISTS=1
    else
        SERVICE_BACKUP_EXISTS=0
    fi

    chmod 600 "${BACKUP_DIR}"/*.tar.gz 2>/dev/null || true
    chmod 600 "${BACKUP_DIR}/requirements.txt" 2>/dev/null || true
    chmod 600 "${BACKUP_DIR}/freeze.txt" 2>/dev/null || true
    chmod 600 "${BACKUP_DIR}/service" 2>/dev/null || true

    BACKUP_READY=1
    log_success "Backup created: ${BACKUP_DIR}"

    prune_old_backups
}

# ============================================================
# Service management
# ============================================================

service_is_active() { systemctl is-active --quiet "${SERVICE_NAME}"; }

stop_service_if_active() {
    SERVICE_WAS_ACTIVE=0
    if service_is_active; then
        SERVICE_WAS_ACTIVE=1
    fi
    log_info "Stopping ${SERVICE_NAME} (if present)..."
    systemctl stop "${SERVICE_NAME}" >/dev/null 2>&1 || true
    sleep 1
    if service_is_active; then
        log_warning "Service did not stop cleanly, forcing..."
        systemctl kill -s SIGKILL "${SERVICE_NAME}" >/dev/null 2>&1 || true
        sleep 1
    fi
}

ensure_service_user() {
    if ! getent group "${SERVICE_GROUP}" >/dev/null 2>&1; then
        groupadd --system "${SERVICE_GROUP}" 2>/dev/null || true
    fi
    if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
        useradd --system \
            --gid "${SERVICE_GROUP}" \
            --shell /usr/sbin/nologin \
            --home-dir "${INSTALL_DIR}" \
            --no-create-home \
            "${SERVICE_USER}" 2>/dev/null || true
    fi
}

fix_permissions() {
    ensure_service_user
    mkdir -p "${DATA_DIR}"
    chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${INSTALL_DIR}" 2>/dev/null || true
    chmod 755 "${INSTALL_DIR}" 2>/dev/null || true
    [[ -f "${CONFIG_FILE}" ]] && chmod 600 "${CONFIG_FILE}" 2>/dev/null || true
    chmod 700 "${DATA_DIR}" 2>/dev/null || true
    find "${DATA_DIR}" -type f -exec chmod 600 {} + 2>/dev/null || true
    find "${INSTALL_DIR}" -maxdepth 1 -type f -name '*.log' \
        -exec chown "${SERVICE_USER}:${SERVICE_GROUP}" {} + 2>/dev/null || true
    find "${INSTALL_DIR}" -maxdepth 1 -type f -name '*.log' \
        -exec chmod 640 {} + 2>/dev/null || true
}

write_service_file() {
    local desired
    desired="$(cat <<EOF
[Unit]
Description=VeloraBot Telegram Bot
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=120
StartLimitBurst=5

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
WorkingDirectory=${INSTALL_DIR}
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=${VENV_DIR}/bin/python ${INSTALL_DIR}/main.py
Restart=always
RestartSec=5
TimeoutStopSec=30
LimitNOFILE=65535

NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=${INSTALL_DIR}
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=yes
LockPersonality=yes
RestrictRealtime=yes
SystemCallArchitectures=native

[Install]
WantedBy=multi-user.target
EOF
)"

    local current=""
    [[ -f "${SERVICE_FILE}" ]] && current="$(cat "${SERVICE_FILE}")"

    if [[ "${current}" != "${desired}" ]]; then
        printf '%s\n' "${desired}" > "${SERVICE_FILE}"
        chmod 644 "${SERVICE_FILE}"
        systemctl daemon-reload
        log_info "systemd unit file updated."
    else
        log_info "systemd unit file unchanged (preserving any local edits)."
    fi

    systemctl enable "${SERVICE_NAME}" >/dev/null 2>&1 || true
    mkdir -p "${SERVICE_OVERRIDE_DIR}" 2>/dev/null || true
}

create_systemd_service() {
    draw_step "Configuring systemd"
    ensure_service_user
    write_service_file
    log_success "systemd service configured."
}

start_service_and_check() {
    draw_step "Starting VeloraBot"
    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}" >/dev/null 2>&1 || true

    systemctl reset-failed "${SERVICE_NAME}" >/dev/null 2>&1 || true
    systemctl restart "${SERVICE_NAME}"

    log_info "Waiting for service to stabilize..."
    sleep 15

    local restarts
    restarts="$(systemctl show "${SERVICE_NAME}" -p NRestarts --value 2>/dev/null || echo 0)"
    [[ -n "${restarts}" ]] || restarts=0

    if ! service_is_active; then
        log_error "${SERVICE_NAME} failed to start."
        printf '\n%s\n%s\n' "Recent service logs:" "------------------------------------------------------------"
        journalctl -u "${SERVICE_NAME}" -n 100 --no-pager || true
        printf '%s\n' "------------------------------------------------------------"
        return 1
    fi

    if [[ "${restarts}" != "0" ]]; then
        log_error "${SERVICE_NAME} is in a restart loop (NRestarts=${restarts})."
        printf '\n%s\n%s\n' "Recent service logs:" "------------------------------------------------------------"
        journalctl -u "${SERVICE_NAME}" -n 100 --no-pager || true
        printf '%s\n' "------------------------------------------------------------"
        return 1
    fi

    if [[ -n "${BOT_TOKEN}" && "${BOT_TOKEN}" != "None" ]]; then
        log_info "Verifying Telegram bot token (getMe)..."
        if printf 'url = "https://api.telegram.org/bot%s/getMe"\n' "${BOT_TOKEN}" \
             | curl --silent --show-error --max-time 15 --config - >/dev/null 2>&1; then
            log_success "Telegram bot token is valid."
        else
            log_warning "Could not verify bot token via getMe (network or token issue)."
        fi
    fi

    log_success "${SERVICE_NAME} is running (NRestarts=0)."
    return 0
}

# ============================================================
# Python venv
# ============================================================

create_virtual_environment_if_needed() {
    if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
        draw_step "Creating Python Virtual Environment"
        log_info "Creating ${VENV_DIR}..."
        mkdir -p "${INSTALL_DIR}"
        python3 -m venv "${VENV_DIR}"
        VENV_CREATED=1
        log_success "Python virtual environment created."
    else
        log_info "Existing Python virtual environment will be preserved."
    fi

    [[ -x "${VENV_DIR}/bin/python" ]] || die "Virtual environment is invalid."
    "${VENV_DIR}/bin/python" --version
    "${VENV_DIR}/bin/python" -m pip --version >/dev/null || die "pip is missing."
}

install_requirements() {
    local req="${INSTALL_DIR}/requirements.txt"
    [[ -f "${req}" ]] || die "requirements.txt does not exist."

    draw_step "Installing Python Dependencies"
    log_info "Installing dependencies from requirements.txt..."

    "${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel
    "${VENV_DIR}/bin/python" -m pip install -r "${req}"
    "${VENV_DIR}/bin/python" -m pip check || \
        log_warning "pip check reported inconsistencies (continuing)."

    log_success "Python dependencies are installed and verified."
}

ensure_data_configs_file() {
    mkdir -p "${DATA_DIR}"
    if [[ ! -f "${DATA_DIR}/configs.json" ]]; then
        printf '{}\n' > "${DATA_DIR}/configs.json"
        chmod 600 "${DATA_DIR}/configs.json"
        log_info "Created placeholder data/configs.json."
    fi
}

# ============================================================
# Config helpers
# ============================================================

release_default_value() {
    local key="$1"
    [[ -f "${RELEASE_ROOT}/config.py" ]] || return 1
    python3 - "${RELEASE_ROOT}/config.py" "${key}" <<'PY'
import ast, sys
path, key = sys.argv[1], sys.argv[2]
try:
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == key:
                    try:
                        v = ast.literal_eval(node.value)
                    except Exception:
                        sys.exit(1)
                    if isinstance(v, bool):
                        print("True" if v else "False")
                    elif v is None:
                        print("None")
                    else:
                        print(v)
                    sys.exit(0)
except Exception:
    pass
sys.exit(1)
PY
}

is_placeholder() {
    local key="$1"
    local value="$2"

    case "${value}" in
        ""|"Main_bot_token"|"Log_bot_token"|"YOUR_TELEGRAM_USER_ID"|\
        "676778785656565656"|"Navid"|"Blue Bank"|"Panel_username"|\
        "Panel_password"|"Gemini_API_Key"|"@your_username_here"|\
        "1234567812345678"|"None")
            return 0
            ;;
    esac

    local sensitive
    for sensitive in "${SENSITIVE_PLACEHOLDER_KEYS[@]}"; do
        if [[ "${key}" == "${sensitive}" ]]; then
            local default
            if default="$(release_default_value "${key}" 2>/dev/null)"; then
                if [[ -n "${default}" && "${value}" == "${default}" ]]; then
                    return 0
                fi
            fi
            break
        fi
    done

    return 1
}

extract_config_values() {
    [[ -f "${CONFIG_FILE}" ]] || return 1
    local values
    values="$(
        python3 - "${CONFIG_FILE}" <<'PY'
import ast, json, sys
path = sys.argv[1]
allowed = {
    "BOT_TOKEN","ADMIN_ID","LOG_BOT_TOKEN","LOG_CHANNEL_ID",
    "BANK_CARD_NUMBER","BANK_CARD_HOLDER","BANK_NAME",
    "SENAI_PANEL_URL","SENAI_PANEL_USERNAME","SENAI_PANEL_PASSWORD",
    "SENAI_SUB_URL","SUPPORT_USERNAME","GEMINI_ENABLED","GEMINI_API_KEY",
    "GEMINI_MODEL","GEMINI_TEMPERATURE","GEMINI_MAX_TOKENS","GEMINI_DAILY_LIMIT",
}
try:
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source)
    result = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            key = target.id
            if key not in allowed:
                continue
            try:
                result[key] = ast.literal_eval(node.value)
            except Exception:
                pass
    print(json.dumps(result))
except Exception:
    print("{}")
PY
    )"
    [[ -n "${values}" ]] || values="{}"

    local exported_json="${values}"

    config_value() {
        local key="$1"
        local default="${2:-}"
        CFG_JSON="${exported_json}" CFG_KEY="${key}" CFG_DEFAULT="${default}" \
        python3 <<'PY'
import json, os
try:
    data = json.loads(os.environ.get("CFG_JSON", "{}"))
    key = os.environ.get("CFG_KEY", "")
    default = os.environ.get("CFG_DEFAULT", "")
    value = data.get(key, default)
    if isinstance(value, bool):
        print("True" if value else "False")
    elif value is None:
        print("None")
    else:
        print(value)
except Exception:
    print(os.environ.get("CFG_DEFAULT", ""))
PY
    }

    BOT_TOKEN="$(config_value "BOT_TOKEN")"
    ADMIN_ID="$(config_value "ADMIN_ID")"
    LOG_BOT_TOKEN="$(config_value "LOG_BOT_TOKEN")"
    LOG_CHANNEL_ID="$(config_value "LOG_CHANNEL_ID")"
    BANK_CARD_NUMBER="$(config_value "BANK_CARD_NUMBER")"
    BANK_CARD_HOLDER="$(config_value "BANK_CARD_HOLDER")"
    BANK_NAME="$(config_value "BANK_NAME")"
    SENAI_PANEL_URL="$(config_value "SENAI_PANEL_URL")"
    SENAI_PANEL_USERNAME="$(config_value "SENAI_PANEL_USERNAME")"
    SENAI_PANEL_PASSWORD="$(config_value "SENAI_PANEL_PASSWORD")"
    SENAI_SUB_URL="$(config_value "SENAI_SUB_URL")"
    SUPPORT_USERNAME="$(config_value "SUPPORT_USERNAME")"
    GEMINI_ENABLED="$(config_value "GEMINI_ENABLED" "False")"
    GEMINI_API_KEY="$(config_value "GEMINI_API_KEY")"
    GEMINI_MODEL="$(config_value "GEMINI_MODEL" "gemini-2.5-flash")"
    GEMINI_TEMPERATURE="$(config_value "GEMINI_TEMPERATURE" "0.7")"
    GEMINI_MAX_TOKENS="$(config_value "GEMINI_MAX_TOKENS" "90")"
    GEMINI_DAILY_LIMIT="$(config_value "GEMINI_DAILY_LIMIT" "3")"
}

# Apply values from $1 (source config.py) onto $2 (target config.py).
# Only values of known keys are copied; comments/structure of the target
# are preserved untouched. Keys present only in the target keep their
# defaults; keys present only in the source are dropped.
apply_config_values() {
    local source="$1" target="$2"
    [[ -f "${source}" && -f "${target}" ]] || return 1

    python3 - "${source}" "${target}" <<'PY'
import ast, re, sys

source_path, target_path = sys.argv[1], sys.argv[2]

ALLOWED = {
    "BOT_TOKEN","ADMIN_ID","LOG_BOT_TOKEN","LOG_CHANNEL_ID",
    "BANK_CARD_NUMBER","BANK_CARD_HOLDER","BANK_NAME",
    "SENAI_PANEL_URL","SENAI_PANEL_USERNAME","SENAI_PANEL_PASSWORD",
    "SENAI_SUB_URL","SUPPORT_USERNAME","GEMINI_ENABLED","GEMINI_API_KEY",
    "GEMINI_MODEL","GEMINI_TEMPERATURE","GEMINI_MAX_TOKENS","GEMINI_DAILY_LIMIT",
}

with open(source_path, "r", encoding="utf-8") as f:
    src = f.read()
tree = ast.parse(src)
values = {}
for node in tree.body:
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id in ALLOWED:
                try:
                    values[t.id] = ast.literal_eval(node.value)
                except Exception:
                    pass

with open(target_path, "r", encoding="utf-8") as f:
    text = f.read()

def fmt(v):
    if isinstance(v, bool):
        return "True" if v else "False"
    if v is None:
        return "None"
    if isinstance(v, (int, float)):
        return str(v)
    return repr(v)

for key, value in values.items():
    replacement = f"{key} = {fmt(value)}"
    pattern = re.compile(rf"(?m)^([ \t]*){re.escape(key)}([ \t]*=[^\n]*)")

    def repl(match):
        line = match.group(0)
        eq = line.find("=")
        comment_idx = line.find("#", eq + 1) if eq >= 0 else -1
        if comment_idx >= 0:
            comment = line[comment_idx:]
            return f"{match.group(1)}{replacement}  {comment}"
        return f"{match.group(1)}{replacement}"

    if pattern.search(text):
        text = pattern.sub(repl, text, count=1)

with open(target_path, "w", encoding="utf-8") as f:
    f.write(text)
PY
}

# Replace config.py with a new version while preserving values from $saved.
update_config_file_with_backup() {
    local new_config="$1"
    local saved_config="$2"

    [[ -f "${new_config}" ]] || return 0

    if [[ ! -f "${saved_config}" ]]; then
        # No existing config to preserve → just install the new one.
        cp -a "${new_config}" "${CONFIG_FILE}"
        chmod 600 "${CONFIG_FILE}"
        log_info "Installed new config.py from release."
        return 0
    fi

    log_info "Replacing config.py with release version..."
    cp -a "${new_config}" "${CONFIG_FILE}"
    chmod 600 "${CONFIG_FILE}"

    log_info "Re-applying existing values onto the new config.py..."
    if apply_config_values "${saved_config}" "${CONFIG_FILE}"; then
        log_success "Existing values were re-applied to the new config.py."
    else
        log_warning "Could not re-apply values; manual config review may be needed."
    fi
}

validate_existing_config() {
    local missing=0
    printf '%s\n' "Checking existing configuration..."

    is_placeholder "BOT_TOKEN" "${BOT_TOKEN}" && \
        { printf '  %bMISSING%b BOT_TOKEN\n' "${RED}" "${NC}"; missing=1; }

    if [[ ! "${ADMIN_ID}" =~ ^[0-9]+$ || "${ADMIN_ID}" == "0" ]] || \
       is_placeholder "ADMIN_ID" "${ADMIN_ID}"; then
        printf '  %bINVALID%b ADMIN_ID\n' "${RED}" "${NC}"; missing=1
    fi

    if ! is_placeholder "LOG_BOT_TOKEN" "${LOG_BOT_TOKEN}" && \
       [[ -n "${LOG_BOT_TOKEN}" ]]; then
        if [[ ! "${LOG_CHANNEL_ID}" =~ ^-?[0-9]+$ && "${LOG_CHANNEL_ID}" != "None" ]]; then
            printf '  %bINVALID%b LOG_CHANNEL_ID\n' "${RED}" "${NC}"; missing=1
        fi
    fi

    if ! [[ "${BANK_CARD_NUMBER}" =~ ^[0-9]{16}$ ]] || \
       is_placeholder "BANK_CARD_NUMBER" "${BANK_CARD_NUMBER}"; then
        printf '  %bINVALID%b BANK_CARD_NUMBER\n' "${RED}" "${NC}"; missing=1
    fi

    is_placeholder "BANK_CARD_HOLDER" "${BANK_CARD_HOLDER}" && \
        { printf '  %bMISSING%b BANK_CARD_HOLDER\n' "${RED}" "${NC}"; missing=1; }

    is_placeholder "BANK_NAME" "${BANK_NAME}" && \
        { printf '  %bMISSING%b BANK_NAME\n' "${RED}" "${NC}"; missing=1; }

    if ! [[ "${SENAI_PANEL_URL}" =~ ^https?:// ]] || \
       is_placeholder "SENAI_PANEL_URL" "${SENAI_PANEL_URL}"; then
        printf '  %bINVALID%b SENAI_PANEL_URL\n' "${RED}" "${NC}"; missing=1
    fi

    is_placeholder "SENAI_PANEL_USERNAME" "${SENAI_PANEL_USERNAME}" && \
        { printf '  %bMISSING%b SENAI_PANEL_USERNAME\n' "${RED}" "${NC}"; missing=1; }

    is_placeholder "SENAI_PANEL_PASSWORD" "${SENAI_PANEL_PASSWORD}" && \
        { printf '  %bMISSING%b SENAI_PANEL_PASSWORD\n' "${RED}" "${NC}"; missing=1; }

    if ! [[ "${SENAI_SUB_URL}" =~ ^https?:// ]] || \
       is_placeholder "SENAI_SUB_URL" "${SENAI_SUB_URL}"; then
        printf '  %bINVALID%b SENAI_SUB_URL\n' "${RED}" "${NC}"; missing=1
    fi

    is_placeholder "SUPPORT_USERNAME" "${SUPPORT_USERNAME}" && \
        { printf '  %bMISSING%b SUPPORT_USERNAME\n' "${RED}" "${NC}"; missing=1; }

    if [[ "${GEMINI_ENABLED}" == "True" ]]; then
        is_placeholder "GEMINI_API_KEY" "${GEMINI_API_KEY}" && \
            { printf '  %bMISSING%b GEMINI_API_KEY\n' "${RED}" "${NC}"; missing=1; }

        [[ -n "${GEMINI_MODEL}" ]] || \
            { printf '  %bMISSING%b GEMINI_MODEL\n' "${RED}" "${NC}"; missing=1; }

        if ! [[ "${GEMINI_TEMPERATURE}" =~ ^[0-9]+(\.[0-9]+)?$ ]] || \
           ! awk -v v="${GEMINI_TEMPERATURE}" 'BEGIN{exit !(v>=0 && v<=1)}'; then
            printf '  %bINVALID%b GEMINI_TEMPERATURE\n' "${RED}" "${NC}"; missing=1
        fi

        if ! [[ "${GEMINI_MAX_TOKENS}" =~ ^[0-9]+$ ]] || (( GEMINI_MAX_TOKENS <= 0 )); then
            printf '  %bINVALID%b GEMINI_MAX_TOKENS\n' "${RED}" "${NC}"; missing=1
        fi

        if ! [[ "${GEMINI_DAILY_LIMIT}" =~ ^[0-9]+$ ]] || (( GEMINI_DAILY_LIMIT <= 0 )); then
            printf '  %bINVALID%b GEMINI_DAILY_LIMIT\n' "${RED}" "${NC}"; missing=1
        fi
    fi

    return "${missing}"
}

# ============================================================
# Config editors (in place)
# ============================================================

_set_config_raw() {
    local key="$1"
    local raw="$2"
    CFG_KEY="${key}" CFG_RAW="${raw}" python3 - "${CONFIG_FILE}" <<'PY'
import os, re, sys
path = sys.argv[1]
key = os.environ["CFG_KEY"]
raw = os.environ["CFG_RAW"]

with open(path, "r", encoding="utf-8") as f:
    text = f.read()

replacement = f"{key} = {raw}"
pattern = re.compile(rf"(?m)^([ \t]*){re.escape(key)}([ \t]*=[^\n]*)")

def repl(match):
    line = match.group(0)
    eq = line.find("=")
    comment_idx = line.find("#", eq + 1) if eq >= 0 else -1
    if comment_idx >= 0:
        comment = line[comment_idx:]
        return f"{match.group(1)}{replacement}  {comment}"
    return f"{match.group(1)}{replacement}"

if pattern.search(text):
    text = pattern.sub(repl, text, count=1)
else:
    if text and not text.endswith("\n"):
        text += "\n"
    text += replacement + "\n"

with open(path, "w", encoding="utf-8") as f:
    f.write(text)
PY
}

set_config_value() {
    local key="$1"
    local value="$2"
    local quoted
    quoted="$(CFG_VAL="${value}" python3 -c 'import os,sys; sys.stdout.write(repr(os.environ["CFG_VAL"]))')"
    _set_config_raw "${key}" "${quoted}"
}

set_config_integer() {
    local key="$1" value="$2"
    [[ "${value}" =~ ^-?[0-9]+$ ]] || die "${key} must be an integer (negative allowed)."
    _set_config_raw "${key}" "${value}"
}

set_config_float() {
    local key="$1" value="$2"
    [[ "${value}" =~ ^[0-9]+(\.[0-9]+)?$ ]] || die "${key} must be a non-negative number."
    _set_config_raw "${key}" "${value}"
}

set_config_boolean() {
    local key="$1" value="$2"
    local normalized="${value,,}"
    local raw
    case "${normalized}" in
        true)  raw="True" ;;
        false) raw="False" ;;
        none)  raw="None" ;;
        *)     die "${key} must be True, False or None." ;;
    esac
    _set_config_raw "${key}" "${raw}"
}

set_config_literal() {
    local key="$1" value="$2"
    _set_config_raw "${key}" "${value}"
}

# ============================================================
# Prompt helpers
# ============================================================

describe() {
    printf '%b  %s%b\n' "${DIM}" "$1" "${NC}" > /dev/tty
}

mask_secret() {
    local v="$1"
    if [[ -z "${v}" || "${v}" == "None" ]]; then
        printf '%s' "${v}"
        return
    fi
    if (( ${#v} <= 8 )); then
        printf '***'
    else
        printf '%s...%s' "${v:0:4}" "${v: -4}"
    fi
}

prompt_for_value() {
    local label="$1"
    local result_var="$2"
    local _pfv_value=""

    while true; do
        if ! read_tty "${label}: " _pfv_value; then
            die "Could not read input from the terminal."
        fi
        if [[ -n "${_pfv_value}" ]]; then
            printf -v "${result_var}" '%s' "${_pfv_value}"
            return 0
        fi
        log_warning "${label} cannot be empty."
    done
}

prompt_for_secret() {
    local label="$1"
    local result_var="$2"
    local _pfs_value=""

    while true; do
        if ! read_secret_tty "${label}: " _pfs_value; then
            die "Could not read input from the terminal."
        fi
        if [[ -n "${_pfs_value}" ]]; then
            printf -v "${result_var}" '%s' "${_pfs_value}"
            return 0
        fi
        log_warning "${label} cannot be empty."
    done
}

prompt_admin_id() {
    local value=""
    while true; do
        if ! read_tty "ADMIN_ID: " value; then
            die "Could not read input from the terminal."
        fi
        if [[ "${value}" =~ ^[0-9]+$ && "${value}" != "0" ]]; then
            ADMIN_ID="${value}"
            return
        fi
        log_warning "ADMIN_ID must contain digits only (and not 0)."
    done
}

prompt_log_channel_id() {
    local value=""
    describe "LOG_CHANNEL_ID: numeric group ID. Group/channel IDs are NEGATIVE,"
    describe "e.g. -36737636783. Leave empty to disable logging (writes None)."

    if ! read_tty "LOG_CHANNEL_ID: " value; then
        die "Could not read input from the terminal."
    fi

    if [[ -z "${value}" ]]; then
        LOG_CHANNEL_ID="None"
        return
    fi

    while true; do
        if [[ "${value}" =~ ^-?[0-9]+$ ]]; then
            LOG_CHANNEL_ID="${value}"
            return
        fi
        log_warning "LOG_CHANNEL_ID must be a number (negative allowed) or empty."
        if ! read_tty "LOG_CHANNEL_ID: " value; then
            die "Could not read input from the terminal."
        fi
        if [[ -z "${value}" ]]; then
            LOG_CHANNEL_ID="None"
            return
        fi
    done
}

prompt_card_number() {
    local value=""
    while true; do
        if ! read_tty "BANK_CARD_NUMBER: " value; then
            die "Could not read input from the terminal."
        fi
        if [[ "${value}" =~ ^[0-9]{16}$ ]]; then
            BANK_CARD_NUMBER="${value}"
            return
        fi
        log_warning "BANK_CARD_NUMBER must contain exactly 16 digits."
    done
}

prompt_http_url() {
    local label="$1"
    local result_var="$2"
    local value=""
    while true; do
        if ! read_tty "${label}: " value; then
            die "Could not read input from the terminal."
        fi
        if [[ "${value}" =~ ^https?:// ]]; then
            printf -v "${result_var}" '%s' "${value}"
            return
        fi
        log_warning "${label} must start with http:// or https://."
    done
}

prompt_with_default() {
    local label="$1"
    local default="$2"
    local result_var="$3"
    local _pwd_value=""

    printf '%s [%s]: ' "${label}" "${default}" > /dev/tty
    if ! IFS= read -r _pwd_value <&3; then
        die "Could not read input from the terminal."
    fi
    [[ -z "${_pwd_value}" ]] && _pwd_value="${default}"
    printf -v "${result_var}" '%s' "${_pwd_value}"
}

prompt_float() {
    local label="$1"
    local default="$2"
    local result_var="$3"
    local value=""

    while true; do
        prompt_with_default "${label}" "${default}" value
        if [[ "${value}" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
            if [[ "${label}" == "GEMINI_TEMPERATURE" ]] && \
               ! awk -v v="${value}" 'BEGIN{exit !(v>=0 && v<=1)}'; then
                log_warning "${label} must be between 0.0 and 1.0."
                continue
            fi
            printf -v "${result_var}" '%s' "${value}"
            return
        fi
        log_warning "${label} must be a number."
    done
}

prompt_positive_int() {
    local label="$1"
    local default="$2"
    local result_var="$3"
    local value=""

    while true; do
        prompt_with_default "${label}" "${default}" value
        if [[ "${value}" =~ ^[0-9]+$ ]] && (( value > 0 )); then
            printf -v "${result_var}" '%s' "${value}"
            return
        fi
        log_warning "${label} must be a positive integer."
    done
}

# ============================================================
# Interactive panel: edit all config keys
# ============================================================

edit_all_config_keys() {
    while true; do
        [[ -f "${CONFIG_FILE}" ]] || { log_error "config.py not found."; return 1; }
        extract_config_values || true

        draw_header "Edit Configuration Keys"

        printf '  %2d) %-22s : %s\n'  1 "BOT_TOKEN"            "$(mask_secret "${BOT_TOKEN}")"
        printf '  %2d) %-22s : %s\n'  2 "ADMIN_ID"             "${ADMIN_ID}"
        printf '  %2d) %-22s : %s\n'  3 "LOG_BOT_TOKEN"        "$(mask_secret "${LOG_BOT_TOKEN}")"
        printf '  %2d) %-22s : %s\n'  4 "LOG_CHANNEL_ID"       "${LOG_CHANNEL_ID}"
        printf '  %2d) %-22s : %s\n'  5 "BANK_CARD_NUMBER"     "${BANK_CARD_NUMBER}"
        printf '  %2d) %-22s : %s\n'  6 "BANK_CARD_HOLDER"     "${BANK_CARD_HOLDER}"
        printf '  %2d) %-22s : %s\n'  7 "BANK_NAME"            "${BANK_NAME}"
        printf '  %2d) %-22s : %s\n'  8 "SENAI_PANEL_URL"      "${SENAI_PANEL_URL}"
        printf '  %2d) %-22s : %s\n'  9 "SENAI_PANEL_USERNAME" "${SENAI_PANEL_USERNAME}"
        printf '  %2d) %-22s : %s\n' 10 "SENAI_PANEL_PASSWORD" "$(mask_secret "${SENAI_PANEL_PASSWORD}")"
        printf '  %2d) %-22s : %s\n' 11 "SENAI_SUB_URL"        "${SENAI_SUB_URL}"
        printf '  %2d) %-22s : %s\n' 12 "SUPPORT_USERNAME"     "${SUPPORT_USERNAME}"
        printf '  %2d) %-22s : %s\n' 13 "GEMINI_ENABLED"       "${GEMINI_ENABLED}"
        printf '  %2d) %-22s : %s\n' 14 "GEMINI_API_KEY"       "$(mask_secret "${GEMINI_API_KEY}")"
        printf '  %2d) %-22s : %s\n' 15 "GEMINI_MODEL"         "${GEMINI_MODEL}"
        printf '  %2d) %-22s : %s\n' 16 "GEMINI_TEMPERATURE"   "${GEMINI_TEMPERATURE}"
        printf '  %2d) %-22s : %s\n' 17 "GEMINI_MAX_TOKENS"    "${GEMINI_MAX_TOKENS}"
        printf '  %2d) %-22s : %s\n' 18 "GEMINI_DAILY_LIMIT"   "${GEMINI_DAILY_LIMIT}"
        printf '\n'
        printf '  b) Back to main menu\n'
        printf '\n'

        local choice=""
        if ! read_tty "Select a key to edit: " choice; then
            return 0
        fi

        case "${choice}" in
            1)
                describe "Get from @BotFather (main bot token)."
                prompt_for_secret "BOT_TOKEN" BOT_TOKEN
                set_config_value "BOT_TOKEN" "${BOT_TOKEN}"
                log_success "BOT_TOKEN updated."
                ;;
            2)
                describe "Your Telegram numeric ID (get from @myidbot)."
                prompt_admin_id
                set_config_integer "ADMIN_ID" "${ADMIN_ID}"
                log_success "ADMIN_ID updated."
                ;;
            3)
                describe "Token of the second bot (must be admin in the log group)."
                describe "Press Enter then Ctrl+C to skip; leave blank to disable."
                prompt_for_secret "LOG_BOT_TOKEN" LOG_BOT_TOKEN
                set_config_value "LOG_BOT_TOKEN" "${LOG_BOT_TOKEN}"
                log_success "LOG_BOT_TOKEN updated."
                ;;
            4)
                prompt_log_channel_id
                if [[ "${LOG_CHANNEL_ID}" == "None" ]]; then
                    set_config_literal "LOG_CHANNEL_ID" "None"
                else
                    set_config_integer "LOG_CHANNEL_ID" "${LOG_CHANNEL_ID}"
                fi
                log_success "LOG_CHANNEL_ID updated."
                ;;
            5)
                describe "Your bank card number — exactly 16 digits (no spaces/dashes/underscores)."
                prompt_card_number
                set_config_value "BANK_CARD_NUMBER" "${BANK_CARD_NUMBER}"
                log_success "BANK_CARD_NUMBER updated."
                ;;
            6)
                describe "Card holder's full name (as printed on the card)."
                prompt_for_value "BANK_CARD_HOLDER" BANK_CARD_HOLDER
                set_config_value "BANK_CARD_HOLDER" "${BANK_CARD_HOLDER}"
                log_success "BANK_CARD_HOLDER updated."
                ;;
            7)
                describe "Bank name — e.g. \"Blue Bank\", \"Melli\", \"Mellat\"."
                prompt_for_value "BANK_NAME" BANK_NAME
                set_config_value "BANK_NAME" "${BANK_NAME}"
                log_success "BANK_NAME updated."
                ;;
            8)
                describe "3x-ui panel URL, e.g. https://panel.Domain.com:2053/<web_path>"
                prompt_http_url "SENAI_PANEL_URL" SENAI_PANEL_URL
                set_config_value "SENAI_PANEL_URL" "${SENAI_PANEL_URL}"
                log_success "SENAI_PANEL_URL updated."
                ;;
            9)
                describe "Panel admin username."
                prompt_for_value "SENAI_PANEL_USERNAME" SENAI_PANEL_USERNAME
                set_config_value "SENAI_PANEL_USERNAME" "${SENAI_PANEL_USERNAME}"
                log_success "SENAI_PANEL_USERNAME updated."
                ;;
            10)
                describe "Panel admin password."
                prompt_for_secret "SENAI_PANEL_PASSWORD" SENAI_PANEL_PASSWORD
                set_config_value "SENAI_PANEL_PASSWORD" "${SENAI_PANEL_PASSWORD}"
                log_success "SENAI_PANEL_PASSWORD updated."
                ;;
            11)
                describe "Subscription URL for clients, e.g. https://sub.Domain.com:2083"
                prompt_http_url "SENAI_SUB_URL" SENAI_SUB_URL
                set_config_value "SENAI_SUB_URL" "${SENAI_SUB_URL}"
                log_success "SENAI_SUB_URL updated."
                ;;
            12)
                describe "Support Telegram username — e.g. @your_username_here"
                prompt_for_value "SUPPORT_USERNAME" SUPPORT_USERNAME
                set_config_value "SUPPORT_USERNAME" "${SUPPORT_USERNAME}"
                log_success "SUPPORT_USERNAME updated."
                ;;
            13)
                local gem=""
                printf 'Enable Gemini? [true/false/none]: ' > /dev/tty
                if ! IFS= read -r gem <&3; then
                    die "Could not read input."
                fi
                gem="${gem,,}"
                case "${gem}" in
                    true|false|none) ;;
                    *) log_warning "Must be true, false or none."; continue ;;
                esac
                set_config_boolean "GEMINI_ENABLED" "${gem}"
                GEMINI_ENABLED="True"
                [[ "${gem}" == "false" ]] && GEMINI_ENABLED="False"
                [[ "${gem}" == "none"  ]] && GEMINI_ENABLED="None"
                log_success "GEMINI_ENABLED updated."
                ;;
            14)
                describe "GEMINI_API_KEY: Get from https://ai.google.dev/"
                prompt_for_secret "GEMINI_API_KEY" GEMINI_API_KEY
                set_config_value "GEMINI_API_KEY" "${GEMINI_API_KEY}"
                log_success "GEMINI_API_KEY updated."
                ;;
            15)
                describe "GEMINI_MODEL: any Gemini model, e.g. gemini-2.5-flash"
                prompt_with_default "GEMINI_MODEL" "${GEMINI_MODEL:-gemini-2.5-flash}" GEMINI_MODEL
                set_config_value "GEMINI_MODEL" "${GEMINI_MODEL}"
                log_success "GEMINI_MODEL updated."
                ;;
            16)
                describe "GEMINI_TEMPERATURE: randomness (0.0 to 1.0)"
                prompt_float "GEMINI_TEMPERATURE" "${GEMINI_TEMPERATURE:-0.7}" GEMINI_TEMPERATURE
                set_config_float "GEMINI_TEMPERATURE" "${GEMINI_TEMPERATURE}"
                log_success "GEMINI_TEMPERATURE updated."
                ;;
            17)
                describe "GEMINI_MAX_TOKENS: maximum response length"
                prompt_positive_int "GEMINI_MAX_TOKENS" "${GEMINI_MAX_TOKENS:-90}" GEMINI_MAX_TOKENS
                set_config_integer "GEMINI_MAX_TOKENS" "${GEMINI_MAX_TOKENS}"
                log_success "GEMINI_MAX_TOKENS updated."
                ;;
            18)
                describe "GEMINI_DAILY_LIMIT: max AI responses per user per day"
                prompt_positive_int "GEMINI_DAILY_LIMIT" "${GEMINI_DAILY_LIMIT:-3}" GEMINI_DAILY_LIMIT
                set_config_integer "GEMINI_DAILY_LIMIT" "${GEMINI_DAILY_LIMIT}"
                log_success "GEMINI_DAILY_LIMIT updated."
                ;;
            b|B|back|q|quit)
                return 0
                ;;
            *)
                log_warning "Invalid option."
                continue
                ;;
        esac

        chmod 600 "${CONFIG_FILE}" 2>/dev/null || true
        log_info "config.py updated in place."
    done
}

# ============================================================
# Interactive management panel
# ============================================================

show_management_panel() {
    while true; do
        draw_header "VeloraBot Management Panel"

        local has_install=0
        if [[ -d "${INSTALL_DIR}" && -f "${INSTALL_DIR}/main.py" ]]; then
            has_install=1
        fi

        if (( has_install == 1 )); then
            read_current_version
            printf 'Status             : %bInstalled%b\n' "${GREEN}" "${NC}"
            printf 'Installed version  : %s\n' "${CURRENT_VERSION}"
            if service_is_active; then
                printf 'Service            : %bactive%b\n' "${GREEN}" "${NC}"
            else
                printf 'Service            : %binactive%b\n' "${YELLOW}" "${NC}"
            fi
            printf 'Install directory  : %s\n' "${INSTALL_DIR}"
            printf '\n'
            printf '  1) Update to latest version\n'
            printf '  2) Force re-sync (re-download current version)\n'
            printf '  3) Edit configuration keys\n'
            printf '  4) Repair installation\n'
            printf '  5) Restart service\n'
            printf '  6) Show recent service logs\n'
            printf '  q) Quit\n'
        else
            printf 'Status             : %bNot installed%b\n' "${YELLOW}" "${NC}"
            printf 'Install directory  : %s\n' "${INSTALL_DIR}"
            printf '\n'
            printf '  1) Install VeloraBot\n'
            printf '  q) Quit\n'
        fi
        printf '\n'

        local choice=""
        if ! read_tty "Select an option: " choice; then
            exit 1
        fi

        case "${choice}" in
            1)
                if (( has_install == 1 )); then
                    SCRIPT_MODE="update"
                    return 0
                else
                    SCRIPT_MODE="install"
                    return 0
                fi
                ;;
            2)
                if (( has_install == 1 )); then
                    FORCE_UPDATE=1
                    SCRIPT_MODE="update"
                    return 0
                fi
                log_warning "Not installed yet."
                ;;
            3)
                if (( has_install == 1 )); then
                    if [[ -f "${CONFIG_FILE}" ]]; then
                        edit_all_config_keys
                    else
                        log_warning "config.py not found in ${INSTALL_DIR}."
                    fi
                fi
                ;;
            4)
                if (( has_install == 1 )); then
                    REPAIR_ONLY=1
                    return 0
                fi
                ;;
            5)
                if (( has_install == 1 )); then
                    log_info "Restarting ${SERVICE_NAME}..."
                    systemctl restart "${SERVICE_NAME}" >/dev/null 2>&1 || true
                    sleep 3
                    if service_is_active; then
                        log_success "Service restarted."
                    else
                        log_error "Service failed to restart."
                    fi
                    local _d=""
                    read_tty "Press Enter to continue..." _d || true
                fi
                ;;
            6)
                if (( has_install == 1 )); then
                    journalctl -u "${SERVICE_NAME}" -n 50 --no-pager || true
                    local _d=""
                    read_tty "Press Enter to continue..." _d || true
                fi
                ;;
            q|Q|quit|exit)
                log_info "Exiting."
                exit 0
                ;;
            *)
                log_warning "Invalid option."
                ;;
        esac
    done
}

# ============================================================
# configure_config_in_place
# ============================================================

configure_config_in_place() {
    draw_step "Configuring VeloraBot (editing config.py in place)"

    [[ -f "${CONFIG_FILE}" ]] || die "config.py does not exist."

    extract_config_values || true

    printf '%s\n' "The installer will only fill missing or invalid fields."
    printf '%s\n' "Existing valid values will be preserved."
    printf '%s\n' "Press Enter at any prompt to keep the shown default."
    printf '\n'

    local changed=0

    # ---------------------------------------------------------
    # Required
    # ---------------------------------------------------------
    draw_step "Required Settings"

    if is_placeholder "BOT_TOKEN" "${BOT_TOKEN}"; then
        describe "Get from @BotFather (main bot token)."
        prompt_for_secret "BOT_TOKEN" BOT_TOKEN
        set_config_value "BOT_TOKEN" "${BOT_TOKEN}"
        changed=1
    else
        printf 'BOT_TOKEN                : %b(kept existing value)%b\n' "${GREEN}" "${NC}"
    fi

    if [[ ! "${ADMIN_ID}" =~ ^[0-9]+$ || "${ADMIN_ID}" == "0" ]] || \
       is_placeholder "ADMIN_ID" "${ADMIN_ID}"; then
        describe "Your Telegram numeric ID (get from @myidbot)."
        prompt_admin_id
        set_config_integer "ADMIN_ID" "${ADMIN_ID}"
        changed=1
    else
        printf 'ADMIN_ID                 : %b(kept existing value)%b\n' "${GREEN}" "${NC}"
    fi

    if ! [[ "${BANK_CARD_NUMBER}" =~ ^[0-9]{16}$ ]] || \
       is_placeholder "BANK_CARD_NUMBER" "${BANK_CARD_NUMBER}"; then
        describe "Your bank card number — exactly 16 digits (no spaces/dashes/underscores)."
        prompt_card_number
        set_config_value "BANK_CARD_NUMBER" "${BANK_CARD_NUMBER}"
        changed=1
    else
        printf 'BANK_CARD_NUMBER         : %b(kept existing value)%b\n' "${GREEN}" "${NC}"
    fi

    if is_placeholder "BANK_CARD_HOLDER" "${BANK_CARD_HOLDER}"; then
        describe "Card holder's full name (as printed on the card)."
        prompt_for_value "BANK_CARD_HOLDER" BANK_CARD_HOLDER
        set_config_value "BANK_CARD_HOLDER" "${BANK_CARD_HOLDER}"
        changed=1
    else
        printf 'BANK_CARD_HOLDER         : %b(kept existing value)%b\n' "${GREEN}" "${NC}"
    fi

    if is_placeholder "BANK_NAME" "${BANK_NAME}"; then
        describe "Bank name — e.g. \"Blue Bank\", \"Melli\", \"Mellat\"."
        prompt_for_value "BANK_NAME" BANK_NAME
        set_config_value "BANK_NAME" "${BANK_NAME}"
        changed=1
    else
        printf 'BANK_NAME                : %b(kept existing value)%b\n' "${GREEN}" "${NC}"
    fi

    if ! [[ "${SENAI_PANEL_URL}" =~ ^https?:// ]] || \
       is_placeholder "SENAI_PANEL_URL" "${SENAI_PANEL_URL}"; then
        describe "3x-ui panel URL, e.g. https://panel.Domain.com:2053/<web_path>"
        describe "or localhost: https://127.0.0.1:2053/<your_web_path>"
        prompt_http_url "SENAI_PANEL_URL" SENAI_PANEL_URL
        set_config_value "SENAI_PANEL_URL" "${SENAI_PANEL_URL}"
        changed=1
    else
        printf 'SENAI_PANEL_URL          : %b(kept existing value)%b\n' "${GREEN}" "${NC}"
    fi

    if is_placeholder "SENAI_PANEL_USERNAME" "${SENAI_PANEL_USERNAME}"; then
        describe "Panel admin username."
        prompt_for_value "SENAI_PANEL_USERNAME" SENAI_PANEL_USERNAME
        set_config_value "SENAI_PANEL_USERNAME" "${SENAI_PANEL_USERNAME}"
        changed=1
    else
        printf 'SENAI_PANEL_USERNAME     : %b(kept existing value)%b\n' "${GREEN}" "${NC}"
    fi

    if is_placeholder "SENAI_PANEL_PASSWORD" "${SENAI_PANEL_PASSWORD}"; then
        describe "Panel admin password."
        prompt_for_secret "SENAI_PANEL_PASSWORD" SENAI_PANEL_PASSWORD
        set_config_value "SENAI_PANEL_PASSWORD" "${SENAI_PANEL_PASSWORD}"
        changed=1
    else
        printf 'SENAI_PANEL_PASSWORD     : %b(kept existing value)%b\n' "${GREEN}" "${NC}"
    fi

    if ! [[ "${SENAI_SUB_URL}" =~ ^https?:// ]] || \
       is_placeholder "SENAI_SUB_URL" "${SENAI_SUB_URL}"; then
        describe "Subscription URL for clients, e.g. https://sub.Domain.com:2083"
        prompt_http_url "SENAI_SUB_URL" SENAI_SUB_URL
        set_config_value "SENAI_SUB_URL" "${SENAI_SUB_URL}"
        changed=1
    else
        printf 'SENAI_SUB_URL            : %b(kept existing value)%b\n' "${GREEN}" "${NC}"
    fi

    if is_placeholder "SUPPORT_USERNAME" "${SUPPORT_USERNAME}"; then
        describe "Support Telegram username — e.g. @your_username_here"
        prompt_for_value "SUPPORT_USERNAME" SUPPORT_USERNAME
        set_config_value "SUPPORT_USERNAME" "${SUPPORT_USERNAME}"
        changed=1
    else
        printf 'SUPPORT_USERNAME         : %b(kept existing value)%b\n' "${GREEN}" "${NC}"
    fi

    # ---------------------------------------------------------
    # Optional: log bot
    # ---------------------------------------------------------
    draw_step "Optional: Log Bot Settings"

    describe "LOG_BOT_TOKEN: Token of the second bot (must be admin in the log group)."
    describe "LOG_CHANNEL_ID: Group/channel ID — NEGATIVE number, e.g. -36737636783."
    describe "                Get it by adding @myidbot to the group and running /getid@myidbot"
    describe "                then pressing Enter on the LOG_CHANNEL_ID prompt."
    printf '\n'

    local logs_currently_configured=0
    if [[ -n "${LOG_BOT_TOKEN}" && "${LOG_BOT_TOKEN}" != "None" ]] && \
       ! is_placeholder "LOG_BOT_TOKEN" "${LOG_BOT_TOKEN}"; then
        logs_currently_configured=1
    fi

    local configure_logs=0
    if (( logs_currently_configured == 1 )); then
        if ask_yes_no "Log bot is currently configured. Reconfigure it? [y/N]: " "n"; then
            configure_logs=1
        fi
    else
        if ask_yes_no "Enable log bot now? [y/N]: " "n"; then
            configure_logs=1
        fi
    fi

    if (( configure_logs == 1 )); then
        if ! is_placeholder "LOG_BOT_TOKEN" "${LOG_BOT_TOKEN}" && \
           [[ -n "${LOG_BOT_TOKEN}" ]]; then
            describe "A LOG_BOT_TOKEN is already set. Press Enter to keep it."
            local keep_choice=""
            printf 'Keep current LOG_BOT_TOKEN? [Y/n]: ' > /dev/tty
            if ! IFS= read -r keep_choice <&3; then
                die "Could not read input from the terminal."
            fi
            keep_choice="${keep_choice,,}"
            if [[ "${keep_choice}" == "n" || "${keep_choice}" == "no" ]]; then
                prompt_for_secret "LOG_BOT_TOKEN" LOG_BOT_TOKEN
                set_config_value "LOG_BOT_TOKEN" "${LOG_BOT_TOKEN}"
                changed=1
            else
                printf 'LOG_BOT_TOKEN            : %b(kept existing value)%b\n' \
                    "${GREEN}" "${NC}"
            fi
        else
            prompt_for_secret "LOG_BOT_TOKEN" LOG_BOT_TOKEN
            set_config_value "LOG_BOT_TOKEN" "${LOG_BOT_TOKEN}"
            changed=1
        fi

        if [[ "${LOG_CHANNEL_ID}" =~ ^-?[0-9]+$ ]]; then
            describe "A LOG_CHANNEL_ID is already set (${LOG_CHANNEL_ID}). Press Enter to keep it."
            local keep_cid=""
            printf 'Keep current LOG_CHANNEL_ID? [Y/n]: ' > /dev/tty
            if ! IFS= read -r keep_cid <&3; then
                die "Could not read input from the terminal."
            fi
            keep_cid="${keep_cid,,}"
            if [[ "${keep_cid}" == "n" || "${keep_cid}" == "no" ]]; then
                prompt_log_channel_id
                if [[ "${LOG_CHANNEL_ID}" == "None" ]]; then
                    set_config_literal "LOG_CHANNEL_ID" "None"
                else
                    set_config_integer "LOG_CHANNEL_ID" "${LOG_CHANNEL_ID}"
                fi
                changed=1
            else
                printf 'LOG_CHANNEL_ID           : %b(kept existing value)%b\n' \
                    "${GREEN}" "${NC}"
            fi
        else
            prompt_log_channel_id
            if [[ "${LOG_CHANNEL_ID}" == "None" ]]; then
                set_config_literal "LOG_CHANNEL_ID" "None"
            else
                set_config_integer "LOG_CHANNEL_ID" "${LOG_CHANNEL_ID}"
            fi
            changed=1
        fi
    else
        if [[ "${LOG_BOT_TOKEN}" != "" ]]; then
            set_config_value "LOG_BOT_TOKEN" ""
            changed=1
        fi
        if [[ "${LOG_CHANNEL_ID}" != "None" ]]; then
            set_config_literal "LOG_CHANNEL_ID" "None"
            changed=1
        fi
        printf 'LOG_BOT_TOKEN            : %b(disabled)%b\n' "${DIM}" "${NC}"
        printf 'LOG_CHANNEL_ID           : %b(disabled)%b\n' "${DIM}" "${NC}"
    fi

    # ---------------------------------------------------------
    # Optional: Gemini AI
    # ---------------------------------------------------------
    draw_step "Optional: Google Gemini AI"

    describe "GEMINI_ENABLED: enable AI responses via Google Gemini."
    describe "GEMINI_API_KEY: Get from https://ai.google.dev/"
    printf '\n'

    local configure_ai=0
    if [[ "${GEMINI_ENABLED}" == "True" ]] && \
       ! is_placeholder "GEMINI_API_KEY" "${GEMINI_API_KEY}"; then
        describe "Currently ENABLED."
        if ask_yes_no "Keep Gemini AI enabled? [Y/n]: " "y"; then
            configure_ai=2
        fi
    else
        if ask_yes_no "Enable Gemini AI now? [y/N]: " "n"; then
            configure_ai=1
        fi
    fi

    if (( configure_ai >= 1 )); then
        set_config_boolean "GEMINI_ENABLED" "True"
        changed=1

        if (( configure_ai == 1 )) || is_placeholder "GEMINI_API_KEY" "${GEMINI_API_KEY}"; then
            describe "GEMINI_API_KEY: Get from https://ai.google.dev/"
            prompt_for_secret "GEMINI_API_KEY" GEMINI_API_KEY
            set_config_value "GEMINI_API_KEY" "${GEMINI_API_KEY}"
            changed=1
        else
            printf 'GEMINI_API_KEY           : %b(kept existing value)%b\n' "${GREEN}" "${NC}"
        fi

        describe "GEMINI_MODEL: any Gemini model, e.g. gemini-2.5-flash"
        prompt_with_default "GEMINI_MODEL" "${GEMINI_MODEL:-gemini-2.5-flash}" GEMINI_MODEL
        set_config_value "GEMINI_MODEL" "${GEMINI_MODEL}"
        changed=1

        describe "GEMINI_TEMPERATURE: randomness (0.0 to 1.0)"
        prompt_float "GEMINI_TEMPERATURE" "${GEMINI_TEMPERATURE:-0.7}" GEMINI_TEMPERATURE
        set_config_float "GEMINI_TEMPERATURE" "${GEMINI_TEMPERATURE}"
        changed=1

        describe "GEMINI_MAX_TOKENS: maximum response length"
        prompt_positive_int "GEMINI_MAX_TOKENS" "${GEMINI_MAX_TOKENS:-90}" GEMINI_MAX_TOKENS
        set_config_integer "GEMINI_MAX_TOKENS" "${GEMINI_MAX_TOKENS}"
        changed=1

        describe "GEMINI_DAILY_LIMIT: max AI responses per user per day"
        prompt_positive_int "GEMINI_DAILY_LIMIT" "${GEMINI_DAILY_LIMIT:-3}" GEMINI_DAILY_LIMIT
        set_config_integer "GEMINI_DAILY_LIMIT" "${GEMINI_DAILY_LIMIT}"
        changed=1
    else
        if [[ "${GEMINI_ENABLED}" != "False" ]]; then
            set_config_boolean "GEMINI_ENABLED" "False"
            changed=1
        fi
        printf 'GEMINI_ENABLED           : %b(disabled)%b\n' "${DIM}" "${NC}"
    fi

    chmod 600 "${CONFIG_FILE}"

    if (( changed == 1 )); then
        log_success "config.py was updated in place."
    else
        log_success "config.py needed no changes."
    fi
}

# ============================================================
# Config key migration (AST-based)
# ============================================================

migrate_config_keys() {
    [[ -f "${CONFIG_FILE}" ]] || return 0
    [[ -f "${RELEASE_ROOT}/config.py" ]] || return 0

    local missing
    missing="$(python3 - "${INSTALL_DIR}" "${CONFIG_FILE}" \
                          "${RELEASE_ROOT}/config.py" \
                          "${VENV_DIR}" "${DATA_DIR}" <<'PY'
import ast, os, sys
install_dir, config_path, release_config, venv_dir, data_dir = sys.argv[1:6]

with open(config_path, "r", encoding="utf-8") as f:
    cfg_tree = ast.parse(f.read())
defined = set()
for node in cfg_tree.body:
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name):
                defined.add(t.id)

with open(release_config, "r", encoding="utf-8") as f:
    rel_src = f.read()
rel_tree = ast.parse(rel_src)
release_keys = set()
for node in rel_tree.body:
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name):
                release_keys.add(t.id)

used = set()
for root, dirs, files in os.walk(install_dir):
    dirs[:] = [d for d in dirs
               if os.path.join(root, d) not in (venv_dir, data_dir)]
    for fn in files:
        if not fn.endswith(".py"):
            continue
        path = os.path.join(root, fn)
        try:
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read())
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name) and node.value.id == "config":
                    used.add(node.attr)
            elif isinstance(node, ast.ImportFrom):
                if node.module == "config":
                    for alias in node.names:
                        used.add(alias.name)

for key in sorted(used - defined):
    if key in release_keys:
        print(key)
PY
    )" || true

    if [[ -z "${missing}" ]]; then
        return 0
    fi

    log_warning "Missing config.py keys detected: $(echo "${missing}" | tr '\n' ' ')"

    printf '%s\n' "${missing}" \
        | python3 - "${CONFIG_FILE}" "${RELEASE_ROOT}/config.py" <<'PY'
import ast, sys

config_path = sys.argv[1]
release_config = sys.argv[2]
missing = set(line.strip() for line in sys.stdin if line.strip())

with open(release_config, "r", encoding="utf-8") as f:
    rel_src = f.read()
rel_tree = ast.parse(rel_src)

to_add = []
for node in rel_tree.body:
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id in missing:
                seg = ast.get_source_segment(rel_src, node)
                if seg:
                    to_add.append(seg)

if to_add:
    with open(config_path, "a", encoding="utf-8") as f:
        f.write("\n# === Added by installer (missing keys from release) ===\n")
        for line in to_add:
            f.write(line + "\n")
PY

    log_success "Missing config.py keys were added from release."
}

# ============================================================
# Validation
# ============================================================

validate_config_syntax() {
    [[ -f "${CONFIG_FILE}" ]] || die "config.py does not exist."
    if ! "${VENV_DIR}/bin/python" -m py_compile "${CONFIG_FILE}" >/dev/null 2>&1; then
        die "config.py contains a Python syntax error."
    fi
    log_success "config.py syntax is valid."
}

validate_python_source() {
    draw_step "Validating Python Source"

    local failed=0 pyfile
    while IFS= read -r -d '' pyfile; do
        if ! "${VENV_DIR}/bin/python" -m py_compile "${pyfile}" >/dev/null 2>&1; then
            printf '%b[FAIL]%b Python syntax error: %s\n' \
                "${RED}" "${NC}" "${pyfile}" >&2
            write_log "FAIL" "Python syntax error: ${pyfile}"
            failed=1
        fi
    done < <(
        find "${INSTALL_DIR}" \
            -path "${VENV_DIR}" -prune -o \
            -path "${DATA_DIR}" -prune -o \
            -type f -name '*.py' -print0
    )

    (( failed == 0 )) || die "One or more Python files contain syntax errors."
    log_success "All Python source files passed syntax validation."
}

validate_application_layout() {
    draw_step "Validating Application Layout"

    [[ -f "${INSTALL_DIR}/main.py" ]] || die "main.py is missing."
    [[ -f "${INSTALL_DIR}/requirements.txt" ]] || die "requirements.txt is missing."
    [[ -f "${CONFIG_FILE}" ]] || die "config.py is missing."
    [[ -x "${VENV_DIR}/bin/python" ]] || die "Virtual environment is invalid."

    log_success "Application layout is valid."
}

# ============================================================
# Fresh install
# ============================================================

prepare_install_directory() {
    mkdir -p "${INSTALL_DIR}"
    chmod 755 "${INSTALL_DIR}"
}

fresh_install() {
    draw_step "Fresh Installation"

    if [[ -d "${BACKUP_ROOT}" ]]; then
        local count
        count="$(find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)"
        if (( count > 0 )); then
            log_warning "Existing backups were found in ${BACKUP_ROOT}."
            log_warning "Backup count: ${count}"
            printf '\n%s\n%s\n\n' \
                "A fresh installation will NOT use those backups." \
                "Restore a backup manually if you need it."
            if ! ask_yes_no "Continue with a fresh installation anyway? [y/N]: " "n"; then
                log_warning "Fresh installation cancelled by user."
                exit 0
            fi
        fi
    fi

    validate_release_for_install
    prepare_install_directory

    # Preserve existing config values (only values, not the file itself).
    local saved_config=""
    if [[ -f "${CONFIG_FILE}" ]]; then
        saved_config="${TEMP_ROOT}/config.py.saved"
        cp -a "${CONFIG_FILE}" "${saved_config}"
        log_warning "Existing config.py detected — its values will be preserved."
    fi

    log_info "Cleaning previous application files (data/, .venv/, *.log preserved)..."
    find "${INSTALL_DIR}" -mindepth 1 -maxdepth 1 \
        ! -name 'data' \
        ! -name '.venv' \
        ! -name '*.log' \
        -exec rm -rf {} + 2>/dev/null || true

    log_info "Copying release files into ${INSTALL_DIR}..."
    rsync -a "${RELEASE_ROOT}/" "${INSTALL_DIR}/"

    if [[ -n "${saved_config}" && -f "${saved_config}" && -f "${CONFIG_FILE}" ]]; then
        log_info "Re-applying existing values onto the release config.py..."
        apply_config_values "${saved_config}" "${CONFIG_FILE}" || \
            log_warning "Could not re-apply values from the old config.py."
        chmod 600 "${CONFIG_FILE}"
    fi

    mkdir -p "${DATA_DIR}"
    ensure_data_configs_file

    create_virtual_environment_if_needed

    if (( SKIP_CONFIG == 0 )); then
        configure_config_in_place
    else
        log_warning "Configuration prompts were skipped."
        log_warning "Edit ${CONFIG_FILE} manually before starting the service."
    fi

    validate_application_layout
    validate_config_syntax
    install_requirements
    validate_python_source

    fix_permissions
    create_systemd_service

    if ! start_service_and_check; then
        die "Fresh installation completed, but the service failed to start."
    fi

    write_version_file
    CURRENT_VERSION="${LATEST_VERSION}"
    log_success "Fresh installation completed successfully."
}

# ============================================================
# Update
# ============================================================

update_existing() {
    draw_step "Updating Existing VeloraBot"

    [[ -d "${INSTALL_DIR}" ]] || die "${INSTALL_DIR} does not exist."

    validate_release_for_update
    create_virtual_environment_if_needed

    # 1) Stop service first.
    stop_service_if_active

    # 2) Save current config.py so we can re-apply values after the sync.
    local saved_config=""
    if [[ -f "${CONFIG_FILE}" ]]; then
        saved_config="${TEMP_ROOT}/config.py.saved"
        cp -a "${CONFIG_FILE}" "${saved_config}"
        log_info "Saved current config.py for value restoration."
    fi

    # 3) Backup (code + data + freeze + current config inside the tar).
    UPDATE_IN_PROGRESS=1
    if ! create_backup; then
        UPDATE_IN_PROGRESS=0
        if (( SERVICE_WAS_ACTIVE == 1 )); then
            systemctl start "${SERVICE_NAME}" >/dev/null 2>&1 || true
        fi
        die "Backup failed; aborting update."
    fi

    # 4) Sync code — INCLUDING config.py from the release.
    #    Values will be re-applied right after.
    draw_step "Synchronizing Application Files"
    log_info "Synchronizing commit ${LATEST_VERSION} (config.py included)..."

    local excludes=()
    while IFS= read -r line; do excludes+=("${line}"); done < <(rsync_excludes_update)

    rsync -a --delete "${excludes[@]}" \
        "${RELEASE_ROOT}/" "${INSTALL_DIR}/"

    log_success "Application files synchronized."

    # 5) Re-apply user values from the saved config onto the new file.
    if [[ -f "${RELEASE_ROOT}/config.py" ]]; then
        update_config_file_with_backup "${RELEASE_ROOT}/config.py" "${saved_config}"
    fi

    # If config.py is still missing entirely, fall back to the release file.
    if [[ ! -f "${CONFIG_FILE}" ]]; then
        log_warning "config.py is missing. Restoring from release..."
        if [[ -f "${RELEASE_ROOT}/config.py" ]]; then
            cp -a "${RELEASE_ROOT}/config.py" "${CONFIG_FILE}"
            chmod 600 "${CONFIG_FILE}"
            log_info "config.py restored from release."
        else
            die "config.py is missing from the release as well."
        fi
    fi

    migrate_config_keys

    local config_ok=0
    if extract_config_values && validate_existing_config; then
        config_ok=1
    fi

    if (( config_ok == 0 )); then
        log_warning "config.py contains missing or invalid values."
        printf '\n'
        if ask_yes_no "Fix config.py now? [Y/n]: " "y"; then
            configure_config_in_place
        else
            die "Cannot continue without a valid config.py."
        fi
    else
        log_success "Existing configuration appears valid."
    fi

    if [[ -d "${DATA_DIR}" && ! -f "${DATA_DIR}/configs.json" ]]; then
        printf '{}\n' > "${DATA_DIR}/configs.json"
        chmod 600 "${DATA_DIR}/configs.json"
        log_info "Created placeholder data/configs.json."
    fi

    draw_step "Synchronizing Python Dependencies"
    log_info "Installing release requirements into .venv..."
    "${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel
    "${VENV_DIR}/bin/python" -m pip install -r "${INSTALL_DIR}/requirements.txt"
    "${VENV_DIR}/bin/python" -m pip check || \
        log_warning "pip check reported inconsistencies (continuing)."
    log_success "Python dependencies are synchronized."

    validate_application_layout
    validate_config_syntax
    validate_python_source

    fix_permissions
    create_systemd_service

    # Health check FIRST, then write .version.
    if ! start_service_and_check; then
        die "Updated application failed the service health check."
    fi

    write_version_file
    UPDATE_IN_PROGRESS=0
    CURRENT_VERSION="${LATEST_VERSION}"
    log_success "VeloraBot was updated successfully."
}

# ============================================================
# Existing install dispatch
# ============================================================

show_existing_status() {
    draw_header "Existing VeloraBot Installation"
    printf 'Installation directory : %s\n' "${INSTALL_DIR}"
    printf 'Installed commit       : %s\n' "${CURRENT_VERSION}"
    printf 'Latest main commit     : %s\n' "${LATEST_VERSION}"
    printf '\n'
}

handle_existing_installation() {
    read_current_version
    show_existing_status

    local config_valid=0
    if [[ -f "${CONFIG_FILE}" ]]; then
        log_info "Validating existing config.py..."
        if extract_config_values && validate_existing_config; then
            log_success "Existing configuration appears valid."
            config_valid=1
        else
            log_warning "Existing configuration contains missing or invalid values."
        fi
    else
        log_warning "config.py is missing from the existing installation."
    fi

    if (( config_valid == 0 )); then
        printf '\n'
        if ask_yes_no "Fix config.py now? [Y/n]: " "y"; then
            if [[ ! -f "${CONFIG_FILE}" ]]; then
                if [[ -f "${RELEASE_ROOT}/config.py" ]]; then
                    cp -a "${RELEASE_ROOT}/config.py" "${CONFIG_FILE}"
                    chmod 600 "${CONFIG_FILE}"
                    log_info "config.py restored from release."
                else
                    die "config.py is missing from the release as well."
                fi
            fi
            configure_config_in_place
        else
            die "Cannot continue without a valid config.py."
        fi
    fi

    if (( FORCE_UPDATE == 0 )) && versions_equal "${CURRENT_VERSION}" "${LATEST_VERSION}"; then
        draw_header "VeloraBot Status"
        log_success "VeloraBot is already up to date."
        printf 'Installed commit : %s\n' "${CURRENT_VERSION}"
        printf 'Latest commit    : %s\n' "${LATEST_VERSION}"
        printf '\n%s\n' "No files were changed."
        return 0
    fi

    printf '\n'
    printf 'Current commit : %s\n' "${CURRENT_VERSION}"
    printf 'Latest commit  : %s\n' "${LATEST_VERSION}"
    printf '\n'

    if (( FORCE_UPDATE == 1 )); then
        log_warning "Force update is enabled."
        update_existing
        return
    fi

    if versions_equal "${CURRENT_VERSION}" "${LATEST_VERSION}"; then
        log_info "The installed commit matches the latest commit."
        log_info "No update is required."
        return 0
    fi

    if ask_yes_no "Update VeloraBot to ${LATEST_VERSION}? [Y/n]: " "y"; then
        update_existing
    else
        log_warning "Update cancelled by user. No files were changed."
        return 0
    fi
}

# ============================================================
# Repair
# ============================================================

repair_only() {
    draw_step "Repairing Existing VeloraBot"
    [[ -d "${INSTALL_DIR}" ]] || die "${INSTALL_DIR} does not exist."
    create_virtual_environment_if_needed

    if [[ ! -f "${CONFIG_FILE}" ]]; then
        log_warning "config.py is missing. Restoring from release..."
        if [[ -f "${RELEASE_ROOT}/config.py" ]]; then
            cp -a "${RELEASE_ROOT}/config.py" "${CONFIG_FILE}"
            chmod 600 "${CONFIG_FILE}"
        else
            die "config.py is missing from the release as well."
        fi
    fi

    migrate_config_keys

    local config_ok=0
    if extract_config_values && validate_existing_config; then
        config_ok=1
    fi

    if (( config_ok == 0 )); then
        if ask_yes_no "Fix config.py now? [Y/n]: " "y"; then
            configure_config_in_place
        else
            die "Cannot continue without a valid config.py."
        fi
    fi

    install_requirements
    validate_application_layout
    validate_config_syntax
    validate_python_source
    fix_permissions
    create_systemd_service

    if ! start_service_and_check; then
        die "Repair failed: service did not start."
    fi

    log_success "Repair completed successfully."
}

# ============================================================
# Summary
# ============================================================

show_final_summary() {
    draw_header "VeloraBot Installation Summary"

    printf 'Repository       : %s\n' "${REPO_URL}"
    printf 'Release          : %s\n' "${CURRENT_VERSION}"
    printf 'Install directory: %s\n' "${INSTALL_DIR}"
    printf 'Virtual env      : %s\n' "${VENV_DIR}"
    printf 'Config           : %s\n' "${CONFIG_FILE}"
    printf 'Persistent data  : %s\n' "${DATA_DIR}"
    printf 'Service          : %s\n' "${SERVICE_NAME}"
    printf 'Service user     : %s\n' "${SERVICE_USER}"
    printf 'Installer log    : %s\n' "${LOG_FILE}"
    printf '\n'

    printf '%s\n' "Update protection:"
    printf '  config.py      : release version installed, user values preserved\n'
    printf '  data/          : never touched (backed up on update)\n'
    printf '  *.log          : never touched (excluded from rsync/tar)\n'
    printf '  .venv/         : preserved\n'
    printf '  updates        : require explicit user consent\n'
    printf '\n'

    if service_is_active; then
        log_success "Service status: active"
    else
        log_warning "Service status: inactive"
    fi

    printf '\n%s\n' "Useful commands:"
    printf '  systemctl status %s\n'  "${SERVICE_NAME}"
    printf '  systemctl restart %s\n' "${SERVICE_NAME}"
    printf '  systemctl stop %s\n'    "${SERVICE_NAME}"
    printf '  journalctl -u %s -f\n'   "${SERVICE_NAME}"
    printf '\n'

    if [[ -n "${BACKUP_DIR}" && -d "${BACKUP_DIR}" ]]; then
        printf 'Latest backup    : %s\n\n' "${BACKUP_DIR}"
    fi

    draw_line
}

# ============================================================
# Main
# ============================================================

main() {
    initialize_logging
    parse_arguments "$@"
    open_tty

    draw_header "VeloraBot Installer / Updater"
    printf 'Repository: %s\n\n' "${REPO_URL}"

    log_info "Installer started."
    log_info "Requested mode: ${SCRIPT_MODE}"

    check_root
    check_operating_system

    # Show the interactive management panel when no explicit action was given.
    if [[ "${SCRIPT_MODE}" == "auto" ]] && \
       (( FORCE_UPDATE == 0 )) && \
       (( REPAIR_ONLY == 0 )); then
        show_management_panel
    fi

    install_system_dependencies
    check_python_version
    check_github_connectivity

    TEMP_ROOT="$(mktemp -d /tmp/velorabot-installer.XXXXXX)"

    fetch_latest_commit
    download_latest_commit
    read_current_version

    if (( REPAIR_ONLY == 1 )); then
        repair_only
        show_final_summary
        log_success "Repair finished successfully."
        return 0
    fi

    local has_install=0
    if [[ -d "${INSTALL_DIR}" && -f "${INSTALL_DIR}/main.py" ]]; then
        has_install=1
    fi

    case "${SCRIPT_MODE}" in
        install)
            if (( has_install == 1 )); then
                die "Cannot perform --install: an installation already exists."
            fi
            fresh_install
            ;;

        update)
            if (( has_install == 0 )); then
                die "Cannot perform --update: no existing installation was found."
            fi
            update_existing
            ;;

        auto)
            die "Internal error: 'auto' mode reached the dispatch stage."
            ;;

        *)
            die "Internal error: unsupported mode '${SCRIPT_MODE}'."
            ;;
    esac

    show_final_summary
    log_success "Installer finished successfully."
}

main "$@"