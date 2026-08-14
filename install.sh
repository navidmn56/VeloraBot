#!/usr/bin/env bash

set -Eeuo pipefail

# ============================================================
# VeloraBot - Interactive Installer
# ============================================================
#
# Repository:
# https://github.com/navidmn56/VeloraBot
#
# This installer:
#   1. Checks the server
#   2. Installs system dependencies
#   3. Downloads VeloraBot
#   4. Creates a Python virtual environment
#   5. Installs Python dependencies
#   6. Collects configuration interactively
#   7. Updates config.py
#   8. Creates a systemd service
#   9. Starts the bot
#  10. Shows live logs and final status
#
# ============================================================

set +m

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
readonly BOLD='\033[1m'
readonly DIM='\033[2m'
readonly NC='\033[0m'

# ============================================================
# Global Variables
# ============================================================

readonly APP_NAME="VeloraBot"
readonly INSTALL_DIR="/opt/VeloraBot"
readonly REPO_URL="https://github.com/navidmn56/VeloraBot.git"
readonly SERVICE_NAME="velorabot"
readonly SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
readonly VENV_DIR="${INSTALL_DIR}/.venv"
readonly CONFIG_FILE="${INSTALL_DIR}/config.py"
readonly INSTALL_LOG="/tmp/velorabot_install.log"

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

exec > >(tee -a "$INSTALL_LOG") 2>&1

# ============================================================
# UI Functions
# ============================================================

print_line() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

print_header() {
    echo
    print_line
    echo -e "${BOLD}${CYAN}  $1${NC}"
    print_line
    echo
}

print_step() {
    echo
    echo -e "${MAGENTA}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${MAGENTA}${BOLD}  STEP $1${NC}"
    echo -e "${MAGENTA}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo
}

print_info() {
    echo -e "${CYAN}ℹ $1${NC}"
}

print_success() {
    echo -e "${GREEN}✔ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✖ $1${NC}"
}

print_command() {
    echo -e "${DIM}➜ $1${NC}"
}

die() {
    print_error "$1"
    echo
    print_error "Installation failed."
    print_info "Installer log: ${INSTALL_LOG}"
    exit 1
}

# ============================================================
# Error Handler
# ============================================================

trap 'print_error "An unexpected error occurred on line $LINENO."; print_info "Check: $INSTALL_LOG"; exit 1' ERR

# ============================================================
# Root Check
# ============================================================

check_root() {

    print_step "1/10 - Checking Permissions"

    if [[ "$EUID" -ne 0 ]]; then
        print_error "This installer must be executed as root."
        echo
        echo "Please run:"
        echo
        echo "    sudo bash install.sh"
        echo
        exit 1
    fi

    print_success "Running as root."
}

# ============================================================
# Operating System Check
# ============================================================

check_os() {

    print_step "2/10 - Checking Operating System"

    if [[ ! -f /etc/os-release ]]; then
        die "Cannot detect the operating system."
    fi

    source /etc/os-release

    echo "Operating System : ${PRETTY_NAME:-Unknown}"
    echo "Architecture     : $(uname -m)"
    echo "Kernel           : $(uname -r)"
    echo

    if [[ "${ID:-}" != "ubuntu" ]]; then
        print_warning "This installer is designed for Ubuntu."
        print_warning "Detected: ${PRETTY_NAME:-Unknown}"
        echo

        read -rp "Continue anyway? [y/N]: " answer

        if [[ ! "$answer" =~ ^[Yy]$ ]]; then
            echo "Installation cancelled."
            exit 0
        fi
    else
        print_success "Ubuntu detected."
    fi
}

# ============================================================
# Internet Check
# ============================================================

check_internet() {

    print_info "Checking internet connectivity..."

    if command -v curl >/dev/null 2>&1; then
        if curl -fsS --connect-timeout 10 https://github.com >/dev/null; then
            print_success "Internet connection is available."
            return
        fi
    fi

    die "The server cannot connect to GitHub. Please check your network."
}

# ============================================================
# Server Information
# ============================================================

show_server_info() {

    print_header "SERVER INFORMATION"

    echo "Hostname        : $(hostname)"
    echo "Operating System: ${PRETTY_NAME:-Unknown}"
    echo "Architecture    : $(uname -m)"
    echo "CPU             : $(nproc) core(s)"
    echo "Memory:"
    free -h
    echo
    echo "Disk:"
    df -h /
    echo
}

# ============================================================
# Install Dependencies
# ============================================================

install_dependencies() {

    print_step "3/10 - Installing System Dependencies"

    print_info "The installer will now install the packages required by VeloraBot."
    echo
    echo "Packages:"
    echo "  - git"
    echo "  - curl"
    echo "  - wget"
    echo "  - Python 3"
    echo "  - Python 3 pip"
    echo "  - Python 3 venv"
    echo "  - Python development tools"
    echo "  - build tools"
    echo

    print_command "apt-get update"

    apt-get update

    echo
    print_command "apt-get install"

    apt-get install -y \
        git \
        curl \
        wget \
        ca-certificates \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        build-essential \
        libssl-dev \
        libffi-dev

    print_success "System dependencies installed."
}

# ============================================================
# Python Check
# ============================================================

check_python() {

    print_info "Checking Python version..."

    if ! command -v python3 >/dev/null 2>&1; then
        die "Python 3 was not installed successfully."
    fi

    local version
    version="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"

    echo "Python version: ${version}"

    if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
        die "VeloraBot requires Python 3.10 or newer."
    fi

    print_success "Python ${version} is supported."
}

# ============================================================
# Repository Installation
# ============================================================

install_repository() {

    print_step "4/10 - Downloading VeloraBot"

    if [[ -d "$INSTALL_DIR" ]]; then

        print_warning "An existing VeloraBot installation was found at:"
        echo
        echo "    $INSTALL_DIR"
        echo

        echo -e "${CYAN}Choose what you want to do:${NC}"
        echo
        echo "  [Y] Keep the existing installation"
        echo "      - Keep the current bot files"
        echo "      - Keep the current virtual environment"
        echo "      - Keep the current dependencies"
        echo "      - Only update/reconfigure config.py"
        echo
        echo "  [N] Remove the existing installation"
        echo "      - Stop the existing bot"
        echo "      - Remove the entire /opt/VeloraBot directory"
        echo "      - Remove the old systemd service"
        echo "      - Clone VeloraBot again"
        echo "      - Create a fresh virtual environment"
        echo "      - Install dependencies again"
        echo
        echo -e "${YELLOW}WARNING: Choosing N will delete the existing VeloraBot installation.${NC}"
        echo

        while true; do

            read -rp "Keep existing installation? [Y/n]: " answer

            answer="${answer:-Y}"

            case "$answer" in

                [Yy]|[Yy][Ee][Ss])

                    echo
                    print_success "Keeping the existing VeloraBot installation."
                    echo
                    print_info "The bot files will NOT be re-downloaded."
                    print_info "The virtual environment will NOT be recreated."
                    print_info "Only configuration will be updated."

                    return 0
                    ;;

                [Nn]|[Nn][Oo])

                    echo
                    print_warning "You selected a fresh installation."
                    echo
                    print_warning "The existing VeloraBot installation will be deleted."
                    echo

                    read -rp "Are you absolutely sure? Type YES to continue: " confirmation

                    if [[ "$confirmation" != "YES" ]]; then
                        echo
                        print_info "Deletion cancelled."
                        print_info "Keeping the existing installation."

                        return 0
                    fi

                    echo
                    print_info "Stopping existing VeloraBot service..."

                    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
                    systemctl disable "$SERVICE_NAME" 2>/dev/null || true

                    echo
                    print_info "Removing existing systemd service..."

                    rm -f "$SERVICE_FILE"

                    systemctl daemon-reload

                    echo
                    print_info "Removing existing VeloraBot files..."

                    rm -rf "$INSTALL_DIR"

                    print_success "Existing installation removed."
                    echo

                    print_info "Cloning a fresh copy of VeloraBot..."

                    git clone "$REPO_URL" "$INSTALL_DIR"

                    print_success "Fresh VeloraBot installation downloaded."

                    return 0
                    ;;

                *)

                    print_warning "Invalid choice."
                    print_info "Please enter Y or N."

                    ;;

            esac

        done

    else

        print_info "No existing installation was found."

        echo
        print_info "Cloning VeloraBot from GitHub..."
        echo

        git clone "$REPO_URL" "$INSTALL_DIR"

        print_success "VeloraBot downloaded successfully."
    fi
}

# ============================================================
# Virtual Environment
# ============================================================

setup_virtualenv() {

    print_step "5/10 - Setting Up Python Environment"

    cd "$INSTALL_DIR"

    if [[ ! -d "$VENV_DIR" ]]; then

        print_info "Creating Python virtual environment..."

        python3 -m venv "$VENV_DIR"

        print_success "Virtual environment created."

    else

        print_info "Existing virtual environment found."
    fi

    echo
    print_info "Upgrading pip, setuptools and wheel..."

    "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel

    echo
    print_info "Installing VeloraBot Python dependencies..."
    echo

    if [[ ! -f "$INSTALL_DIR/requirements.txt" ]]; then
        die "requirements.txt was not found."
    fi

    "$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

    print_success "Python dependencies installed."
}

# ============================================================
# Input Helpers
# ============================================================

ask_required() {

    local variable_name="$1"
    local prompt="$2"
    local description="$3"
    local example="$4"

    local value=""

    while [[ -z "$value" ]]; do

        echo
        print_line
        echo -e "${BOLD}${WHITE}  ${prompt}${NC}"
        print_line
        echo
        echo -e "${CYAN}${description}${NC}"
        echo

        if [[ -n "$example" ]]; then
            echo -e "${DIM}Example: ${example}${NC}"
            echo
        fi

        read -rp "Enter ${prompt}: " value

        if [[ -z "$value" ]]; then
            print_error "${prompt} cannot be empty."
        fi
    done

    printf -v "$variable_name" '%s' "$value"
}

ask_secret() {

    local variable_name="$1"
    local prompt="$2"
    local description="$3"
    local example="$4"

    local value=""

    while [[ -z "$value" ]]; do

        echo
        print_line
        echo -e "${BOLD}${WHITE}  ${prompt}${NC}"
        print_line
        echo
        echo -e "${CYAN}${description}${NC}"
        echo

        if [[ -n "$example" ]]; then
            echo -e "${DIM}Example: ${example}${NC}"
            echo
        fi

        read -rsp "Enter ${prompt}: " value
        echo

        if [[ -z "$value" ]]; then
            print_error "${prompt} cannot be empty."
        fi
    done

    printf -v "$variable_name" '%s' "$value"
}

# ============================================================
# Validation
# ============================================================

validate_bot_token_value() {

    local token="$1"

    [[ "$token" =~ ^[0-9]{6,12}:[A-Za-z0-9_-]{20,}$ ]]
}

validate_admin_id_value() {

    local id="$1"

    [[ "$id" =~ ^[0-9]+$ ]]
}

validate_group_id_value() {

    local id="$1"

    [[ "$id" =~ ^-[0-9]+$ ]]
}

validate_card_value() {

    local card="$1"

    [[ "$card" =~ ^[0-9]{16}$ ]]
}

validate_url_value() {

    local url="$1"

    [[ "$url" =~ ^https?:// ]]
}

# ============================================================
# Main Bot Token
# ============================================================

get_main_bot_token() {

    while true; do

        ask_secret \
            "BOT_TOKEN" \
            "Main Telegram Bot Token" \
            "This is the token of the main Telegram bot that your customers will interact with.

You can get it from @BotFather:

1. Open Telegram.
2. Open @BotFather.
3. Send /mybots.
4. Select your bot.
5. Open the API Token section.
6. Copy the token and paste it here.

This token is a secret. Never share it publicly." \
            "1234567890:AAxxxxxxxxxxxxxxxxxxxxxxxx"

        if validate_bot_token_value "$BOT_TOKEN"; then
            print_success "Bot token format looks valid."
            break
        fi

        print_error "The Bot Token format does not look valid."
        print_warning "Please copy the complete token from @BotFather."
    done
}

# ============================================================
# Admin ID
# ============================================================

get_admin_id() {

    while true; do

        ask_required \
            "ADMIN_ID" \
            "Telegram Admin ID" \
            "This is your personal Telegram numeric ID.

VeloraBot uses this ID to identify the main administrator.

To find your Telegram ID:

1. Open Telegram.
2. Open @myidbot.
3. Press Start.
4. The bot will show your numeric Telegram ID.
5. Enter that number here.

Only numbers are allowed. Do not enter @username." \
            "123456789"

        if validate_admin_id_value "$ADMIN_ID"; then
            print_success "Telegram Admin ID accepted."
            break
        fi

        print_error "Admin ID must contain numbers only."
    done
}

# ============================================================
# Log Bot
# ============================================================

get_log_bot_token() {

    while true; do

        ask_secret \
            "LOG_BOT_TOKEN" \
            "Log Bot Token" \
            "VeloraBot uses a second Telegram bot to send logs to your Log group.

You need to create another bot using @BotFather.

Important:

1. Create a separate bot with @BotFather.
2. Copy its API Token.
3. Add this Log Bot to your Log group.
4. Make the Log Bot an ADMINISTRATOR of that group.
5. Make sure the Log Bot has permission to SEND MESSAGES.
6. The bot must be able to post messages in the group.

If the Log Bot cannot send messages, VeloraBot will not be able to deliver Telegram logs." \
            "1234567890:AAxxxxxxxxxxxxxxxxxxxxxxxx"

        if validate_bot_token_value "$LOG_BOT_TOKEN"; then
            print_success "Log Bot Token format looks valid."
            break
        fi

        print_error "The Log Bot Token format does not look valid."
    done
}

# ============================================================
# Log Group ID
# ============================================================

get_log_group_id() {

    while true; do

        ask_required \
            "LOG_CHANNEL_ID" \
            "Log Group ID" \
            "This is the numeric ID of the Telegram group where VeloraBot will send logs.

Before entering the ID, make sure:

1. Your Log Bot is already inside the group.
2. Your Log Bot is an ADMINISTRATOR.
3. The Log Bot has permission to SEND MESSAGES.

To find the group ID:

1. Add @myidbot to your Log group.
2. Open the group.
3. Send this command:

   /getgroupid@myidbot

4. @myidbot will display the group ID.
5. Copy that numeric ID and enter it here.

Typical examples look like:

   -5637636475454
   -1004387169176

The value must start with a minus sign." \
            "-1004387169176"

        if validate_group_id_value "$LOG_CHANNEL_ID"; then
            print_success "Log Group ID accepted."
            break
        fi

        print_error "The Log Group ID must be a negative number."
        print_info "Example: -5637636475454 or -1004387169176"
    done
}

# ============================================================
# Bank Card
# ============================================================

get_bank_card() {

    while true; do

        ask_required \
            "BANK_CARD_NUMBER" \
            "Bank Card Number" \
            "This is the 16-digit bank card number that VeloraBot will display to customers when they need to make a payment.

Enter the card number without spaces or dashes." \
            "6037991234567890"

        if validate_card_value "$BANK_CARD_NUMBER"; then
            print_success "Bank card number accepted."
            break
        fi

        print_error "The card number must contain exactly 16 digits."
    done
}

# ============================================================
# Card Holder
# ============================================================

get_card_holder() {

    ask_required \
        "BANK_CARD_HOLDER" \
        "Bank Card Holder Name" \
        "Enter the full name of the person who owns the bank card.

This name can be displayed to customers so they can verify the payment recipient." \
        "Navid Moradi"
}

# ============================================================
# Bank Name
# ============================================================

get_bank_name() {

    ask_required \
        "BANK_NAME" \
        "Bank Name" \
        "Enter the name of the bank that issued the payment card.

This is displayed together with the card number when customers make payments." \
        "Mellat"
}

# ============================================================
# 3X-UI Panel URL
# ============================================================

get_panel_url() {

    while true; do

        ask_required \
            "SENAI_PANEL_URL" \
            "3X-UI Panel URL" \
            "Enter the complete URL of your MHSanaei 3X-UI panel.

IMPORTANT:

If VeloraBot and 3X-UI are installed on the SAME SERVER, you can use a LOCAL URL.

For example:

   https://127.0.0.1:2053/your_web_path

or:

   http://127.0.0.1:2053/your_web_path

Using a local URL is recommended when the bot and panel are on the same server because the bot can communicate with the panel directly without going through the public internet.

If your panel is on another server, use its accessible URL instead.

The URL must include the Web Path if your 3X-UI panel uses a custom Web Path." \
            "https://127.0.0.1:2053/your_web_path"

        if validate_url_value "$SENAI_PANEL_URL"; then
            print_success "3X-UI Panel URL accepted."
            break
        fi

        print_error "The panel URL must start with http:// or https://."
    done
}

# ============================================================
# 3X-UI Username
# ============================================================

get_panel_username() {

    ask_required \
        "SENAI_PANEL_USERNAME" \
        "3X-UI Panel Username" \
        "Enter the administrator username that you use to log in to your MHSanaei 3X-UI panel.

This account must have enough permissions for VeloraBot to manage clients and configurations." \
        "admin"
}

# ============================================================
# 3X-UI Password
# ============================================================

get_panel_password() {

    ask_secret \
        "SENAI_PANEL_PASSWORD" \
        "3X-UI Panel Password" \
        "Enter the administrator password of your MHSanaei 3X-UI panel.

Your password will not be displayed while you type it." \
        "YourPanelPassword"
}

# ============================================================
# Subscription URL
# ============================================================

get_subscription_url() {

    while true; do

        ask_required \
            "SENAI_SUB_URL" \
            "Subscription URL" \
            "This is the public base URL that VeloraBot uses when generating subscription links for customers.

IMPORTANT:

This is NOT necessarily the same URL as your 3X-UI admin panel.

For example:

Panel URL:
https://panel.example.com:2053/xxxxx

Subscription URL:
https://sub.example.com:2083

Enter the base subscription URL used by your clients." \
            "https://sub.example.com:2083"

        if validate_url_value "$SENAI_SUB_URL"; then
            print_success "Subscription URL accepted."
            break
        fi

        print_error "The Subscription URL must start with http:// or https://."
    done
}

# ============================================================
# Support Username
# ============================================================

get_support_username() {

    while true; do

        ask_required \
            "SUPPORT_USERNAME" \
            "Support Telegram Username" \
            "Enter the Telegram username that customers should contact when they need support.

The username should normally start with @." \
            "@your_username"

        if [[ "$SUPPORT_USERNAME" == @* ]]; then
            print_success "Support username accepted."
            break
        fi

        print_error "The support username should start with @."
    done
}

# ============================================================
# Gemini
# ============================================================

get_gemini_settings() {

    echo
    print_line
    echo -e "${BOLD}${WHITE}  OPTIONAL: Google Gemini AI${NC}"
    print_line
    echo

    echo -e "${CYAN}VeloraBot has optional Google Gemini AI support.${NC}"
    echo
    echo "Gemini can be used for AI-powered customer support."
    echo
    echo "This feature is OPTIONAL."
    echo
    echo "If you do not want to use AI, choose No."
    echo "You can enable it later by editing config.py."
    echo

    while true; do

        read -rp "Enable Google Gemini AI? [y/N]: " answer
        answer="${answer:-N}"

        case "$answer" in

            [Yy]|[Yy][Ee][Ss])

                GEMINI_ENABLED="True"

                echo
                print_success "Google Gemini AI will be enabled."

                while true; do

                    ask_secret \
                        "GEMINI_API_KEY" \
                        "Google Gemini API Key" \
                        "This API key allows VeloraBot to communicate with Google Gemini.

You can create an API key through Google AI Studio.

Open:

https://aistudio.google.com/apikey

Create an API key, copy it, and paste it here.

Keep this key private." \
                        "AIzaSyxxxxxxxxxxxxxxxxxxxxxxxx"

                    if [[ ${#GEMINI_API_KEY} -ge 20 ]]; then
                        print_success "Gemini API key accepted."
                        break
                    fi

                    print_error "The Gemini API key appears to be too short."
                done

                break
                ;;

            [Nn]|[Nn][Oo])

                GEMINI_ENABLED="False"
                GEMINI_API_KEY="Gemini_API_Key"

                print_info "Google Gemini AI will remain disabled."

                break
                ;;

            *)

                print_warning "Please answer Y or N."
                ;;

        esac
    done
}

# ============================================================
# Collect All Configuration
# ============================================================

collect_configuration() {

    print_step "6/10 - VeloraBot Configuration"

    echo
    echo -e "${BOLD}${CYAN}The installer will now configure your bot.${NC}"
    echo
    echo "You will be asked for:"
    echo
    echo "  1. Main Telegram Bot Token"
    echo "  2. Telegram Admin ID"
    echo "  3. Log Bot Token"
    echo "  4. Log Group ID"
    echo "  5. Bank Card Number"
    echo "  6. Bank Card Holder"
    echo "  7. Bank Name"
    echo "  8. 3X-UI Panel URL"
    echo "  9. 3X-UI Username"
    echo " 10. 3X-UI Password"
    echo " 11. Subscription URL"
    echo " 12. Support Username"
    echo " 13. Optional Google Gemini AI"
    echo

    read -rp "Press ENTER to start configuration..."

    get_main_bot_token
    get_admin_id

    get_log_bot_token
    get_log_group_id

    get_bank_card
    get_card_holder
    get_bank_name

    get_panel_url
    get_panel_username
    get_panel_password
    get_subscription_url

    get_support_username

    get_gemini_settings
}

# ============================================================
# Backup config
# ============================================================

backup_config() {

    if [[ -f "$CONFIG_FILE" ]]; then

        local backup

        backup="${CONFIG_FILE}.backup.$(date +%Y%m%d_%H%M%S)"

        cp "$CONFIG_FILE" "$backup"

        chmod 600 "$backup"

        print_success "Existing config.py backed up:"
        echo "    $backup"
    fi
}

# ============================================================
# Write Config
# ============================================================

write_config() {

    print_step "7/10 - Writing Configuration"

    if [[ ! -f "$CONFIG_FILE" ]]; then
        die "config.py was not found at $CONFIG_FILE"
    fi

    backup_config

    export BOT_TOKEN
    export ADMIN_ID
    export LOG_BOT_TOKEN
    export LOG_CHANNEL_ID

    export BANK_CARD_NUMBER
    export BANK_CARD_HOLDER
    export BANK_NAME

    export SENAI_PANEL_URL
    export SENAI_PANEL_USERNAME
    export SENAI_PANEL_PASSWORD
    export SENAI_SUB_URL

    export SUPPORT_USERNAME

    export GEMINI_ENABLED
    export GEMINI_API_KEY

    print_info "Updating required settings in config.py..."

    python3 <<'PYTHON'
from pathlib import Path
import os
import re

config = Path("/opt/VeloraBot/config.py")

text = config.read_text(encoding="utf-8")

values = {
    "BOT_TOKEN": os.environ["BOT_TOKEN"],
    "ADMIN_ID": os.environ["ADMIN_ID"],
    "LOG_BOT_TOKEN": os.environ["LOG_BOT_TOKEN"],
    "LOG_CHANNEL_ID": int(os.environ["LOG_CHANNEL_ID"]),

    "BANK_CARD_NUMBER": os.environ["BANK_CARD_NUMBER"],
    "BANK_CARD_HOLDER": os.environ["BANK_CARD_HOLDER"],
    "BANK_NAME": os.environ["BANK_NAME"],

    "SENAI_PANEL_URL": os.environ["SENAI_PANEL_URL"],
    "SENAI_PANEL_USERNAME": os.environ["SENAI_PANEL_USERNAME"],
    "SENAI_PANEL_PASSWORD": os.environ["SENAI_PANEL_PASSWORD"],
    "SENAI_SUB_URL": os.environ["SENAI_SUB_URL"],

    "SUPPORT_USERNAME": os.environ["SUPPORT_USERNAME"],

    "GEMINI_ENABLED": os.environ["GEMINI_ENABLED"] == "True",
    "GEMINI_API_KEY": os.environ["GEMINI_API_KEY"],
}

for key, value in values.items():

    if isinstance(value, bool):
        replacement = f"{key} = {value}"

    elif isinstance(value, int):
        replacement = f"{key} = {value}"

    else:
        replacement = f"{key} = {value!r}"

    pattern = rf"(?m)^[ \t]*{re.escape(key)}[ \t]*=[^\n]*$"

    text, count = re.subn(
        pattern,
        replacement,
        text,
        count=1
    )

    if count != 1:
        raise RuntimeError(
            f"Could not find exactly one configuration variable named {key}"
        )

config.write_text(text, encoding="utf-8")

PYTHON

    chmod 600 "$CONFIG_FILE"

    print_success "config.py has been configured."
    print_info "Existing configuration settings were preserved."
}

# ============================================================
# Verify Configuration
# ============================================================

verify_configuration() {

    print_info "Running configuration verification..."

    "$VENV_DIR/bin/python" - <<'PYTHON'
import config

required = [
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
]

for item in required:
    if not hasattr(config, item):
        raise RuntimeError(f"Missing configuration: {item}")

print("Configuration import: OK")
PYTHON

    print_success "Configuration verification completed."
}

# ============================================================
# Create systemd service
# ============================================================

create_service() {

    print_step "8/10 - Creating VeloraBot Service"

    print_info "Creating systemd service:"
    echo "    $SERVICE_FILE"
    echo

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

    print_command "systemctl daemon-reload"

    systemctl daemon-reload

    print_command "systemctl enable $SERVICE_NAME"

    systemctl enable "$SERVICE_NAME"

    print_success "systemd service created and enabled."
}

# ============================================================
# Start Bot
# ============================================================

start_bot() {

    print_step "9/10 - Starting VeloraBot"

    print_info "Starting the bot..."
    echo

    systemctl restart "$SERVICE_NAME"

    sleep 3

    if systemctl is-active --quiet "$SERVICE_NAME"; then

        print_success "VeloraBot service is running."

    else

        print_error "VeloraBot failed to start."

        echo
        print_header "LAST SERVICE LOGS"

        journalctl -u "$SERVICE_NAME" -n 50 --no-pager

        die "VeloraBot could not be started."
    fi
}

# ============================================================
# Live Logs
# ============================================================

show_live_logs() {

    print_step "10/10 - Checking Live Bot Logs"

    echo
    print_info "VeloraBot is now running."
    echo
    echo "The next logs are from the actual systemd service."
    echo "This allows you to see exactly what the bot is doing."
    echo
    echo "Press Ctrl+C when you want to stop watching the logs."
    echo
    sleep 2

    print_line
    echo

    journalctl -u "$SERVICE_NAME" -n 100 --no-pager

    echo
    print_line
    echo

    read -rp "Do you want to watch live logs now? [Y/n]: " answer
    answer="${answer:-Y}"

    if [[ "$answer" =~ ^[Yy]$ ]]; then

        echo
        print_info "Live logs started. Press Ctrl+C to exit."
        echo

        set +e
        journalctl -u "$SERVICE_NAME" -f
        set -e

        echo
        print_info "Live log viewer closed."
    fi
}

# ============================================================
# Final Status
# ============================================================

show_final_status() {

    print_header "INSTALLATION COMPLETED"

    echo -e "${GREEN}${BOLD}VeloraBot has been installed successfully.${NC}"
    echo

    echo "Installation directory:"
    echo "    $INSTALL_DIR"
    echo

    echo "Configuration:"
    echo "    $CONFIG_FILE"
    echo

    echo "Systemd service:"
    echo "    $SERVICE_NAME"
    echo

    echo "Service status:"
    systemctl --no-pager --full status "$SERVICE_NAME" || true

    echo
    print_line
    echo

    echo -e "${BOLD}${CYAN}Useful commands:${NC}"
    echo
    echo "  Check status:"
    echo "    systemctl status velorabot"
    echo
    echo "  Restart:"
    echo "    systemctl restart velorabot"
    echo
    echo "  Stop:"
    echo "    systemctl stop velorabot"
    echo
    echo "  View live logs:"
    echo "    journalctl -u velorabot -f"
    echo
    echo "  View recent logs:"
    echo "    journalctl -u velorabot -n 100 --no-pager"
    echo

    print_line

    echo
    echo -e "${GREEN}Thank you for using VeloraBot.${NC}"
    echo
}

# ============================================================
# Main
# ============================================================

main() {

    clear || true

    echo
    echo -e "${CYAN}${BOLD}"
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║                                                            ║"
    echo "║                     VeloraBot Installer                    ║"
    echo "║                                                            ║"
    echo "║          Telegram VPN Configuration Management             ║"
    echo "║                                                            ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"

    echo
    echo "Repository:"
    echo "https://github.com/navidmn56/VeloraBot"
    echo

    check_root
    check_os
    check_internet
    show_server_info

    install_dependencies
    check_python

    install_repository
    setup_virtualenv

    collect_configuration
    write_config
    verify_configuration

    create_service
    start_bot

    show_live_logs
    show_final_status
}

main "$@"