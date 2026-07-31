#!/usr/bin/env python3
"""
beacon1 數據分析程式
從實驗數據中找出最佳路徑損耗指數 n

使用 RSSI 路徑損耗模型:
  RSSI(d) = A - 10 * n * log10(d)
  
其中:
  A = 參考功率 @ 1m
  d = 距離
  n = 路徑損耗指數 (待優化)

我們用最小平方法 (Least Squares) 找出最佳 n，
使 RSSI_predicted 與 RSSI_measured 的誤差平方和最小。
"""

import re
import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import minimize_scalar

# ============================================================
# 1. 讀取數據檔案
# ============================================================
DATA_FILE = "data/beacon1"

with open(DATA_FILE, "r", encoding="utf-8") as f:
    content = f.read()

# ============================================================
# 2. 解析檔案內容
# ============================================================

# 提取參考功率 A
a_match = re.search(r"參考功率 \(A\) @ 1m:\s*([+-]?\d+\.?\d*)\s*dBm", content)
if not a_match:
    raise ValueError("找不到參考功率 A")
A = float(a_match.group(1))
print(f"參考功率 A = {A:.2f} dBm")

# 提取距離與 RSSI 數據
lines = content.strip().split("\n")
data_rows = []
for line in lines:
    # 匹配 "數字 | 數字" 格式的行
    match = re.match(r"^\s*(\d+\.?\d*)\s*\|\s*([+-]?\d+\.?\d*)\s*\|\s*([+-]?\d+\.?\d*)", line)
    if match:
        dist = float(match.group(1))
        rssi = float(match.group(2))
        n_given = float(match.group(3))  # 實驗報告給的 n (不是最佳化結果)
        data_rows.append((dist, rssi, n_given))

distances = np.array([row[0] for row in data_rows])
rssi_measured = np.array([row[1] for row in data_rows])
n_reported = np.array([row[2] for row in data_rows])

print(f"數據點數: {len(data_rows)}")
print(f"距離範圍: {distances.min()}m ~ {distances.max()}m")
print()

# ============================================================
# 3. 用最小平方法找出最佳 n
# ============================================================
# RSSI_model(d) = A - 10 * n * log10(d)
# 誤差平方和: S = Σ (RSSI_measured - (A - 10*n*log10(d)))^2
# 對 n 微分求極值:
# dS/dn = 2 * Σ (RSSI_measured - A + 10*n*log10(d)) * (-10*log10(d)) = 0
# => Σ (RSSI_measured - A + 10*n*log10(d)) * log10(d) = 0
# => n * 10 * Σ (log10(d))^2 = Σ (A - RSSI_measured) * log10(d)
# => n = Σ (A - RSSI_measured) * log10(d) / (10 * Σ (log10(d))^2)

log_d = np.log10(distances)
numerator = np.sum((A - rssi_measured) * log_d)
denominator = 10.0 * np.sum(log_d ** 2)
n_optimal = numerator / denominator

print("=" * 60)
print("  最佳化結果 (最小平方法)")
print("=" * 60)
print(f"  最佳路徑損耗指數 n = {n_optimal:.4f}")
print()

# ============================================================
# 4. 計算模型預測值與誤差
# ============================================================
rssi_predicted = A - 10.0 * n_optimal * log_d
residuals = rssi_measured - rssi_predicted
rmse = np.sqrt(np.mean(residuals ** 2))
mae = np.mean(np.abs(residuals))

print(f"  RMSE (均方根誤差) = {rmse:.4f} dBm")
print(f"  MAE (平均絕對誤差) = {mae:.4f} dBm")
print()

# 逐筆顯示
print("-" * 80)
print(f"{'距離 (m)':>10} | {'RSSI 量測':>12} | {'RSSI 預測':>12} | {'殘差':>8} | {'報告 n':>8}")
print("-" * 80)
for d, rm, rp, res, nr in zip(distances, rssi_measured, rssi_predicted, residuals, n_reported):
    print(f"{d:>10.1f} | {rm:>12.2f} | {rp:>12.2f} | {res:>+8.4f} | {nr:>8.4f}")
print("-" * 80)
print()

# ============================================================
# 5. 繪圖
# ============================================================

# 設定中文字型
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["PingFang TC", "Microsoft JhengHei", "Noto Sans CJK", "WenQuanYi Micro Hei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))

# ---- 圖 1: RSSI vs 距離 (含模型曲線) ----
ax1 = axes[0]
ax1.scatter(distances, rssi_measured, color="royalblue", s=60, zorder=5, label="量測數據")

# 繪製連續模型曲線
d_smooth = np.linspace(1, max(distances), 200)
rssi_smooth = A - 10.0 * n_optimal * np.log10(d_smooth)
ax1.plot(d_smooth, rssi_smooth, "r-", linewidth=2, label=f"最佳模型 (n={n_optimal:.4f})")

# 也繪製各點自己的 n 值曲線 (虛線)
for d, r, nv in zip(distances, rssi_measured, n_reported):
    if np.abs(nv) < 10:  # 忽略明顯異常值
        d_arr = np.array([d * 0.8, d * 1.2])
        r_arr = A - 10.0 * nv * np.log10(d_arr)
        ax1.plot(d_arr, r_arr, "--", color="gray", alpha=0.3, linewidth=0.8)

ax1.set_xlabel("距離 (m)", fontsize=12)
ax1.set_ylabel("RSSI (dBm)", fontsize=12)
ax1.set_title("RSSI 路徑損耗模型", fontsize=13, fontweight="bold")
ax1.legend(fontsize=11)
ax1.grid(True, alpha=0.3)
ax1.invert_yaxis()  # RSSI 越負越弱

# 標註參考點
ax1.annotate(f"A = {A:.2f} dBm @ 1m",
             xy=(1, A), xytext=(2.5, A - 2),
             arrowprops=dict(arrowstyle="->", color="darkgreen"),
             fontsize=10, color="darkgreen")

# ---- 圖 2: 殘差分佈 ----
ax2 = axes[1]
ax2.bar(distances, residuals, width=0.6, color="coral", edgecolor="darkred", alpha=0.8,
        label=f"RMSE = {rmse:.4f} dBm")
ax2.axhline(y=0, color="gray", linestyle="-", linewidth=0.8)
ax2.set_xlabel("距離 (m)", fontsize=12)
ax2.set_ylabel("殘差 (RSSI量測 - RSSI預測) (dBm)", fontsize=12)
ax2.set_title("模型殘差分佈", fontsize=13, fontweight="bold")
ax2.legend(fontsize=11)
ax2.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig("data/beacon1_analysis.png", dpi=150, bbox_inches="tight")
print(f"圖表已儲存至 data/beacon1_analysis.png")
plt.show()

# ============================================================
# 6. 摘要輸出
# ============================================================
print()
print("=" * 60)
print("  摘要")
print("=" * 60)
print(f"  參考功率 A          = {A:.2f} dBm")
print(f"  最佳路徑損耗指數 n  = {n_optimal:.4f}")
print(f"  模型公式: RSSI(d) = {A:.2f} - 10 × {n_optimal:.4f} × log10(d)")
print(f"  RMSE                = {rmse:.4f} dBm")
print(f"  MAE                 = {mae:.4f} dBm")
print("=" * 60)
