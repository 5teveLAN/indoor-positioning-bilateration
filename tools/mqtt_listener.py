#!/usr/bin/env python3
"""
MQTT Listener — 訂閱樹莓派 BLE Beacon 定位資料

用途：
  用來監聽樹莓派感測器端 (`beacons/code.py`) 發布的 MQTT 訊息，
  驗證多裝置定位的資料是否正確送達。

訂閱主題：
  - {topic}/receivers/+   → 各樹莓派回報的 RSSI 資料
  - {topic}/status/+      → 各樹莓派的開機狀態/IP

使用方式：
  python3 mqtt_listener.py                      # 使用預設 broker
  python3 mqtt_listener.py --broker test.mosquitto.org --topic my/topic

輸出範例：
  ────────────────────────────────────────────────
  📡 [receivers/1] 2025-07-15 14:30:22
      學號: 11012345 | MAC: B4E7B36041B4 | RSSI: -72 dBm
  ────────────────────────────────────────────────
  🟢 [status/1] 2025-07-15 14:30:22
      Receiver #1 | IP: 192.168.1.100 | online
"""

import argparse
import json
import signal
import sys
from datetime import datetime

import paho.mqtt.client as mqtt


# ─── 設定 ──────────────────────────────────────
DEFAULT_BROKER = "broker.hivemq.com"
DEFAULT_PORT = 1883
DEFAULT_TOPIC = "ble/beacons/ggg"
TIMEOUT = 5  # seconds


# ─── 全域計數器 ────────────────────────────────
stats = {
    "receivers": 0,
    "status": 0,
    "parse_errors": 0,
    "students": set(),
    "scanners": set(),
}


def on_connect(client, userdata, flags, rc, reason=None):
    if rc == 0:
        print(f"✅ 已連線到 MQTT Broker ({userdata['broker']})")
        topic_receivers = f"{userdata['topic']}/receivers/+"
        topic_status = f"{userdata['topic']}/status/+"
        client.subscribe(topic_receivers)
        client.subscribe(topic_status)
        print(f"   訂閱: {topic_receivers}")
        print(f"   訂閱: {topic_status}")
        print(f"   按 Ctrl+C 結束監聽\n")
    else:
        print(f"❌ 連線失敗，RC={rc}")


def on_message(client, userdata, msg):
    topic = msg.topic
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        stats["parse_errors"] += 1
        print(f"⚠️  [解碼錯誤] {topic}: {e}")
        print(f"   原始內容: {msg.payload}")
        return

    # 判斷是哪類主題
    if "/receivers/" in topic:
        stats["receivers"] += 1
        _display_receiver(timestamp, topic, payload)
    elif "/status/" in topic:
        stats["status"] += 1
        _display_status(timestamp, topic, payload)


def _display_receiver(timestamp, topic, data):
    """顯示 RSSI 資料訊息"""
    student_id = data.get("student_id", "N/A")
    mac = data.get("mac", "N/A")
    rssi = data.get("rssi", "N/A")
    scanner = data.get("scanner_id", "?")
    time_field = data.get("time", "N/A")

    # 更新統計
    if student_id != "N/A":
        stats["students"].add(student_id)
    stats["scanners"].add(scanner)

    border = "─" * 55

    # RSSI 強度視覺化
    if isinstance(rssi, (int, float)):
        if rssi > -50:
            strength = "🟢 強"
        elif rssi > -70:
            strength = "🟡 中"
        elif rssi > -85:
            strength = "🟠 弱"
        else:
            strength = "🔴 極弱"
    else:
        strength = ""

    print(border)
    print(f"📡 [receivers/{scanner}] {timestamp}")
    print(f"    學號: {student_id} | MAC: {mac}")
    print(f"    RSSI: {rssi} dBm {strength}")
    print(f"    時間戳: {time_field}")
    print(border)


def _display_status(timestamp, topic, data):
    """顯示狀態訊息"""
    receiver_no = data.get("receiver_no", "?")
    ip = data.get("ip", "N/A")
    status = data.get("status", "N/A")

    if status == "online":
        icon = "🟢"
    else:
        icon = "⚪"

    border = "─" * 55
    print(border)
    print(f"{icon} [status/{receiver_no}] {timestamp}")
    print(f"    Receiver #{receiver_no} | IP: {ip} | {status}")
    print(border)


def print_summary():
    """離開時列印統計摘要"""
    print("\n" + "=" * 55)
    print("  📊 監聽統計摘要")
    print("=" * 55)
    print(f"  接收 RSSI 資料: {stats['receivers']} 筆")
    print(f"  接收狀態訊息:   {stats['status']} 筆")
    print(f"  解碼錯誤:       {stats['parse_errors']} 筆")
    print(f"  發現學生數:     {len(stats['students'])}")
    if stats['students']:
        for s in sorted(stats['students']):
            print(f"    - 學號 {s}")
    print(f"  發現樹莓派數:   {len(stats['scanners'])}")
    if stats['scanners']:
        for s in sorted(stats['scanners']):
            print(f"    - Scanner #{s}")
    print("=" * 55)


def signal_handler(sig, frame):
    print("\n\n👋 收到中斷訊號，結束監聽...")
    print_summary()
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(
        description="MQTT Listener — 監聽樹莓派 BLE Beacon 定位資料"
    )
    parser.add_argument(
        "--broker",
        default=DEFAULT_BROKER,
        help=f"MQTT Broker 位址 (預設: {DEFAULT_BROKER})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"MQTT Port (預設: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--topic",
        default=DEFAULT_TOPIC,
        help=f"MQTT Topic prefix (預設: {DEFAULT_TOPIC})",
    )
    parser.add_argument(
        "--username",
        default=None,
        help="MQTT 使用者名稱 (如有需要)",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="MQTT 密碼 (如有需要)",
    )

    args = parser.parse_args()

    # 註冊中斷處理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("=" * 55)
    print("  🎧 MQTT BLE Beacon 監聽器")
    print("=" * 55)
    print(f"  Broker: {args.broker}:{args.port}")
    print(f"  Topic:  {args.topic}/#")
    print("=" * 55)
    print()

    # 建立 MQTT 客戶端 (使用 v5 API)
    client = mqtt.Client(
        protocol=mqtt.MQTTv5,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.user_data_set({
        "broker": args.broker,
        "topic": args.topic,
    })

    # 設定認證
    if args.username and args.password:
        client.username_pw_set(args.username, args.password)

    # 設定 callback
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        print(f"🔄 正在連線到 {args.broker}:{args.port}...")
        client.connect(args.broker, args.port, keepalive=60)
        client.loop_forever()
    except KeyboardInterrupt:
        pass
    except ConnectionRefusedError:
        print(f"❌ 無法連線到 {args.broker}:{args.port}，請檢查 Broker 位址")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 發生錯誤: {e}")
        sys.exit(1)
    finally:
        client.disconnect()
        print_summary()


if __name__ == "__main__":
    main()
