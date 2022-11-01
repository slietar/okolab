from setuptools import setup

setup(
  name="okolab",
  version="0.1.0",

  description="Control of the H401-T-CONTROLLER temperature controller from Okolab",
  url="https://github.com/slietar/okolab",

  python_requires=">=3.10",
  install_requires=[
    "aioserial==1.3.1",
    "pyserial==3.5"
  ]
)
