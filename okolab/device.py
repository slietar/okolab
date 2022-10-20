import asyncio
import re
import traceback
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Optional

import serial
import serial.tools.list_ports
from aioserial import AioSerial
from serial.serialutil import SerialException


class OkolabDeviceStatus(IntEnum):
  Transient = 1
  Alarm = 2
  Error = 3
  Disabled = 4

class OkolabDeviceDisconnectedError(Exception):
  pass

class OkolabDeviceSystemError(Exception):
  pass

class OkolabDevice:
  def __init__(self, *, address: Optional[str] = None, serial_number: Optional[str] = None):
    self._address = address
    self._serial_number = serial_number

    self._lock = asyncio.Lock()
    self._serial = None
    self._reconnect_task = None

    self.connected = False


  # Callback methods to be implemented by subclasses

  async def _on_connection(self, *, reconnection: bool):
    pass

  async def _on_connection_fail(self, reconnection: bool):
    pass

  async def _on_disconnection(self, *, lost: bool):
    pass


  # Connection methods

  async def _connect(self):
    if self._address is not None:
      await self._connect_address(self._address)
    else:
      infos = serial.tools.list_ports.comports()

      for info in infos:
        if (info.vid, info.pid) == (0x03eb, 0x2404) or 1:
          await self._connect_address(info.device)

          if self.connected:
            break

    return self.connected

  async def _connect_address(self, address: str):
    try:
      self._serial = AioSerial(
        baudrate=115200,
        port=address
      )
    except SerialException:
      self._serial = None
    else:
      serial_number = await self.get_serial_number()

      if (self._serial_number is None) or (serial_number == self._serial_number):
        self.connected = True

  async def connect(self):
    connected = await self._connect()

    if connected:
      await self._on_connection(reconnection=False)
    else:
      await self._on_connection_fail(reconnection=False)

    return connected

  def reconnect(self, *, initial_wait = False, interval = 1):
    async def reconnect_loop():
      try:
        if initial_wait:
          await asyncio.sleep(interval)

        while True:
          if await self._connect():
            await self._on_connection(reconnection=True)
            return
          else:
            await self._on_connection_fail(reconnection=True)

          await asyncio.sleep(interval)
      except asyncio.CancelledError:
        pass
      except Exception:
        traceback.print_exc()
      finally:
        self._reconnect_task = None

    self._reconnect_task = asyncio.create_task(reconnect_loop())
    return self._reconnect_task

  async def start(self):
    if not await self.connect():
      self.reconnect(initial_wait=True)

  async def stop(self):
    if self._serial:
      await self._lock.acquire()
      self._lock.release()

      self._serial.close()
      self._serial = None

    if self._reconnect_task:
      self._reconnect_task.cancel()

    await self._on_disconnection(lost=False)


  # Request methods

  async def _request(self, command):
    await self._lock.acquire()

    if not self._serial:
      raise OkolabDeviceDisconnectedError()

    try:
      await self._serial.write_async(f"{command}\r".encode("ascii"))
      res = (await self._serial.read_until_async(b"\r")).decode("ascii")

      if res[0] == "E":
        match int(res[1:]):
          case 1:
            raise OkolabDeviceSystemError("Command ID not valid")
          case 2:
            raise OkolabDeviceSystemError("Message request too long")
          case 3:
            raise OkolabDeviceSystemError("Message request too short")
          case 4:
            raise OkolabDeviceSystemError("Command cannot be executed")
          case 5:
            raise OkolabDeviceSystemError("Value out of range")
          case 6:
            raise OkolabDeviceSystemError("Value not available")
          case 8:
            raise OkolabDeviceSystemError("Generic error")
          case 15:
            raise OkolabDeviceSystemError("Request not properly formatted")
          case _:
            raise OkolabDeviceSystemError()

      return res[3:-1]
    except SerialException as e:
      self.connected = False
      self._serial = None

      # if self._check_task:
      #   self._check_task.cancel()

      await self._on_disconnection(lost=True)
      self.reconnect()

      raise OkolabDeviceDisconnectedError() from e
    finally:
      self._lock.release()

  async def get_serial_number(self):
    return await self._request("018")

  async def get_time(self):
    return datetime.strptime(await self._request("070"), "%m/%d/%Y %H:%M:%S")

  async def set_time(self, date: datetime):
    await self._request("071" + date.strftime("%m/%d/%Y %H:%M:%S"))

  async def set_device1(self, type: Optional[int], *, side: Optional[int] = None):
    await self._request("112" + str(type if type is not None else -1))

    if side is not None:
      await self._request("116" + str(side))

  async def set_device2(self, type: Optional[int], *, side: Optional[int] = None):
    await self._request("114" + str(type if type is not None else -1))

    if side is not None:
      await self._request("118" + str(side))

  async def get_temperature1(self):
    value = await self._request("001")
    return float(value) if value != "OFF" else None

  async def get_temperature_setpoint1(self):
    return float(await self._request("002"))

  async def set_temperature_setpoint1(self, /, value: float):
    assert 25.0 <= value <= 60.0
    await self._request("008" + str(value))

  async def get_status(self):
    return OkolabDeviceStatus(int(await self._request("110")))

  async def get_uptime(self):
    match = re.match(r"(\d+) d, (\d\d):(\d\d):(\d\d)", await self._request("025"))

    if not match:
      raise ValueError()

    days, hours, minutes, seconds = match.groups()
    return timedelta(days=int(days), hours=int(hours), minutes=int(minutes), seconds=int(seconds))


__all__ = [
  "OkolabDevice",
  "OkolabDeviceDisconnectedError",
  "OkolabDeviceSystemError"
]


if __name__ == "__main__":
  async def main():
    class Device(OkolabDevice):
      async def _on_connection(self, *, reconnection: bool):
        print("Connected")

      async def _on_connection_fail(self, reconnection: bool):
        print("Connection failed")

      async def _on_disconnection(self, *, lost: bool):
        print("Disconnected")

    device = Device(serial_number="2133")

    await device.connect()

    if not device.connected:
      await device.reconnect(initial_wait=True)

    await device.set_time(await device.get_time() + timedelta(hours=1))

    print(await device.get_uptime())
    print(await asyncio.gather(
      device.get_temperature1(),
      device.get_temperature_setpoint1()
    ))

  asyncio.run(main())
