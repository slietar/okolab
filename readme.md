# Okolab

This Python package provides control of the [H401-T-CONTROLLER](https://www.oko-lab.com/27-ivf/191-controllers-2) temperature controller from Okolab.


## Installation

```sh
$ pip install okolab

# List available devices
$ python -m okolab
```


## Usage

```py
from okolab import OkolabDevice

device = OkolabDevice(address="COM3")
device = OkolabDevice(address="/dev/tty.usbmodem1101")
```

```py
def on_close(*, lost):
  print(f"Connection closed, lost={lost}")

device = Device(address="COM3", on_close=on_close)
```

```py
# Read temperature
temp = await device.get_temperature1()
temp = await device.get_temperature2()

# Write temperature
await device.set_temperature_setpoint1(37.0)
await device.set_temperature_setpoint2(37.0)
```

```py
# Read in parallel
await asyncio.gather(
  device.get_temperature1(),
  device.get_temperature2()
)
```

```py
from okolab import OkolabDeviceDisconnectedError, OkolabDeviceSystemError

# Catching errors
try:
  temp = await device.get_temperature1()
except OkolabDeviceDisconnectedError:
  # The device has been disconnected
except OkolabDeviceSystemError:
  # The device has reported an error
```

```py
from okolab import OkolabDevice

infos = OkolabDevice.list()

for info in infos:
  device = info.create()
  print(await device.get_serial_number())
```
