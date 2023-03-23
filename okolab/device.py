import asyncio
import re
from asyncio import Future, Lock
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Optional

import serial
import serial.tools.list_ports
from serial import Serial, SerialException


class OkolabDeviceStatus(IntEnum):
  Ok = 0
  Transient = 1
  Alarm = 2
  Error = 3
  Disabled = 4

class OkolabDeviceConnectionLostError(Exception):
  """
  An error raised by `OkolabDevice.closed()` when the connection to the controller is lost.
  """

class OkolabDeviceConnectionError(Exception):
  """
  An error raised when the connection to the controller fails or is corrupted.
  """

class OkolabDeviceProtocolError(OkolabDeviceConnectionError):
  """
  An error raised when the controller returns malformed data.
  """

class OkolabDeviceSystemError(Exception):
  """
  An error raised when the controller reports an error.
  """


@dataclass(frozen=True, kw_only=True)
class OkolabDeviceInfo:
  address: str

  def create(self):
    return OkolabDevice(self.address)


class OkolabDevice:
  """
  An object represting a connection to an H401-T-CONTROLLER from Okolab.

  Only one request to the controller is permitted at a time; concurrent requests will be queued. Every method may raise an `OkolabDeviceDisconnectedError` if the controller is or becomes disconnected, and an `OkolabDeviceSystemError` if the controller reports an error.

  Attributes
    address: The address of the device.
  """

  def __init__(self, address: str):
    """
    Constructs an `OkolabDevice` instance and opens the connection to the controller.

    Parameters
      address: The address of the device, such as `COM3` or `/dev/tty.usbmodem1101`.

    Raises
      OkolabDeviceDisconnectedError: If the controller is unreachable.
    """

    self.address = address

    self._closed = Future[bool]() # true = lost
    self._lock = Lock()

    try:
      self._serial: Optional[Serial] = Serial(
        baudrate=115200,
        port=address
      )
    except (OSError, SerialException) as e:
      raise OkolabDeviceConnectionError from e

  async def close(self):
    """
    Closes the connection to the controller.
    """

    async with self._lock:
      if self._serial:
        self._serial.close()
        self._serial = None

        self._closed.set_result(False)

  async def closed(self):
    """
    Returns once the connection to the controller is closed.

    Closes the connection when cancelled.

    Raises
      OkolabDeviceConnectionLostError: If the connection was lost, as opposed to closed using `close()`.
      asyncio.CancelledError
    """

    try:
      if await asyncio.shield(self._closed):
        raise OkolabDeviceConnectionLostError
    except asyncio.CancelledError:
      await self.close()
      raise

  async def _request(self, command: str):
    def request():
      assert self._serial
      self._serial.write(f"{command}\r".encode("ascii"))
      return self._serial.read_until(b"\r").decode("ascii")

    async with self._lock:
      if not self._serial:
        raise OkolabDeviceConnectionError

      loop = asyncio.get_event_loop()

      try:
        res = await asyncio.wait_for(loop.run_in_executor(None, request), timeout=2.0)
      except (SerialException, asyncio.TimeoutError) as e:
        self._serial.close()
        self._serial = None

        self._closed.set_result(True)

        raise OkolabDeviceConnectionError from e

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
    """
    Returns the temperature of the controller's board.

    Returns
      The temperature of the controller's board, in Celsius degrees.
    """

    return float(await self._request("026"))

  async def get_product_name(self):
    """
    Returns the controller's product name.

    Returns
      The controller's product name, such as `...`.
    """

    return await self._request("017")

  async def get_serial_number(self):
    """
    Returns the serial number of the controller.
    """

    return await self._request("018")

  async def get_time(self):
    """
    Returns the time on the controller's clock.

    Raises
      OkolabDeviceProtocolError
    """

    raw_value = await self._request("070")

    try:
      return datetime.strptime(raw_value, "%m/%d/%Y %H:%M:%S")
    except ValueError as e:
      raise OkolabDeviceProtocolError from e

  async def set_time(self, date: datetime, /):
    """
    Sets the time on the controller's clock.
    """

    await self._request("071" + date.strftime("%m/%d/%Y %H:%M:%S"))

  async def get_device1(self):
    """
    Returns the type id number of device 1.

    Returns
      The type id number, or `None` if the device is disabled.
    """

    res = await self._request("111")
    return type if (res != "Disabled") and ((type := int(res)) >= 0) else None

  async def get_device2(self):
    res = await self._request("113")
    return type if (res != "Disabled") and ((type := int(res)) >= 0) else None

  async def set_device1(self, type: Optional[int], *, side: Optional[int] = None):
    """
    Sets the type id number of device 1.

    Parameters
      type: The type id number to set.
      side: The side to set, relevant only for metal-glass plates (0 = not specified, 1 = glass, 2 = metal).
    """

    await self._request("112" + str(type if type is not None else -1))

    if side is not None:
      await self._request("116" + str(side))

  async def set_device2(self, type: Optional[int], *, side: Optional[int] = None):
    await self._request("114" + str(type if type is not None else -1))

    if side is not None:
      await self._request("118" + str(side))

  async def get_temperature1(self):
    """
    Returns the observed temperature of device 1.

    Returns
      The observed temperature, in Celsius degrees, or `None` if the device is disabled or disconnected.
    """

    value = await self._request("001")
    return float(value) if (value != "OFF") and (value != "OPEN") else None

  async def get_temperature2(self):
    value = await self._request("037")
    return float(value) if (value != "OFF") and (value != "OPEN") else None

  async def get_temperature_setpoint1(self):
    """
    Returns the temperature setpoint of device 1.

    Returns
      The temperature setpoint, in Celsius degrees.
    """

    return float(await self._request("002"))

  async def get_temperature_setpoint2(self):
    return float(await self._request("067"))

  async def set_temperature_setpoint1(self, value: float, /):
    """
    Sets the temperature setpoint of device 1.

    Parameters
      value: The temperature setpoint, in Celsius degrees. Must be between 25°C and 60°C. Precision is limited to 0.01°C.
    """

    assert 25.0 <= value <= 60.0
    await self._request(f"008{value:.01f}")

  async def set_temperature_setpoint2(self, value: float, /):
    assert 25.0 <= value <= 60.0
    await self._request(f"063{value:.01f}")

  async def get_temperature_setpoint_range1(self):
    """
    Returns the temperature setpoint range of device 1.

    Returns
      A tuple (min, max) which represents the temperature setpoint range.
    """

    return (
      float(await self._request("005")),
      float(await self._request("006"))
    )

  async def get_temperature_setpoint_range2(self):
    return (
      float(await self._request("068")),
      float(await self._request("069"))
    )

  async def get_status(self):
    return OkolabDeviceStatus(int(await self._request("110")))

  async def get_status1(self):
    """
    Returns the status of device 1.
    """

    return OkolabDeviceStatus(int(await self._request("004")))

  async def get_status2(self):
    return OkolabDeviceStatus(int(await self._request("039")))

  async def get_uptime(self):
    """
    Returns the uptime of the controller.

    Raises
      OkolabDeviceProtocolError
    """

    match = re.match(r"(\d+) d, (\d\d):(\d\d):(\d\d)", await self._request("025"))

    if not match:
      raise OkolabDeviceProtocolError

    days, hours, minutes, seconds = match.groups()
    return timedelta(days=int(days), hours=int(hours), minutes=int(minutes), seconds=int(seconds))

  async def __aenter__(self):
    assert self._serial

  async def __aexit__(self, exc_type, exc, tb):
    await self.close()

  @staticmethod
  def list(*, all: bool = False):
    """
    Lists visible devices.

    Parameters
      all: Whether to include devices that do not have recognized vendor and product ids.

    Yields
      Instances of `OkolabDeviceInfo`.
    """

    infos = serial.tools.list_ports.comports()

    for info in infos:
      if all or (info.vid, info.pid) == (0x03eb, 0x2404):
        yield OkolabDeviceInfo(address=info.device)


__all__ = [
  "OkolabDevice",
  "OkolabDeviceConnectionError",
  "OkolabDeviceConnectionLostError",
  "OkolabDeviceProtocolError",
  "OkolabDeviceStatus",
  "OkolabDeviceSystemError"
]
