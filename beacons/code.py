"""
BLE Beacon Scanner (bleak 版本)

改用 bleak (BlueZ) 做 *active scan*，主動觸發 scan response，
以取得手機 App 放在 scan response 裡的 Service Data (AD Type 0x16)。
原 adafruit_ble 在 BlueZ 上不易收到 scan response，故改用 bleak。
"""

import asyncio
import json
import socket as _socket
import time

from bleak import BleakScanner
from bleak.exc import BleakError

import adafruit_minimqtt.adafruit_minimqtt as MQTT

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
# 學生端 App 廣播時用的完整 UUID
SERVICE_UUID = "00001111-0000-1000-8000-00805f9b34fb"
# 縮短成 16-bit 的表示法，用來比對 service_data / service_uuids 的 key
SERVICE_UUID_SHORT = "1111"

# ─── MQTT 設定 ──────────────────────────────
mqtt_client = MQTT.MQTT(
    broker=mqtt_env["broker"],
    port=mqtt_env["port"],
    socket_pool=_socket,
    ssl_context=None,
)
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


mqtt_client.on_connect = __mqtt_connect_handler
mqtt_client.on_disconnect = __mqtt_disconnect_handler
mqtt_client.on_publish = __mqtt_publish_handler


def publish_message(message: str):
    mqtt_client.publish(mqtt_env["topic"] + "/receivers/" + str(RECEIVER_NO), message)


def publish_status(message: str):
    """Publish a status message (e.g. IP info) to the status topic."""
    mqtt_client.publish(mqtt_env["topic"] + "/status/" + str(RECEIVER_NO), message)


def get_time():
    """回傳目前本地時間字串 (dd/mm/yyyy HH:MM:SS)。"""
    return time.strftime("%d/%m/%Y %H:%M:%S", time.localtime())


def get_local_ip():
    """Get the local IP address of this machine."""
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception as e:
        print("Failed to get local IP:", e)
        return "0.0.0.0"


# 先連接 MQTT，之後的 publish_status 才能成功
print(f"Trying to connect to MQTT broker - {mqtt_client.broker}")
mqtt_client.connect()

# --- Startup: report local IP ---
local_ip = get_local_ip()
print(f"Receiver #{RECEIVER_NO} local IP: {local_ip}")
status_msg = json.dumps({
    "receiver_no": RECEIVER_NO,
    "ip": local_ip,
    "status": "online",
})
publish_status(status_msg)


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


def extract_student_id(service_data: bytes, mac_str: str, xor_key: str = TEST_XOR_KEY):
    """
    從 bleak 取得的 Service Data payload 中 XOR 解密 → 取出學號。

    注意：bleak 的 service_data dict value 已經「去掉 UUID 前綴」，
    所以 service_data 傳入的就是純加密 payload。

    回傳 student_id 或 None。
    """
    if not service_data or len(service_data) < 15:
        print(f"    ⚠️ {mac_str} service_data 不足 (len={len(service_data)}): "
              f"{service_data.hex() if service_data else '(空)'}")
        return None

    try:
        encrypted = service_data[:15]
        decrypted = xor_decrypt(encrypted, xor_key)
        plaintext = decrypted.decode("utf-8", errors="replace")

        if "|" not in plaintext:
            print(f"    ⚠️ {mac_str} XOR 解密結果沒有分隔符 '|'")
            print(f"          解密後 bytes={decrypted.hex()}")
            print(f"          解密後文字={plaintext!r}")
            print(f"          (XOR Key={xor_key!r}, 原始 service_data={service_data.hex()})")
            return None

        student_id = plaintext.split("|", 1)[0].strip()
        if not student_id.isdigit() or len(student_id) != 8:
            print(f"    ⚠️ 學號格式異常: {student_id}")
            return None

        return student_id
    except Exception as e:
        print(f"    ⚠️ 解密失敗 {mac_str}: {e}")
        return None


def _is_target_uuid(uuid_str):
    """判斷某個 UUID 字串是否屬於我們的 SERVICE_UUID (1111)。"""
    upper = str(uuid_str).upper()
    return SERVICE_UUID_SHORT in upper or SERVICE_UUID.upper() in upper


def _find_service_data(adv):
    """
    在 bleak 的 AdvertisementData.service_data dict 中，找出 UUID=1111
    對應的加密 payload。回傳 bytes 或 None。
    """
    sd = adv.service_data or {}
    for key, val in sd.items():
        if _is_target_uuid(key):
            return bytes(val)
    return None


async def _scan_once(timeout: float = 3.0):
    """
    執行一次 active scan，回傳符合條件裝置的清單。
    每筆：{"mac": str, "rssi": int, "payload": bytes}

    使用 BleakScanner detection_callback（bleak 2.x 標準 API），
    scanning_mode="active" 會觸發 scan response。
    """
    found = []
    seen_macs = set()

    def _detection_callback(device, advertisement_data):
        nonlocal found
        mac = str(getattr(device, "address", "") or "").replace(":", "").upper()
        rssi = getattr(advertisement_data, "rssi", None)
        sd = getattr(advertisement_data, "service_data", None) or {}
        service_uuids = list(getattr(advertisement_data, "service_uuids", []) or [])
        local_name = getattr(advertisement_data, "local_name", None)
        manufacturer_data = getattr(advertisement_data, "manufacturer_data", None)
        tx_power = getattr(advertisement_data, "tx_power", None)

        # Debug：印出所有掃到的裝置（前 5 台）
        if mac not in seen_macs:
            seen_macs.add(mac)
            if len(seen_macs) <= 5:
                print(f"       [SCAN] {mac} RSSI:{rssi} "
                      f"uuids={service_uuids} sd={list(sd.keys()) if sd else None} "
                      f"name={local_name!r}")

        # 判斷是不是目標裝置
        is_target = _is_target_uuid(local_name) if local_name else False
        for u in service_uuids:
            if _is_target_uuid(u):
                is_target = True
                break
        if not is_target and sd:
            for k in sd.keys():
                if _is_target_uuid(k):
                    is_target = True
                    break

        # Debug：印出目標封包
        if is_target:
            print(f"  📡 TARGET UUID MATCH! MAC:{mac} RSSI:{rssi}")
            print(f"       service_data keys: {list(sd.keys()) if sd else 'None'}")
            print(f"       service_data (raw): {sd}")
            print(f"       full: rssi={rssi}, service_uuids={service_uuids}, "
                  f"local_name={local_name}, manufacturer_data={manufacturer_data}, "
                  f"tx_power={tx_power}")

            payload = None
            for key, val in sd.items():
                if _is_target_uuid(key):
                    payload = bytes(val)
                    break
            if payload is not None:
                found.append({"mac": mac, "rssi": rssi, "payload": payload})

    scanner = BleakScanner(
        detection_callback=_detection_callback,
        scanning_mode="active",
    )
    await scanner.start()
    await asyncio.sleep(timeout)
    await scanner.stop()
    return found


def start_scan():
    """
    使用 bleak active scan 掃描 BLE 廣告封包。
    收集所有 UUID=1111 且帶 Service Data 的裝置 → XOR 解密 → MQTT publish。
    """
    print("Starting BLE scan (bleak / active mode)...")
    devices_found = []

    xor_key = TEST_XOR_KEY
    if USE_TEST_MODE:
        print(f"    🔑 測試模式，XOR Key: {xor_key}")
    else:
        print(f"    ⚠️ 正式模式尚未實作 API，暫時使用測試 Key")

    try:
        results = asyncio.run(_scan_once(timeout=3.0))

        for dev in results:
            mac_str = dev["mac"]
            rssi = dev["rssi"]
            payload = dev["payload"]
            print(f"       [DBG {mac_str}] service_data payload({len(payload)}B)={payload.hex()}")

            student_id = extract_student_id(payload, mac_str, xor_key)
            if student_id is None:
                continue

            print(f"  ✅ {mac_str} → 學號:{student_id} RSSI:{rssi}")
            devices_found.append({
                "student_id": student_id,
                "mac": mac_str,
                "rssi": rssi,
                "time": get_time(),
            })

    except BleakError as e:
        print(f"BLE bleak error during scan: {e}")
        raise
    except Exception as e:
        print(f"Unexpected scan error: {e}")
        raise

    # 批次發布 MQTT
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


def main():
    while True:
        try:
            start_scan()
        except BleakError as e:
            print(f"BLE bleak error, retrying: {e}")
            time.sleep(2)
            continue
        except OSError as e:
            print("Failed to scan: ", e)
            time.sleep(2)
            continue
        except Exception as e:
            print("Unexpected error:", e)
            try:
                mqtt_client.disconnect()
            except Exception:
                pass
            raise e
        time.sleep(2)


if __name__ == "__main__":
    main()

