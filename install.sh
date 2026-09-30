#!/usr/bin/env bash

set -Eeuo pipefail
IFS=$'\n\t'

# ============================================================
# VeloraBot
# Complete Installer + Release Updater
# ============================================================
# Source of truth:
#   https://github.com/navidmn56/VeloraBot
#
# Modes:
#   bash velorabot-installer.sh
#       Automatically install or update.
#
#   bash velorabot-installer.sh --install
#       Perform a fresh installation.
#
#   bash velorabot-installer.sh --update
#       Update an existing installation.
#
#   bash velorabot-installer.sh --force-update
#       Force an update even when the installed release is current.
#
#   bash velorabot-installer.sh --skip-config
#       Skip configuration prompts during a fresh installation.
#
# Update guarantees:
#   1. data/ is never modified during an update.
#   2. config.py is never replaced during a normal update.
#   3. If config.py is missing or invalid, the installer prompts
#      the user for values and writes a complete config.py.
#   4. .venv/ is preserved during an update.
#   5. requirements.txt from the release is always installed.
#   6. All other application files are synchronized from the release.
#   7. Stale application files are removed during synchronization.
#   8. A backup of the application source is created before update.
#   9. If an update fails, application source and config are rolled back.
#  10. The service is restarted only after validation succeeds.
#
# All installer output, logs, comments, prompts, and messages are English.
# ============================================================


# ============================================================
# Terminal Handling
# ============================================================

# FD 3 is permanently used for the interactive terminal.
# This is required because when the installer is executed as:
#
#   curl ... | sudo bash
#
# Bash stdin is connected to curl's pipe, not the user's terminal.
#
# /dev/tty gives us direct access to the SSH terminal.

open_tty() {
    if [[ ! -r /dev/tty || ! -w /dev/tty ]]; then
        printf '%s\n' "ERROR: An interactive terminal is required." >&2
        printf '%s\n' "The installer must be run from an SSH terminal." >&2
        exit 1
    fi

    # IMPORTANT:
    # Do NOT use:
    #
    #   exec ${TTY_FD}<>/dev/tty
    #
    # because Bash interprets the expanded "3" as a command.
    #
    # FD 3 must be written literally.

    exec 3<>/dev/tty
}

close_tty() {
    exec 3>&- 2>/dev/null || true
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
readonly WHITE='\033[1;37m'
readonly DIM='\033[2m'
readonly BOLD='\033[1m'
readonly NC='\033[0m'


# ============================================================
# Application Constants
# ============================================================

readonly APP_NAME="VeloraBot"
readonly OWNER="navidmn56"
readonly REPO="VeloraBot"
readonly REPO_FULL="${OWNER}/${REPO}"

readonly REPO_URL="https://github.com/${REPO_FULL}"
readonly API_URL="https://api.github.com/repos/${REPO_FULL}"

readonly INSTALL_DIR="/opt/VeloraBot"
readonly VENV_DIR="${INSTALL_DIR}/.venv"
readonly CONFIG_FILE="${INSTALL_DIR}/config.py"
readonly DATA_DIR="${INSTALL_DIR}/data"
readonly DATA_CONFIGS_FILE="${DATA_DIR}/configs.json"
readonly VERSION_FILE="${INSTALL_DIR}/.version"

readonly SERVICE_NAME="velorabot"
readonly SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

readonly BACKUP_ROOT="/opt/VeloraBot-backups"
readonly LOG_FILE="/var/log/velorabot-installer.log"
readonly FALLBACK_LOG_FILE="/tmp/velorabot-installer.log"

readonly MIN_PYTHON_MAJOR=3
readonly MIN_PYTHON_MINOR=10


# ============================================================
# Runtime State
# ============================================================

SCRIPT_MODE="auto"

CURRENT_VERSION="unknown"
LATEST_VERSION="unknown"
LATEST_RELEASE_URL=""
LATEST_ZIP_URL=""

TEMP_ROOT=""
RELEASE_ROOT=""

BACKUP_DIR=""
BACKUP_READY=0

SERVICE_WAS_ACTIVE=0
UPDATE_IN_PROGRESS=0

VENV_CREATED=0
FRESH_INSTALL=0

FORCE_UPDATE=0
SKIP_CONFIG=0
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

timestamp() {
    date '+%Y-%m-%d %H:%M:%S'
}

write_log() {
    local level="$1"
    shift

    printf '[%s] [%s] %s\n' \
        "$(timestamp)" \
        "${level}" \
        "$*" \
        >> "${LOG_FILE}" 2>/dev/null || true
}

log_info() {
    printf '%b[INFO]%b %s\n' "${CYAN}" "${NC}" "$*"
    write_log "INFO" "$*"
}

log_success() {
    printf '%b[ OK ]%b %s\n' "${GREEN}" "${NC}" "$*"
    write_log "OK" "$*"
}

log_warning() {
    printf '%b[WARN]%b %s\n' "${YELLOW}" "${NC}" "$*" >&2
    write_log "WARN" "$*"
}

log_error() {
    printf '%b[FAIL]%b %s\n' "${RED}" "${NC}" "$*" >&2
    write_log "FAIL" "$*"
}

log_command() {
    printf '%b[CMD ]%b %s\n' "${DIM}" "${NC}" "$*"
    write_log "CMD" "$*"
}

die() {
    log_error "$*"

    printf '\n'
    printf '%s\n' "Installer log:"
    printf '  %s\n' "${LOG_FILE}"

    exit 1
}


# ============================================================
# UI
# ============================================================

draw_line() {
    printf '%b%s%b\n' \
        "${BLUE}" \
        '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━' \
        "${NC}"
}

draw_header() {
    printf '\n'
    draw_line

    printf '%b  %s%b\n' \
        "${BOLD}${CYAN}" \
        "$1" \
        "${NC}"

    draw_line
    printf '\n'
}

draw_step() {
    printf '\n'

    printf '%b%s%b\n' \
        "${MAGENTA}${BOLD}" \
        '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━' \
        "${NC}"

    printf '%b  %s%b\n' \
        "${MAGENTA}${BOLD}" \
        "$1" \
        "${NC}"

    printf '%b%s%b\n' \
        "${MAGENTA}${BOLD}" \
        '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━' \
        "${NC}"

    printf '\n'
}


# ============================================================
# Error Handling
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

    tar -xzf \
        "${BACKUP_DIR}/application.tar.gz" \
        -C "${rollback_root}"

    mkdir -p "${INSTALL_DIR}"

    # Restore application source.
    #
    # IMPORTANT:
    # data/ is excluded because it was never part of the backup
    # and was never modified during the update.
    #
    # .venv/ and .version are also protected.

    rsync -a --delete \
        --exclude='data' \
        --exclude='.venv' \
        --exclude='.version' \
        "${rollback_root}/" \
        "${INSTALL_DIR}/"

    if [[ "${SERVICE_BACKUP_EXISTS}" -eq 1 &&
          -f "${BACKUP_DIR}/service" ]]; then

        cp -a \
            "${BACKUP_DIR}/service" \
            "${SERVICE_FILE}"
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

    if [[ -f "${BACKUP_DIR}/requirements.txt" &&
          -x "${VENV_DIR}/bin/python" ]]; then

        log_info "Restoring previous Python dependencies..."

        if ! "${VENV_DIR}/bin/python" -m pip install \
            -r "${BACKUP_DIR}/requirements.txt" \
            >>"${LOG_FILE}" 2>&1; then

            log_warning \
                "Previous Python dependencies could not be fully restored."
        fi
    fi

    systemctl daemon-reload >/dev/null 2>&1 || true

    log_success "Application rollback completed."

    return 0
}

on_exit() {
    local exit_code=$?

    if (( exit_code != 0 )) &&
       (( UPDATE_IN_PROGRESS == 1 )) &&
       (( BACKUP_READY == 1 )); then

        printf '\n'

        log_error \
            "The update failed with exit code ${exit_code}."

        if rollback_update; then

            if (( SERVICE_WAS_ACTIVE == 1 )); then
                log_info "Starting the previous service version..."

                systemctl start \
                    "${SERVICE_NAME}" \
                    >/dev/null 2>&1 || true
            fi

            log_warning \
                "The previous application version has been restored."
        else
            log_error \
                "Automatic rollback was not fully successful."

            log_error \
                "Manual recovery may be required."
        fi
    fi

    close_tty
    cleanup_temp

    exit "${exit_code}"
}

trap on_exit EXIT


# ============================================================
# Input Helpers
# ============================================================

read_tty() {
    local prompt="$1"
    local result_var="$2"
    local value=""

    printf '%s' "${prompt}" >&3

    if ! IFS= read -r value <&3; then
        return 1
    fi

    printf -v "${result_var}" '%s' "${value}"

    return 0
}

read_secret_tty() {
    local prompt="$1"
    local result_var="$2"
    local value=""

    printf '%s' "${prompt}" >&3

    stty -echo <&3 2>/dev/null || true

    if ! IFS= read -r value <&3; then
        stty echo <&3 2>/dev/null || true

        printf '\n' >&3

        return 1
    fi

    stty echo <&3 2>/dev/null || true

    printf '\n' >&3

    printf -v "${result_var}" '%s' "${value}"

    return 0
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

        if [[ -z "${answer}" ]]; then
            answer="${default}"
        fi

        case "${answer}" in
            y|yes)
                return 0
                ;;

            n|no)
                return 1
                ;;

            *)
                log_warning "Please answer yes or no."
                ;;
        esac
    done
}


# ============================================================
# Argument Parsing
# ============================================================

show_help() {
    cat <<EOF
VeloraBot Installer / Updater

Usage:
  sudo bash $0
  sudo bash $0 --install
  sudo bash $0 --update
  sudo bash $0 --force-update
  sudo bash $0 --skip-config
  sudo bash $0 --update --force-update
  sudo bash $0 --help

Options:
  --install         Perform a fresh installation.
  --update          Update an existing installation.
  --force-update    Force the latest release to be installed.
  --skip-config     Skip configuration prompts during a fresh install.
  --help, -h        Show this help message.

Automatic mode:
  If ${INSTALL_DIR} does not exist, a fresh installation is performed.
  If ${INSTALL_DIR} exists, an update is performed.

Protected update paths:
  ${CONFIG_FILE}
  ${DATA_DIR}
  ${VENV_DIR}

Update source:
  ${REPO_URL}
EOF
}

parse_arguments() {
    while [[ $# -gt 0 ]]; do

        case "$1" in

            --install)
                SCRIPT_MODE="install"
                ;;

            --update)
                SCRIPT_MODE="update"
                ;;

            --force-update)
                FORCE_UPDATE=1
                ;;

            --skip-config)
                SKIP_CONFIG=1
                ;;

            --help|-h)
                show_help
                exit 0
                ;;

            *)
                die "Unknown argument: $1"
                ;;
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
    [[ -f /etc/os-release ]] ||
        die "Cannot detect the operating system."

    # shellcheck disable=SC1091
    source /etc/os-release

    printf 'Operating System : %s\n' "${PRETTY_NAME:-Unknown}"
    printf 'Architecture     : %s\n' "$(uname -m)"
    printf 'Kernel           : %s\n' "$(uname -r)"
    printf '\n'

    if [[ "${ID:-}" != "ubuntu" ]]; then

        log_warning "This installer is designed for Ubuntu."
        log_warning \
            "Detected operating system: ${PRETTY_NAME:-Unknown}"

        if ! ask_yes_no "Continue anyway? [y/N]: " "n"; then
            exit 0
        fi
    fi
}

install_system_dependencies() {
    draw_step "Installing System Dependencies"

    export DEBIAN_FRONTEND=noninteractive

    log_command "apt-get update"

    apt-get update

    log_command "Installing required packages"

    apt-get install -y \
        ca-certificates \
        curl \
        unzip \
        rsync \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        build-essential \
        libssl-dev \
        libffi-dev

    command -v python3 >/dev/null 2>&1 ||
        die "python3 is not available."

    command -v curl >/dev/null 2>&1 ||
        die "curl is not available."

    command -v unzip >/dev/null 2>&1 ||
        die "unzip is not available."

    command -v rsync >/dev/null 2>&1 ||
        die "rsync is not available."

    log_success "System dependencies are installed."
}

check_python_version() {
    local version

    version="$(
        python3 -c \
            'import sys; print(".".join(map(str, sys.version_info[:2])))'
    )"

    printf 'Python version: %s\n' "${version}"

    if ! python3 -c \
        'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)'
    then
        die "VeloraBot requires Python 3.10 or newer."
    fi

    log_success "Python version is supported."
}

check_github_connectivity() {
    draw_step "Checking GitHub Connectivity"

    if curl \
        --fail \
        --silent \
        --show-error \
        --location \
        --connect-timeout 10 \
        --max-time 30 \
        "https://github.com" \
        >/dev/null; then

        log_success "GitHub is reachable."
    else
        die "Unable to connect to GitHub."
    fi
}


# ============================================================
# GitHub Release Handling
# ============================================================

fetch_latest_release() {
    draw_step "Checking Latest GitHub Release"

    local metadata_file="${TEMP_ROOT}/release.json"

    log_info \
        "Requesting latest release information from GitHub..."

    curl \
        --fail \
        --silent \
        --show-error \
        --location \
        --retry 4 \
        --retry-delay 2 \
        --connect-timeout 15 \
        --max-time 60 \
        -H "Accept: application/vnd.github+json" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        "${API_URL}/releases/latest" \
        -o "${metadata_file}"

    local parsed

    parsed="$(
        python3 - "${metadata_file}" <<'PY'
import json
import sys

path = sys.argv[1]

with open(path, "r", encoding="utf-8") as handle:
    data = json.load(handle)

if data.get("message"):
    raise SystemExit(
        f"GitHub API error: {data['message']}"
    )

if data.get("draft"):
    raise SystemExit(
        "The latest GitHub release is a draft."
    )

if data.get("prerelease"):
    raise SystemExit(
        "The latest GitHub release is a prerelease."
    )

tag = data.get("tag_name", "")
html_url = data.get("html_url", "")

if not tag:
    raise SystemExit(
        "GitHub did not return a release tag."
    )

zipball_url = (
    f"https://codeload.github.com/navidmn56/VeloraBot/"
    f"zip/refs/tags/{tag}"
)

print(tag)
print(html_url)
print(zipball_url)
PY
    )" || die "Failed to parse GitHub release information."

    LATEST_VERSION="$(
        printf '%s\n' "${parsed}" | sed -n '1p'
    )"

    LATEST_RELEASE_URL="$(
        printf '%s\n' "${parsed}" | sed -n '2p'
    )"

    LATEST_ZIP_URL="$(
        printf '%s\n' "${parsed}" | sed -n '3p'
    )"

    [[ -n "${LATEST_VERSION}" ]] ||
        die "Latest release version could not be determined."

    [[ -n "${LATEST_ZIP_URL}" ]] ||
        die "Latest release ZIP URL could not be determined."

    printf '\n'
    printf 'Latest Release : %s\n' "${LATEST_VERSION}"
    printf 'Release URL    : %s\n' "${LATEST_RELEASE_URL}"
    printf '\n'

    log_success "Latest release detected."
}

download_latest_release() {
    draw_step "Downloading Release"

    local archive="${TEMP_ROOT}/release.zip"
    local extract_dir="${TEMP_ROOT}/release"

    mkdir -p "${extract_dir}"

    log_info \
        "Downloading release ${LATEST_VERSION}..."

    curl \
        --fail \
        --silent \
        --show-error \
        --location \
        --retry 4 \
        --retry-delay 2 \
        --connect-timeout 15 \
        --max-time 300 \
        "${LATEST_ZIP_URL}" \
        -o "${archive}"

    [[ -s "${archive}" ]] ||
        die "The downloaded release archive is empty."

    log_info "Extracting release archive..."

    rm -rf -- "${extract_dir}"
    mkdir -p "${extract_dir}"

    if ! unzip -q "${archive}" -d "${extract_dir}"; then
        die "Failed to extract the release archive."
    fi

    RELEASE_ROOT=""

    while IFS= read -r -d '' directory; do

        if [[ -f "${directory}/main.py" &&
              -f "${directory}/requirements.txt" ]]; then

            RELEASE_ROOT="${directory}"
            break
        fi

    done < <(
        find "${extract_dir}" \
            -mindepth 1 \
            -maxdepth 2 \
            -type d \
            -print0
    )

    [[ -n "${RELEASE_ROOT}" ]] ||
        die \
            "Invalid release structure. main.py and requirements.txt were not found."

    log_success \
        "Release archive extracted successfully."
}

validate_release_for_install() {
    [[ -f "${RELEASE_ROOT}/main.py" ]] ||
        die "main.py is missing from the release."

    [[ -f "${RELEASE_ROOT}/requirements.txt" ]] ||
        die "requirements.txt is missing from the release."

    [[ -f "${RELEASE_ROOT}/config.py" ]] ||
        die \
            "config.py is missing from the release. Fresh installation cannot continue."

    log_success \
        "Release structure is valid for installation."
}

validate_release_for_update() {
    [[ -f "${RELEASE_ROOT}/main.py" ]] ||
        die "main.py is missing from the release."

    [[ -f "${RELEASE_ROOT}/requirements.txt" ]] ||
        die "requirements.txt is missing from the release."

    log_success \
        "Release structure is valid for update."
}


# ============================================================
# Version Handling
# ============================================================

read_current_version() {
    if [[ -f "${VERSION_FILE}" ]]; then

        CURRENT_VERSION="$(
            tr -d '\r\n' < "${VERSION_FILE}"
        )"

        [[ -n "${CURRENT_VERSION}" ]] ||
            CURRENT_VERSION="unknown"

    else
        CURRENT_VERSION="unknown"
    fi
}

normalize_version() {
    local version="$1"

    version="${version#v}"

    printf '%s\n' "${version}"
}

versions_equal() {
    local left
    local right

    left="$(normalize_version "$1")"
    right="$(normalize_version "$2")"

    [[ "${left}" == "${right}" ]]
}

write_version_file() {
    printf '%s\n' "${LATEST_VERSION}" > "${VERSION_FILE}"

    chmod 644 "${VERSION_FILE}"
}


# ============================================================
# Backup
# ============================================================

create_backup() {
    local timestamp

    timestamp="$(date '+%Y%m%d_%H%M%S')"

    BACKUP_DIR="${BACKUP_ROOT}/${timestamp}_${LATEST_VERSION}"

    mkdir -p "${BACKUP_DIR}"

    draw_step "Creating Update Backup"

    log_info \
        "Creating application source backup..."

    # IMPORTANT:
    #
    # data/ is completely excluded.
    #
    # It is not read by tar.
    # It is not copied.
    # It is not backed up.
    #
    # config.py IS backed up.
    # .venv/ is excluded.
    # .version is included only if present, but rollback excludes it.

    tar -czf \
        "${BACKUP_DIR}/application.tar.gz" \
        --exclude='./.venv' \
        --exclude='./data' \
        -C "${INSTALL_DIR}" .

    if [[ -f "${INSTALL_DIR}/requirements.txt" ]]; then

        cp -a \
            "${INSTALL_DIR}/requirements.txt" \
            "${BACKUP_DIR}/requirements.txt"
    fi

    if [[ -f "${SERVICE_FILE}" ]]; then

        cp -a \
            "${SERVICE_FILE}" \
            "${BACKUP_DIR}/service"

        SERVICE_BACKUP_EXISTS=1
    else
        SERVICE_BACKUP_EXISTS=0
    fi

    chmod 600 \
        "${BACKUP_DIR}"/*.tar.gz \
        2>/dev/null || true

    chmod 600 \
        "${BACKUP_DIR}/requirements.txt" \
        2>/dev/null || true

    chmod 600 \
        "${BACKUP_DIR}/service" \
        2>/dev/null || true

    BACKUP_READY=1

    log_success \
        "Backup created: ${BACKUP_DIR}"
}


# ============================================================
# Service Management
# ============================================================

service_is_active() {
    systemctl is-active --quiet "${SERVICE_NAME}"
}

stop_service_if_active() {
    SERVICE_WAS_ACTIVE=0

    if service_is_active; then

        SERVICE_WAS_ACTIVE=1

        log_info \
            "Stopping ${SERVICE_NAME}..."

        systemctl stop "${SERVICE_NAME}"

        log_success "Service stopped."

    else
        log_info \
            "Service is not currently running."
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

    systemctl enable \
        "${SERVICE_NAME}" \
        >/dev/null

    log_success \
        "systemd service configured."
}

start_service_and_check() {
    draw_step "Starting VeloraBot"

    systemctl daemon-reload

    systemctl enable \
        "${SERVICE_NAME}" \
        >/dev/null

    systemctl restart "${SERVICE_NAME}"

    sleep 5

    if service_is_active; then

        log_success \
            "${SERVICE_NAME} is running."

        return 0
    fi

    log_error \
        "${SERVICE_NAME} failed to start."

    printf '\n'
    printf '%s\n' "Recent service logs:"
    printf '%s\n' "------------------------------------------------------------"

    journalctl \
        -u "${SERVICE_NAME}" \
        -n 100 \
        --no-pager \
        || true

    printf '%s\n' "------------------------------------------------------------"

    return 1
}


# ============================================================
# Python Virtual Environment
# ============================================================

create_virtual_environment_if_needed() {
    if [[ ! -x "${VENV_DIR}/bin/python" ]]; then

        draw_step \
            "Creating Python Virtual Environment"

        log_info \
            "Creating ${VENV_DIR}..."

        mkdir -p "${INSTALL_DIR}"

        python3 -m venv "${VENV_DIR}"

        VENV_CREATED=1

        log_success \
            "Python virtual environment created."

    else

        log_info \
            "Existing Python virtual environment will be preserved."
    fi

    [[ -x "${VENV_DIR}/bin/python" ]] ||
        die \
            "Virtual environment Python executable is missing."

    "${VENV_DIR}/bin/python" --version

    "${VENV_DIR}/bin/python" -m pip --version >/dev/null ||
        die \
            "pip is not available inside the virtual environment."
}

install_requirements() {
    local requirements_file="${INSTALL_DIR}/requirements.txt"

    [[ -f "${requirements_file}" ]] ||
        die \
            "requirements.txt does not exist."

    draw_step \
        "Installing Python Dependencies"

    log_info \
        "Installing dependencies from requirements.txt..."

    "${VENV_DIR}/bin/python" -m pip install \
        --upgrade \
        pip \
        setuptools \
        wheel

    "${VENV_DIR}/bin/python" -m pip install \
        -r "${requirements_file}"

    "${VENV_DIR}/bin/python" -m pip check

    log_success \
        "Python dependencies are installed and verified."
}

ensure_data_configs_file() {
    # ONLY used during fresh installation.
    #
    # Never call this function during an update.
    #
    # Existing data is never overwritten.

    if [[ ! -f "${DATA_CONFIGS_FILE}" ]]; then

        printf '{}\n' > "${DATA_CONFIGS_FILE}"

        chmod 600 \
            "${DATA_CONFIGS_FILE}"

        log_info \
            "Created placeholder ${DATA_CONFIGS_FILE}."
    fi
}


# ============================================================
# Configuration Helpers
# ============================================================

is_placeholder() {
    local value="$1"

    case "${value}" in

        "" \
        |"Main_bot_token" \
        |"YOUR_TELEGRAM_USER_ID" \
        |"Log_bot_token" \
        |"676778785656565656" \
        |"Navid" \
        |"Blue Bank" \
        |"Panel_username" \
        |"Panel_password" \
        |"Gemini_API_Key" \
        |"@your_username_here" \
        |"1234567812345678")

            return 0
            ;;

        *)
            return 1
            ;;
    esac
}

extract_config_values() {
    [[ -f "${CONFIG_FILE}" ]] || return 1

    local values

    values="$(
        python3 - "${CONFIG_FILE}" <<'PY'
import ast
import json
import sys

path = sys.argv[1]

allowed = {
    "BOT_TOKEN",
    "ADMIN_ID",
    "LOG_BOT_TOKEN",
    "LOG_CHANNEL_ID",
    "BANK_CARD_NUMBER",
    "BANK_CARD_HOLDER",
    "BANK_NAME",
    "SENAI_PANEL_URL",
    "SENAI_PANEL_USERNAME",
    "SENAI_PANEL_PASSWORD",
    "SENAI_SUB_URL",
    "SUPPORT_USERNAME",
    "GEMINI_ENABLED",
    "GEMINI_API_KEY",
}

try:
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()

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

    [[ -n "${values}" ]] ||
        values="{}"

    config_value() {
        local key="$1"
        local default="${2:-}"

        python3 - "${values}" "${key}" "${default}" <<'PY'
import json
import sys

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

    printf '%s\n' \
        "Checking existing configuration..."

    if is_placeholder "${BOT_TOKEN}"; then
        printf '  %bMISSING%b BOT_TOKEN\n' \
            "${RED}" "${NC}"
        missing=1
    fi

    if [[ ! "${ADMIN_ID}" =~ ^[0-9]+$ ]]; then
        printf '  %bINVALID%b ADMIN_ID\n' \
            "${RED}" "${NC}"
        missing=1
    fi

    if is_placeholder "${LOG_BOT_TOKEN}"; then
        printf '  %bMISSING%b LOG_BOT_TOKEN\n' \
            "${RED}" "${NC}"
        missing=1
    fi

    if [[ ! "${LOG_CHANNEL_ID}" =~ ^-?[0-9]+$ &&
          "${LOG_CHANNEL_ID}" != "None" ]]; then

        printf '  %bINVALID%b LOG_CHANNEL_ID\n' \
            "${RED}" "${NC}"

        missing=1
    fi

    if [[ ! "${BANK_CARD_NUMBER}" =~ ^[0-9]{16}$ ]]; then
        printf '  %bINVALID%b BANK_CARD_NUMBER\n' \
            "${RED}" "${NC}"
        missing=1
    fi

    if is_placeholder "${BANK_CARD_HOLDER}"; then
        printf '  %bMISSING%b BANK_CARD_HOLDER\n' \
            "${RED}" "${NC}"
        missing=1
    fi

    if is_placeholder "${BANK_NAME}"; then
        printf '  %bMISSING%b BANK_NAME\n' \
            "${RED}" "${NC}"
        missing=1
    fi

    if ! [[ "${SENAI_PANEL_URL}" =~ ^https?:// ]]; then
        printf '  %bINVALID%b SENAI_PANEL_URL\n' \
            "${RED}" "${NC}"
        missing=1
    fi

    if is_placeholder "${SENAI_PANEL_USERNAME}"; then
        printf '  %bMISSING%b SENAI_PANEL_USERNAME\n' \
            "${RED}" "${NC}"
        missing=1
    fi

    if is_placeholder "${SENAI_PANEL_PASSWORD}"; then
        printf '  %bMISSING%b SENAI_PANEL_PASSWORD\n' \
            "${RED}" "${NC}"
        missing=1
    fi

    if ! [[ "${SENAI_SUB_URL}" =~ ^https?:// ]]; then
        printf '  %bINVALID%b SENAI_SUB_URL\n' \
            "${RED}" "${NC}"
        missing=1
    fi

    if is_placeholder "${SUPPORT_USERNAME}"; then
        printf '  %bMISSING%b SUPPORT_USERNAME\n' \
            "${RED}" "${NC}"
        missing=1
    fi

    if [[ "${GEMINI_ENABLED}" == "True" ]] &&
       is_placeholder "${GEMINI_API_KEY}"; then

        printf '  %bMISSING%b GEMINI_API_KEY\n' \
            "${RED}" "${NC}"

        missing=1
    fi

    return "${missing}"
}


# ============================================================
# Configuration Template Generation
# ============================================================

write_fresh_config() {
    local config_path="$1"

    cat > "${config_path}" <<EOF
# ==================== REQUIRED SETTINGS ====================
BOT_TOKEN = "${BOT_TOKEN}"
ADMIN_ID = ${ADMIN_ID}

BANK_CARD_NUMBER = "${BANK_CARD_NUMBER}"
BANK_CARD_HOLDER = "${BANK_CARD_HOLDER}"
BANK_NAME = "${BANK_NAME}"

SENAI_PANEL_URL = "${SENAI_PANEL_URL}"
SENAI_PANEL_USERNAME = "${SENAI_PANEL_USERNAME}"
SENAI_PANEL_PASSWORD = "${SENAI_PANEL_PASSWORD}"
SENAI_SUB_URL = "${SENAI_SUB_URL}"

SUPPORT_USERNAME = "${SUPPORT_USERNAME}"

# ==================== OPTIONAL LOG SETTINGS ====================
LOG_BOT_TOKEN = "${LOG_BOT_TOKEN}"
LOG_CHANNEL_ID = ${LOG_CHANNEL_ID}

# ==================== OPTIONAL GEMINI SETTINGS ====================
GEMINI_ENABLED = ${GEMINI_ENABLED}
GEMINI_API_KEY = "${GEMINI_API_KEY}"

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_TEMPERATURE = 0.7
GEMINI_MAX_TOKENS = 90
GEMINI_DAILY_LIMIT = 3
EOF

    chmod 600 "${config_path}"
}


# ============================================================
# Fresh Installation Configuration Prompts
# ============================================================

prompt_required() {
    local label="$1"
    local variable="$2"
    local value=""

    while true; do

        if ! read_tty "${label}: " value; then
            die \
                "Could not read input from the terminal."
        fi

        if [[ -n "${value}" ]]; then

            printf -v "${variable}" '%s' "${value}"

            return
        fi

        log_warning \
            "${label} cannot be empty."
    done
}

prompt_secret_required() {
    local label="$1"
    local variable="$2"
    local value=""

    while true; do

        if ! read_secret_tty "${label}: " value; then
            die \
                "Could not read input from the terminal."
        fi

        if [[ -n "${value}" ]]; then

            printf -v "${variable}" '%s' "${value}"

            return
        fi

        log_warning \
            "${label} cannot be empty."
    done
}

prompt_admin_id() {
    local value=""

    while true; do

        if ! read_tty "ADMIN_ID: " value; then
            die \
                "Could not read input from the terminal."
        fi

        if [[ "${value}" =~ ^[0-9]+$ ]]; then

            ADMIN_ID="${value}"

            return
        fi

        log_warning \
            "ADMIN_ID must contain digits only."
    done
}

prompt_log_channel_id() {
    local value=""

    printf '%s\n' \
        "LOG_CHANNEL_ID can be left empty (press Enter) to disable logging."

    if ! read_tty "LOG_CHANNEL_ID: " value; then
        die \
            "Could not read input from the terminal."
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

        log_warning \
            "LOG_CHANNEL_ID must be a numeric value or empty for None."

        if ! read_tty "LOG_CHANNEL_ID: " value; then
            die \
                "Could not read input from the terminal."
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
            die \
                "Could not read input from the terminal."
        fi

        if [[ "${value}" =~ ^[0-9]{16}$ ]]; then

            BANK_CARD_NUMBER="${value}"

            return
        fi

        log_warning \
            "BANK_CARD_NUMBER must contain exactly 16 digits."
    done
}

prompt_http_url() {
    local label="$1"
    local variable="$2"
    local value=""

    while true; do

        if ! read_tty "${label}: " value; then
            die \
                "Could not read input from the terminal."
        fi

        if [[ "${value}" =~ ^https?:// ]]; then

            printf -v "${variable}" '%s' "${value}"

            return
        fi

        log_warning \
            "${label} must start with http:// or https://."
    done
}

prompt_gemini() {
    local answer=""
    local value=""

    while true; do

        if ! read_tty \
            "Enable Gemini AI? [y/N]: " \
            answer; then

            die \
                "Could not read input from the terminal."
        fi

        case "${answer,,}" in

            y|yes)
                GEMINI_ENABLED="True"
                break
                ;;

            ""|n|no)
                GEMINI_ENABLED="False"
                GEMINI_API_KEY=""
                return
                ;;

            *)
                log_warning \
                    "Please answer y or n."
                ;;
        esac
    done

    while true; do

        if ! read_secret_tty \
            "GEMINI_API_KEY: " \
            value; then

            die \
                "Could not read input from the terminal."
        fi

        if [[ ${#value} -ge 20 ]]; then

            GEMINI_API_KEY="${value}"

            return
        fi

        log_warning \
            "The Gemini API key appears too short."
    done
}

configure_fresh_install() {
    draw_step "Configuring VeloraBot"

    printf '%s\n' \
        "The following values will be written to config.py."

    printf '%s\n' \
        "This is only performed when config.py must be created or completed."

    printf '\n'

    prompt_secret_required \
        "BOT_TOKEN" \
        BOT_TOKEN

    prompt_admin_id

    printf '\n'

    printf '%s\n' \
        "Log settings are optional."

    printf '%s\n' \
        "Press Enter on each to leave them empty."

    printf '\n'

    if ask_yes_no \
        "Configure log bot token? [y/N]: " \
        "n"; then

        prompt_secret_required \
            "LOG_BOT_TOKEN" \
            LOG_BOT_TOKEN

        prompt_log_channel_id

    else

        LOG_BOT_TOKEN=""
        LOG_CHANNEL_ID="None"
    fi

    printf '\n'

    prompt_card_number

    prompt_required \
        "BANK_CARD_HOLDER" \
        BANK_CARD_HOLDER

    prompt_required \
        "BANK_NAME" \
        BANK_NAME

    printf '\n'

    prompt_http_url \
        "SENAI_PANEL_URL" \
        SENAI_PANEL_URL

    prompt_required \
        "SENAI_PANEL_USERNAME" \
        SENAI_PANEL_USERNAME

    prompt_secret_required \
        "SENAI_PANEL_PASSWORD" \
        SENAI_PANEL_PASSWORD

    prompt_http_url \
        "SENAI_SUB_URL" \
        SENAI_SUB_URL

    printf '\n'

    prompt_required \
        "SUPPORT_USERNAME" \
        SUPPORT_USERNAME

    printf '\n'

    prompt_gemini

    write_fresh_config "${CONFIG_FILE}"

    log_success \
        "config.py was written."
}


# ============================================================
# Validation
# ============================================================

validate_config_syntax() {
    [[ -f "${CONFIG_FILE}" ]] ||
        die "config.py does not exist."

    if ! "${VENV_DIR}/bin/python" \
        -m py_compile \
        "${CONFIG_FILE}" \
        >/dev/null 2>&1; then

        die \
            "config.py contains a Python syntax error."
    fi

    log_success \
        "config.py syntax is valid."
}

validate_python_source() {
    draw_step "Validating Python Source"

    local failed=0
    local pyfile

    while IFS= read -r -d '' pyfile; do

        if ! "${VENV_DIR}/bin/python" \
            -m py_compile \
            "${pyfile}" \
            >/dev/null 2>&1; then

            printf \
                '%b[FAIL]%b Python syntax error: %s\n' \
                "${RED}" \
                "${NC}" \
                "${pyfile}" \
                >&2

            write_log \
                "FAIL" \
                "Python syntax error: ${pyfile}"

            failed=1
        fi

    done < <(
        find "${INSTALL_DIR}" \
            -path "${VENV_DIR}" -prune -o \
            -path "${DATA_DIR}" -prune -o \
            -type f \
            -name '*.py' \
            -print0
    )

    (( failed == 0 )) ||
        die \
            "One or more Python files contain syntax errors."

    log_success \
        "All Python source files passed syntax validation."
}

validate_application_layout() {
    draw_step "Validating Application Layout"

    [[ -f "${INSTALL_DIR}/main.py" ]] ||
        die \
            "main.py is missing from the installed application."

    [[ -f "${INSTALL_DIR}/requirements.txt" ]] ||
        die \
            "requirements.txt is missing from the installed application."

    [[ -f "${CONFIG_FILE}" ]] ||
        die \
            "config.py is missing from the installed application."

    [[ -x "${VENV_DIR}/bin/python" ]] ||
        die \
            "The Python virtual environment is invalid."

    log_success \
        "Application layout is valid."
}


# ============================================================
# Fresh Installation
# ============================================================

prepare_install_directory() {
    mkdir -p "${INSTALL_DIR}"

    chmod 755 "${INSTALL_DIR}"
}

fresh_install() {
    FRESH_INSTALL=1

    draw_step "Fresh Installation"

    if [[ -d "${BACKUP_ROOT}" ]]; then

        local backup_count

        backup_count="$(
            find "${BACKUP_ROOT}" \
                -mindepth 1 \
                -maxdepth 1 \
                -type d \
                2>/dev/null |
            wc -l
        )"

        if (( backup_count > 0 )); then

            log_warning \
                "Existing backups were found in ${BACKUP_ROOT}."

            log_warning \
                "Backup count: ${backup_count}"

            printf '\n'

            printf '%s\n' \
                "A fresh installation will NOT use those backups."

            printf '%s\n' \
                "If you want to restore a previous installation, cancel now"

            printf '%s\n' \
                "and restore the backup manually before running this installer."

            printf '\n'

            if ! ask_yes_no \
                "Continue with a fresh installation anyway? [y/N]: " \
                "n"; then

                log_warning \
                    "Fresh installation cancelled by user."

                exit 0
            fi
        fi
    fi

    validate_release_for_install

    prepare_install_directory

    if find "${INSTALL_DIR}" \
        -mindepth 1 \
        -maxdepth 1 \
        -print -quit |
        grep -q .; then

        die \
            "${INSTALL_DIR} is not empty. Refusing to overwrite an existing installation."
    fi

    log_info \
        "Copying release files into ${INSTALL_DIR}..."

    rsync -a \
        "${RELEASE_ROOT}/" \
        "${INSTALL_DIR}/"

    mkdir -p "${DATA_DIR}"

    ensure_data_configs_file

    create_virtual_environment_if_needed

    if [[ "${SKIP_CONFIG}" -eq 0 ]]; then

        configure_fresh_install

    else

        log_warning \
            "Configuration prompts were skipped."

        log_warning \
            "The release config.py must already contain valid settings."
    fi

    validate_application_layout

    validate_config_syntax

    install_requirements

    validate_python_source

    create_systemd_service

    write_version_file

    if ! start_service_and_check; then

        die \
            "Fresh installation completed, but the service failed to start."
    fi

    CURRENT_VERSION="${LATEST_VERSION}"

    log_success \
        "Fresh installation completed successfully."
}


# ============================================================
# Existing Installation Update
# ============================================================

update_existing() {
    draw_step "Updating Existing VeloraBot"

    [[ -d "${INSTALL_DIR}" ]] ||
        die \
            "${INSTALL_DIR} does not exist."

    [[ -f "${CONFIG_FILE}" ]] ||
        die \
            "config.py does not exist. The updater will never create or reconstruct it."

    validate_release_for_update

    create_virtual_environment_if_needed

    UPDATE_IN_PROGRESS=1

    # Backup is created BEFORE any update modification.
    create_backup

    stop_service_if_active

    # --------------------------------------------------------
    # Synchronization
    #
    # data/ is NEVER moved.
    # data/ is NEVER copied.
    # data/ is NEVER deleted.
    # data/ is NEVER recreated.
    #
    # rsync excludes data/ entirely.
    #
    # config.py is protected.
    # .venv/ is protected.
    # .version is protected.
    #
    # --delete removes stale application files while respecting
    # all protected paths.
    # --------------------------------------------------------

    draw_step \
        "Synchronizing Application Files"

    log_info \
        "Synchronizing release ${LATEST_VERSION}..."

    rsync -a --delete \
        --exclude='config.py' \
        --exclude='data' \
        --exclude='.venv' \
        --exclude='.version' \
        "${RELEASE_ROOT}/" \
        "${INSTALL_DIR}/"

    log_success \
        "Application files synchronized."

    # IMPORTANT:
    #
    # DO NOT call ensure_data_configs_file here.
    #
    # If data/ does not exist, it must remain absent.
    # This guarantees that the update process does not touch data/.

    # --------------------------------------------------------
    # Python dependencies
    # --------------------------------------------------------

    draw_step \
        "Synchronizing Python Dependencies"

    log_info \
        "Installing release requirements into .venv..."

    "${VENV_DIR}/bin/python" -m pip install \
        --upgrade \
        pip \
        setuptools \
        wheel

    "${VENV_DIR}/bin/python" -m pip install \
        -r "${INSTALL_DIR}/requirements.txt"

    "${VENV_DIR}/bin/python" -m pip check

    log_success \
        "Python dependencies are synchronized."

    # --------------------------------------------------------
    # Final validation before service restart
    # --------------------------------------------------------

    validate_application_layout

    validate_config_syntax

    validate_python_source

    create_systemd_service

    write_version_file

    if ! start_service_and_check; then

        die \
            "Updated application failed the service health check."
    fi

    UPDATE_IN_PROGRESS=0

    CURRENT_VERSION="${LATEST_VERSION}"

    log_success \
        "VeloraBot was updated successfully."
}


# ============================================================
# Existing Installation Status
# ============================================================

show_existing_status() {
    draw_header \
        "Existing VeloraBot Installation"

    printf \
        'Installation directory : %s\n' \
        "${INSTALL_DIR}"

    printf \
        'Installed release      : %s\n' \
        "${CURRENT_VERSION}"

    printf \
        'Latest release         : %s\n' \
        "${LATEST_VERSION}"

    printf '\n'
}

handle_existing_installation() {
    read_current_version

    show_existing_status

    local config_valid=0

    if [[ -f "${CONFIG_FILE}" ]]; then

        log_info \
            "Validating existing config.py..."

        if extract_config_values &&
           validate_existing_config; then

            log_success \
                "Existing configuration appears valid."

            config_valid=1

        else

            log_warning \
                "Existing configuration contains missing or invalid values."
        fi

    else

        log_warning \
            "config.py is missing from the existing installation."
    fi

    # If config.py is missing or invalid, ask the user whether
    # to reconstruct it.

    if (( config_valid == 0 )); then

        log_warning \
            "The installer will now collect the required settings."

        log_warning \
            "and write a complete config.py."

        printf '\n'

        if ask_yes_no \
            "Configure VeloraBot now? [Y/n]: " \
            "y"; then

            configure_fresh_install

        else

            die \
                "Cannot continue without a valid config.py."
        fi
    fi

    if (( FORCE_UPDATE == 0 )) &&
       versions_equal \
           "${CURRENT_VERSION}" \
           "${LATEST_VERSION}"; then

        draw_header \
            "VeloraBot Status"

        log_success \
            "VeloraBot is already up to date."

        printf \
            'Installed release : %s\n' \
            "${CURRENT_VERSION}"

        printf \
            'Latest release    : %s\n' \
            "${LATEST_VERSION}"

        printf '\n'

        printf '%s\n' \
            "config.py was validated and is now complete."

        return 0
    fi

    if (( FORCE_UPDATE == 1 )); then

        log_warning \
            "Force update is enabled."

        update_existing

        return
    fi

    printf '\n'

    printf \
        'Current release : %s\n' \
        "${CURRENT_VERSION}"

    printf \
        'Latest release : %s\n' \
        "${LATEST_VERSION}"

    printf '\n'

    if versions_equal \
        "${CURRENT_VERSION}" \
        "${LATEST_VERSION}"; then

        log_info \
            "The installed release matches the latest release."

        log_info \
            "No update is required."

        return 0
    fi

    log_info \
        "A newer release is available. Starting update automatically..."

    update_existing
}


# ============================================================
# Final Summary
# ============================================================

show_final_summary() {
    draw_header \
        "VeloraBot Installation Summary"

    printf \
        'Repository       : %s\n' \
        "${REPO_URL}"

    printf \
        'Release          : %s\n' \
        "${CURRENT_VERSION}"

    printf \
        'Install directory: %s\n' \
        "${INSTALL_DIR}"

    printf \
        'Virtual env      : %s\n' \
        "${VENV_DIR}"

    printf \
        'Config           : %s\n' \
        "${CONFIG_FILE}"

    printf \
        'Persistent data  : %s\n' \
        "${DATA_DIR}"

    printf \
        'Service          : %s\n' \
        "${SERVICE_NAME}"

    printf \
        'Installer log    : %s\n' \
        "${LOG_FILE}"

    printf '\n'

    printf '%s\n' \
        "Update protection:"

    printf \
        '  config.py      : never modified during a normal update\n'

    printf \
        '  config.py      : created or completed only when missing/invalid\n'

    printf \
        '  data/          : never touched during updates\n'

    printf \
        '  .venv/         : preserved during updates\n'

    printf \
        '  requirements   : always synchronized with the release\n'

    printf '\n'

    if service_is_active; then

        log_success \
            "Service status: active"

    else

        log_warning \
            "Service status: inactive"
    fi

    printf '\n'

    printf '%s\n' \
        "Useful commands:"

    printf \
        '  systemctl status %s\n' \
        "${SERVICE_NAME}"

    printf \
        '  systemctl restart %s\n' \
        "${SERVICE_NAME}"

    printf \
        '  systemctl stop %s\n' \
        "${SERVICE_NAME}"

    printf \
        '  journalctl -u %s -f\n' \
        "${SERVICE_NAME}"

    printf '\n'

    if [[ -n "${BACKUP_DIR}" &&
          -d "${BACKUP_DIR}" ]]; then

        printf \
            'Latest backup    : %s\n' \
            "${BACKUP_DIR}"

        printf '\n'
    fi

    draw_line
}


# ============================================================
# Main
# ============================================================

main() {
    initialize_logging

    # Parse arguments BEFORE opening /dev/tty.
    # This allows --help to work without an interactive terminal.

    parse_arguments "$@"

    open_tty

    draw_header \
        "VeloraBot Installer / Updater"

    printf \
        'Repository: %s\n' \
        "${REPO_URL}"

    printf '\n'

    log_info \
        "Installer started."

    log_info \
        "Requested mode: ${SCRIPT_MODE}"

    check_root

    check_operating_system

    install_system_dependencies

    check_python_version

    check_github_connectivity

    TEMP_ROOT="$(
        mktemp -d /tmp/velorabot-installer.XXXXXX
    )"

    fetch_latest_release

    download_latest_release

    read_current_version

    case "${SCRIPT_MODE}" in

        install)

            if [[ -e "${INSTALL_DIR}" ]]; then
                die \
                    "Cannot perform --install because ${INSTALL_DIR} already exists."
            fi

            fresh_install
            ;;

        update)

            if [[ ! -d "${INSTALL_DIR}" ]]; then
                die \
                    "Cannot perform --update because no existing installation was found."
            fi

            update_existing
            ;;

        auto)

            if [[ -d "${INSTALL_DIR}" ]]; then

                handle_existing_installation

            else

                fresh_install
            fi
            ;;

        *)

            die \
                "Internal error: unsupported script mode '${SCRIPT_MODE}'."
            ;;
    esac

    show_final_summary

    log_success \
        "Installer finished successfully."
}

main "$@"