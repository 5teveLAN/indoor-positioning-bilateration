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
    from my_secrets import addresses_to_filter, mqtt_env, RECEIVER_NO, USE_TEST_MODE
except ImportError:
    print("WiFi secrets are kept in secrets.py, please add them there!")
    raise

# ─── 測試模式固定參數 ──────────────────────────
# 參考 ble-packet-encryption.md 5.2
TEST_XOR_KEY = "TEST_KEY_2024"

# ─── Service UUID ────────────────────────────
SERVICE_UUID_1111 = "00001111-0000-1000-8000-00805f9b34fb"
SERVICE_UUID_SHORT = "1111"

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

# BleakDBusError fallback
try:
    from bleak.exc import BleakDBusError
except ImportError:
    BleakDBusError = Exception


# ─── XOR 解密 ──────────────────────────────────


def xor_decrypt(encrypted_bytes: bytes, key: str) -> bytes:
    """
    XOR 解密：encrypted[i] = rawBytes[i] XOR keyBytes[i % keyBytes.length]
    參考 ble-packet-encryption.md 3.2
    """
    key_bytes = key.encode("utf-8")
    result = bytearray(len(encrypted_bytes))
    for i, b in enumerate(encrypted_bytes):
        result[i] = b ^ key_bytes[i % len(key_bytes)]
    return bytes(result)


def extract_student_id(advertisement, xor_key: str = TEST_XOR_KEY):
    """
    從 BLE 廣告封包中提取 Service Data → XOR 解密 → 取出學號。

    回傳 (student_id, mac_str) 或 (None, mac_str) 若失敗。
    """
    # 取得 MAC
    addr_bytes = advertisement.address.address_bytes
    mac_str = "".join("{:02x}".format(b) for b in addr_bytes).upper()

    # 提取 Service Data (AD Type 0x16 = Service Data - 16-bit UUID)
    service_data = b""
    try:
        if hasattr(advertisement, "data_dict") and advertisement.data_dict:
            SERVICE_DATA_16BIT_UUID = 0x16
            if SERVICE_DATA_16BIT_UUID in advertisement.data_dict:
                raw = advertisement.data_dict[SERVICE_DATA_16BIT_UUID]
                if len(raw) > 2:
                    service_data = raw[2:]  # 跳過 2 bytes UUID
    except Exception:
        pass

    if not service_data or len(service_data) < 15:
        return None, mac_str

    try:
        encrypted = service_data[:15]
        decrypted = xor_decrypt(encrypted, xor_key)
        plaintext = decrypted.decode("utf-8", errors="replace")

        # 解析 student_id|otp
        if "|" not in plaintext:
            return None, mac_str

        student_id = plaintext.split("|", 1)[0].strip()

        # 基本驗證：學號應為 8 位數字
        if not student_id.isdigit() or len(student_id) != 8:
            print(f"    ⚠️ 學號格式異常: {student_id}")
            return None, mac_str

        return student_id, mac_str
    except Exception as e:
        print(f"    ⚠️ 解密失敗 {mac_str}: {e}")
        return None, mac_str


# ─── BLE 掃描 ──────────────────────────────


def start_scan():
    """
    掃描 BLE 廣告封包，收集所有 UUID=1111 的裝置。

    對每個封包：解密 → 取出 student_id → MQTT publish
    不再 break 只找一個，不負責 Kalman 濾波（留給伺服器）。
    """
    print("Starting BLE scan (multi-device mode)...")
    scanner = None
    devices_found = []

    # 決定要用哪個 XOR Key
    if USE_TEST_MODE:
        xor_key = TEST_XOR_KEY
        print(f"    🔑 測試模式，XOR Key: {xor_key}")
    else:
        # TODO: 正式模式下向後端 API 取得 XOR Key
        xor_key = TEST_XOR_KEY
        print(f"    ⚠️ 正式模式尚未實作 API，暫時使用測試 Key")

    try:
        scanner = ble.start_scan(ProvideServicesAdvertisement, timeout=1)
        for advertisement in scanner:
            if not isinstance(advertisement, ProvideServicesAdvertisement):
                continue
            if SERVICE_UUID_SHORT not in str(advertisement.services):
                continue

            rssi = advertisement.rssi
            current_time_str = get_time()

            # 解密取出 student_id
            student_id, mac_str = extract_student_id(advertisement, xor_key)
            if student_id is None:
                continue

            print(f"  ✅ {mac_str} → 學號:{student_id} RSSI:{rssi}")

            devices_found.append({
                "student_id": student_id,
                "mac": mac_str,
                "rssi": rssi,
                "time": current_time_str,
            })

    except BleakDBusError as e:
        print(f"BLE DBus error during scan: {e}")
        raise
    finally:
        if scanner is not None:
            try:
                ble.stop_scan()
            except BleakDBusError:
                pass
            except Exception:
                pass

    # 批次發布 MQTT（每個學生一則）
    if devices_found:
        print(f"  發布 {len(devices_found)} 筆資料到 MQTT...")
        for device in devices_found:
            message = json.dumps({
                "student_id": device["student_id"],
                "mac": device["mac"],
                "rssi": device["rssi"],
                "scanner_id": RECEIVER_NO,
                "time": device["time"],
            })
            publish_message(message)
            print(f"    📤 {device['student_id']} RSSI:{device['rssi']}")
    else:
        print("  本次掃描未發現有效裝置。")

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

