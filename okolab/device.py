import asyncio
import re
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Awaitable, Callable, Optional, Sequence

import serial
import serial.tools.list_ports
from aioserial import AioSerial
from serial.serialutil import SerialException


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


class OkolabDevice:
  def __init__(self, address: str, *, on_close: Optional[Callable[..., Awaitable[None]]] = None):
    self._lock = asyncio.Lock()
    self._on_close = on_close
    self._serial: Optional[AioSerial] = AioSerial(
      baudrate=115200,
      port=address
    )

  async def close(self):
    await self._lock.acquire()

    if not self._serial:
      raise OkolabDeviceDisconnectedError()

    self._serial.close()
    self._serial = None

    if self._on_close:
      await self._on_close(lost=False)

    self._lock.release()

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
      self._serial = None

      if self._on_close:
        await self._on_close(lost=True)

      raise OkolabDeviceDisconnectedError() from e
    finally:
      self._lock.release()

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
      raise ValueError()

    days, hours, minutes, seconds = match.groups()
    return timedelta(days=int(days), hours=int(hours), minutes=int(minutes), seconds=int(seconds))

  @staticmethod
  def list(*, all = False) -> Sequence[OkolabDeviceInfo]:
    infos = serial.tools.list_ports.comports()
    return [OkolabDeviceInfo(address=info.device) for info in infos if all or (info.vid, info.pid) == (0x03eb, 0x2404)]


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
