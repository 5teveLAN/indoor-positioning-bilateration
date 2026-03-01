import math

def calculate_path_loss_exponent(distance, measured_power, rssi):
    """
    Calculates the Path Loss Exponent (n).
    :param distance: d_i (distance from the source)
    :param measured_power: A (RSSI at 1 meter)
    :param rssi: The received signal strength at distance d_i
    :return: path_loss_exponent (n)
    """
    try:
        # Distance must be > 0 and not equal to 1 to avoid math errors
        if distance <= 0:
            return "Distance must be positive."
        if distance == 1:
            return "Distance cannot be 1 (log(1) is zero). Use a different sample point."
        
        numerator = measured_power - rssi
        denominator = 10 * math.log10(distance)
        
        n = numerator / denominator
        return n

    except Exception as e:
        return f"Error in calculation: {e}"

# Example Usage:
# If at 5 meters, the RSSI is -70, and the 1-meter measured power is -50:
d_i = float(input("Enter distance: "))
a = -72.57
rssi_val = float(input("Enter RSSI: "))

n_result = calculate_path_loss_exponent(d_i, a, rssi_val)
print(f"Path Loss Exponent (n): {n_result:.2f}")
