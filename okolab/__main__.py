import asyncio
from dataclasses import dataclass, field
from typing import Self

from .device import OkolabDevice


@dataclass
class HierarchyNode:
  value: list[str]
  children: 'list[Self]' = field(default_factory=list)

  def format(self, *, prefix: str = str()):
    return ("\n" + prefix).join(self.value) + str().join([
      "\n" + prefix
        + ("└── " if (last := (index == (len(self.children) - 1))) else "├── ")
        + child.format(prefix=(prefix + ("    " if last else "│   ")))
        for index, child in enumerate(self.children)
    ])


async def main():
  found_device = False
  root = HierarchyNode(["System"])

  for device_info in OkolabDevice.list():
    found_device = True
    device = device_info.create()

    root.children.append(device_node := HierarchyNode([
      (await device.get_product_name()),
      f"Address: {device.address}"
      f"Serial number: {await device.get_serial_number()}",
      f"Uptime: {await device.get_uptime()}",
      "Time"
    ]))

    if (id1 := await device.get_device1()) is not None:
      device_node.children.append(HierarchyNode([
        'Device 1',
        f"Status: {(await device.get_status1()).name}"
        f"Temperature: {(await device.get_temperature1()):.1f}°C",
        f"Setpoint: {(await device.get_temperature_setpoint1()):.1f}°C"
      ]))
    else:
      device_node.children.append(HierarchyNode(['<closed>']))

    if (id2 := await device.get_device2()) is not None:
      device_node.children.append(HierarchyNode([
        'Device 2',
        f"Status: {(await device.get_status2()).name}"
        f"Temperature: {(await device.get_temperature2()):.1f}°C",
        f"Setpoint: {(await device.get_temperature_setpoint2()):.1f}°C"
      ]))
    else:
      device_node.children.append(HierarchyNode(['<closed>']))

  if found_device:
    print(root.format())
  else:
    print("No device found.")


asyncio.run(main())
