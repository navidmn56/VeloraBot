#!/usr/bin/env bash

set -Eeuo pipefail

# ============================================================
# VeloraBot Smart Installer / Updater / Repairer
# ============================================================

# IMPORTANT: This section must be at the top to handle input correctly
# when script is executed via: curl ... | bash

# Save the original stdin
# ============================================================
# Interactive Terminal
# ============================================================

# Always read interactive input from /dev/tty.
# This works even when the installer is executed using:
# curl ... | bash
if [[ -r /dev/tty ]]; then
    exec 3</dev/tty
else
    echo "ERROR: Interactive terminal is required." >&2
    exit 1
fi

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
readonly REPO_URL="https://github.com/${OWNER}/${REPO}.git"
readonly API_URL="https://api.github.com/repos/${OWNER}/${REPO}"

readonly INSTALL_DIR="/opt/VeloraBot"
readonly VENV_DIR="${INSTALL_DIR}/.venv"
readonly CONFIG_FILE="${INSTALL_DIR}/config.py"
readonly DATA_DIR="${INSTALL_DIR}/data"
readonly VERSION_FILE="${INSTALL_DIR}/.version"

readonly SERVICE_NAME="velorabot"
readonly SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

readonly BACKUP_ROOT="/opt/VeloraBot-backups"
readonly INSTALL_LOG="/tmp/velorabot-install.log"

# ============================================================
# Runtime Variables
# ============================================================

CURRENT_VERSION=""
LATEST_VERSION=""
LATEST_RELEASE_URL=""

INSTALL_MODE=""
NEEDS_CONFIG_REPAIR="false"

SKIP_CONFIG="${SKIP_CONFIG:-false}"
FORCE_UPDATE="${FORCE_UPDATE:-false}"

# ============================================================
# Critical Configuration Values
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
# Installer Logging
# ============================================================

touch "$INSTALL_LOG" 2>/dev/null || INSTALL_LOG="/tmp/velorabot-install-$(date +%s).log"
touch "$INSTALL_LOG"
chmod 600 "$INSTALL_LOG"

log() {
    echo "$*" | tee -a "$INSTALL_LOG"
}

# ============================================================
# UI Functions
# ============================================================

line() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

header() {
    echo
    line
    echo -e "${BOLD}${CYAN}  $1${NC}"
    line
    echo
}

step() {
    echo
    echo -e "${MAGENTA}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${MAGENTA}${BOLD}  $1${NC}"
    echo -e "${MAGENTA}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo
}

info() {
    echo -e "${CYAN}ℹ $1${NC}"
}

success() {
    echo -e "${GREEN}✔ $1${NC}"
}

warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

error() {
    echo -e "${RED}✖ $1${NC}"
}

command_info() {
    echo -e "${DIM}➜ $1${NC}"
}

die() {
    error "$1"
    echo
    info "Installer log:"
    echo "  $INSTALL_LOG"
    exit 1
}

# ============================================================
# Error Trap
# ============================================================

trap '
    error "Unexpected error on line $LINENO."
    error "Command: $BASH_COMMAND"
    echo
    info "Installer log: $INSTALL_LOG"
    exit 1
' ERR

# ============================================================
# Input Functions (Fixed for curl | bash)
# ============================================================

read_tty() {
    local prompt="$1"
    local __resultvar="$2"
    local value=""

    printf "%s" "$prompt" >&2

    if ! IFS= read -r value <&3; then
        return 1
    fi

    printf -v "$__resultvar" '%s' "$value"
}

read_secret_tty() {
    local prompt="$1"
    local __resultvar="$2"
    local value=""

    printf "%s" "$prompt" >&2

    if ! IFS= read -r -s value <&3; then
        return 1
    fi

    printf '\n' >&2

    printf -v "$__resultvar" '%s' "$value"
}

# ============================================================
# Root Check
# ============================================================

check_root() {
    if [[ "$EUID" -ne 0 ]]; then
        die "Please run this installer as root."
    fi
    success "Running with root privileges."
}

# ============================================================
# OS Check
# ============================================================

check_os() {
    if [[ ! -f /etc/os-release ]]; then
        die "Cannot detect the operating system."
    fi

    source /etc/os-release

    echo "Operating System : ${PRETTY_NAME:-Unknown}"
    echo "Architecture     : $(uname -m)"
    echo "Kernel           : $(uname -r)"
    echo

    if [[ "${ID:-}" != "ubuntu" ]]; then
        warning "This installer is designed for Ubuntu."
        warning "Detected OS: ${PRETTY_NAME:-Unknown}"
        echo

        local answer
        if ! read_tty "Continue anyway? [y/N]: " answer; then
            die "Could not read input from the terminal."
        fi

        if [[ ! "$answer" =~ ^[Yy]$ ]]; then
            exit 0
        fi
    fi
}

# ============================================================
# System Dependencies
# ============================================================

install_system_dependencies() {
    step "Installing System Dependencies"

    export DEBIAN_FRONTEND=noninteractive

    command_info "apt-get update"
    apt-get update

    command_info "Installing required packages"
    apt-get install -y \
        git \
        curl \
        ca-certificates \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        build-essential \
        libssl-dev \
        libffi-dev

    success "System dependencies installed."
}

# ============================================================
# Python Check
# ============================================================

check_python() {
    local version

    version="$(
        python3 -c \
        'import sys; print(".".join(map(str, sys.version_info[:2])))'
    )"

    echo "Python version: $version"

    if ! python3 -c \
        'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'
    then
        die "VeloraBot requires Python 3.10 or newer."
    fi

    success "Python version is supported."
}

# ============================================================
# Internet Check
# ============================================================

check_internet() {
    info "Checking GitHub connectivity..."

    if curl \
        --fail \
        --silent \
        --show-error \
        --connect-timeout 10 \
        https://github.com \
        >/dev/null
    then
        success "GitHub is reachable."
    else
        die "Unable to connect to GitHub."
    fi
}

# ============================================================
# GitHub API
# ============================================================

get_latest_release() {
    step "Checking GitHub Releases"

    local response

    response="$(
        curl \
            --fail \
            --silent \
            --show-error \
            --location \
            --connect-timeout 15 \
            -H "Accept: application/vnd.github+json" \
            -H "X-GitHub-Api-Version: 2022-11-28" \
            "${API_URL}/releases/latest"
    )"

    LATEST_VERSION="$(
        printf '%s' "$response" |
        python3 -c '
import json
import sys

data = json.load(sys.stdin)
print(data.get("tag_name", ""))
'
    )"

    LATEST_RELEASE_URL="$(
        printf '%s' "$response" |
        python3 -c '
import json
import sys

data = json.load(sys.stdin)
print(data.get("html_url", ""))
'
    )"

    if [[ -z "$LATEST_VERSION" ]]; then
        die "Could not determine the latest GitHub Release."
    fi

    echo
    echo "Latest GitHub Release:"
    echo -e "  ${GREEN}${LATEST_VERSION}${NC}"
    echo
    echo "Release:"
    echo "  ${LATEST_RELEASE_URL}"
    echo

    success "Latest release detected."
}

# ============================================================
# Detect Installed Version (Using .version file)
# ============================================================

get_current_version() {
    if [[ ! -f "$VERSION_FILE" ]]; then
        # Fallback to git if .version doesn't exist
        if [[ -d "$INSTALL_DIR/.git" ]]; then
            CURRENT_VERSION="$(
                git -C "$INSTALL_DIR" describe \
                    --tags \
                    --exact-match \
                    2>/dev/null || true
            )"
        fi
        
        if [[ -z "$CURRENT_VERSION" ]]; then
            CURRENT_VERSION="unknown"
        fi
    else
        CURRENT_VERSION="$(cat "$VERSION_FILE" 2>/dev/null || echo "unknown")"
    fi
}

save_version_file() {
    echo "$LATEST_VERSION" > "$VERSION_FILE"
    chmod 644 "$VERSION_FILE"
}

# ============================================================
# Version Comparison
# ============================================================

normalize_version() {
    local version="$1"
    version="${version#v}"
    echo "$version"
}

version_is_equal() {
    local a b
    a="$(normalize_version "$1")"
    b="$(normalize_version "$2")"
    [[ "$a" == "$b" ]]
}

# ============================================================
# Backup (Enhanced)
# ============================================================

create_backup() {
    local timestamp backup_dir
    timestamp="$(date '+%Y%m%d_%H%M%S')"
    backup_dir="${BACKUP_ROOT}/${timestamp}"

    mkdir -p "$backup_dir"

    # Backup config.py
    if [[ -f "$CONFIG_FILE" ]]; then
        cp -a "$CONFIG_FILE" "$backup_dir/config.py"
    fi

    # Backup data directory
    if [[ -d "$DATA_DIR" ]]; then
        cp -a "$DATA_DIR" "$backup_dir/data"
    fi

    # Backup version file
    if [[ -f "$VERSION_FILE" ]]; then
        cp -a "$VERSION_FILE" "$backup_dir/.version"
    fi

    # Backup requirements.txt
    if [[ -f "$INSTALL_DIR/requirements.txt" ]]; then
        cp -a "$INSTALL_DIR/requirements.txt" "$backup_dir/requirements.txt"
    fi

    echo "$backup_dir"
}

# ============================================================
# Extract Configuration (Robust with Regex Fallback)
# ============================================================

extract_config_values() {
    [[ -f "$CONFIG_FILE" ]] || return 1

    local values=""
    
    # Method 1: Try AST parsing
    values="$(python3 - "$CONFIG_FILE" <<'PY' 2>/dev/null || echo "{}"
import ast
import json
import sys

path = sys.argv[1]

try:
    with open(path, encoding="utf-8") as f:
        source = f.read()
    
    tree = ast.parse(source, filename=path)
    
    allowed = {
        "BOT_TOKEN", "ADMIN_ID", "LOG_BOT_TOKEN", "LOG_CHANNEL_ID",
        "BANK_CARD_NUMBER", "BANK_CARD_HOLDER", "BANK_NAME",
        "SENAI_PANEL_URL", "SENAI_PANEL_USERNAME", "SENAI_PANEL_PASSWORD",
        "SENAI_SUB_URL", "SUPPORT_USERNAME",
        "GEMINI_ENABLED", "GEMINI_API_KEY",
    }
    
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
                value = ast.literal_eval(node.value)
                result[key] = value
            except Exception:
                continue
    
    print(json.dumps(result))
except Exception:
    print("{}")
PY
)"

    # Method 2: If AST failed, try regex
    if [[ -z "$values" ]] || [[ "$values" == "{}" ]]; then
        warning "Using regex extraction for config values..."
        
        values="$(python3 - "$CONFIG_FILE" <<'PY' 2>/dev/null || echo "{}"
import json
import re
import sys

path = sys.argv[1]

try:
    with open(path, encoding="utf-8") as f:
        content = f.read()
except Exception:
    print("{}")
    sys.exit(0)

result = {}

# Define patterns for each key
patterns = {
    "BOT_TOKEN": r'BOT_TOKEN\s*=\s*["\']([^"\']+)["\']',
    "ADMIN_ID": r'ADMIN_ID\s*=\s*["\']?(\d+)["\']?',
    "LOG_BOT_TOKEN": r'LOG_BOT_TOKEN\s*=\s*["\']([^"\']+)["\']',
    "LOG_CHANNEL_ID": r'LOG_CHANNEL_ID\s*=\s*(-?\d+)',
    "BANK_CARD_NUMBER": r'BANK_CARD_NUMBER\s*=\s*["\']([^"\']+)["\']',
    "BANK_CARD_HOLDER": r'BANK_CARD_HOLDER\s*=\s*["\']([^"\']+)["\']',
    "BANK_NAME": r'BANK_NAME\s*=\s*["\']([^"\']+)["\']',
    "SENAI_PANEL_URL": r'SENAI_PANEL_URL\s*=\s*["\']([^"\']+)["\']',
    "SENAI_PANEL_USERNAME": r'SENAI_PANEL_USERNAME\s*=\s*["\']([^"\']+)["\']',
    "SENAI_PANEL_PASSWORD": r'SENAI_PANEL_PASSWORD\s*=\s*["\']([^"\']+)["\']',
    "SENAI_SUB_URL": r'SENAI_SUB_URL\s*=\s*["\']([^"\']+)["\']',
    "SUPPORT_USERNAME": r'SUPPORT_USERNAME\s*=\s*["\']([^"\']+)["\']',
    "GEMINI_ENABLED": r'GEMINI_ENABLED\s*=\s*["\']?(True|False)["\']?',
    "GEMINI_API_KEY": r'GEMINI_API_KEY\s*=\s*["\']([^"\']+)["\']',
}

for key, pattern in patterns.items():
    match = re.search(pattern, content, re.MULTILINE)
    if match:
        if key == "GEMINI_ENABLED":
            result[key] = match.group(1) == "True"
        elif key in ["ADMIN_ID", "LOG_CHANNEL_ID"]:
            try:
                result[key] = int(match.group(1))
            except:
                result[key] = match.group(1)
        else:
            result[key] = match.group(1)

print(json.dumps(result))
PY
)"
    fi

    # Extract values from JSON
    extract_single_value() {
        local key="$1"
        local default="$2"
        local value
        
        value="$(python3 -c "
import json, sys
try:
    d = json.loads('''$values''')
    val = d.get('$key', '$default')
    if isinstance(val, bool):
        print('True' if val else 'False')
    else:
        print(val)
except Exception as e:
    print('$default')
" 2>/dev/null)"
        
        echo "$value"
    }

    BOT_TOKEN="$(extract_single_value "BOT_TOKEN" "")"
    ADMIN_ID="$(extract_single_value "ADMIN_ID" "")"
    LOG_BOT_TOKEN="$(extract_single_value "LOG_BOT_TOKEN" "")"
    LOG_CHANNEL_ID="$(extract_single_value "LOG_CHANNEL_ID" "")"
    
    BANK_CARD_NUMBER="$(extract_single_value "BANK_CARD_NUMBER" "")"
    BANK_CARD_HOLDER="$(extract_single_value "BANK_CARD_HOLDER" "")"
    BANK_NAME="$(extract_single_value "BANK_NAME" "")"
    
    SENAI_PANEL_URL="$(extract_single_value "SENAI_PANEL_URL" "")"
    SENAI_PANEL_USERNAME="$(extract_single_value "SENAI_PANEL_USERNAME" "")"
    SENAI_PANEL_PASSWORD="$(extract_single_value "SENAI_PANEL_PASSWORD" "")"
    SENAI_SUB_URL="$(extract_single_value "SENAI_SUB_URL" "")"
    
    SUPPORT_USERNAME="$(extract_single_value "SUPPORT_USERNAME" "")"
    
    GEMINI_ENABLED="$(extract_single_value "GEMINI_ENABLED" "False")"
    GEMINI_API_KEY="$(extract_single_value "GEMINI_API_KEY" "")"
}

# ============================================================
# Configuration Validation
# ============================================================

is_placeholder() {
    local value="$1"

    case "$value" in
        ""|\
        "Main_bot_token"|\
        "YOUR_TELEGRAM_USER_ID"|\
        "Log_bot_token"|\
        "676778785656565656"|\
        "Navid"|\
        "Blue Bank"|\
        "Panel_username"|\
        "Panel_password"|\
        "Gemini_API_Key"|\
        "@your_username_here")
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

validate_config() {
    local missing=0

    if is_placeholder "$BOT_TOKEN"; then
        echo "  ✖ BOT_TOKEN"
        missing=1
    fi

    if [[ ! "$ADMIN_ID" =~ ^[0-9]+$ ]]; then
        echo "  ✖ ADMIN_ID"
        missing=1
    fi

    if is_placeholder "$LOG_BOT_TOKEN"; then
        echo "  ✖ LOG_BOT_TOKEN"
        missing=1
    fi

    if [[ ! "$LOG_CHANNEL_ID" =~ ^-[0-9]+$ ]]; then
        echo "  ✖ LOG_CHANNEL_ID"
        missing=1
    fi

    if [[ ! "$BANK_CARD_NUMBER" =~ ^[0-9]{16}$ ]]; then
        echo "  ✖ BANK_CARD_NUMBER"
        missing=1
    fi

    if is_placeholder "$BANK_CARD_HOLDER"; then
        echo "  ✖ BANK_CARD_HOLDER"
        missing=1
    fi

    if is_placeholder "$BANK_NAME"; then
        echo "  ✖ BANK_NAME"
        missing=1
    fi

    if ! [[ "$SENAI_PANEL_URL" =~ ^https?:// ]]; then
        echo "  ✖ SENAI_PANEL_URL"
        missing=1
    fi

    if is_placeholder "$SENAI_PANEL_USERNAME"; then
        echo "  ✖ SENAI_PANEL_USERNAME"
        missing=1
    fi

    if is_placeholder "$SENAI_PANEL_PASSWORD"; then
        echo "  ✖ SENAI_PANEL_PASSWORD"
        missing=1
    fi

    if ! [[ "$SENAI_SUB_URL" =~ ^https?:// ]]; then
        echo "  ✖ SENAI_SUB_URL"
        missing=1
    fi

    if is_placeholder "$SUPPORT_USERNAME"; then
        echo "  ✖ SUPPORT_USERNAME"
        missing=1
    fi

    if [[ "$GEMINI_ENABLED" == "True" ]] && is_placeholder "$GEMINI_API_KEY"; then
        echo "  ✖ GEMINI_API_KEY"
        missing=1
    fi

    return "$missing"
}

# ============================================================
# Interactive Configuration Functions
# ============================================================

ask_main_config() {
    local value

    while true; do
        echo
        header "MAIN TELEGRAM BOT"

        echo "This is the Telegram bot that your customers will use."
        echo
        echo "Get the token from @BotFather:"
        echo
        echo "  1. Open @BotFather."
        echo "  2. Send /mybots."
        echo "  3. Select your bot."
        echo "  4. Open the API Token section."
        echo "  5. Copy the complete token."
        echo

        if ! read_secret_tty "Bot Token: " value; then
            die "Could not read input from the terminal."
        fi

        if [[ "$value" =~ ^[0-9]{6,12}:[A-Za-z0-9_-]{20,}$ ]]; then
            BOT_TOKEN="$value"
            break
        fi

        error "Invalid Telegram Bot Token format. Got: '$value'"
    done
}

ask_admin_id() {
    local value

    while true; do
        echo
        header "TELEGRAM ADMIN ID"

        echo "This is your personal numeric Telegram ID."
        echo
        echo "To get it:"
        echo
        echo "  1. Open @myidbot."
        echo "  2. Press Start."
        echo "  3. Copy your numeric Telegram ID."
        echo
        echo "Example:"
        echo "  123456789"
        echo

        if ! read_tty "Admin ID: " value; then
            die "Could not read input from the terminal."
        fi

        if [[ "$value" =~ ^[0-9]+$ ]]; then
            ADMIN_ID="$value"
            break
        fi

        error "Admin ID must contain numbers only. Got: '$value'"
    done
}

ask_log_bot() {
    local value

    while true; do
        echo
        header "LOG BOT TOKEN"

        echo "VeloraBot uses a second Telegram bot to send logs."
        echo
        echo "IMPORTANT:"
        echo
        echo "  1. Create a second bot with @BotFather."
        echo "  2. Add this bot to your Log group."
        echo "  3. Make the Log Bot an ADMINISTRATOR."
        echo "  4. Make sure it has permission to SEND MESSAGES."
        echo "  5. Then enter its Bot Token below."
        echo

        if ! read_secret_tty "Log Bot Token: " value; then
            die "Could not read input from the terminal."
        fi

        if [[ "$value" =~ ^[0-9]{6,12}:[A-Za-z0-9_-]{20,}$ ]]; then
            LOG_BOT_TOKEN="$value"
            break
        fi

        error "Invalid Telegram Bot Token format. Got: '$value'"
    done
}

ask_log_group() {
    local value

    while true; do
        echo
        header "LOG GROUP ID"

        echo "This is the Telegram group where VeloraBot will send logs."
        echo
        echo "Before continuing, make sure your Log Bot:"
        echo
        echo "  • Is inside the group."
        echo "  • Is an administrator."
        echo "  • Can send messages."
        echo
        echo "To get the Group ID:"
        echo
        echo "  1. Add @myidbot to the Log group."
        echo "  2. Open the group."
        echo "  3. Send:"
        echo
        echo "       /getgroupid@myidbot"
        echo
        echo "  4. Copy the Group ID."
        echo
        echo "Examples:"
        echo "  -56376"
        echo "  -107637"
        echo

        if ! read_tty "Log Group ID: " value; then
            die "Could not read input from the terminal."
        fi

        if [[ "$value" =~ ^-[0-9]+$ ]]; then
            LOG_CHANNEL_ID="$value"
            break
        fi

        error "Group ID must be a negative number. Got: '$value'"
    done
}

ask_bank_card() {
    local value

    while true; do
        echo
        header "BANK CARD NUMBER"

        echo "Enter the 16-digit bank card number used for customer payments."
        echo
        echo "Do not use spaces or dashes."
        echo
        echo "Example:"
        echo "  6037991234567890"
        echo

        if ! read_tty "Card Number: " value; then
            die "Could not read input from the terminal."
        fi

        if [[ "$value" =~ ^[0-9]{16}$ ]]; then
            BANK_CARD_NUMBER="$value"
            break
        fi

        error "Card number must contain exactly 16 digits. Got: '$value'"
    done
}

ask_card_holder() {
    echo
    header "BANK CARD HOLDER"

    echo "Enter the full name of the bank card owner."
    echo
    echo "Example:"
    echo "  Navid Moradi"
    echo

    if ! read_tty "Card Holder Name: " BANK_CARD_HOLDER; then
        die "Could not read input from the terminal."
    fi
}

ask_bank_name() {
    echo
    header "BANK NAME"

    echo "Enter the name of the bank that issued the card."
    echo
    echo "Example:"
    echo "  Mellat"
    echo

    if ! read_tty "Bank Name: " BANK_NAME; then
        die "Could not read input from the terminal."
    fi
}

ask_panel_url() {
    local value

    while true; do
        echo
        header "3X-UI PANEL URL"

        echo "VeloraBot requires MHSanaei 3X-UI."
        echo
        echo "Enter the complete URL of your 3X-UI panel."
        echo
        echo "If VeloraBot and 3X-UI are on the SAME SERVER,"
        echo "you can use a local URL."
        echo
        echo "Examples:"
        echo
        echo "  https://127.0.0.1:2053/your_web_path"
        echo "  http://127.0.0.1:2053/your_web_path"
        echo
        echo "Using a local URL is recommended when both applications"
        echo "are installed on the same server."
        echo
        echo "If the panel is on another server, use its accessible URL."
        echo

        if ! read_tty "3X-UI Panel URL: " value; then
            die "Could not read input from the terminal."
        fi

        if [[ "$value" =~ ^https?:// ]]; then
            SENAI_PANEL_URL="$value"
            break
        fi

        error "URL must start with http:// or https://. Got: '$value'"
    done
}

ask_panel_credentials() {
    echo
    header "3X-UI PANEL LOGIN"

    echo "Enter the administrator username used to log into 3X-UI."
    echo

    if ! read_tty "Panel Username: " SENAI_PANEL_USERNAME; then
        die "Could not read input from the terminal."
    fi

    echo
    echo "Enter the administrator password."
    echo "The password will not be displayed."
    echo

    if ! read_secret_tty "Panel Password: " SENAI_PANEL_PASSWORD; then
        die "Could not read input from the terminal."
    fi
}

ask_subscription_url() {
    local value

    while true; do
        echo
        header "SUBSCRIPTION URL"

        echo "This is the public base URL used when generating"
        echo "subscription links for your customers."
        echo
        echo "It is NOT necessarily the same as your 3X-UI admin URL."
        echo
        echo "Example:"
        echo
        echo "  Panel:"
        echo "    https://panel.example.com:2053/xxxxx"
        echo
        echo "  Subscription:"
        echo "    https://sub.example.com:2083"
        echo

        if ! read_tty "Subscription URL: " value; then
            die "Could not read input from the terminal."
        fi

        if [[ "$value" =~ ^https?:// ]]; then
            SENAI_SUB_URL="$value"
            break
        fi

        error "URL must start with http:// or https://. Got: '$value'"
    done
}

ask_support() {
    echo
    header "SUPPORT USERNAME"

    echo "Enter the Telegram username customers should contact"
    echo "when they need support."
    echo
    echo "Example:"
    echo "  @your_username"
    echo

    if ! read_tty "Support Username: " SUPPORT_USERNAME; then
        die "Could not read input from the terminal."
    fi
}

ask_gemini() {
    local answer value

    echo
    header "OPTIONAL GOOGLE GEMINI AI"

    echo "Google Gemini AI support is optional."
    echo
    echo "If enabled, VeloraBot can use Gemini for AI-powered support."
    echo
    echo "Would you like to enable Gemini?"
    echo

    if ! read_tty "Enable Gemini? [y/N]: " answer; then
        die "Could not read input from the terminal."
    fi

    if [[ "$answer" =~ ^[Yy]$ ]]; then
        GEMINI_ENABLED="True"

        echo
        echo "Create an API key here:"
        echo
        echo "  https://aistudio.google.com/apikey"
        echo

        while true; do
            if ! read_secret_tty "Gemini API Key: " value; then
                die "Could not read input from the terminal."
            fi

            if [[ ${#value} -ge 20 ]]; then
                GEMINI_API_KEY="$value"
                break
            fi

            error "The Gemini API key appears invalid."
        done
    else
        GEMINI_ENABLED="False"
        GEMINI_API_KEY="Gemini_API_Key"
        info "Gemini AI will remain disabled."
    fi
}

# ============================================================
# Write Critical Values (More Robust)
# ============================================================

write_critical_values() {
    python3 - <<PY
from pathlib import Path
import re

path = Path("${CONFIG_FILE}")
text = path.read_text(encoding="utf-8")

values = {
    "BOT_TOKEN": ${BOT_TOKEN@Q},
    "ADMIN_ID": ${ADMIN_ID@Q},
    "LOG_BOT_TOKEN": ${LOG_BOT_TOKEN@Q},
    "LOG_CHANNEL_ID": ${LOG_CHANNEL_ID@Q},
    "BANK_CARD_NUMBER": ${BANK_CARD_NUMBER@Q},
    "BANK_CARD_HOLDER": ${BANK_CARD_HOLDER@Q},
    "BANK_NAME": ${BANK_NAME@Q},
    "SENAI_PANEL_URL": ${SENAI_PANEL_URL@Q},
    "SENAI_PANEL_USERNAME": ${SENAI_PANEL_USERNAME@Q},
    "SENAI_PANEL_PASSWORD": ${SENAI_PANEL_PASSWORD@Q},
    "SENAI_SUB_URL": ${SENAI_SUB_URL@Q},
    "SUPPORT_USERNAME": ${SUPPORT_USERNAME@Q},
    "GEMINI_ENABLED": ${GEMINI_ENABLED@Q},
    "GEMINI_API_KEY": ${GEMINI_API_KEY@Q},
}

for key, value in values.items():
    if key == "LOG_CHANNEL_ID":
        try:
            replacement = f"{key} = {int(value)}"
        except:
            replacement = f'{key} = "{value}"'
    elif key == "GEMINI_ENABLED":
        replacement = f"{key} = {value == 'True'}"
    else:
        replacement = f"{key} = {value!r}"

    # More flexible pattern matching
    pattern = rf"(?m)^[ \t]*{re.escape(key)}[ \t]*[:=][^\n]*$"
    text, count = re.subn(pattern, replacement, text, count=1)

    if count == 0:
        # If key not found, add it after the REQUIRED SETTINGS marker
        marker = "# ==================== 🔴 REQUIRED SETTINGS 🔴 ===================="
        if marker in text:
            text = text.replace(marker, marker + "\n" + replacement)
        else:
            text += f"\n{replacement}\n"

path.write_text(text, encoding="utf-8")
PY

    chmod 600 "$CONFIG_FILE"
}

# ============================================================
# Repair Configuration
# ============================================================

repair_config() {
    step "Repairing Configuration"

    if [[ "$SKIP_CONFIG" == "true" ]]; then
        warning "Skipping configuration repair (SKIP_CONFIG=true)"
        return 0
    fi

    echo "The current config.py is incomplete."
    echo
    echo "Only missing or invalid critical settings will be requested."
    echo "Existing valid settings will be preserved."
    echo

    is_placeholder "$BOT_TOKEN" && ask_main_config
    [[ "$ADMIN_ID" =~ ^[0-9]+$ ]] || ask_admin_id
    is_placeholder "$LOG_BOT_TOKEN" && ask_log_bot
    [[ "$LOG_CHANNEL_ID" =~ ^-[0-9]+$ ]] || ask_log_group
    [[ "$BANK_CARD_NUMBER" =~ ^[0-9]{16}$ ]] || ask_bank_card
    is_placeholder "$BANK_CARD_HOLDER" && ask_card_holder
    is_placeholder "$BANK_NAME" && ask_bank_name
    [[ "$SENAI_PANEL_URL" =~ ^https?:// ]] || ask_panel_url

    if is_placeholder "$SENAI_PANEL_USERNAME"; then
        ask_panel_credentials
    elif is_placeholder "$SENAI_PANEL_PASSWORD"; then
        echo
        header "3X-UI PANEL PASSWORD"
        if ! read_secret_tty "Panel Password: " SENAI_PANEL_PASSWORD; then
            die "Could not read input from the terminal."
        fi
    fi

    [[ "$SENAI_SUB_URL" =~ ^https?:// ]] || ask_subscription_url
    is_placeholder "$SUPPORT_USERNAME" && ask_support

    if [[ "$GEMINI_ENABLED" == "True" ]] && is_placeholder "$GEMINI_API_KEY"; then
        ask_gemini
    fi

    write_critical_values
    success "Configuration repaired successfully."
}

# ============================================================
# Installation Functions
# ============================================================

fresh_install() {
    step "Fresh Installation"

    INSTALL_MODE="fresh"

    if [[ -d "$INSTALL_DIR" ]]; then
        warning "Existing installation found."
        
        local answer
        if ! read_tty "Remove existing installation and start fresh? [y/N]: " answer; then
            die "Could not read input from the terminal."
        fi

        if [[ ! "$answer" =~ ^[Yy]$ ]]; then
            die "Fresh installation cancelled."
        fi

        # Create backup before removing
        local backup_dir
        backup_dir="$(create_backup)"
        info "Backup created before fresh install:"
        echo "  $backup_dir"
        echo

        systemctl stop "$SERVICE_NAME" 2>/dev/null || true
        systemctl disable "$SERVICE_NAME" 2>/dev/null || true
        rm -f "$SERVICE_FILE"
        systemctl daemon-reload
        rm -rf "$INSTALL_DIR"
        success "Previous installation removed."
    fi

    mkdir -p "$INSTALL_DIR"

    command_info "Downloading latest release: $LATEST_VERSION"

    local archive temp_dir extracted_dir
    archive="/tmp/VeloraBot-${LATEST_VERSION}.tar.gz"
    temp_dir="$(mktemp -d)"

    curl \
        --fail \
        --location \
        --silent \
        --show-error \
        "${API_URL}/tarball/${LATEST_VERSION}" \
        -o "$archive"

    tar -xzf "$archive" -C "$temp_dir"

    extracted_dir="$(find "$temp_dir" -mindepth 1 -maxdepth 1 -type d | head -n 1)"

    if [[ -z "$extracted_dir" ]]; then
        rm -rf "$temp_dir"
        rm -f "$archive"
        die "Could not extract GitHub release."
    fi

    cp -a "$extracted_dir"/. "$INSTALL_DIR"/

    rm -rf "$temp_dir"
    rm -f "$archive"

    mkdir -p "$DATA_DIR"
    
    # Save version file
    save_version_file

    success "VeloraBot ${LATEST_VERSION} downloaded."
}

update_existing() {
    step "Updating Existing VeloraBot"

    INSTALL_MODE="update"

    local backup_dir
    backup_dir="$(create_backup)"

    info "Backup created:"
    echo "  $backup_dir"
    echo

    systemctl stop "$SERVICE_NAME" 2>/dev/null || true

    # Save critical configuration values before replacing config.py
    extract_config_values

    local temp_dir archive extracted_dir saved_data
    temp_dir="$(mktemp -d)"
    archive="/tmp/VeloraBot-${LATEST_VERSION}.tar.gz"
    saved_data="$(mktemp -d)"

    command_info "Downloading release ${LATEST_VERSION}"

    curl \
        --fail \
        --location \
        --silent \
        --show-error \
        "${API_URL}/tarball/${LATEST_VERSION}" \
        -o "$archive"

    tar -xzf "$archive" -C "$temp_dir"

    extracted_dir="$(find "$temp_dir" -mindepth 1 -maxdepth 1 -type d | head -n 1)"

    if [[ -z "$extracted_dir" ]]; then
        rm -rf "$temp_dir" "$saved_data"
        rm -f "$archive"
        die "Could not extract GitHub release."
    fi

    # Preserve data/
    if [[ -d "$DATA_DIR" ]]; then
        cp -a "$DATA_DIR"/. "$saved_data"/
    fi

    # Replace application files
    info "Replacing application files with release ${LATEST_VERSION}..."

    find "$INSTALL_DIR" \
        -mindepth 1 \
        -maxdepth 1 \
        ! -name ".venv" \
        ! -name "data" \
        -exec rm -rf {} +

    cp -a "$extracted_dir"/. "$INSTALL_DIR"/

    # Restore data/
    mkdir -p "$DATA_DIR"
    cp -a "$saved_data"/. "$DATA_DIR"/ 2>/dev/null || true

    rm -rf "$saved_data" "$temp_dir"
    rm -f "$archive"

    # Restore critical settings into NEW config.py
    write_critical_values
    
    # Save version file
    save_version_file

    success "Application updated to ${LATEST_VERSION}."
    success "config.py updated from GitHub."
    success "Critical configuration restored."
    success "data/ preserved."
}

# ============================================================
# Setup Python Environment
# ============================================================

setup_python_environment() {
    step "Python Environment"

    if [[ ! -d "$VENV_DIR" ]]; then
        info "Creating Python virtual environment..."
        python3 -m venv "$VENV_DIR"
        success "Virtual environment created."
    else
        info "Existing virtual environment preserved."
    fi

    echo
    info "Upgrading pip..."

    "$VENV_DIR/bin/python" -m pip install \
        --upgrade \
        pip \
        setuptools \
        wheel

    echo
    info "Installing project dependencies..."

    "$VENV_DIR/bin/pip" install \
        -r "$INSTALL_DIR/requirements.txt"

    success "Python dependencies are up to date."
}

# ============================================================
# Validate Final Configuration
# ============================================================

validate_final_config() {
    step "Validating Configuration"

    if [[ ! -f "$CONFIG_FILE" ]]; then
        die "config.py does not exist."
    fi

    # Check if config.py has syntax errors
    if ! python3 -m py_compile "$CONFIG_FILE" 2>/dev/null; then
        error "config.py has syntax errors."
        
        # Try to extract values and rewrite
        extract_config_values
        write_critical_values
        
        if ! python3 -m py_compile "$CONFIG_FILE" 2>/dev/null; then
            die "Could not fix config.py syntax errors."
        fi
        
        warning "Fixed config.py syntax errors."
    fi

    # Check if config.py can be imported from the INSTALL_DIR
    cd "$INSTALL_DIR"
    
    "$VENV_DIR/bin/python" - <<'PY'
import sys
import os

# Add the install directory to Python path
sys.path.insert(0, os.getcwd())

try:
    import config
    
    required = [
        "BOT_TOKEN", "ADMIN_ID", "LOG_BOT_TOKEN", "LOG_CHANNEL_ID",
        "BANK_CARD_NUMBER", "BANK_CARD_HOLDER", "BANK_NAME",
        "SENAI_PANEL_URL", "SENAI_PANEL_USERNAME", "SENAI_PANEL_PASSWORD",
        "SENAI_SUB_URL", "SUPPORT_USERNAME",
        "GEMINI_ENABLED", "GEMINI_API_KEY",
    ]
    
    missing = [name for name in required if not hasattr(config, name)]
    
    if missing:
        print(f"Missing configuration: {', '.join(missing)}")
        sys.exit(1)
    
    print("config.py import: OK")
    print("Required configuration: OK")
    
except SyntaxError as e:
    print(f"Syntax error in config.py: {e}")
    sys.exit(1)
except Exception as e:
    print(f"Error importing config.py: {e}")
    sys.exit(1)
PY

    chmod 600 "$CONFIG_FILE"
    success "Configuration is valid."
}

# ============================================================
# Create systemd Service
# ============================================================

create_service() {
    step "Configuring systemd"

    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=VeloraBot Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python $INSTALL_DIR/main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"

    success "systemd service configured."
}

# ============================================================
# Start and Health Check
# ============================================================

start_and_check() {
    step "Starting VeloraBot"

    systemctl restart "$SERVICE_NAME"

    sleep 5

    if systemctl is-active --quiet "$SERVICE_NAME"; then
        success "VeloraBot service is running."
    else
        error "VeloraBot failed to start."

        echo
        header "SERVICE LOGS"

        journalctl -u "$SERVICE_NAME" -n 100 --no-pager

        die "Service health check failed."
    fi
}

# ============================================================
# Show Logs
# ============================================================

show_logs() {
    echo
    header "LATEST VELOraBOT LOGS"

    journalctl -u "$SERVICE_NAME" -n 50 --no-pager

    echo
    line
    echo

    local answer
    if ! read_tty "Watch live logs now? [Y/n]: " answer; then
        warning "Could not read input. Skipping live logs."
        return
    fi

    answer="${answer:-Y}"

    if [[ "$answer" =~ ^[Yy]$ ]]; then
        echo
        info "Live logs started."
        info "Press Ctrl+C to stop watching logs."
        echo

        set +e
        journalctl -u "$SERVICE_NAME" -f
        set -e
    fi
}

# ============================================================
# Final Summary
# ============================================================

final_summary() {
    header "INSTALLATION COMPLETE"

    echo -e "${GREEN}${BOLD}VeloraBot is ready.${NC}"
    echo

    echo "Installed Release:"
    echo -e "  ${GREEN}${CURRENT_VERSION}${NC}"
    echo

    echo "Installation:"
    echo "  $INSTALL_DIR"
    echo

    echo "Configuration:"
    echo "  $CONFIG_FILE"
    echo

    echo "Persistent data:"
    echo "  $DATA_DIR"
    echo

    echo "Service:"
    echo "  $SERVICE_NAME"
    echo

    echo "Status:"
    systemctl is-active "$SERVICE_NAME" || true
    echo

    line

    echo
    echo "Useful commands:"
    echo
    echo "  systemctl status velorabot"
    echo "  systemctl restart velorabot"
    echo "  systemctl stop velorabot"
    echo "  journalctl -u velorabot -f"
    echo

    line

    echo
    echo "Installer log:"
    echo "  $INSTALL_LOG"
    echo
}

# ============================================================
# Handle Existing Installation (Optimized)
# ============================================================

handle_existing_installation() {
    get_current_version

    echo
    header "EXISTING VELOraBOT DETECTED"

    echo "Installation directory:"
    echo "  $INSTALL_DIR"
    echo

    echo "Installed version:"
    echo -e "  ${YELLOW}${CURRENT_VERSION}${NC}"
    echo

    # Read existing config
    if [[ -f "$CONFIG_FILE" ]]; then
        info "Checking existing config.py..."

        if extract_config_values && validate_config; then
            echo
            success "Existing config.py is complete."
        else
            echo
            warning "Existing config.py is incomplete."
            NEEDS_CONFIG_REPAIR="true"
        fi
    else
        warning "config.py does not exist."
        NEEDS_CONFIG_REPAIR="true"
    fi

    # Already latest and no repair needed - EXIT EARLY
    if [[ "$NEEDS_CONFIG_REPAIR" == "false" ]] && \
       [[ "$FORCE_UPDATE" != "true" ]] && \
       version_is_equal "$CURRENT_VERSION" "$LATEST_VERSION"; then
        echo
        header "VELOraBOT STATUS"

        echo -e "${GREEN}✔ VeloraBot is already up to date.${NC}"
        echo
        echo "Installed Release:"
        echo -e "  ${GREEN}${CURRENT_VERSION}${NC}"
        echo
        echo "Latest Release:"
        echo -e "  ${GREEN}${LATEST_VERSION}${NC}"
        echo
        echo -e "${GREEN}✔ Configuration is valid.${NC}"
        echo -e "${GREEN}✔ No update is required.${NC}"
        echo
        echo "Nothing was changed."
        echo

        exit 0
    fi

    # Repair configuration if needed
    if [[ "$NEEDS_CONFIG_REPAIR" == "true" ]]; then
        repair_config
        extract_config_values
    fi

    # Check if update is needed
    if [[ "$FORCE_UPDATE" == "true" ]] || \
       ! version_is_equal "$CURRENT_VERSION" "$LATEST_VERSION"; then
        echo
        header "UPDATE AVAILABLE"

        echo "Current Release:"
        echo -e "  ${YELLOW}${CURRENT_VERSION}${NC}"
        echo
        echo "Latest Release:"
        echo -e "  ${GREEN}${LATEST_VERSION}${NC}"
        echo

        local answer

        if [[ "$FORCE_UPDATE" == "true" ]]; then
            answer="Y"
        else
            if ! read_tty "Update VeloraBot to ${LATEST_VERSION}? [Y/n]: " answer; then
                die "Could not read input from the terminal."
            fi
            answer="${answer:-Y}"
        fi

        if [[ "$answer" =~ ^[Yy]$ ]]; then
            update_existing
        else
            warning "Update skipped."

            if [[ "$NEEDS_CONFIG_REPAIR" == "true" ]]; then
                info "Configuration was repaired."
            fi

            return 0
        fi
    fi
}

# ============================================================
# Main
# ============================================================

main() {
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --skip-config)
                SKIP_CONFIG="true"
                shift
                ;;
            --force-update)
                FORCE_UPDATE="true"
                shift
                ;;
            --help|-h)
                echo "Usage: $0 [OPTIONS]"
                echo
                echo "Options:"
                echo "  --skip-config    Skip configuration prompts"
                echo "  --force-update   Force update even if already latest"
                echo "  --help, -h       Show this help message"
                exit 0
                ;;
            *)
                warning "Unknown option: $1"
                shift
                ;;
        esac
    done

    # Don't clear screen - keep history visible
    # clear || true

    echo
    echo -e "${CYAN}${BOLD}"
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║                                                            ║"
    echo "║                    VeloraBot Installer                     ║"
    echo "║                                                            ║"
    echo "║             Smart Install / Update / Repair                ║"
    echo "║                                                            ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"

    echo
    echo "Repository:"
    echo "https://github.com/${OWNER}/${REPO}"
    echo

    check_root
    check_os
    check_internet

    install_system_dependencies
    check_python

    get_latest_release

    # New installation
    if [[ ! -d "$INSTALL_DIR" ]]; then
        fresh_install

        # Collect all required settings for new installation
        extract_config_values || true

        if [[ "$SKIP_CONFIG" != "true" ]]; then
            ask_main_config
            ask_admin_id
            ask_log_bot
            ask_log_group
            ask_bank_card
            ask_card_holder
            ask_bank_name
            ask_panel_url
            ask_panel_credentials
            ask_subscription_url
            ask_support
            ask_gemini
        else
            warning "Skipping configuration prompts (--skip-config)"
        fi

        write_critical_values
    else
        # Existing installation
        handle_existing_installation
    fi

    # Setup Python environment
    setup_python_environment

    # Validate configuration
    validate_final_config

    # Create systemd service
    create_service

    # Start and health check
    start_and_check

    # Show final output
    show_logs
    final_summary
}

# Run main with all arguments
main "$@"