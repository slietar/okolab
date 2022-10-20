# Okolab

This Python package provides control of the [H401-T-CONTROLLER](https://www.oko-lab.com/27-ivf/191-controllers-2) temperature controller from Okolab.


## Installation

```sh
$ pip install okolab
```


## Usage

To create an Okolab

```py
from okolab import OkolabDevice

# If you know the device's address
device = OkolabDevice(address="COM3")
device = OkolabDevice(address="/dev/tty.usbmodem1101")

# If you know the device's serial number
device = OkolabDevice(serial_number="2133")
```

```py
# Try connecting
await device.connect()

if device.connected:
  # Do something
```

```py
# Reconnect every few seconds
task = device.reconnect(interval=1)

# Wait for reconnect (or cancellation)
await task

# Stop try to reconnect
task.cancel()
```

```py
# Using callbacks

class Device(OkolabDevice):
  async def _on_connection(self, *, reconnection: bool):
    print("Connected")

  async def _on_connection_fail(self, reconnection: bool):
    print("Connection failed")

  async def _on_disconnection(self, *, lost: bool):
    print("Disconnected")

device = Device(...)
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
