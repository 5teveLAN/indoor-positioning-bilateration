import json
import ssl
import time
import socket

import adafruit_minimqtt.adafruit_minimqtt as MQTT
import adafruit_ntp
# import socketpool
# import wifi
from adafruit_ble import BLERadio
from adafruit_ble.advertising.standard import ProvideServicesAdvertisement

# Get wifi details and more from a secrets.py file
try:
    from my_secrets import addresses_to_filter, mqtt_env, RECEIVER_NO
except ImportError:
    print("WiFi secrets are kept in secrets.py, please add them there!")
    raise

# Connect to WiFi
# wifi.radio.connect(secrets["ssid"], secrets["password"])

# Create a socket pool
pool = socket

# Get time server (Network Time Protocol)
ntp = adafruit_ntp.NTP(pool, tz_offset=0)

# Bluetooth
ble = BLERadio()
counter = 0

# Set up MQTT client
mqtt_client = MQTT.MQTT(
    broker=mqtt_env["broker"],
    port=mqtt_env["port"],
    socket_pool=pool,
    ssl_context=ssl.create_default_context(),
)
# Only set username/password if they are provided (None causes issues in some adafruit_minimqtt versions)
if mqtt_env.get("username") is not None:
    mqtt_client.username = mqtt_env["username"]
if mqtt_env.get("password") is not None:
    mqtt_client.password = mqtt_env["password"]


# MQTT Event Handlers
def __mqtt_connect_handler(mqtt_client, userdata, flags, rc):
    print("Successfully connected to MQTT broker.")
    print("     Flags: {0}\n     RC: {1}".format(flags, rc))


def __mqtt_disconnect_handler(mqtt_client, userdata, rc):
    print("Disconnected from MQTT broker.")


def __mqtt_publish_handler(mqtt_client, userdata, topic, pid):
    print("Published to {0} with PID {1}".format(topic, pid))


# Set the event handlers
mqtt_client.on_connect = __mqtt_connect_handler
mqtt_client.on_disconnect = __mqtt_disconnect_handler
mqtt_client.on_publish = __mqtt_publish_handler


# Connect to the MQTT broker
print(f"Trying to connect to MQTT broker - {mqtt_client.broker}")
mqtt_client.connect()


# Publish a message
def publish_message(message: str):
    mqtt_client.publish(mqtt_env["topic"]+"/receivers/"+str(RECEIVER_NO), message)


def publish_status(message: str):
    """Publish a status message (e.g. IP info) to the status topic."""
    mqtt_client.publish(mqtt_env["topic"]+"/status/"+str(RECEIVER_NO), message)


def get_time():
    current_time = ntp.datetime  # Fetch current time once
    year, month, day, hour, mins, secs, weekday, yearday, tm_isdst = current_time
    return "{:02d}/{:02d}/{} {:02d}:{:02d}:{:02d}".format(
        day, month, year, hour, mins, secs
    )


def get_local_ip():
    """Get the local IP address of this machine."""
    try:
        # Create a temporary socket to figure out our IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception as e:
        print("Failed to get local IP:", e)
        return "0.0.0.0"


# --- Startup: report local IP ---
local_ip = get_local_ip()
print(f"Receiver #{RECEIVER_NO} local IP: {local_ip}")
status_msg = json.dumps({
    "receiver_no": RECEIVER_NO,
    "ip": local_ip,
    "status": "online",
})
publish_status(status_msg)
print(f"Published startup status: {status_msg}")

uuid_filter = "1111"  # Filter for advertisements containing this UUID

# BleakDBusError fallback
try:
    from bleak.exc import BleakDBusError
except ImportError:
    BleakDBusError = Exception


# Start BLE scan for advertisements
def start_scan():
    # write a function to scan for BLE advertisements and print the address and RSSI
    print("Starting BLE scan...")
    scanner = None
    try:
        scanner = ble.start_scan(ProvideServicesAdvertisement, timeout=1)
        for advertisement in scanner:
            if isinstance(advertisement, ProvideServicesAdvertisement) and uuid_filter in str(advertisement.services):
                addr_bytes = advertisement.address.address_bytes
                addr_str = "".join("{:02x}".format(b) for b in addr_bytes).upper()
                current_time_str = get_time()
                print(addr_str, current_time_str, "RSSI:", advertisement.rssi)

                # Send the message to the MQTT broker
                message = json.dumps(
                    {
                        "address": addr_str,
                        "time": current_time_str,
                        "rssi": advertisement.rssi,
                    }
                )
                publish_message(message)

                # 找到目標後 break 離開迴圈
                break
    except BleakDBusError as e:
        print(f"BLE DBus error during scan: {e}")
        raise
    finally:
        # 確保 scan 一定被停止，並忽略停止時的 BleakDBusError
        if scanner is not None:
            try:
                ble.stop_scan()
            except BleakDBusError:
                pass
            except Exception:
                pass
    print("Scan done.")



while True:
    try:
        start_scan()
    except BleakDBusError as e:
        print(f"BLE DBus error, retrying: {e}")
        time.sleep(2)
        continue
    except OSError as e:
        print("Failed to scan: ", e)
        time.sleep(2)
        continue
    except Exception as e:
        print("Unexpected error:", e)
        mqtt_client.disconnect()
        raise e
    time.sleep(2)  # sleep for 2 seconds before scanning again

