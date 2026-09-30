#!/usr/bin/env bash

set -Eeuo pipefail
IFS=$'\n\t'

# ============================================================
# VeloraBot — Universal Installer / Updater / Repairer
# ============================================================
# Source of truth:
#   https://github.com/navidmn56/VeloraBot (main branch)
#
# Architecture:
#   * /dev/tty is opened on FD 3 for all interactive prompts.
#   * stdin is never modified, so `curl ... | sudo bash` works
#     and the SSH session is never closed.
#   * config.py is taken from the GitHub release and edited
#     in place: only values change, comments and structure are
#     preserved.
#   * data/ is never touched by any operation.
#   * Updates require explicit user consent.
#   * Missing files are restored from the release.
# ============================================================

# ============================================================
# Terminal Handling (FD 3 based, SSH-safe)
# ============================================================

open_tty() {
    if [[ ! -r /dev/tty || ! -w /dev/tty ]]; then
        printf '%s\n' "ERROR: An interactive terminal is required." >&2
        exit 1
    fi

    # باز کردن /dev/tty فقط برای خواندن روی FD 3
    # stdin دست‌نخورده می‌ماند → curl | sudo bash کار می‌کند و SSH نمی‌بندد
    exec 3< /dev/tty
}

close_tty() {
    exec 3<&- 2>/dev/null || true
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
# Application Constants
# ============================================================

readonly APP_NAME="VeloraBot"
readonly OWNER="navidmn56"
readonly REPO="VeloraBot"
readonly REPO_FULL="${OWNER}/${REPO}"
readonly BRANCH="main"

readonly REPO_URL="https://github.com/${REPO_FULL}"
readonly COMMITS_API="https://api.github.com/repos/${REPO_FULL}/commits/${BRANCH}"
readonly ZIP_URL="https://codeload.github.com/${REPO_FULL}/zip/refs/heads/${BRANCH}"

readonly INSTALL_DIR="/opt/VeloraBot"
readonly VENV_DIR="${INSTALL_DIR}/.venv"
readonly CONFIG_FILE="${INSTALL_DIR}/config.py"
readonly DATA_DIR="${INSTALL_DIR}/data"
readonly VERSION_FILE="${INSTALL_DIR}/.version"

readonly SERVICE_NAME="velorabot"
readonly SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

readonly BACKUP_ROOT="/opt/VeloraBot-backups"
readonly LOG_FILE="/var/log/velorabot-installer.log"
readonly FALLBACK_LOG_FILE="/tmp/velorabot-installer.log"

# ============================================================
# Runtime State
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

# ============================================================
# Configuration State
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

# ============================================================
# Logging
# ============================================================

initialize_logging() {
    if ! mkdir -p "$(dirname "${LOG_FILE}")" 2>/dev/null; then
        LOG_FILE="${FALLBACK_LOG_FILE}"
    fi
    if ! touch "${LOG_FILE}" 2>/dev/null; then
        LOG_FILE="${FALLBACK_LOG_FILE}"
        touch "${LOG_FILE}" || true
    fi
    chmod 600 "${LOG_FILE}" 2>/dev/null || true
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
# Cleanup / Rollback
# ============================================================

cleanup_temp() {
    if [[ -n "${TEMP_ROOT}" && -d "${TEMP_ROOT}" ]]; then
        rm -rf -- "${TEMP_ROOT}"
    fi
}

restore_application_backup() {
    [[ "${BACKUP_READY}" -eq 1 ]] || return 1
    [[ -n "${BACKUP_DIR}" ]] || return 1
    [[ -f "${BACKUP_DIR}/application.tar.gz" ]] || return 1

    local rollback_root="${TEMP_ROOT}/rollback"
    rm -rf -- "${rollback_root}"
    mkdir -p "${rollback_root}"

    log_info "Restoring application files from backup..."
    tar -xzf "${BACKUP_DIR}/application.tar.gz" -C "${rollback_root}"

    mkdir -p "${INSTALL_DIR}"

    rsync -a --delete \
        --exclude='data' \
        --exclude='.venv' \
        --exclude='.version' \
        "${rollback_root}/" \
        "${INSTALL_DIR}/"

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

    if [[ -f "${BACKUP_DIR}/requirements.txt" && -x "${VENV_DIR}/bin/python" ]]; then
        log_info "Restoring previous Python dependencies..."
        if ! "${VENV_DIR}/bin/python" -m pip install \
            -r "${BACKUP_DIR}/requirements.txt" \
            >>"${LOG_FILE}" 2>&1; then
            log_warning "Previous Python dependencies could not be fully restored."
        fi
    fi

    systemctl daemon-reload >/dev/null 2>&1 || true
    log_success "Application rollback completed."
    return 0
}

on_exit() {
    local exit_code=$?

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

# ============================================================
# Input Helpers — FD 3 based, works in curl|bash
# ============================================================

read_tty() {
    # Prefixed names on purpose: bash uses dynamic scoping, so a local with the
    # same name as the caller's target variable would shadow it.
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
    stty -echo < /dev/tty 2>/dev/null || true

    IFS= read -r _rs_value <&3 || _rs_rc=1

    if [[ -n "${_rs_stty_state}" ]]; then
        stty "${_rs_stty_state}" < /dev/tty 2>/dev/null || true
    else
        stty echo < /dev/tty 2>/dev/null || true
    fi
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
# Argument Parsing
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
# Environment Checks
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
    apt-get update -qq

    log_command "Installing required packages"
    apt-get install -y -qq \
        ca-certificates curl unzip rsync python3 python3-pip \
        python3-venv python3-dev build-essential libssl-dev libffi-dev

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
# GitHub main Branch Handling
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
    draw_step "Downloading Latest ${BRANCH} Branch"
    local archive="${TEMP_ROOT}/main.zip"
    local extract_dir="${TEMP_ROOT}/main"
    mkdir -p "${extract_dir}"

    log_info "Downloading ${BRANCH} branch (${LATEST_VERSION})..."

    curl --fail --silent --show-error --location \
        --retry 4 --retry-delay 2 \
        --connect-timeout 15 --max-time 300 \
        "${ZIP_URL}" -o "${archive}"

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
# Version Handling
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

create_backup() {
    local ts
    ts="$(date '+%Y%m%d_%H%M%S')"
    BACKUP_DIR="${BACKUP_ROOT}/${ts}_${LATEST_VERSION}"
    mkdir -p "${BACKUP_DIR}"

    draw_step "Creating Update Backup"
    log_info "Creating application source backup..."

    tar -czf "${BACKUP_DIR}/application.tar.gz" \
        --exclude='./.venv' \
        --exclude='./data' \
        -C "${INSTALL_DIR}" .

    if [[ -f "${INSTALL_DIR}/requirements.txt" ]]; then
        cp -a "${INSTALL_DIR}/requirements.txt" "${BACKUP_DIR}/requirements.txt"
    fi

    if [[ -f "${SERVICE_FILE}" ]]; then
        cp -a "${SERVICE_FILE}" "${BACKUP_DIR}/service"
        SERVICE_BACKUP_EXISTS=1
    else
        SERVICE_BACKUP_EXISTS=0
    fi

    chmod 600 "${BACKUP_DIR}"/*.tar.gz 2>/dev/null || true
    chmod 600 "${BACKUP_DIR}/requirements.txt" 2>/dev/null || true
    chmod 600 "${BACKUP_DIR}/service" 2>/dev/null || true

    BACKUP_READY=1
    log_success "Backup created: ${BACKUP_DIR}"
}

# ============================================================
# Service Management
# ============================================================

service_is_active() { systemctl is-active --quiet "${SERVICE_NAME}"; }

stop_service_if_active() {
    SERVICE_WAS_ACTIVE=0
    if service_is_active; then
        SERVICE_WAS_ACTIVE=1
        log_info "Stopping ${SERVICE_NAME}..."
        systemctl stop "${SERVICE_NAME}"
        log_success "Service stopped."
    else
        log_info "Service is not currently running."
    fi
}

create_systemd_service() {
    draw_step "Configuring systemd"
    cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=VeloraBot Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=${VENV_DIR}/bin/python ${INSTALL_DIR}/main.py
Restart=always
RestartSec=5
TimeoutStopSec=30
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

    chmod 644 "${SERVICE_FILE}"
    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}" >/dev/null
    log_success "systemd service configured."
}

start_service_and_check() {
    draw_step "Starting VeloraBot"
    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}" >/dev/null
    systemctl restart "${SERVICE_NAME}"
    sleep 6

    if service_is_active; then
        log_success "${SERVICE_NAME} is running."
        return 0
    fi

    log_error "${SERVICE_NAME} failed to start."
    printf '\n%s\n%s\n' "Recent service logs:" "------------------------------------------------------------"
    journalctl -u "${SERVICE_NAME}" -n 100 --no-pager || true
    printf '%s\n' "------------------------------------------------------------"
    return 1
}

# ============================================================
# Python Virtual Environment
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
    "${VENV_DIR}/bin/python" -m pip check

    log_success "Python dependencies are installed and verified."
}

ensure_data_configs_file() {
    if [[ ! -f "${DATA_DIR}/configs.json" ]]; then
        printf '{}\n' > "${DATA_DIR}/configs.json"
        chmod 600 "${DATA_DIR}/configs.json"
        log_info "Created placeholder data/configs.json."
    fi
}

# ============================================================
# Configuration Helpers
# ============================================================

is_placeholder() {
    local value="$1"
    case "${value}" in
        ""|"Main_bot_token"|"YOUR_TELEGRAM_USER_ID"|"Log_bot_token"|\
        "676778785656565656"|"Navid"|"Blue Bank"|"Panel_username"|\
        "Panel_password"|"Gemini_API_Key"|"@your_username_here"|\
        "1234567812345678")
            return 0
            ;;
        *) return 1 ;;
    esac
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

    config_value() {
        local key="$1"
        local default="${2:-}"
        python3 - "${values}" "${key}" "${default}" <<'PY'
import json, sys
try:
    data = json.loads(sys.argv[1])
    key = sys.argv[2]
    default = sys.argv[3]
    value = data.get(key, default)
    if isinstance(value, bool):
        print("True" if value else "False")
    elif value is None:
        print("None")
    else:
        print(value)
except Exception:
    print(sys.argv[3])
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
}

validate_existing_config() {
    local missing=0
    printf '%s\n' "Checking existing configuration..."

    is_placeholder "${BOT_TOKEN}"        && { printf '  %bMISSING%b BOT_TOKEN\n'        "${RED}" "${NC}"; missing=1; }
    [[ "${ADMIN_ID}" =~ ^[0-9]+$ ]]      || { printf '  %bINVALID%b ADMIN_ID\n'         "${RED}" "${NC}"; missing=1; }
    is_placeholder "${LOG_BOT_TOKEN}"    && { printf '  %bMISSING%b LOG_BOT_TOKEN\n'    "${RED}" "${NC}"; missing=1; }
    [[ "${LOG_CHANNEL_ID}" =~ ^-?[0-9]+$ || "${LOG_CHANNEL_ID}" == "None" ]] \
                                          || { printf '  %bINVALID%b LOG_CHANNEL_ID\n'  "${RED}" "${NC}"; missing=1; }
    [[ "${BANK_CARD_NUMBER}" =~ ^[0-9]{16}$ ]] \
                                          || { printf '  %bINVALID%b BANK_CARD_NUMBER\n' "${RED}" "${NC}"; missing=1; }
    is_placeholder "${BANK_CARD_HOLDER}" && { printf '  %bMISSING%b BANK_CARD_HOLDER\n' "${RED}" "${NC}"; missing=1; }
    is_placeholder "${BANK_NAME}"        && { printf '  %bMISSING%b BANK_NAME\n'        "${RED}" "${NC}"; missing=1; }
    [[ "${SENAI_PANEL_URL}" =~ ^https?:// ]] \
                                          || { printf '  %bINVALID%b SENAI_PANEL_URL\n' "${RED}" "${NC}"; missing=1; }
    is_placeholder "${SENAI_PANEL_USERNAME}" \
                                          && { printf '  %bMISSING%b SENAI_PANEL_USERNAME\n' "${RED}" "${NC}"; missing=1; }
    is_placeholder "${SENAI_PANEL_PASSWORD}" \
                                          && { printf '  %bMISSING%b SENAI_PANEL_PASSWORD\n' "${RED}" "${NC}"; missing=1; }
    [[ "${SENAI_SUB_URL}" =~ ^https?:// ]] || { printf '  %bINVALID%b SENAI_SUB_URL\n'  "${RED}" "${NC}"; missing=1; }
    is_placeholder "${SUPPORT_USERNAME}" && { printf '  %bMISSING%b SUPPORT_USERNAME\n' "${RED}" "${NC}"; missing=1; }

    if [[ "${GEMINI_ENABLED}" == "True" ]] && is_placeholder "${GEMINI_API_KEY}"; then
        printf '  %bMISSING%b GEMINI_API_KEY\n' "${RED}" "${NC}"; missing=1
    fi

    return "${missing}"
}

# ============================================================
# Configuration Editors — edit values in place
# ============================================================

set_config_value() {
    local key="$1"
    local value="$2"
    CFG_KEY="${key}" CFG_VALUE="${value}" python3 - "${CONFIG_FILE}" <<'PY'
import os, re, sys
path = sys.argv[1]
key = os.environ["CFG_KEY"]
value = os.environ["CFG_VALUE"]

with open(path, "r", encoding="utf-8") as f:
    text = f.read()

replacement = f'{key} = {value!r}'
pattern = re.compile(rf"(?m)^([ \t]*){re.escape(key)}([ \t]*=[^\n]*)")

def repl(match):
    line = match.group(0)
    comment_idx = line.find("#")
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

set_config_integer() {
    local key="$1"
    local value="$2"
    CFG_KEY="${key}" CFG_VALUE="${value}" python3 - "${CONFIG_FILE}" <<'PY'
import os, re, sys
path = sys.argv[1]
key = os.environ["CFG_KEY"]
value = os.environ["CFG_VALUE"]

if not re.fullmatch(r"-?[0-9]+", value):
    raise SystemExit(f"{key} must be an integer.")

replacement = f"{key} = {int(value)}"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

pattern = re.compile(rf"(?m)^([ \t]*){re.escape(key)}([ \t]*=[^\n]*)")

def repl(match):
    line = match.group(0)
    comment_idx = line.find("#")
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

set_config_boolean() {
    local key="$1"
    local value="$2"
    CFG_KEY="${key}" CFG_VALUE="${value}" python3 - "${CONFIG_FILE}" <<'PY'
import os, re, sys
path = sys.argv[1]
key = os.environ["CFG_KEY"]
value = os.environ["CFG_VALUE"]

normalized = value.lower()
if normalized == "true":
    raw = "True"
elif normalized == "false":
    raw = "False"
else:
    raise SystemExit(f"{key} must be True or False.")

replacement = f"{key} = {raw}"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

pattern = re.compile(rf"(?m)^([ \t]*){re.escape(key)}([ \t]*=[^\n]*)")

def repl(match):
    line = match.group(0)
    comment_idx = line.find("#")
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

# ============================================================
# Prompt Helpers
# ============================================================

prompt_for_value() {
    local label="$1"
    local result_var="$2"
    local value=""

    while true; do
        if ! read_tty "${label}: " value; then
            die "Could not read input from the terminal."
        fi
        if [[ -n "${value}" ]]; then
            printf -v "${result_var}" '%s' "${value}"
            return 0
        fi
        log_warning "${label} cannot be empty."
    done
}

prompt_for_secret() {
    local label="$1"
    local result_var="$2"
    local value=""

    while true; do
        if ! read_secret_tty "${label}: " value; then
            die "Could not read input from the terminal."
        fi
        if [[ -n "${value}" ]]; then
            printf -v "${result_var}" '%s' "${value}"
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
        if [[ "${value}" =~ ^[0-9]+$ ]]; then
            ADMIN_ID="${value}"
            return
        fi
        log_warning "ADMIN_ID must contain digits only."
    done
}

prompt_log_channel_id() {
    local value=""
    printf '%s\n' "LOG_CHANNEL_ID can be left empty (press Enter) to disable logging."

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
        log_warning "LOG_CHANNEL_ID must be numeric or empty."
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

# ============================================================
# Configure VeloraBot — fill only missing/invalid fields in place
# ============================================================

configure_config_in_place() {
    draw_step "Configuring VeloraBot (editing config.py in place)"

    [[ -f "${CONFIG_FILE}" ]] || die "config.py does not exist."

    extract_config_values || true

    printf '%s\n' "The installer will only fill missing or invalid fields."
    printf '%s\n' "Existing valid values will be preserved."
    printf '\n'

    local changed=0

    if is_placeholder "${BOT_TOKEN}"; then
        prompt_for_secret "BOT_TOKEN" BOT_TOKEN
        set_config_value "BOT_TOKEN" "${BOT_TOKEN}"
        changed=1
    else
        printf 'BOT_TOKEN                : %b(kept existing value)%b\n' "${GREEN}" "${NC}"
    fi

    if [[ ! "${ADMIN_ID}" =~ ^[0-9]+$ ]]; then
        prompt_admin_id
        set_config_integer "ADMIN_ID" "${ADMIN_ID}"
        changed=1
    else
        printf 'ADMIN_ID                 : %b(kept existing value)%b\n' "${GREEN}" "${NC}"
    fi

    if is_placeholder "${LOG_BOT_TOKEN}"; then
        if ask_yes_no "Configure log bot token now? [y/N]: " "n"; then
            prompt_for_secret "LOG_BOT_TOKEN" LOG_BOT_TOKEN
            set_config_value "LOG_BOT_TOKEN" "${LOG_BOT_TOKEN}"
            changed=1

            if [[ ! "${LOG_CHANNEL_ID}" =~ ^-?[0-9]+$ && "${LOG_CHANNEL_ID}" != "None" ]]; then
                prompt_log_channel_id
                if [[ "${LOG_CHANNEL_ID}" == "None" ]]; then
                    set_config_value "LOG_CHANNEL_ID" "None"
                else
                    set_config_integer "LOG_CHANNEL_ID" "${LOG_CHANNEL_ID}"
                fi
                changed=1
            fi
        fi
    else
        printf 'LOG_BOT_TOKEN            : %b(kept existing value)%b\n' "${GREEN}" "${NC}"
        if [[ ! "${LOG_CHANNEL_ID}" =~ ^-?[0-9]+$ && "${LOG_CHANNEL_ID}" != "None" ]]; then
            prompt_log_channel_id
            if [[ "${LOG_CHANNEL_ID}" == "None" ]]; then
                set_config_value "LOG_CHANNEL_ID" "None"
            else
                set_config_integer "LOG_CHANNEL_ID" "${LOG_CHANNEL_ID}"
            fi
            changed=1
        fi
    fi

    if [[ ! "${BANK_CARD_NUMBER}" =~ ^[0-9]{16}$ ]]; then
        prompt_card_number
        set_config_value "BANK_CARD_NUMBER" "${BANK_CARD_NUMBER}"
        changed=1
    else
        printf 'BANK_CARD_NUMBER         : %b(kept existing value)%b\n' "${GREEN}" "${NC}"
    fi

    if is_placeholder "${BANK_CARD_HOLDER}"; then
        prompt_for_value "BANK_CARD_HOLDER" BANK_CARD_HOLDER
        set_config_value "BANK_CARD_HOLDER" "${BANK_CARD_HOLDER}"
        changed=1
    else
        printf 'BANK_CARD_HOLDER         : %b(kept existing value)%b\n' "${GREEN}" "${NC}"
    fi

    if is_placeholder "${BANK_NAME}"; then
        prompt_for_value "BANK_NAME" BANK_NAME
        set_config_value "BANK_NAME" "${BANK_NAME}"
        changed=1
    else
        printf 'BANK_NAME                : %b(kept existing value)%b\n' "${GREEN}" "${NC}"
    fi

    if ! [[ "${SENAI_PANEL_URL}" =~ ^https?:// ]]; then
        prompt_http_url "SENAI_PANEL_URL" SENAI_PANEL_URL
        set_config_value "SENAI_PANEL_URL" "${SENAI_PANEL_URL}"
        changed=1
    else
        printf 'SENAI_PANEL_URL          : %b(kept existing value)%b\n' "${GREEN}" "${NC}"
    fi

    if is_placeholder "${SENAI_PANEL_USERNAME}"; then
        prompt_for_value "SENAI_PANEL_USERNAME" SENAI_PANEL_USERNAME
        set_config_value "SENAI_PANEL_USERNAME" "${SENAI_PANEL_USERNAME}"
        changed=1
    else
        printf 'SENAI_PANEL_USERNAME     : %b(kept existing value)%b\n' "${GREEN}" "${NC}"
    fi

    if is_placeholder "${SENAI_PANEL_PASSWORD}"; then
        prompt_for_secret "SENAI_PANEL_PASSWORD" SENAI_PANEL_PASSWORD
        set_config_value "SENAI_PANEL_PASSWORD" "${SENAI_PANEL_PASSWORD}"
        changed=1
    else
        printf 'SENAI_PANEL_PASSWORD     : %b(kept existing value)%b\n' "${GREEN}" "${NC}"
    fi

    if ! [[ "${SENAI_SUB_URL}" =~ ^https?:// ]]; then
        prompt_http_url "SENAI_SUB_URL" SENAI_SUB_URL
        set_config_value "SENAI_SUB_URL" "${SENAI_SUB_URL}"
        changed=1
    else
        printf 'SENAI_SUB_URL            : %b(kept existing value)%b\n' "${GREEN}" "${NC}"
    fi

    if is_placeholder "${SUPPORT_USERNAME}"; then
        prompt_for_value "SUPPORT_USERNAME" SUPPORT_USERNAME
        set_config_value "SUPPORT_USERNAME" "${SUPPORT_USERNAME}"
        changed=1
    else
        printf 'SUPPORT_USERNAME         : %b(kept existing value)%b\n' "${GREEN}" "${NC}"
    fi

    if [[ "${GEMINI_ENABLED}" == "True" ]] && is_placeholder "${GEMINI_API_KEY}"; then
        prompt_for_secret "GEMINI_API_KEY" GEMINI_API_KEY
        set_config_value "GEMINI_API_KEY" "${GEMINI_API_KEY}"
        changed=1
    fi

    chmod 600 "${CONFIG_FILE}"

    if (( changed == 1 )); then
        log_success "config.py was updated in place."
    else
        log_success "config.py needed no changes."
    fi
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
# Fresh Installation
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

    if [[ -d "${INSTALL_DIR}" ]]; then
        log_info "Cleaning previous application files (data/ is preserved)..."
        find "${INSTALL_DIR}" -mindepth 1 -maxdepth 1 \
            ! -name 'data' \
            ! -name '.venv' \
            -exec rm -rf {} + 2>/dev/null || true
    fi

    log_info "Copying release files into ${INSTALL_DIR}..."
    rsync -a "${RELEASE_ROOT}/" "${INSTALL_DIR}/"

    mkdir -p "${DATA_DIR}"
    ensure_data_configs_file

    create_virtual_environment_if_needed

    if (( SKIP_CONFIG == 0 )); then
        configure_config_in_place
    else
        log_warning "Configuration prompts were skipped."
    fi

    validate_application_layout
    validate_config_syntax
    install_requirements
    validate_python_source

    create_systemd_service
    write_version_file

    if ! start_service_and_check; then
        die "Fresh installation completed, but the service failed to start."
    fi

    CURRENT_VERSION="${LATEST_VERSION}"
    log_success "Fresh installation completed successfully."
}

# ============================================================
# Update Existing Installation
# ============================================================

update_existing() {
    draw_step "Updating Existing VeloraBot"

    [[ -d "${INSTALL_DIR}" ]] || die "${INSTALL_DIR} does not exist."

    validate_release_for_update
    create_virtual_environment_if_needed

    UPDATE_IN_PROGRESS=1
    create_backup
    stop_service_if_active

    draw_step "Synchronizing Application Files"
    log_info "Synchronizing commit ${LATEST_VERSION}..."

    rsync -a --delete \
        --exclude='config.py' \
        --exclude='data' \
        --exclude='.venv' \
        --exclude='.version' \
        "${RELEASE_ROOT}/" \
        "${INSTALL_DIR}/"

    log_success "Application files synchronized."

    if [[ ! -f "${CONFIG_FILE}" ]]; then
        log_warning "config.py is missing from the server. Restoring from release..."
        if [[ -f "${RELEASE_ROOT}/config.py" ]]; then
            cp -a "${RELEASE_ROOT}/config.py" "${CONFIG_FILE}"
            chmod 600 "${CONFIG_FILE}"
            log_info "config.py restored from release."
        else
            die "config.py is missing from the release as well."
        fi
    fi

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
    "${VENV_DIR}/bin/python" -m pip check

    log_success "Python dependencies are synchronized."

    validate_application_layout
    validate_config_syntax
    validate_python_source

    create_systemd_service
    write_version_file

    if ! start_service_and_check; then
        die "Updated application failed the service health check."
    fi

    UPDATE_IN_PROGRESS=0
    CURRENT_VERSION="${LATEST_VERSION}"
    log_success "VeloraBot was updated successfully."
}

# ============================================================
# Existing Installation Handling
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
# Repair Only
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
    create_systemd_service

    if ! start_service_and_check; then
        die "Repair failed: service did not start."
    fi

    log_success "Repair completed successfully."
}

# ============================================================
# Final Summary
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
    printf 'Installer log    : %s\n' "${LOG_FILE}"
    printf '\n'

    printf '%s\n' "Update protection:"
    printf '  config.py      : values edited in place, file never regenerated\n'
    printf '  data/          : never touched\n'
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
            if (( has_install == 1 )); then
                handle_existing_installation
            else
                fresh_install
            fi
            ;;

        *)
            die "Internal error: unsupported mode '${SCRIPT_MODE}'."
            ;;
    esac

    show_final_summary
    log_success "Installer finished successfully."
}

main "$@"