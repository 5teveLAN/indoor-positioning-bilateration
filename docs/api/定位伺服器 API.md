# 定位計算程式 — 跨程式介面規格

> **本文件負責：** 定位計算程式（Python）**所有跨程式的介面** —— MQTT 2 支 + HTTP 2 支，共 4 支。
> **以角色為軸：** 定位計算程式是唯一同時碰 MQTT 與 HTTP 的元件（http server 兼 http client）。
>
> | 角色 | 通訊方式 | 說明 |
> |------|----------|------|
> | 感測器（樹莓派） | **MQTT only** | 訂閱 `session_key`、發布 `receivers/{NO}` 封包 |
> | 定位計算程式（Python） | **MQTT + HTTP** | http server（收 §2.1）+ http client（送 §2.2） |
> | 點名伺服器（Node.js） | **HTTP only** | 不碰 MQTT |
>
> **兩種方向的寫法差異：**
> - **MQTT 是單向發布**，沒有回信 → 只定義「送出的 topic + payload」。
> - **HTTP 是一問一答** → 每支介面同時定義「請求 + 回應 + 錯誤碼」。

## TOC

- [1. MQTT](定位伺服器%20API.md#1-mqtt)
  - [1.1 定位計算 → 感測器：發布 Session XOR Key](定位伺服器%20API.md#11-定位計算--感測器發布-session-xor-key)
  - [1.2 感測器 → 定位計算：發布 RSSI 封包](定位伺服器%20API.md#12-感測器--定位計算發布-rssi-封包)
- [2. HTTP（點名伺服器 & 定位伺服器）](定位伺服器%20API.md#2-http點名伺服器--定位伺服器)
  - [2.1 點名 → 定位：Session 設定（驗證管道）](定位伺服器%20API.md#21-點名--定位session-設定驗證管道)
  - [2.2 定位 → 點名：上傳座標](定位伺服器%20API.md#22-定位--點名上傳座標)
- [3. 介面總覽與文件分工](定位伺服器%20API.md#3-介面總覽與文件分工)

> 📌 **角色命名約定：** 本系列文件把 Node.js 那一端稱作「**點名伺服器**」（因為它有 `/api/session/*`、`/api/coords*`），
> 把 Python 那一端稱作「**定位伺服器 / 定位計算程式**」。
> 兩者在同一台機器上、不同 port，彼此用 `127.0.0.1` 互打 HTTP。

---

## 1. MQTT

### 1.1 定位計算 → 感測器：發布 Session XOR Key

**目的：** 定位計算程式收到 §2.1 的 `xor_key` 後，轉發給感測器，讓感測器能解開手機 beacon 的學號。

**發送方：** 定位計算程式 publish（源自 §2.1 收到的 `xor_key`）
**接收方：** 感測器 subscribe

| Topic | QoS | Retained | 說明 |
|-------|:---:|:--------:|------|
| `{topic}/session_key` | 1 | **是** | retained → 新開機的感測器一訂閱就立刻拿到，不必等下一次點名 |

> `{topic}` 預設為 `mcu/indoor-location`（見 [附錄：預設值](定位伺服器%20API.md#附錄預設值實作現況)）。

**Payload（json）：**
```json
{
    "session_id": "9f3c1a7e4b2d4c8f",
    "xor_key": "TEST_KEY_2024"
}
```

| 欄位 | 型態 | 必填 | 說明 |
|------|------|:---:|------|
| `session_id` | string | 是 | 本次點名 session 的唯一識別（不可預測的隨機值） |
| `xor_key` | string | 是 | 本次共用 XOR 加密金鑰（與 §2.1 收到的相同） |

> ⚠️ **欄位統一用小寫 `xor_key`**（與 §2.1 相同），各文件不要再混用 `XOR_KEY` / `xorKey` 等大小寫。

---

### 1.2 感測器 → 定位計算：發布 RSSI 封包

**目的：** 感測器把「聽到某手機 beacon」的結果送上來，定位計算程式據此判斷封包有效性、再餵進定位引擎。

**發送方：** 感測器（樹莓派）publish
**接收方：** 定位計算程式 subscribe

| Topic | 方向 |
|-------|------|
| `{topic}/receivers/{RECEIVER_NO}` | 感測器 → Broker → 定位計算程式 |

**Payload（json）：**
```json
{
    "session_id": "9f3c1a7e4b2d4c8f",
    "student_id": "11012345",
    "OTP": "A1B2C3",
    "mac": "B4E7B36041B4",
    "rssi": -72,
    "scanner_id": 1,
    "time": "09/09/2026 14:30:22"
}
```

| 欄位 | 型態 | 必填 | 說明 |
|------|------|:---:|------|
| `session_id` | string | 是 | 對應 §2.1 建立的 session |
| `student_id` | string | 是 | 8 位學號（封包 XOR 解密取得）★ **唯一識別，定位引擎的 key** |
| `OTP` | string | 是 | 該學生 beacon 內嵌 OTP（與 §2.1 `otp_list` 對照） |
| `mac` | string | 否 | 手機 BLE MAC（大寫無分隔）。**僅供除錯／顯示，不可作為識別**（MAC 會隨機化變動） |
| `rssi` | int | 是 | 原始 RSSI（濾波留給定位計算端做，見 [[2.2.2 定位計算程式 — 計算]]） |
| `scanner_id` | int | 是 | 樹莓派編號 |
| `time` | string | 是 | `dd/mm/yyyy HH:MM:SS`（NTP 同步後） |

> ⚠️ **`OTP` 的大小寫就是大寫 `OTP`**（本欄位與 §2.1 的小寫 `xor_key` 不同，勿統一）。

#### 「有效封包」的定義（嚴格模式，2026-09 決議）

必須 **`student_id ∈ otp_list` 且其對應 OTP 相符**，兩個條件**同時成立**才算有效封包。

> **理由：** OTP 對不上可能代表「XOR key 沒更新 / App 用了舊的 OTP」，
> 此時解出的學號也可能是錯的 —— 若拿來定位會污染別人的位置。
> 因此 **OTP 不通過的封包一律丟棄、不進定位引擎、不產生座標、不送 §2.2 座標**，
> 而 §2.1 的回應即為 `failed` / `reason: "otp_mismatch"`。

---


## 2. HTTP（點名伺服器 & 定位伺服器）

> **共同前提：** 兩支 API 都在**同一台機器**上以 `127.0.0.1` 互打，
> Content-Type 皆為 `application/json; charset=UTF-8`。
> **兩支都不可暴露到公網**（見 [3.2 存取控制](定位伺服器%20API.md#32-存取控制重要)）。

| 編號 | Method | Path | 方向 | server 端是誰實作 | 規格權威 |
|:---:|--------|------|------|------------------|----------|
| 2.1 | `POST` | `/api/session/config` | 點名 → 定位 | **定位計算程式** | **本文件 §2.1**（唯一） |
| 2.2 | `POST` | `/api/coords` | 定位 → 點名 | **Node.js** | [[點名伺服器 API]] §2.1 |

> 💡 **為什麼 2.2 不在本文件展開？** 因為它的 server 端是 Node，
> 正式規格（request／response／buffer 語意）寫在 [[點名伺服器 API]] §2.1，
> 本文件只以「定位計算程式這一側的 client 視角」做重點提示，**避免兩份打架**。

---

### 2.1 點名 → 定位：Session 設定（驗證管道）

**目的：** 點名伺服器開始一次點名時，把本次的 XOR Key 和「學號 → OTP」對照表送給定位計算程式，並**驗證整條管道是否打通**（key 能不能解、有沒有學生真的在場）。

**發送方：** [[點名伺服器 API]]（http client）
**接收方：** 定位計算程式（localhost http server）

| 項目 | 值 |
|------|-----|
| Method | `POST` |
| Path | `/api/session/config` |
| Host / Port | `http://127.0.0.1:8020`（定位計算程式，**預設 8020**） |
| Content-Type | `application/json; charset=UTF-8` |
| **同步阻塞** | **是**：收到第一個有效封包才回；最長等 `timeout` 秒（建議 **5** 秒） |
| 暴露範圍 | 🔒 只綁 `127.0.0.1`，不掛對外／ngrok |

> ⚠️ **這是同步阻塞呼叫，不是 fire-and-forget。**
> 點名伺服器發出去後會**卡住最多 5 秒**等回應，且**必須處理 4 種回應分支**（見下表）。

**Request Body：**
```json
{
    "session_id": "9f3c1a7e4b2d4c8f",
    "xor_key": "TEST_KEY_2024",
    "otp_list": {
        "11012345": "A1B2C3",
        "11012346": "D4E5F6",
        "11012347": "G7H8I9",
        "11012348": "J0K1L2"
    },
    "timeout": 5
}
```

**Request 欄位：**

| 欄位 | 型態 | 必填 | 說明 |
|------|------|:---:|------|
| `session_id` | string | 是 | 本次點名 session 的唯一識別（**不可預測的隨機值**，見下方警告） |
| `xor_key` | string | 是 | 本次共用 XOR 加密金鑰（會轉發到 MQTT §1.1） |
| `otp_list` | object | 是 | key = 8 位學號，value = 該生 **OTP 明文字串**。**空物件視為不存在** → 回 `invalid_body` |
| `timeout` | number | 否 | 最長等待秒數。**省略時定位計算程式用預設 5 秒**；上限 60 秒，超過以 60 計 |

> ⚠️ **OTP 一律以「明文」傳輸。** `otp_list` 的值是 `"A1B2C3"` 這種明文，
> **不是 MD5 / hash**。雜湊只在定位計算程式**內部**比對時使用，對外協定不變。
> （與 [[點名伺服器 API]] §1.2 的 `otp_list`、§1.3 的 `otp` 格式一致。）

> ⚠️ **`session_id` 必須是不可預測的隨機值**（例如 UUID v4 或 128-bit 隨機 hex），
> **不可用 `sess_20260909_01` 這種「日期 + 流水號」格式**。
> 理由：`session_id` 是 [[點名伺服器 API]] §2.2 的存取憑證之一，可預測就等於把全班座標的門打開（IDOR 漏洞）。
> （本文件所有範例都已改用隨機值 `9f3c1a7e4b2d4c8f`。）


#### 定位計算程式收到後做的事（依序）

1. **驗證欄位**：`session_id` / `xor_key` 為非空字串、`otp_list` 為非空物件且值皆為字串。任一不合格 → 立即回 `400 invalid_body`。
2. 把收到的 `xor_key` 以 MQTT publish 至 `{topic}/session_key`（**retained, QoS 1**），供感測器訂閱解密。（見 [§1.1](定位伺服器%20API.md#11-定位計算--感測器發布-session-xor-key)）
3. 訂閱 `{topic}/receivers/#`，等待 **「第一個有效封包」**（見 [§1.2](定位伺服器%20API.md#12-感測器--定位計算發布-rssi-封包)：`student_id ∈ otp_list` **且** OTP 相符）。
4. 以該封包解出的學號去 `otp_list` 查出「應該的 OTP」，並與該封包攜帶的 OTP 比對。
5. 比對一致 → 回 `200 ok`；比對不一致 → 回 `400 otp_mismatch`；等不到有效封包 → 回 `504 timeout`。
6. **OTP 不一致的封包會被整筆丟棄**（不進定位引擎、不產生座標、不送 §2.2），以免用到可能錯誤的學號。

#### Response Body（一問一答，只回一次）

| 情境 | HTTP 狀態 | `status` | `reason` | 備註 |
|------|:---------:|:--------:|----------|------|
| 第一個有效封包 OTP 相符 | `200 OK` | `ok` | — | 附 `student_id` |
| OTP 不符 | `400 Bad Request` | `failed` | `otp_mismatch` | 附 `session_id` |
| 等不到有效封包 | `504 Gateway Timeout` | `failed` | `timeout` | 附 `session_id` |
| 欄位／JSON 格式錯誤 | `400 Bad Request` | `failed` | `invalid_body` | 附 `message` |

**`reason` 值總表（點名伺服器端可據此分流處理）：**

| `reason` | 代表意義 | 點名伺服器建議處置 |
|----------|----------|-------------------|
| （無，`status: ok`） | 管道打通、有人在場且 OTP 正確 | 正常點名，開始等 §2.2 座標進來 |
| `otp_mismatch` | 有人在場，但 OTP 對不上（key 未更新／App 用舊 OTP） | ⚠️ **規格未定義**（目前 code：回 failed 但不中斷；**待決議**是否擋下本次點名） |
| `timeout` | 5 秒內沒有任何有效封包 | ⚠️ **規格未定義**（目前 code：回 failed；**待決議**是否提示老師「可能沒人帶手機／感測器離線」） |
| `invalid_body` | 我方 request 有問題（理論上不該發生） | 視為 **程式 bug**，應記 log 並告警，不要靜默吞掉 |

**成功（`200 OK`）：**
```json
{
    "status": "ok",
    "session_id": "9f3c1a7e4b2d4c8f",
    "student_id": "11012345"
}
```

| 欄位 | 型態 | 說明 |
|------|------|------|
| `status` | string | 固定 `ok` |
| `session_id` | string | 回音，方便點名伺服器確認是同一場 |
| `student_id` | string | 第一個通過 OTP 驗證的學號（僅供「驗證管道」，不是座標） |

**OTP 不符（`400 Bad Request`）：**
```json
{
    "status": "failed",
    "session_id": "9f3c1a7e4b2d4c8f",
    "reason": "otp_mismatch"
}
```

**逾時（`504 Gateway Timeout`）：**
```json
{
    "status": "failed",
    "session_id": "9f3c1a7e4b2d4c8f",
    "reason": "timeout"
}
```

**格式錯誤（`400 Bad Request`）：**
```json
{
    "status": "failed",
    "reason": "invalid_body",
    "message": "缺少欄位或 JSON 解析失敗"
}
```

---


### 2.2 定位 → 點名：上傳座標

> 📖 **正式規格請看 [[點名伺服器 API]] §2.1**（server 端實作者是 Node）。
> 本節只做「定位計算程式這一側的 client 摘要」，**兩份不一致時以 2.3 為準**。

**目的：** 每個算好座標的有效學生，主動送回點名伺服器更新。此介面在一次 session 內可**連續呼叫多次（一個學生一次）**。

**發送方：** 定位計算程式（http client）
**接收方：** [[點名伺服器 API]]（點名伺服器 http server）

| 項目 | 值 |
|------|-----|
| Method | `POST` |
| Path | `/api/coords` |
| Host / Port | `http://127.0.0.1:3000`（Node，**預設 3000**；與 §2.1 同機不同 service） |
| Content-Type | `application/json; charset=UTF-8` |
| 呼叫時機 | 每次算完**一個**學生的座標（同一學生更新會再呼叫一次） |
| 暴露範圍 | 🔒 只綁 `127.0.0.1`，不掛對外 |

> 💡 **觀念：** §2.1 那次的 response（ok/failed）已經回完、結束了。
> **座標是另一支 request**，不可能回給同一支。

**Request Body：**
```json
{
    "session_id": "9f3c1a7e4b2d4c8f",
    "student_id": "11012345",
    "x": 12,
    "y": 20,
    "coordinate_system": "grid32",
    "timestamp": "09/09/2026 14:30:22"
}
```

| 欄位 | 型態 | 必填 | 說明 |
|------|------|:---:|------|
| `session_id` | string | 是 | 對應 §2.1 建立的 session |
| `student_id` | string | 是 | 8 位學號 |
| `x` | float | 是 | 座標 X |
| `y` | float | 是 | 座標 Y |
| `coordinate_system` | string | 是 | 座標單位。`grid32` = 0~31 格點 / `meter` = 公尺，二擇一 |
| `timestamp` | string | 是 | `dd/mm/yyyy HH:MM:SS`（NTP 同步後時間） |

> ℹ️ 定位計算程式**不需要**送 `otp`、`mac`、`rssi`。
> 只有「已通過 OTP 驗證」的學生才會被定位（見 [§1.2 嚴格模式](定位伺服器%20API.md#有效封包的定義嚴格模式2026-09-決議)），
> 因此能到達這支 API 的 `student_id` 本身就已經是被信任的。

**「有效座標」的定義（決定 Node 是否回 ok）：**
1. `session_id`、`student_id`、`x`、`y`、`coordinate_system` 欄位齊全且型態正確。
2. `student_id` 是本次 session 內**已通過 OTP 驗證**的學生。
3. 若 `coordinate_system = grid32`，需 `0 ≤ x, y ≤ 31`；若 `meter`，需在教室允許範圍內。
4. （可選）以「3 台（含）以上接收到的 RSSI」算出的座標才算有效。

**Response Body：**

| 情境 | HTTP 狀態 | 內容 |
|------|:---------:|------|
| 有效座標，接受 | `200 OK` | `{ "status": "ok", "accepted": true }` |
| 無效座標 | `400 Bad Request` | `{ "status": "failed", "reason": "invalid_coord", "message": "…" }` |
| 格式錯誤 | `400 Bad Request` | `{ "status": "failed", "reason": "invalid_body", "message": "…" }` |

---
