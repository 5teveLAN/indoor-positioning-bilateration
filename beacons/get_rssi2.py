import time
import math
import json
from adafruit_ble import BLERadio
from adafruit_ble.advertising.standard import ProvideServicesAdvertisement

# --- Kalman Filter Class ---
class SimpleKalmanFilter:
    def __init__(self, process_variance=0.01, measurement_variance=0.5, estimation_error=1.0, initial_value=-70):
        self.q = process_variance      # Process noise
        self.r = measurement_variance  # Measurement noise
        self.p = estimation_error      # Estimation error
        self.x = initial_value         # Estimated state

    def update(self, measurement):
        # Prediction update
        self.p = self.p + self.q
        # Measurement update (Correction)
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
    print(f"Collecting {sample_count} samples (1 sample/sec)...")
    
    while len(readings) < sample_count:
        found = False
        # Scan for 0.8s to capture advertising packets
        for advertisement in ble.start_scan(ProvideServicesAdvertisement, timeout=0.8):
            if uuid_filter in str(advertisement.services):
                readings.append(advertisement.rssi)
                print(f"  [{len(readings)}/{sample_count}] Caught RSSI: {advertisement.rssi}")
                found = True
                break
        ble.stop_scan()
        if not found:
            print("  No signal detected this second. Retrying...")
        
        time.sleep(1)
    
    # Initialize Kalman Filter with the first reading
    kf = SimpleKalmanFilter(initial_value=readings[0])
    final_val = 0
    for r in readings:
        final_val = kf.update(r)
    return round(final_val, 2)

def calculate_n(d_i, measured_power, rssi_i):
    """Calculates Path Loss Exponent: n = (A - RSSI) / (10 * log10(d_i))"""
    if d_i <= 1: return 0
    try:
        n = (measured_power - rssi_i) / (10 * math.log10(d_i))
        return round(n, 4)
    except Exception:
        return 0

def save_results_to_file(measured_power, data_points):
    """Saves the experiment results to a text file."""
    timestamp = int(time.time())
    filename = f"ble_experiment_{timestamp}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write("=== BLE RSSI Experiment Report ===\n")
        f.write(f"Date: {time.ctime()}\n")
        f.write(f"Reference Power (A) at 1m: {measured_power} dBm\n")
        f.write("-" * 55 + "\n")
        f.write(f"{'Distance (m)':<15} | {'RSSI (dBm)':<12} | {'Exponent (n)':<15}\n")
        f.write("-" * 55 + "\n")
        
        for dist, rssi, n in data_points:
            f.write(f"{dist:<15} | {rssi:<12} | {n:<15.4f}\n")
        
        f.write("-" * 55 + "\n")
        f.write("Experiment Finished.\n")
    return filename

# --- Main Program Flow ---
data_points = [] # Stores (distance, filtered_rssi, calculated_n)

print("=== Step 1: Calibration (1 meter) ===")
input("Place the device exactly 1m away and press Enter to start...")
measured_power = collect_filtered_rssi(10)
print(f"Calibration Complete. Reference Power (A): {measured_power} dBm\n")

# --- Loop for other distances ---
while True:
    print("-" * 40)
    user_input = input("Enter distance (m) or type 'q' to save and exit: ").strip().lower()
    
    if user_input == 'q':
        break
    
    try:
        dist = float(user_input)
        if dist <= 1:
            print("Please enter a distance greater than 1m for calculation.")
            continue
            
        print(f"Sampling at {dist} meters...")
        filtered_rssi = collect_filtered_rssi(10)
        n_val = calculate_n(dist, measured_power, filtered_rssi)
        
        data_points.append((dist, filtered_rssi, n_val))
        print(f"Result: {dist}m | RSSI: {filtered_rssi} dBm | n: {n_val}")
        
    except ValueError:
        print("Invalid input. Please enter a number or 'q'.")

# --- Final Summary & File Output ---
if not data_points:
    print("No data points collected. Exiting.")
else:
    fname = save_results_to_file(measured_power, data_points)
    
    print("\n" + "="*55)
    print(f"{'Distance (m)':<15} | {'RSSI (dBm)':<12} | {'Exponent (n)':<15}")
    print("-" * 55)
    for d, r, n in data_points:
        print(f"{d:<15} | {r:<12} | {n:<15.4f}")
    print("="*55)
    print(f"Results successfully saved to: {fname}")
    print("Program terminated.")
