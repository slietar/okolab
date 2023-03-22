import asyncio
import re
from asyncio import Lock
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Optional, Protocol

import serial
import serial.tools.list_ports
from serial import Serial, SerialException


class OkolabDeviceStatus(IntEnum):
  Ok = 0
  Transient = 1
  Alarm = 2
  Error = 3
  Disabled = 4

class OkolabDeviceDisconnectedError(Exception):
  pass

class OkolabDeviceSystemError(Exception):
  pass

class OkolabDeviceInfo:
  def __init__(self, *, address: str):
    self.address = address

  def create(self, **kwargs):
    return OkolabDevice(self.address, **kwargs)


class OkolabDeviceLostCallback(Protocol):
  async def __call__(self, *, lost: bool):
    ...


class OkolabDevice:
  def __init__(self, address: str, *, on_close: Optional[OkolabDeviceLostCallback] = None):
    self._lock = Lock()
    self._on_close = on_close

    try:
      self._serial: Optional[Serial] = Serial(
        baudrate=115200,
        port=address
      )
    except SerialException as e:
      raise OkolabDeviceDisconnectedError from e

  async def close(self):
    if not self._serial:
      raise OkolabDeviceDisconnectedError

    async with self._lock:
      self._serial.close()
      self._serial = None

      if self._on_close:
        await self._on_close(lost=False)

  async def _request(self, command):
    if not self._serial:
      raise OkolabDeviceDisconnectedError

    def request():
      assert self._serial
      self._serial.write(f"{command}\r".encode("ascii"))
      return self._serial.read_until(b"\r").decode("ascii")

    async with self._lock:
      loop = asyncio.get_event_loop()

      try:
        res = await loop.run_in_executor(None, request)
      except SerialException as e:
        self._serial = None

        if self._on_close:
          await self._on_close(lost=True)

        raise OkolabDeviceDisconnectedError from e

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
            raise OkolabDeviceSystemError

      return res[3:-1]

  async def get_board_temperature(self):
    return float(await self._request("026"))

  async def get_product_name(self):
    return await self._request("017")

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
    return float(value) if (value != "OFF") and (value != "OPEN") else None

  async def get_temperature_setpoint1(self):
    return float(await self._request("002"))

  async def set_temperature_setpoint1(self, /, value: float):
    assert 25.0 <= value <= 60.0
    await self._request(f"008{value:.01f}")

  async def get_temperature_setpoint_range1(self):
    return (
      float(await self._request("005")),
      float(await self._request("006"))
    )

  async def get_status(self):
    return OkolabDeviceStatus(int(await self._request("110")))

  async def get_status1(self):
    return OkolabDeviceStatus(int(await self._request("004")))

  async def get_uptime(self):
    match = re.match(r"(\d+) d, (\d\d):(\d\d):(\d\d)", await self._request("025"))

    if not match:
      raise ValueError("Malformed response")

    days, hours, minutes, seconds = match.groups()
    return timedelta(days=int(days), hours=int(hours), minutes=int(minutes), seconds=int(seconds))

  @staticmethod
  def list(*, all: bool = False):
    infos = serial.tools.list_ports.comports()

    for info in infos:
      if all or (info.vid, info.pid) == (0x03eb, 0x2404):
        yield OkolabDeviceInfo(address=info.device)


__all__ = [
  "OkolabDevice",
  "OkolabDeviceDisconnectedError",
  "OkolabDeviceStatus",
  "OkolabDeviceSystemError"
]


if __name__ == "__main__":
  async def main():
    device = next(iter(OkolabDevice.list())).create()

    await device.set_time(await device.get_time() + timedelta(hours=1))

    print(await device.get_board_temperature())
    print(await device.get_product_name())
    print(await device.get_uptime())
    print(await asyncio.gather(
      device.get_temperature1(),
      device.get_temperature_setpoint1()
    ))
    print(await device.get_temperature_setpoint_range1())

  asyncio.run(main())
