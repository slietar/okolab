import asyncio
from dataclasses import dataclass, field
from typing import Self

from .device import OkolabDevice, OkolabDeviceConnectionError


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
  root = HierarchyNode(["."])

  for device_info in OkolabDevice.list(all=True):
    try:
      async with (device := device_info.create()):
        device_node = HierarchyNode([
          (await device.get_product_name()),
          f"Address: {device.address}",
          f"Serial number: {await device.get_serial_number()}",
          f"Uptime: {await device.get_uptime()}",
          f"Time: {await device.get_time()}"
        ])

        if (id1 := await device.get_device1()) is not None:
          temp1 = await device.get_temperature1()
          device_node.children.append(HierarchyNode([
            'Device 1',
            f"Type id number: {id1}",
            f"Status: {(await device.get_status1()).name}",
            f"Temperature: " + (f"{temp1:.1f}°C" if temp1 is not None else "<closed>"),
            f"Setpoint: {(await device.get_temperature_setpoint1()):.1f}°C"
          ]))
        else:
          device_node.children.append(HierarchyNode(['<closed>']))

        if (id2 := await device.get_device2()) is not None:
          temp2 = await device.get_temperature2()
          device_node.children.append(HierarchyNode([
            'Device 2',
            f"Type id number: {id2}",
            f"Status: {(await device.get_status2()).name}",
            f"Temperature: " + (f"{temp2:.1f}°C" if temp2 is not None else "<closed>"),
            f"Setpoint: {(await device.get_temperature_setpoint2()):.1f}°C"
          ]))
        else:
          device_node.children.append(HierarchyNode(['<closed>']))
    except OkolabDeviceConnectionError:
      pass
    else:
      root.children.append(device_node)

  if root.children:
    print(root.format())
  else:
    print("No device found.")


asyncio.run(main())
