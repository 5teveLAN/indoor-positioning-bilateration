import time
import math
from adafruit_ble import BLERadio
from adafruit_ble.advertising.standard import ProvideServicesAdvertisement

# --- Kalman Filter Class ---
class SimpleKalmanFilter:
    def __init__(self, process_variance=0.01, measurement_variance=0.5, estimation_error=1.0, initial_value=-70):
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

# --- Core Functions ---
ble = BLERadio()
uuid_filter = "1111"

def collect_filtered_rssi(sample_count=10):
    """Scans for BLE devices and returns a Kalman-filtered RSSI value."""
    readings = []
    print(f"Collecting {sample_count} samples...")
    
    while len(readings) < sample_count:
        found = False
        for advertisement in ble.start_scan(ProvideServicesAdvertisement, timeout=0.8):
            if uuid_filter in str(advertisement.services):
                readings.append(advertisement.rssi)
                print(f"  [{len(readings)}/{sample_count}] Caught RSSI: {advertisement.rssi}")
                found = True
                break
        ble.stop_scan()
        if not found:
            print("  Signal lost, retrying...")
        time.sleep(1)
    
    # Apply Kalman Filter
    kf = SimpleKalmanFilter(initial_value=readings[0])
    final_val = 0
    for r in readings:
        final_val = kf.update(r)
    return round(final_val, 2)

def calculate_n(d_i, measured_power, rssi_i):
    """Rearranged formula: n = (A - RSSI) / (10 * log10(d_i))"""
    if d_i <= 1: return 0
    return (measured_power - rssi_i) / (10 * math.log10(d_i))

# --- Main Program Flow ---
data_points = [] # Stores (distance, filtered_rssi)

print("=== Step 1: Calibration (1 meter) ===")
input("Please place the device at exactly 1m and press Enter...")
measured_power = collect_filtered_rssi(10)
print(f"Calibration Complete. Measured Power (A) at 1m: {measured_power} dBm\n")

# --- Loop for other distances ---
while True:
    print("-" * 30)
    user_input = input("Enter distance in meters (e.g., 2, 3, 5) or 'q' to finish: ").strip().lower()
    
    if user_input == 'q':
        break
    
    try:
        dist = float(user_input)
        if dist <= 1:
            print("Please enter a distance greater than 1m for calculation.")
            continue
            
        print(f"Sampling for {dist} meters...")
        filtered_rssi = collect_filtered_rssi(10)
        data_points.append((dist, filtered_rssi))
        print(f"Result for {dist}m: {filtered_rssi} dBm")
        
    except ValueError:
        print("Invalid input. Please enter a number or 'q'.")

# --- Final Calculation & Summary ---
if not data_points:
    print("No data collected. Exiting.")
else:
    print("\n" + "="*45)
    print(f"{'Distance (m)':<15} | {'RSSI (dBm)':<12} | {'Exponent (n)':<10}")
    print("-" * 45)
    
    for dist, rssi in data_points:
        n = calculate_n(dist, measured_power, rssi)
        print(f"{dist:<15} | {rssi:<12} | {n:<10.2f}")
    
    print("="*45)
    print("Experiment complete.")
