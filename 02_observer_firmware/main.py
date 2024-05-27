import wifi
import busio
import board
import supervisor
import neopixel
import time
from adafruit_ina260 import INA260, Mode, ConversionTime, AveragingCount
import filter
import decision_tree_custom
clf_microcontroller = decision_tree_custom.DecisionTreeCustom()

class RunningMode:
    USB_PC_DISABLED = 0
    USB_PC_ENABLED = 1
    
# running_mode = RunningMode.USB_PC_ENABLED
running_mode = RunningMode.USB_PC_DISABLED

if running_mode == RunningMode.USB_PC_DISABLED:
    print('\nOBSERVER\n')

# disable wifi to reduce current usage
wifi.radio.enabled = False

supervisor.runtime.autoreload = False

# disable this LED, which should be the RGB LED controlled by the CircuitPyhton supervisor
supervisor.runtime.rgb_status_brightness = 0

def list_i2c_devices_addresses(i2c):
    # find devices I2C 
    while not i2c.try_lock():
        pass

    try:
        if running_mode == RunningMode.USB_PC_DISABLED:
            print(f'I2C devices addresses founds: {[hex(device_address) for device_address in i2c.scan()]}')
        
    finally:  # unlock the i2c bus when ctrl-c'ing out of the loop
        i2c.unlock()

# configure INA260 current sensor
i2c = busio.I2C(board.IO15, board.IO16)
# list_i2c_devices_addresses(i2c)

# RED LED at max 255:
# INA21873 --> 8.72mV
# Resistor = 0.1 ohm
# Current = 0.00872 / 0.1 = 87.2mA
ina226_current_factor = 0.046582

ina226 = INA260(i2c, address=0x44, ina2xx_id=550, current_factor=ina226_current_factor)
ina226.averaging_count = AveragingCount.COUNT_1
ina226.current_conversion_time = ConversionTime.TIME_8_244_ms
ina226.mode = Mode.TRIGGERED

# filter_current = filter.FilterLowPass()
filter_current = filter.FilterMedian()

# filter settings: read current every 15ms / 66Hz, and get the samples of 0.2 second -- total of 14 samples
# this values were tested and the results were very good - std: 0.00015 amp
reading_current_delta_time = 0.015
reading_current_total_time = 0.200

# configure UART for communications with the target board
uart = busio.UART(
    board.IO10,
    board.IO9,
    baudrate = 9600,
    timeout = 0.002, # 10ms is enough for reading the UART
    receiver_buffer_size = 64)

# configure the RGB LED
led_rgb_pixels = neopixel.NeoPixel(board.NEOPIXEL, 1)
led_rgb_pixels[0] = (0, 0, 0)

if running_mode == RunningMode.USB_PC_ENABLED:
    import usb_cdc
    uart_usb = usb_cdc.data
    # timeout of 10ms should be enough
    uart_usb.timeout = 0.010
    uart_usb.write_timeout = 0.010

def set_rgb_led(r, g, b):
    led_rgb_pixels[0] = (r, g, b)
    
def read_target_current():
    # trigger a new measure
    ina226.mode = Mode.TRIGGERED
    return ina226.current / 1000.0

def read_target_current_filtered():
    current_value = 0
    
    # read ADC value, doing the oversampling to reduce the noise
    reading_current_initial_time = time.monotonic()
    while True:
        initial_time = time.monotonic()
        
        current_value = read_target_current()
        filter_current.add_new_sample(current_value)
        
        # stop if adc_reading_total_time has passed
        current_time = time.monotonic()
        if current_time > (reading_current_total_time + reading_current_initial_time):
            break
        
        # wait _reading_delta_time
        time_to_sleep = reading_current_delta_time - (current_time - initial_time)
        # if running_mode == RunningMode.USB_PC_DISABLED:
        #     print(f'time_to_sleep: {time_to_sleep}')
        
        # because sometimes seems there is a long time measured.....
        if time_to_sleep > reading_current_delta_time or time_to_sleep < 0:
            time_to_sleep = reading_current_delta_time
        
        time.sleep(time_to_sleep)
    
    mean, median, std = filter_current.get_end_stats()
    
    if running_mode == RunningMode.USB_PC_DISABLED:
        # print(f'current mean: {mean:.6f}')
        # print(f'current median: {median:.6f}')
        # print(f'std: {std}')
        # print()
        pass
    
    return median

r = 0
g = 0
b = 0
rx_new_rgb_values = False
tx_new_rgb_values = False
command = 0

previous_rgb_list = [0, 0, 0]
rgb_equal_counter = 0
while True:
                        
    target_current = read_target_current_filtered()
    
    # clf_init_time = time.monotonic()
    r, g, b = clf_microcontroller.predict(target_current)
    # print(f'processing time microcontroller classifier: {time.monotonic() - clf_init_time}')
    
    if [r, g, b] == previous_rgb_list:
        if rgb_equal_counter < 2:
            rgb_equal_counter += 1
    else:
        previous_rgb_list = [r, g, b]
        rgb_equal_counter = 0
        
    if rgb_equal_counter >= 2:  
        set_rgb_led(r, g, b)
        print(f'{r:3}, {g:3}, {b:3} - {target_current:.6f}')
