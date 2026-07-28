#!/usr/bin/env bash
# ============================================================
# install_systemd.sh
#
# One-click installer for BLE Beacon Scanner.
# Automatically:
#   1. Installs pip & venv (if missing)          via apt
#   2. Creates Python virtual environment
#   3. Installs required adafruit packages       via pip
#   4. Prompts for my_secrets.py configuration
#   5. Installs & starts the systemd service     (uses venv Python)
#
# Usage:
#   sudo ./install_systemd.sh install     # Full one-click setup
#   sudo ./install_systemd.sh uninstall   # Stop & remove the service
#   sudo ./install_systemd.sh status      # Check service status
# ============================================================

set -euo pipefail

SERVICE_NAME="ble-beacon-scanner"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
# Resolve the directory where this script lives (even if called via symlink)
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_PATH="${SCRIPT_DIR}/code.py"
WORKING_DIR="${SCRIPT_DIR}"
VENV_DIR="${SCRIPT_DIR}/venv"
VENV_PYTHON="${VENV_DIR}/bin/python3"

# --- Systemd Unit Definition ---
UNIT_CONTENT=$(cat <<EOF
[Unit]
Description=BLE Beacon Scanner – scans BLE advertisements and publishes via MQTT
Documentation=https://github.com/your-org/indoor-positioning-bilateration
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ggd
Group=ggd
WorkingDirectory=${WORKING_DIR}
ExecStart=${VENV_PYTHON} -u ${PYTHON_PATH}
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
)

# ──────────────────────────────────────────────
# Setup venv & install Python dependencies
# ──────────────────────────────────────────────
setup_venv() {
    echo ""
    echo "╔═══════════════════════════════════════════════╗"
    echo "║   Step 1: Setting up Python virtual env...    ║"
    echo "╚═══════════════════════════════════════════════╝"

    # Install pip and venv if missing
    if ! command -v pip3 &>/dev/null; then
        echo ">>> Installing pip..."
        apt-get update -qq
        apt-get install -y -qq python3-pip python3-venv
    fi

    # Ensure venv module available
    if ! python3 -m venv --help &>/dev/null; then
        echo ">>> Installing python3-venv..."
        apt-get install -y -qq python3-venv
    fi

    # Create virtual environment (if not already exists)
    if [ ! -d "${VENV_DIR}" ]; then
        echo ">>> Creating virtual environment at ${VENV_DIR}..."
        python3 -m venv "${VENV_DIR}"
    else
        echo ">>> Virtual environment already exists at ${VENV_DIR}"
    fi

    # Upgrade pip inside venv
    echo ">>> Upgrading pip in venv..."
    "${VENV_DIR}/bin/pip3" install --upgrade pip -q

    # Install required packages
    echo ">>> Installing adafruit-circuitpython packages..."
    "${VENV_DIR}/bin/pip3" install \
        adafruit-circuitpython-minimqtt \
        adafruit-circuitpython-ntp \
        adafruit-circuitpython-ble \
        -q

    echo "✅ Virtual environment ready."
}

# ──────────────────────────────────────────────
# Configure my_secrets.py interactively
# ──────────────────────────────────────────────
setup_secrets() {
    echo ""
    echo "╔═══════════════════════════════════════════════╗"
    echo "║   Step 2: Configuring my_secrets.py...        ║"
    echo "╚═══════════════════════════════════════════════╝"

    SECRETS_FILE="${SCRIPT_DIR}/my_secrets.py"

    # Read current values if file exists
    current_broker="broker.hivemq.com"
    current_port="1883"
    current_username="None"
    current_password="None"
    current_topic="ble/beacons/ggg"
    current_filter="B4E7B36041B4"
    current_no="1"

    if [ -f "${SECRETS_FILE}" ]; then
        echo ">>> Existing my_secrets.py found. Reading current values as defaults."
        current_broker=$(sed -n 's/.*"broker":\s*"\(.*\)".*/\1/p' "${SECRETS_FILE}" | head -1)
        current_port=$(sed -n 's/.*"port":\s*\([0-9]*\).*/\1/p' "${SECRETS_FILE}" | head -1)
        current_username=$(sed -n 's/.*"username":\s*\([^,]*\).*/\1/p' "${SECRETS_FILE}" | head -1 | xargs)
        current_password=$(sed -n 's/.*"password":\s*\([^,]*\).*/\1/p' "${SECRETS_FILE}" | head -1 | xargs)
        current_topic=$(sed -n 's/.*"topic":\s*"\(.*\)".*/\1/p' "${SECRETS_FILE}" | head -1)
        current_filter=$(grep -oP 'addresses_to_filter\s*=\s*\["[^"]*' "${SECRETS_FILE}" | grep -oP '"[^"]+$' | tr -d '"')
        current_no=$(grep -oP 'RECEIVER_NO\s*=\s*\K[0-9]+' "${SECRETS_FILE}")
    fi

    # Prompt user (with defaults)
    read -r -p "MQTT Broker [${current_broker}]: " input_broker
    broker="${input_broker:-$current_broker}"

    read -r -p "MQTT Port [${current_port}]: " input_port
    port="${input_port:-$current_port}"

    read -r -p "MQTT Username (or None) [${current_username}]: " input_username
    username="${input_username:-$current_username}"

    read -r -s -p "MQTT Password (or None) [${current_password}]: " input_password
    echo ""
    password="${input_password:-$current_password}"

    read -r -p "MQTT Topic [${current_topic}]: " input_topic
    topic="${input_topic:-$current_topic}"

    read -r -p "BLE MAC addresses to filter (comma-separated) [${current_filter}]: " input_filter
    filter="${input_filter:-$current_filter}"

    read -r -p "Receiver No. [${current_no}]: " input_no
    no="${input_no:-$current_no}"

    # Format filter list as Python list of strings
    filter_list="["
    IFS=',' read -ra addrs <<< "$filter"
    for i in "${!addrs[@]}"; do
        addr=$(echo "${addrs[$i]}" | xargs)  # trim
        if [ $i -gt 0 ]; then
            filter_list+=", "
        fi
        filter_list+="\"${addr}\""
    done
    filter_list+="]"

    # Write secrets file
    echo ">>> Writing ${SECRETS_FILE}..."
    cat > "${SECRETS_FILE}" <<EOF
mqtt_env = {
    "broker": "${broker}",
    "port": ${port},
    "username": ${username},
    "password": ${password},
    "topic": "${topic}",
}
addresses_to_filter = ${filter_list}

RECEIVER_NO = ${no}
EOF

    echo "✅ my_secrets.py configured."
}

# ──────────────────────────────────────────────
# Install systemd service
# ──────────────────────────────────────────────
install_service() {
    echo ""
    echo "╔═══════════════════════════════════════════════╗"
    echo "║   Step 3: Installing systemd service...       ║"
    echo "╚═══════════════════════════════════════════════╝"

    if [ "$EUID" -ne 0 ]; then
        echo "ERROR: Please run with sudo or as root to install a systemd service."
        exit 1
    fi

    # Check that Python exists
    if ! command -v python3 &>/dev/null; then
        echo "ERROR: python3 not found. Please install Python 3."
        exit 1
    fi

    # Check that the code.py exists
    if [ ! -f "${PYTHON_PATH}" ]; then
        echo "ERROR: ${PYTHON_PATH} not found!"
        exit 1
    fi

    # Check venv is ready
    if [ ! -f "${VENV_PYTHON}" ]; then
        echo "ERROR: Virtual environment not found at ${VENV_DIR}."
        echo "       Please run the install script again without skipping steps."
        exit 1
    fi

    # Write the unit file
    echo "${UNIT_CONTENT}" | tee "${SERVICE_FILE}" > /dev/null
    echo ">>> Wrote ${SERVICE_FILE}"

    # Reload systemd and enable
    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}"
    systemctl start "${SERVICE_NAME}"

    echo ""
    echo "✅ Service '${SERVICE_NAME}' installed and started."
    echo "   To view logs:  sudo journalctl -u ${SERVICE_NAME} -f"
    echo "   To stop:       sudo systemctl stop ${SERVICE_NAME}"
    echo "   To restart:    sudo systemctl restart ${SERVICE_NAME}"
}

# ──────────────────────────────────────────────
# Uninstall systemd service
# ──────────────────────────────────────────────
uninstall_service() {
    echo ""
    echo "╔═══════════════════════════════════════════════╗"
    echo "║   Uninstalling systemd service...              ║"
    echo "╚═══════════════════════════════════════════════╝"

    if [ "$EUID" -ne 0 ]; then
        echo "ERROR: Please run with sudo or as root to uninstall a systemd service."
        exit 1
    fi

    if systemctl is-enabled "${SERVICE_NAME}" &>/dev/null 2>&1; then
        systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
        systemctl disable "${SERVICE_NAME}" 2>/dev/null || true
    fi

    if [ -f "${SERVICE_FILE}" ]; then
        rm -f "${SERVICE_FILE}"
        echo ">>> Removed ${SERVICE_FILE}"
    fi

    systemctl daemon-reload

    read -r -p "Remove virtual environment at ${VENV_DIR}? [y/N]: " remove_venv
    if [[ "${remove_venv}" =~ ^[Yy]$ ]]; then
        rm -rf "${VENV_DIR}"
        echo ">>> Removed ${VENV_DIR}"
    fi

    echo "✅ Service '${SERVICE_NAME}' uninstalled."
}

# ──────────────────────────────────────────────
# Show status
# ──────────────────────────────────────────────
show_status() {
    echo ">>> Status of service: ${SERVICE_NAME}"
    echo ""
    if systemctl is-enabled "${SERVICE_NAME}" &>/dev/null 2>&1; then
        systemctl status "${SERVICE_NAME}" 2>/dev/null || echo "(service may not be running)"
    else
        echo "Service '${SERVICE_NAME}' is not installed."
    fi
}

# ──────────────────────────────────────────────
# Full install (all steps)
# ──────────────────────────────────────────────
full_install() {
    echo ""
    echo "╔═══════════════════════════════════════════════╗"
    echo "║   BLE Beacon Scanner – One-Click Installer    ║"
    echo "╚═══════════════════════════════════════════════╝"

    # Step 1: Virtual environment (needs sudo for apt)
    if [ "$EUID" -ne 0 ]; then
        echo ">>> This script needs sudo for some steps. Please run as:"
        echo "    sudo $0 install"
        exit 1
    fi

    setup_venv

    # Step 2: Secrets (drop to normal user for interactive prompts)
    echo ""
    echo "╔═══════════════════════════════════════════════╗"
    echo "║   Step 2: Configuring my_secrets.py...        ║"
    echo "╚═══════════════════════════════════════════════╝"
    sudo -u "${SUDO_USER}" "$0" setup-secrets

    # Step 3: Systemd service
    install_service

    echo ""
    echo "🎉 Installation complete!"
    echo "   Service: ${SERVICE_NAME}"
    echo "   Logs:    sudo journalctl -u ${SERVICE_NAME} -f"
}

# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
case "${1:-help}" in
    install)
        full_install
        ;;
    install-service)
        install_service
        ;;
    uninstall|remove)
        uninstall_service
        ;;
    status)
        show_status
        ;;
    setup-venv)
        setup_venv
        ;;
    setup-secrets)
        setup_secrets
        ;;
    *)
        echo "Usage: sudo $0 {install|uninstall|status}"
        echo ""
        echo "  install   – Full one-click setup (venv + secrets + service)"
        echo "  uninstall – Stop & remove the service"
        echo "  status    – Show current service status"
        echo ""
        echo "Advanced usage (run individual steps):"
        echo "  sudo $0 setup-venv     – Only create/recreate venv"
        echo "  $0 setup-secrets       – Only configure my_secrets.py"
        exit 1
        ;;
esac
