#!/bin/bash
#
# debug_output.sh
# Usage: ./debug_output.sh [service_name]
#
# Show real-time debug output from the beacon service running on Raspberry Pi.
# Default service name: beacon.service (change SERVICE_NAME below if different)
#

# ─── Configuration ────────────────────────────
SERVICE_NAME="${1:-ble-beacon-scanner.service}"
LINES=50

# ─── Color helpers ────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}══════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Beacon Debug Output Viewer${NC}"
echo -e "${BLUE}  Service: ${SERVICE_NAME}${NC}"
echo -e "${BLUE}══════════════════════════════════════════════════${NC}"
echo ""

# ─── 1. Check if service exists ──────────────
if ! systemctl list-units --type=service | grep -q "${SERVICE_NAME}"; then
    echo -e "${RED}❌ Service '${SERVICE_NAME}' not found!${NC}"
    echo ""
    echo "Available beacon services:"
    systemctl list-units --type=service | grep -i "beacon\|beac"
    exit 1
fi

# ─── 2. Show service status ───────────────────
echo -e "${YELLOW}── Service Status ──${NC}"
systemctl status "${SERVICE_NAME}" --no-pager
echo ""

# ─── 3. Show recent log lines ─────────────────
echo -e "${YELLOW}── Recent ${LINES} log lines ──${NC}"
sudo journalctl -u "${SERVICE_NAME}" -n "${LINES}" --no-pager
echo ""

# ─── 4. Follow logs in real-time ──────────────
echo -e "${GREEN}── Tailing logs (press Ctrl+C to stop) ──${NC}"
echo -e "${GREEN}   Watching for: BLE packets, MQTT publishes, errors${NC}"
echo ""
sudo journalctl -u "${SERVICE_NAME}" -f --no-pager \
    | while read line; do
        # Color-code different message types
        case "$line" in
            *"TARGET UUID"*)  echo -e "${GREEN}${line}${NC}" ;;
            *"MQTT"*|*"mqtt"*|*"Published"*) echo -e "${BLUE}${line}${NC}" ;;
            *"error"*|*"Error"*|*"ERROR"*|*"Failed"*|*"⚠️"*) echo -e "${RED}${line}${NC}" ;;
            *"✅"*)           echo -e "${GREEN}${line}${NC}" ;;
            *"Scan done"*)    echo -e "${YELLOW}${line}${NC}" ;;
            *)                echo "${line}" ;;
        esac
    done
