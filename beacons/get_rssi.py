import json
import time
import adafruit_ntp
import socket
from adafruit_ble import BLERadio
from adafruit_ble.advertising.standard import ProvideServicesAdvertisement

# --- Kalman Filter Class ---
# A simple linear Kalman Filter to smooth RSSI fluctuations
class SimpleKalmanFilter:
    def __init__(self, process_variance, measurement_variance, estimation_error, initial_value):
        self.q = process_variance      # Process noise (environmental changes)
        self.r = measurement_variance  # Measurement noise (RSSI jitter)
        self.p = estimation_error      # Estimation error
        self.x = initial_value         # Initial state estimate
        self.k = 0                     # Kalman Gain

    def update(self, measurement):
        # Prediction Update
        self.p = self.p + self.q
        
        # Measurement Update (Correction)
        self.k = self.p / (self.p + self.r)
        self.x = self.x + self.k * (measurement - self.x)
        self.p = (1 - self.k) * self.p
        
        return self.x

# --- Hardware Initialization ---
pool = socket
# Attempt to fetch NTP time (retained from original logic)
try:
    ntp = adafruit_ntp.NTP(pool, tz_offset=0)
    t = ntp.datetime
    time_str = "{:02d}/{:02d}/{} {:02d}:{:02d}:{:02d}".format(
        t[2], t[1], t[0], t[3], t[4], t[5]
    )
except Exception:
    time_str = "NTP Unavailable"

ble = BLERadio()
uuid_filter = "1111"  # Filter for specific UUID

def run_sampling_and_exit():
    rssi_readings = []
    target_addr = "Unknown"
    
    print(f"--- Starting RSSI Sampling (Target UUID: {uuid_filter}) ---")
    
    while len(rssi_readings) < 10:
        found_in_second = False
        
        # Scan for 0.8s to capture advertising packets
        for advertisement in ble.start_scan(ProvideServicesAdvertisement, timeout=0.8):
            if uuid_filter in str(advertisement.services):
                addr_bytes = advertisement.address.address_bytes
                target_addr = ":".join("{:02X}".format(b) for b in addr_bytes)
                
                rssi_readings.append(advertisement.rssi)
                print(f"Progress: {len(rssi_readings)}/10 | Device: {target_addr} | Raw RSSI: {advertisement.rssi}")
                found_in_second = True
                break  # Stop scanning for this specific second once caught
        
        ble.stop_scan()
        
        if not found_in_second:
            print("Warning: No signal detected this second. Retrying...")
        
        # Ensure 1-second interval between samples
        time.sleep(1)

    # --- Execute Kalman Filter for Best Estimate ---
    # Parameters: r=0.5 accounts for typical BLE RSSI noise levels
    kf = SimpleKalmanFilter(
        process_variance=0.01, 
        measurement_variance=0.5, 
        estimation_error=1.0, 
        initial_value=rssi_readings[0]
    )
    
    final_best_estimate = 0
    for r in rssi_readings:
        final_best_estimate = kf.update(r)

    # --- Final Output ---
    print("\n" + "="*40)
    print(f"Timestamp: {time_str}")
    print(f"Device Address: {target_addr}")
    print(f"Raw Samples: {rssi_readings}")
    print(f"Simple Average: {sum(rssi_readings)/10:.2f}")
    print(f"Kalman Filtered Best Value: {final_best_estimate:.2f}")
    print("="*40)
    print("Task completed. Exiting.")

if __name__ == "__main__":
    try:
        run_sampling_and_exit()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        ble.stop_scan()
