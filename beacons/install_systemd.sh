#!/usr/bin/env bash
# ============================================================
# install_systemd.sh
#
# Installs (or uninstalls) beacons/code.py as a systemd service
# that auto-starts on boot.
#
# Usage:
#   sudo ./install_systemd.sh install     # Install & enable the service
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

# --- Systemd Unit Definition ---
UNIT_CONTENT=$(cat <<EOF
[Unit]
Description=BLE Beacon Scanner – scans BLE advertisements and publishes via MQTT
Documentation=https://github.com/your-org/indoor-positioning-bilateration
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
Group=pi
WorkingDirectory=${WORKING_DIR}
ExecStart=/usr/bin/python3 -u ${PYTHON_PATH}
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
)

install_service() {
    echo ">>> Installing systemd service: ${SERVICE_NAME}"

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

    # Write the unit file
    echo "${UNIT_CONTENT}" | tee "${SERVICE_FILE}" > /dev/null

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

uninstall_service() {
    echo ">>> Uninstalling systemd service: ${SERVICE_NAME}"

    if [ "$EUID" -ne 0 ]; then
        echo "ERROR: Please run with sudo or as root to uninstall a systemd service."
        exit 1
    fi

    if systemctl is-enabled "${SERVICE_NAME}" &>/dev/null; then
        systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
        systemctl disable "${SERVICE_NAME}" 2>/dev/null || true
    fi

    if [ -f "${SERVICE_FILE}" ]; then
        rm -f "${SERVICE_FILE}"
        echo "Removed ${SERVICE_FILE}"
    fi

    systemctl daemon-reload

    echo "✅ Service '${SERVICE_NAME}' uninstalled."
}

show_status() {
    echo ">>> Status of service: ${SERVICE_NAME}"
    echo ""
    if systemctl is-enabled "${SERVICE_NAME}" &>/dev/null 2>&1; then
        systemctl status "${SERVICE_NAME}" 2>/dev/null || echo "(service may not be running)"
    else
        echo "Service '${SERVICE_NAME}' is not installed."
    fi
}

# --- Main ---
case "${1:-help}" in
    install)
        install_service
        ;;
    uninstall|remove)
        uninstall_service
        ;;
    status)
        show_status
        ;;
    *)
        echo "Usage: $0 {install|uninstall|status}"
        echo ""
        echo "  install   – Install & start the systemd service"
        echo "  uninstall – Stop & remove the systemd service"
        echo "  status    – Show current service status"
        exit 1
        ;;
esac
