mqtt_env = {
    "broker": "broker.hivemq.com",  # Public MQTT broker
    "port": 1883,                  # Default MQTT port
    "username": None,              # Public brokers may not require authentication
    "password": None,
    "topic": "ble/beacons/ggg",  # Topic to publish BLE beacon data
}
addresses_to_filter = ["B4E7B36041B4"]

RECEIVER_NO = 1