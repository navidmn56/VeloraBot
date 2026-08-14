#!/bin/bash

# ============================================
# 🚀 VeloraBot - Complete Installation Script
# Optimized for Ubuntu Server 20.04/22.04/24.04
# ============================================

set -e  # Exit on error
set -o pipefail  # Exit on pipe failure

# ============================================
# 🎨 Color Definitions
# ============================================
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly MAGENTA='\033[0;35m'
readonly CYAN='\033[0;36m'
readonly WHITE='\033[1;37m'
readonly BOLD='\033[1m'
readonly DIM='\033[2m'
readonly BLINK='\033[5m'
readonly REVERSE='\033[7m'
readonly NC='\033[0m' # No Color

# ============================================
# 📁 Global Variables
# ============================================
readonly INSTALL_DIR="/opt/VeloraBot"
readonly REPO_URL="https://github.com/navidmn56/VeloraBot.git"
readonly SERVICE_NAME="velorabot"
readonly SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
readonly REQUIREMENTS_FILE="requirements.txt"
readonly CONFIG_FILE="config.py"
readonly VENV_DIR=".venv"
readonly LOG_FILE="/tmp/velorabot_install.log"
readonly BACKUP_DIR="/tmp/velorabot_backup_$(date +%Y%m%d_%H%M%S)"

# ============================================
# 🎯 Helper Functions
# ============================================

# Print formatted messages
print_header() {
    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}${CYAN}  $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo -e "${CYAN}ℹ️  $1${NC}"
}

print_progress() {
    echo -e "${MAGENTA}🔄 $1${NC}"
}

# Exit with error message
error_exit() {
    print_error "$1"
    print_info "Check the log file for details: $LOG_FILE"
    exit 1
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check if running as root
check_root() {
    if [[ $EUID -eq 0 ]]; then
        print_warning "Running as root is not recommended."
        print_warning "Please run as a regular user with sudo privileges."
        read -p "Continue anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
        CURRENT_USER="root"
        USER_HOME="/root"
    else
        CURRENT_USER=$(whoami)
        USER_HOME=$HOME
    fi
}

# Check Ubuntu version
check_ubuntu_version() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        if [[ "$ID" != "ubuntu" ]]; then
            print_warning "This script is optimized for Ubuntu, but you're running $PRETTY_NAME"
            read -p "Continue anyway? (y/N): " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        else
            print_info "Detected: $PRETTY_NAME"
        fi
    fi
}

# Check internet connection
check_internet() {
    print_progress "Checking internet connection..."
    if ! ping -c 1 -W 5 google.com >/dev/null 2>&1; then
        if ! ping -c 1 -W 5 github.com >/dev/null 2>&1; then
            error_exit "No internet connection detected"
        fi
    fi
    print_success "Internet connection is available"
}

# Check disk space
check_disk_space() {
    print_progress "Checking disk space..."
    local available_space=$(df /opt --output=avail -BG 2>/dev/null | tail -1 | tr -dc '0-9')
    if [[ -z "$available_space" ]]; then
        available_space=$(df / --output=avail -BG 2>/dev/null | tail -1 | tr -dc '0-9')
    fi
    
    if [[ "$available_space" -lt 2 ]]; then
        error_exit "Insufficient disk space. Need at least 2GB, but only ${available_space}GB available"
    fi
    print_success "Disk space is sufficient (${available_space}GB available)"
}

# Check memory
check_memory() {
    print_progress "Checking system memory..."
    local total_memory=$(free -m | awk '/^Mem:/{print $2}')
    if [[ "$total_memory" -lt 256 ]]; then
        print_warning "Low memory detected (${total_memory}MB). Bot may not run smoothly."
    else
        print_success "System memory: ${total_memory}MB"
    fi
}

# Check Python version
check_python() {
    print_progress "Checking Python..."
    if ! command_exists python3; then
        print_info "Python 3 not found. Installing..."
        sudo apt install -y python3 >/dev/null 2>&1 || error_exit "Failed to install Python 3"
    fi
    
    local python_version=$(python3 --version 2>&1 | awk '{print $2}')
    local major_version=$(echo "$python_version" | cut -d. -f1)
    local minor_version=$(echo "$python_version" | cut -d. -f2)
    
    if [[ "$major_version" -lt 3 ]] || [[ "$major_version" -eq 3 && "$minor_version" -lt 8 ]]; then
        error_exit "Python 3.8 or higher is required. Current version: $python_version"
    fi
    
    print_success "Python $python_version found"
}

# Create loading animation
show_spinner() {
    local pid=$1
    local delay=0.1
    local spinstr='|/-\'
    while ps -p "$pid" >/dev/null 2>&1; do
        local temp=${spinstr#?}
        printf " [%c]  " "$spinstr"
        local spinstr=$temp${spinstr%"$temp"}
        sleep $delay
        printf "\b\b\b\b\b\b"
    done
    printf "    \b\b\b\b"
}

# Function to get valid input
get_valid_input() {
    local prompt="$1"
    local default="$2"
    local input=""
    
    while [[ -z "$input" ]]; do
        if [[ -n "$default" ]]; then
            read -p "$prompt [$default]: " input
            input=${input:-$default}
        else
            read -p "$prompt: " input
        fi
        
        if [[ -z "$input" ]]; then
            print_error "This field cannot be empty!"
        fi
    done
    
    echo "$input"
}

# Function to get yes/no input
get_yes_no() {
    local prompt="$1"
    local default="${2:-n}"
    local reply=""
    
    while true; do
        if [[ "$default" == "y" ]]; then
            read -p "$prompt [Y/n]: " reply
            reply=${reply:-y}
        else
            read -p "$prompt [y/N]: " reply
            reply=${reply:-n}
        fi
        
        case $reply in
            [Yy]|[Yy][Ee][Ss]) return 0 ;;
            [Nn]|[Nn][Oo]) return 1 ;;
            *) print_warning "Please answer yes or no" ;;
        esac
    done
}

# Validate Telegram bot token
validate_bot_token() {
    local token="$1"
    if [[ "$token" =~ ^[0-9]{8,10}:[A-Za-z0-9_-]{35}$ ]]; then
        return 0
    else
        return 1
    fi
}

# Validate bank card number
validate_card_number() {
    local card="$1"
    if [[ "$card" =~ ^[0-9]{16}$ ]]; then
        return 0
    else
        return 1
    fi
}

# ============================================
# 🚀 Installation Functions
# ============================================

# Install system dependencies
install_system_deps() {
    print_header "📦 Installing System Dependencies"
    
    print_progress "Updating package list..."
    sudo apt update >/dev/null 2>&1 || error_exit "Failed to update package list"
    show_spinner $!
    
    print_progress "Installing required packages..."
    local packages=("python3" "python3-venv" "python3-pip" "git" "wget" "curl" "build-essential" "libssl-dev" "libffi-dev")
    
    for package in "${packages[@]}"; do
        if ! command_exists "$package"; then
            print_info "Installing $package..."
            sudo apt install -y "$package" >/dev/null 2>&1 || print_warning "Failed to install $package"
        fi
    done
    
    print_success "System dependencies installed"
}

# Clone repository
clone_repository() {
    print_header "📥 Cloning Repository"
    
    if [[ -d "$INSTALL_DIR" ]]; then
        print_warning "Directory $INSTALL_DIR already exists!"
        
        if get_yes_no "Do you want to backup and remove existing installation?" "n"; then
            print_progress "Creating backup..."
            sudo mv "$INSTALL_DIR" "$BACKUP_DIR" || error_exit "Failed to create backup"
            print_info "Backup created at: $BACKUP_DIR"
        else
            error_exit "Installation cancelled. Please remove $INSTALL_DIR manually."
        fi
    fi
    
    print_progress "Cloning repository..."
    sudo git clone "$REPO_URL" "$INSTALL_DIR" >/dev/null 2>&1 || error_exit "Failed to clone repository"
    show_spinner $!
    
    sudo chown -R "$CURRENT_USER:$CURRENT_USER" "$INSTALL_DIR" || error_exit "Failed to change ownership"
    
    cd "$INSTALL_DIR" || error_exit "Failed to enter $INSTALL_DIR"
    
    print_success "Repository cloned to $INSTALL_DIR"
}

# Setup virtual environment
setup_venv() {
    print_header "🐍 Setting up Virtual Environment"
    
    cd "$INSTALL_DIR" || error_exit "Failed to enter $INSTALL_DIR"
    
    if [[ -d "$VENV_DIR" ]]; then
        print_warning "Virtual environment already exists!"
        if ! get_yes_no "Do you want to recreate it?" "n"; then
            print_info "Using existing virtual environment"
            return
        fi
        rm -rf "$VENV_DIR"
    fi
    
    print_progress "Creating virtual environment..."
    python3 -m venv "$VENV_DIR" || error_exit "Failed to create virtual environment"
    show_spinner $!
    
    print_success "Virtual environment created"
}

# Install Python dependencies
install_python_deps() {
    print_header "📚 Installing Python Dependencies"
    
    cd "$INSTALL_DIR" || error_exit "Failed to enter $INSTALL_DIR"
    
    if [[ ! -f "$REQUIREMENTS_FILE" ]]; then
        error_exit "requirements.txt not found in $INSTALL_DIR"
    fi
    
    print_progress "Upgrading pip..."
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip >/dev/null 2>&1 || error_exit "Failed to upgrade pip"
    show_spinner $!
    
    print_progress "Installing requirements..."
    pip install -r "$REQUIREMENTS_FILE" >/dev/null 2>&1 || error_exit "Failed to install requirements"
    show_spinner $!
    
    deactivate
    
    print_success "Python dependencies installed"
}

# Configure bot
configure_bot() {
    print_header "⚙️  Bot Configuration"
    
    cd "$INSTALL_DIR" || error_exit "Failed to enter $INSTALL_DIR"
    
    if [[ ! -f "$CONFIG_FILE" ]]; then
        error_exit "config.py not found in $INSTALL_DIR"
    fi
    
    # Create backup
    cp "$CONFIG_FILE" "${CONFIG_FILE}.backup"
    print_info "Backup created: ${CONFIG_FILE}.backup"
    
    echo
    print_info "Please provide the following information:"
    echo
    
    # Bot Token
    while true; do
        BOT_TOKEN=$(get_valid_input "🔑 Main Bot Token (from @BotFather)")
        if validate_bot_token "$BOT_TOKEN"; then
            break
        else
            print_error "Invalid bot token format! Expected: 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
        fi
    done
    
    # Admin ID
    ADMIN_ID=$(get_valid_input "👤 Admin Telegram ID (from @myidbot)")
    
    # Log Bot Token
    if get_yes_no "📝 Use different bot for logging?" "n"; then
        while true; do
            LOG_BOT_TOKEN=$(get_valid_input "Log Bot Token")
            if validate_bot_token "$LOG_BOT_TOKEN"; then
                break
            else
                print_error "Invalid bot token format!"
            fi
        done
    else
        LOG_BOT_TOKEN="$BOT_TOKEN"
        print_info "Using main bot for logging"
    fi
    
    # Log Channel ID
    LOG_CHANNEL_ID=$(get_valid_input "📢 Log Channel/Group ID")
    # Remove leading -100 if present for consistency
    LOG_CHANNEL_ID=${LOG_CHANNEL_ID#-100}
    
    # Bank Details
    echo
    print_info "Payment Information:"
    while true; do
        BANK_CARD_NUMBER=$(get_valid_input "💳 Bank Card Number (16 digits)")
        if validate_card_number "$BANK_CARD_NUMBER"; then
            break
        else
            print_error "Invalid card number! Must be 16 digits."
        fi
    done
    
    BANK_CARD_HOLDER=$(get_valid_input "👤 Card Holder Name")
    BANK_NAME=$(get_valid_input "🏦 Bank Name")
    
    # Support Username
    SUPPORT_USERNAME=$(get_valid_input "💬 Support Username (with @)")
    
    # Senai Panel
    echo
    print_info "🟡 Optional: Senai Panel Configuration"
    if get_yes_no "Configure Senai Panel?" "n"; then
        SENAI_PANEL_ENABLED="True"
        SENAI_PANEL_URL=$(get_valid_input "Panel URL")
        SENAI_PANEL_USERNAME=$(get_valid_input "Panel Username")
        SENAI_PANEL_PASSWORD=$(get_valid_input "Panel Password")
        SENAI_SUB_URL=$(get_valid_input "Subscription URL")
    else
        SENAI_PANEL_ENABLED="False"
        SENAI_PANEL_URL="https://panel.Domain.com:2053/c7UvLu2tMjFjP8BwiW"
        SENAI_PANEL_USERNAME="Panel_username"
        SENAI_PANEL_PASSWORD="Panel_password"
        SENAI_SUB_URL="https://sub.Domain.com:2083"
    fi
    
    # Gemini AI
    echo
    print_info "🟡 Optional: Google Gemini AI"
    if get_yes_no "Enable Gemini AI?" "n"; then
        GEMINI_ENABLED="True"
        GEMINI_API_KEY=$(get_valid_input "Gemini API Key")
    else
        GEMINI_ENABLED="False"
        GEMINI_API_KEY="Gemini_API_Key"
    fi
    
    # Update config.py
    update_config
}

# Update config.py with new values
update_config() {
    print_header "🔧 Updating Configuration"
    
    cd "$INSTALL_DIR" || error_exit "Failed to enter $INSTALL_DIR"
    
    print_progress "Updating config.py..."
    
    # Create temporary file
    local temp_file=$(mktemp)
    
    # Read config.py line by line and update
    while IFS= read -r line; do
        case "$line" in
            BOT_TOKEN*)
                line="BOT_TOKEN = \"$BOT_TOKEN\"  # Get from @BotFather"
                ;;
            ADMIN_ID*)
                line="ADMIN_ID = \"$ADMIN_ID\"  # Your Telegram ID (get from @myidbot)"
                ;;
            LOG_BOT_TOKEN*)
                line="LOG_BOT_TOKEN = \"$LOG_BOT_TOKEN\"  # Token of the second bot"
                ;;
            LOG_CHANNEL_ID*)
                line="LOG_CHANNEL_ID = -100$LOG_CHANNEL_ID  # Channel/Group ID for logs"
                ;;
            BANK_CARD_NUMBER*)
                line="BANK_CARD_NUMBER = \"$BANK_CARD_NUMBER\"  # Your bank card number"
                ;;
            BANK_CARD_HOLDER*)
                line="BANK_CARD_HOLDER = \"$BANK_CARD_HOLDER\"  # Card holder's full name"
                ;;
            BANK_NAME*)
                line="BANK_NAME = \"$BANK_NAME\"  # Bank name"
                ;;
            SUPPORT_USERNAME*)
                line="SUPPORT_USERNAME = \"$SUPPORT_USERNAME\"  # Support username"
                ;;
            SENAI_PANEL_ENABLED*)
                line="SENAI_PANEL_ENABLED = $SENAI_PANEL_ENABLED  # Set to True to enable"
                ;;
            SENAI_PANEL_URL*)
                line="SENAI_PANEL_URL = \"$SENAI_PANEL_URL\"  # Panel URL"
                ;;
            SENAI_PANEL_USERNAME*)
                line="SENAI_PANEL_USERNAME = \"$SENAI_PANEL_USERNAME\"  # Panel username"
                ;;
            SENAI_PANEL_PASSWORD*)
                line="SENAI_PANEL_PASSWORD = \"$SENAI_PANEL_PASSWORD\"  # Panel password"
                ;;
            SENAI_SUB_URL*)
                line="SENAI_SUB_URL = \"$SENAI_SUB_URL\"  # Subscription URL"
                ;;
            GEMINI_ENABLED*)
                line="GEMINI_ENABLED = $GEMINI_ENABLED  # Set to True to enable"
                ;;
            GEMINI_API_KEY*)
                line="GEMINI_API_KEY = \"$GEMINI_API_KEY\"  # Gemini API Key"
                ;;
        esac
        echo "$line" >> "$temp_file"
    done < "$CONFIG_FILE"
    
    mv "$temp_file" "$CONFIG_FILE"
    
    print_success "Configuration updated successfully"
}

# Test configuration
test_config() {
    print_header "🧪 Testing Configuration"
    
    cd "$INSTALL_DIR" || error_exit "Failed to enter $INSTALL_DIR"
    
    print_progress "Validating config.py..."
    
    if ! source "$VENV_DIR/bin/activate" 2>/dev/null; then
        error_exit "Failed to activate virtual environment"
    fi
    
    if python -c "import config; print('Config loaded successfully')" >/dev/null 2>&1; then
        print_success "Configuration is valid"
    else
        print_warning "Could not validate config. Please check manually."
    fi
    
    deactivate
}

# Create systemd service
create_systemd_service() {
    print_header "🚀 Setting up Systemd Service"
    
    cd "$INSTALL_DIR" || error_exit "Failed to enter $INSTALL_DIR"
    
    print_progress "Creating systemd service..."
    
    sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=VeloraBot Telegram VPN Sales Bot
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=$CURRENT_USER
Group=$CURRENT_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/$VENV_DIR/bin/python $INSTALL_DIR/main.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=$SERVICE_NAME

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=false

[Install]
WantedBy=multi-user.target
EOF
    
    print_progress "Reloading systemd..."
    sudo systemctl daemon-reload || error_exit "Failed to reload systemd"
    
    print_progress "Enabling service..."
    sudo systemctl enable "$SERVICE_NAME" >/dev/null 2>&1 || error_exit "Failed to enable service"
    
    print_progress "Starting service..."
    sudo systemctl start "$SERVICE_NAME" || error_exit "Failed to start service"
    
    print_success "Systemd service created and started"
}

# Check service status
check_service_status() {
    print_header "📊 Checking Service Status"
    
    sleep 3
    
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        print_success "VeloraBot is running successfully!"
        echo
        print_info "Service Status:"
        systemctl status "$SERVICE_NAME" --no-pager -l | head -n 15
    else
        print_error "VeloraBot failed to start!"
        echo
        print_info "Check logs with:"
        echo -e "${YELLOW}  sudo journalctl -u $SERVICE_NAME -n 50 --no-pager${NC}"
        echo
        print_info "Common issues:"
        echo "  1. Invalid bot token"
        echo "  2. Missing dependencies"
        echo "  3. Permission issues"
        echo "  4. Port already in use"
    fi
}

# Show installation summary
show_summary() {
    print_header "🎉 Installation Complete!"
    
    print_success "VeloraBot has been installed and configured!"
    echo
    echo -e "${BOLD}📁 Installation Details:${NC}"
    echo -e "  ${CYAN}•${NC} Directory: ${YELLOW}$INSTALL_DIR${NC}"
    echo -e "  ${CYAN}•${NC} Config: ${YELLOW}$INSTALL_DIR/$CONFIG_FILE${NC}"
    echo -e "  ${CYAN}•${NC} Backup: ${YELLOW}$INSTALL_DIR/$CONFIG_FILE.backup${NC}"
    echo -e "  ${CYAN}•${NC} Service: ${YELLOW}$SERVICE_NAME${NC}"
    echo
    echo -e "${BOLD}📋 Useful Commands:${NC}"
    echo -e "  ${CYAN}•${NC} Check status:    ${YELLOW}sudo systemctl status $SERVICE_NAME${NC}"
    echo -e "  ${CYAN}•${NC} View logs:       ${YELLOW}sudo journalctl -u $SERVICE_NAME -f${NC}"
    echo -e "  ${CYAN}•${NC} Restart bot:     ${YELLOW}sudo systemctl restart $SERVICE_NAME${NC}"
    echo -e "  ${CYAN}•${NC} Stop bot:        ${YELLOW}sudo systemctl stop $SERVICE_NAME${NC}"
    echo -e "  ${CYAN}•${NC} Start bot:       ${YELLOW}sudo systemctl start $SERVICE_NAME${NC}"
    echo -e "  ${CYAN}•${NC} Edit config:     ${YELLOW}nano $INSTALL_DIR/$CONFIG_FILE${NC}"
    echo
    echo -e "${BOLD}💡 Tips:${NC}"
    echo -e "  ${CYAN}•${NC} After editing config.py, restart the bot: ${YELLOW}sudo systemctl restart $SERVICE_NAME${NC}"
    echo -e "  ${CYAN}•${NC} Monitor logs in real-time: ${YELLOW}sudo journalctl -u $SERVICE_NAME -f${NC}"
    echo -e "  ${CYAN}•${NC} Check bot status: ${YELLOW}sudo systemctl status $SERVICE_NAME${NC}"
    echo
    echo -e "${GREEN}${BOLD}✅ You are done till here, you can enjoy your bot!${NC}"
    echo
}

# Cleanup function
cleanup() {
    print_progress "Cleaning up..."
    rm -f /tmp/velorabot_install.log
}

# ============================================
# 📋 Main Installation Flow
# ============================================

main() {
    # Clear screen
    clear
    
    # Show welcome message
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}${WHITE}                    🚀 VeloraBot Installation${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}              Telegram VPN Sales Bot - Auto Installer${NC}"
    echo -e "${CYAN}              Optimized for Ubuntu Server 20.04+${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo
    
    # Initial checks
    print_header "🔍 Pre-Installation Checks"
    
    check_root
    check_ubuntu_version
    check_internet
    check_disk_space
    check_memory
    check_python
    
    print_success "All pre-installation checks passed!"
    
    # Ask for confirmation
    echo
    if ! get_yes_no "Ready to begin installation?" "y"; then
        print_info "Installation cancelled."
        exit 0
    fi
    
    # Installation steps
    install_system_deps
    clone_repository
    setup_venv
    install_python_deps
    configure_bot
    test_config
    create_systemd_service
    check_service_status
    show_summary
    
    # Cleanup
    cleanup
}

# Trap errors
trap 'print_error "An error occurred on line $LINENO" ' ERR

# Run main function
main "$@"