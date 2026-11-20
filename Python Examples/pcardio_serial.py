"""PCARDIO Serial Interface - ASCII framing over USB serial.

The Serial Interface carries Core Interface packets over the micro-USB
connection, wrapped in an ASCII message:

    $ <opcode> <hex encoded Core Interface packet> \\n

It adds two commands that the wireless BLE link does not have: putting the
recorder into bootloader mode for a firmware upgrade, and a hard reboot.

Port settings: 460800 baud, no parity, one stop bit, DTR enabled.
Identify the port by VID 16D0 / PID 06A1 or by the product name "PCardio".
Use a USB cable that carries data, not a charge-only cable.
"""

from __future__ import annotations

import pcardio_core as core

PREFIX = b"$"
POSTFIX = b"\n"

OPCODE_TRANSMIT = b"T"  # host -> recorder, carries a Core Interface packet
OPCODE_RECEIVE = b"R"   # recorder -> host, reply to a transmit
OPCODE_UPGRADE = b"U"   # enter bootloader mode for a firmware update
OPCODE_REBOOT = b"B"    # hard reset


def frame(core_packet: bytes, opcode: bytes = OPCODE_TRANSMIT) -> bytes:
    """Wrap a Core Interface packet in a Serial Interface message."""
    return PREFIX + opcode + core_packet.hex().upper().encode("ascii") + POSTFIX


def upgrade() -> bytes:
    """Put the recorder into bootloader mode. No data field."""
    return PREFIX + OPCODE_UPGRADE + POSTFIX


def reboot() -> bytes:
    """Hard-reset the recorder. No data field."""
    return PREFIX + OPCODE_REBOOT + POSTFIX


def unframe(message: bytes) -> tuple[bytes, bytes]:
    """Return (opcode, Core Interface packet) from a Serial Interface message."""
    msg = message.strip()
    if not msg.startswith(PREFIX):
        raise ValueError("message does not start with '$'")
    opcode = msg[1:2]
    body = msg[2:]
    if len(body) % 2:
        raise ValueError("hex payload has an odd number of characters")
    return opcode, bytes.fromhex(body.decode("ascii"))


def find_port() -> str | None:
    """Return the serial port of the first recorder found, or None.

    Requires pyserial.
    """
    from serial.tools import list_ports

    for port in list_ports.comports():
        if port.vid == core.USB_VID and port.pid == core.USB_PID:
            return port.device
        if port.product and "pcardio" in port.product.lower():
            return port.device
    return None


class SerialSession:
    """Minimal request/response helper over the Serial Interface.

    Requires pyserial. The recorder handles one operation at a time, so wait
    for each reply before sending the next request.

        with SerialSession() as s:
            s.unlock()
            print(s.read(core.ADDR_BATTERY, 4)[0], "%")
    """

    def __init__(self, port: str | None = None, timeout: float = 2.0):
        import serial

        port = port or find_port()
        if port is None:
            raise RuntimeError("no PCARDIO recorder found on any serial port")
        self.port = serial.Serial(
            port,
            baudrate=core.SERIAL_BAUDRATE,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
            dsrdtr=True,
        )
        self.port.dtr = True

    def __enter__(self) -> "SerialSession":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self.port.close()

    def _request(self, core_packet: bytes) -> bytes:
        self.port.write(frame(core_packet))
        self.port.flush()
        line = self.port.readline()
        if not line:
            raise TimeoutError("no reply from recorder")
        opcode, reply = unframe(line)
        if opcode != OPCODE_RECEIVE:
            raise ValueError(f"unexpected serial opcode {opcode!r}")
        return reply

    def read(self, address: int, length: int) -> bytes:
        """Read `length` bytes from `address`."""
        parsed = core.parse_packet(self._request(core.read_packet(address, length)))
        return parsed.data[:length]

    def write(self, address: int, data: bytes) -> None:
        """Write `data` to `address`."""
        self.port.write(frame(core.data_packet(address, data)))
        self.port.flush()

    def unlock(self) -> None:
        """Write the PIN so the protected registers become accessible."""
        self.write(core.ADDR_PIN, core.PIN_VALUE)

    def read_u32(self, address: int) -> int:
        return int.from_bytes(self.read(address, 4), "little")

    def battery_percent(self) -> int:
        return self.read_u32(core.ADDR_BATTERY)

    def device_status(self) -> core.DeviceStatus:
        return core.decode_device_status(self.read_u32(core.ADDR_DEVICE_STATUS))

    def firmware_version(self) -> str:
        return core.decode_version(self.read(core.ADDR_VERSION, 4))

    def last_input_error(self) -> str:
        code = self.read_u32(core.ADDR_INPUT_ERROR_CODE)
        return core.INPUT_ERRORS.get(code, f"unknown error {code}")

    def sampling_config(self) -> list[core.SensorConfig]:
        return core.decode_sampling_config(
            self.read(core.ADDR_SAMPLING_CONFIG, core.SAMPLING_CONFIG_SIZE))


if __name__ == "__main__":
    port = find_port()
    print(f"recorder found on {port}" if port else "no recorder found")
