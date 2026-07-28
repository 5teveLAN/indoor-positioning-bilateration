"""
Receiver Monitor
================
Subscribes to MQTT status topics for all receivers (topic + "/status/+")
and maintains a live mapping of receiver_no → IP address.

Usage:
    python receiver_monitor.py

Press Ctrl+C to exit.
"""

import json
import logging
import signal
import sys
import time
from datetime import datetime

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

try:
    from my_secrets import mqtt_env
except ImportError:
    print("WiFi secrets are kept in my_secrets.py, please add them there!")
    raise

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("ReceiverMonitor")

# Global state
running = True
receiver_map: dict[int, dict] = {}  # receiver_no -> {ip, last_seen, status}


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code != 0:
        logger.error(f"Failed to connect, return code: {reason_code}")
        return

    logger.info("Connected to MQTT broker")
    topic = mqtt_env["topic"] + "/status/+"
    logger.info(f"Subscribing to: {topic}")
    client.subscribe(topic)


def on_message(client, userdata, msg):  # noqa: F811
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        receiver_no = payload.get("receiver_no")
        ip = payload.get("ip", "unknown")
        status = payload.get("status", "unknown")

        receiver_map[receiver_no] = {
            "ip": ip,
            "status": status,
            "last_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        logger.info(
            f"📡 Receiver #{receiver_no} | IP: {ip} | Status: {status}"
        )
        print_receivers()

    except Exception as e:
        logger.error(f"Error processing status message: {e}")


def print_receivers():
    """Print a table of all known receivers."""
    if not receiver_map:
        return

    print("\n" + "=" * 60)
    print(f"{'Receiver #':<12} {'IP Address':<18} {'Status':<10} {'Last Seen':<20}")
    print("-" * 60)
    for no in sorted(receiver_map.keys()):
        info = receiver_map[no]
        print(
            f"{no:<12} {info['ip']:<18} {info['status']:<10} {info['last_seen']:<20}"
        )
    print("=" * 60 + "\n")


def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully."""
    global running
    logger.info("Shutting down...")
    running = False
    client.disconnect()
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)

    host = mqtt_env["broker"]
    port = mqtt_env["port"]
    username = mqtt_env.get("username")
    password = mqtt_env.get("password")

    client = mqtt.Client(CallbackAPIVersion.VERSION2, "ReceiverMonitor")
    if username and password:
        client.username_pw_set(username, password)

    client.on_connect = on_connect
    client.on_message = on_message

    logger.info(f"Connecting to {host}:{port}...")
    client.connect(host, port)

    # Start network loop in a background thread
    client.loop_start()

    try:
        while running:
            time.sleep(1)
    except KeyboardInterrupt:
        signal_handler(None, None)
