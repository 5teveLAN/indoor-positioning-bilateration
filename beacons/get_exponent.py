#!/usr/bin/env python3
"""
beacons/get_exponent.py — 程式一：路徑損耗參數量測

用途：
  互動式測量 BLE 路徑損耗參數 n (Path Loss Exponent) 與 A (Reference Power @ 1m)。

行為：
  1. 若 systemd 服務 `ble-beacon-scanner` (程式二) 正在運作，自動將其暫停，
     避免 BLE 適配器被佔用衝突。
  2. 使用者依提示在不同距離取樣 RSSI。
  3. 結束時自動重啟程式二 (若之前有暫停)。

執行方式：
  ssh 登入樹莓派後手動執行：
      cd ~/indoor-positioning-bilateration/beacons
      python3 get_exponent.py

參考：
  - 七、路徑損耗指數量測（事前準備）
  - indoor-positioning-bilateration/other/get_loss.py (公式實作)
"""

import time
import math
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

# ─── 設定 ───────────────────────────────────
SERVICE_NAME = "ble-beacon-scanner"
SYSTEMCTL = "/usr/bin/systemctl" if os.path.exists("/usr/bin/systemctl") else "systemctl"

# ─── BLE 相關 ────────────────────────────────
UUID_FILTER = "1111"  # 只過濾包含此 UUID 的 BLE 廣告封包
# ─── adafruit_ble ────────────────────────────
# 使用與 code.py 相同的 BLE 函式庫，確保掃到相同裝置
from adafruit_ble import BLERadio
from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
# BleakDBusError fallback
try:
    from bleak.exc import BleakDBusError
except ImportError:
    BleakDBusError = Exception

ble = BLERadio()

# ─── 程式二管理 ──────────────────────────────

_service_was_running = False


def _is_service_active() -> bool:
    """檢查 systemd 服務是否正在運作。"""
    try:
        result = subprocess.run(
            [SYSTEMCTL, "is-active", "--quiet", SERVICE_NAME],
            capture_output=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _is_code_py_running() -> bool:
    """檢查 code.py 程序是否正在執行（以防 systemd 服務沒抓到）。"""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "code.py"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _stop_service():
    """暫停程式二 (用 sudo 徹底關閉 + 重置藍牙)。"""
    global _service_was_running

    # 1) 關 systemd 服務 (需要 sudo)
    if _is_service_active():
        print(f"\n🔧 偵測到「{SERVICE_NAME}」正在執行，暫時停止中...")
        subprocess.run(["sudo", SYSTEMCTL, "stop", SERVICE_NAME], check=True)
        _service_was_running = True
        print("✅ 已暫停 systemd 服務。")
    else:
        _service_was_running = False

    # 2) 補 kill 所有 code.py (含 root 權限的)
    try:
        subprocess.run(["pkill", "-f", "code.py"], capture_output=True, timeout=5)
        subprocess.run(["sudo", "pkill", "-f", "code.py"], capture_output=True, timeout=5)
    except Exception:
        pass
    time.sleep(0.5)

    # 3) 重置藍牙適配器，釋放 BlueZ D-Bus 狀態
    print("   🔄 重置藍牙適配器...")
    subprocess.run(["sudo", "bluetoothctl", "power", "off"], capture_output=True, timeout=5)
    time.sleep(0.5)
    subprocess.run(["sudo", "bluetoothctl", "power", "on"], capture_output=True, timeout=5)
    time.sleep(0.5)
    print("✅ 藍牙已重置完成。\n")


def _restart_service_if_needed():
    """若之前暫停了程式二，現在重啟它 (需 sudo)。"""
    if _service_was_running:
        print(f"\n🔧 量測完成，重新啟動「{SERVICE_NAME}」...")
        subprocess.run(["sudo", SYSTEMCTL, "start", SERVICE_NAME], check=True)
        print("✅ 已重啟。\n")


# ─── Kalman 濾波器 ───────────────────────────

class SimpleKalmanFilter:
    def __init__(self, process_variance=0.01, measurement_variance=0.5,
                 estimation_error=1.0, initial_value=-70):
        self.q = process_variance
        self.r = measurement_variance
        self.p = estimation_error
        self.x = initial_value

    def update(self, measurement):
        self.p = self.p + self.q
        k = self.p / (self.p + self.r)
        self.x = self.x + k * (measurement - self.x)
        self.p = (1 - k) * self.p
        return self.x


# ─── 核心函式 ────────────────────────────────

def _scan_adafruit_once(timeout=1.5) -> list:
    """
    使用 adafruit_ble（與 code.py 相同）掃描一次，
    回傳 [(mac_str, rssi), ...] 清單，只包含 ProvideServicesAdvertisement
    且 services 字串包含 UUID_FILTER 的裝置。
    """
    results = []
    scanner = None
    try:
        scanner = ble.start_scan(ProvideServicesAdvertisement, timeout=timeout)
        for advertisement in scanner:
            if not isinstance(advertisement, ProvideServicesAdvertisement):
                continue
            if UUID_FILTER not in str(advertisement.services):
                continue
            # MAC 轉成大寫無分隔格式（與 code.py 一致）
            addr_bytes = advertisement.address.address_bytes
            addr_str = "".join("{:02x}".format(b) for b in addr_bytes).upper()
            results.append((addr_str, advertisement.rssi))
            # 有找到就 break，一次掃描一個廣告
            break
    except BleakDBusError as e:
        print(f"      ⚠️ BLE DBus error: {e}")
        raise
    finally:
        if scanner is not None:
            try:
                ble.stop_scan()
            except BleakDBusError:
                pass
            except Exception:
                pass
    return results


def collect_filtered_rssi(sample_count=10) -> float:
    """
    使用 adafruit_ble 掃描 BLE 裝置，只取 UUID_FILTER 匹配裝置的 RSSI，
    回傳 Kalman 濾波後的值。
    """
    readings = []
    print(f"  收集 {sample_count} 個樣本...")

    while len(readings) < sample_count:
        results = _scan_adafruit_once(timeout=1.2)
        if results:
            for addr_str, rssi in results:
                if len(readings) < sample_count:
                    readings.append(rssi)
                    print(f"    [{len(readings)}/{sample_count}] RSSI: {rssi}  ({addr_str})")
                else:
                    break

        if len(readings) == 0:
            print("    ⚠️ 未偵測到目標裝置，重試中...")
            time.sleep(1)
        elif len(readings) < sample_count:
            print(f"    ⚠️ 目前 {len(readings)}/{sample_count} 個樣本，繼續收集...")
            time.sleep(0.5)

    if not readings:
        print("    ❌ 無法取得任何 RSSI 樣本！")
        return -100.0

    kf = SimpleKalmanFilter(initial_value=readings[0])
    final_val = 0
    for r in readings:
        final_val = kf.update(r)
    return round(final_val, 2)


def calculate_n(distance: float, measured_power: float, rssi: float) -> float:
    """計算路徑損耗指數 n = (A - RSSI) / (10 * log10(d))"""
    if distance <= 1:
        return 0.0
    try:
        n = (measured_power - rssi) / (10 * math.log10(distance))
        return round(n, 4)
    except Exception:
        return 0.0


def save_results(measured_power: float, data_points: list) -> str:
    """將實驗結果覆寫到 result.txt。"""
    filename = "result.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write("=== BLE RSSI 路徑損耗實驗報告 ===\n")
        f.write(f"日期: {time.ctime()}\n")
        f.write(f"參考功率 (A) @ 1m: {measured_power} dBm\n")
        f.write("-" * 55 + "\n")
        f.write(f"{'距離 (m)':<15} | {'RSSI (dBm)':<12} | {'損耗指數 (n)':<15}\n")
        f.write("-" * 55 + "\n")
        for dist, rssi, n in data_points:
            f.write(f"{dist:<15} | {rssi:<12} | {n:<15.4f}\n")
        f.write("-" * 55 + "\n")
        f.write("實驗結束。\n")
    return filename


# ─── 中斷處理 ────────────────────────────────

def _signal_handler(sig, frame):
    """捕捉 Ctrl+C 等中斷訊號，確保重啟程式二。"""
    print("\n\n⚠️  收到中斷訊號，正在清理...")
    _restart_service_if_needed()
    print("👋 已退出。")
    sys.exit(0)


# ─── 主流程 ──────────────────────────────────
def main():
    # 註冊中斷處理 (Ctrl+C 時也要重啟服務)
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # 1) 暫停程式二 (若正在執行)
    _stop_service()

    data_points = []  # 存放 (distance, filtered_rssi, calculated_n)

    print("=" * 60)
    print("  BLE 路徑損耗參數量測工具")
    print("  UUID 過濾:", UUID_FILTER)
    print("  BLE 引擎: adafruit_ble (與 code.py 相同)")
    print("=" * 60)

    # --- Step 1: 校正 (1 公尺) ---
    print("\n📏 Step 1: 校正 (1 公尺)")
    print(f"   目標: 掃描 UUID={UUID_FILTER} 的 BLE beacon")
    input("   請將手機/beacon 放在距離感測器「1 公尺」處，然後按下 Enter ⏎...")
    measured_power = collect_filtered_rssi(10)
    print(f"   ✅ 參考功率 (A) @ 1m = {measured_power} dBm\n")

    # --- Step 2: 量測其他距離 ---
    print("📏 Step 2: 量測其他距離")
    print("   照預設距離清自動輪流測量，或手動輸入任意距離。")
    print("   輸入 q 結束並儲存結果。\n")

    # 預設距離清單 (可自行增減)
    default_distances = [2, 3, 4, 5, 6, 7, 8, 9, 10]
    distance_iter = iter(default_distances)
    use_auto_mode = True  # 是否使用自動模式

    while True:
        print("-" * 50)

        if use_auto_mode:
            # 嘗試取下一個預設距離
            try:
                next_dist = next(distance_iter)
                prompt = f"   距離 (m) [Enter=測 {next_dist}m | 手動輸入距離 | q 結束] > "
            except StopIteration:
                # 預設距離都測完了，切換到手動模式
                use_auto_mode = False
                prompt = "   距離 (m) [輸入數字 | q 結束] > "
        else:
            prompt = "   距離 (m) [輸入數字 | q 結束] > "

        user_input = input(prompt).strip().lower()

        if user_input == "q":
            break
        elif user_input == "" and use_auto_mode:
            # 按下 Enter，使用預設距離
            dist = next_dist
        else:
            # 使用者手動輸入
            use_auto_mode = False  # 一旦手動輸入，就不再使用自動模式
            try:
                dist = float(user_input)
            except ValueError:
                print("   ⚠️ 請輸入數字、按下 Enter 使用預設距離，或輸入 q 結束。")
                continue

        if dist <= 1:
            print("   ⚠️ 請輸入大於 1 公尺的距離。(1m 已在 Step 1 測量)")
            continue

        print(f"   📡 在 {dist} 公尺處取樣...")
        filtered_rssi = collect_filtered_rssi(10)
        n_val = calculate_n(dist, measured_power, filtered_rssi)

        data_points.append((dist, filtered_rssi, n_val))
        print(f"   ✅ {dist}m | RSSI: {filtered_rssi} dBm | n = {n_val}")

    # --- Step 3: 結果彙整與儲存 ---
    if not data_points:
        print("\n⚠️  未收集到任何資料點。")
    else:
        fname = save_results(measured_power, data_points)

        print("\n" + "=" * 60)
        print("   📊 實驗結果")
        print("=" * 60)
        print(f"   參考功率 (A) @ 1m = {measured_power} dBm\n")
        print(f"   {'距離 (m)':<15} | {'RSSI (dBm)':<12} | {'損耗指數 (n)':<15}")
        print("   " + "-" * 55)
        for d, r, n in data_points:
            print(f"   {d:<15} | {r:<12} | {n:<15.4f}")
        print("=" * 60)
        print(f"   📁 結果已儲存至: {fname}")

    # 4) 重啟程式二 (若之前有暫停)
    _restart_service_if_needed()

    print("\n👋 程式結束。")


if __name__ == "__main__":
    main()

