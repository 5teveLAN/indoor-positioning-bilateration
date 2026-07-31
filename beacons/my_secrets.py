mqtt_env = {
    "broker": "broker.hivemq.com",  # Public MQTT broker
    "port": 1883,                  # Default MQTT port
    "username": None,              # Public brokers may not require authentication
    "password": None,
    "topic": "ble/beacons/ggg",  # Topic to publish BLE beacon data
}
addresses_to_filter = ["B4E7B36041B4"]

RECEIVER_NO = 1

# 測試模式：True = 用固定 TEST_KEY_2024 離線測試，False = 需向後端 API 取得 XOR Key
USE_TEST_MODE = True