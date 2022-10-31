import asyncio
import re
import traceback
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Awaitable, Callable, Coroutine, Generic, Optional, Protocol, Sequence, TypeVar, cast

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
  def __init__(self, *, address):
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
    await self._request("008" + str(value))

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

  @classmethod
  def list(cls, *, all = False):
    infos = serial.tools.list_ports.comports()
    return [OkolabDeviceInfo(address=info.device) for info in infos if all or (info.vid, info.pid) == (0x03eb, 0x2404)]


class GeneralDevice(Protocol):
  def __init__(self, address: str, *, on_close: Optional[Callable[..., Awaitable[None]]] = None):
    pass

  async def close(self):
    raise NotImplementedError()

  async def get_serial_number(self) -> Optional[str]:
    raise NotImplementedError()

  @classmethod
  def list(cls) -> Sequence[OkolabDeviceInfo]:
    raise NotImplementedError()


T = TypeVar('T', bound=GeneralDevice)

class GeneralDeviceAdapter(Generic[T]):
  def __init__(self, Device: type[T], *, address: Optional[str] = None, reconnect_device: bool = True, serial_number: Optional[str] = None):
    self._Device = Device

    self._address = address
    self._serial_number = serial_number

    self._device: Optional[T] = None
    self._reconnect_task = None

    self.connected = False
    self.reconnect_device = reconnect_device

  @property
  def device(self):
    if not self.connected:
      raise OkolabDeviceDisconnectedError()

    return cast(T, self._device)


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
      for info in self._Device.list():
        await self._connect_address(info.address)

        if self.connected:
          break

    return self.connected

  async def _connect_address(self, address: str):
    async def on_close(*, lost: bool):
      if lost:
        self.connected = False
        self._device = None

        if self.reconnect_device:
          self.reconnect()

        await self._on_disconnection(lost=lost)

    try:
      self._device = self._Device(address, on_close=on_close)
      serial_number = await asyncio.wait_for(self._device.get_serial_number(), timeout=1)
    except (asyncio.TimeoutError, SerialException):
      self._device = None
    else:
      if (self._serial_number is None) or (serial_number == self._serial_number):
        self.connected = True
      else:
        self._device = None


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
    if self._device:
      await self._device.close()

      self.connected = False
      self._device = None

      await self._on_disconnection(lost=False)

    if self._reconnect_task:
      self._reconnect_task.cancel()



__all__ = [
  "OkolabDevice",
  "OkolabDeviceDisconnectedError",
  "OkolabDeviceStatus",
  "OkolabDeviceSystemError"
]


if __name__ == "__main__":
  async def main():
    class Adapter(GeneralDeviceAdapter[OkolabDevice]):
      def __init__(self, serial_number):
        super().__init__(OkolabDevice, serial_number=serial_number)

      async def _on_connection(self, *, reconnection: bool):
        print("Connected, reconnection=", reconnection)

      async def _on_connection_fail(self, reconnection: bool):
        print("Connection failed, reconnection=", reconnection)

      async def _on_disconnection(self, *, lost: bool):
        print("Disconnected, lost=", lost)

    adapter = Adapter(serial_number="2133")

    await adapter.connect()

    # if not adapter.connected:
    #   await adapter.reconnect(initial_wait=True)

    adapter.reconnect(initial_wait=True)

    # await adapter.device.set_time(await adapter.device.get_time() + timedelta(hours=1))

    # print(await adapter.device.get_board_temperature())
    # print(await adapter.device.get_product_name())
    # print(await adapter.device.get_uptime())
    # print(await asyncio.gather(
    #   adapter.device.get_temperature1(),
    #   adapter.device.get_temperature_setpoint1()
    # ))
    # print(await adapter.device.get_temperature_setpoint_range1())

    while True:
      await asyncio.sleep(1)

      if adapter.connected:
        try:
          print(await adapter.device.get_uptime())
        except Exception as e:
          print(e)

    # await adapter.stop()

  asyncio.run(main())
