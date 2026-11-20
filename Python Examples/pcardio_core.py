"""PCARDIO Core Interface - packet building, parsing and sampling configuration.

Reference implementation of the Core Interface described in the PCARDIO
Interface document (v8, 2026-10-23). Pure Python, no dependencies, no I/O:
build the bytes here and send them over whichever transport you use
(wireless BLE Nordic UART Service, or the serial interface in
pcardio_serial.py).

Firmware supported: v1.1.2 or higher.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import NamedTuple

# --------------------------------------------------------------------------
# Core Interface opcodes
# --------------------------------------------------------------------------

OPCODE_READ = 0x01
OPCODE_DATA = 0x02
OPCODE_ABORT = 0x03  # Not stated in the document; see README.md
OPCODE_STREAM = 0x04

# --------------------------------------------------------------------------
# Memory map (Interface document, table 12)
# --------------------------------------------------------------------------

# Info memory - read only
ADDR_ID = 0
ADDR_ADDRESS = 8
ADDR_VERSION = 16
ADDR_FREE_SPACE = 20
ADDR_FILE_SIZE = 24
ADDR_BATTERY = 28
ADDR_DEVICE_STATUS = 32
ADDR_INPUT_ERROR_CODE = 36
ADDR_INPUT_ERROR_TIMESTAMP = 40
ADDR_HARDWARE_VERSION = 44
ADDR_HARDWARE_VARIANT = 45

# Device configuration memory - read/write
ADDR_PIN = 128
ADDR_TIME = 132
ADDR_BUTTON_MODE = 136
ADDR_ADVERTISING_MODE = 140
ADDR_ADVERTISING_TIME = 144

# Measurement configuration memory - read/write, idle only
ADDR_USER_ID = 256
ADDR_START_TIME = 268
ADDR_STOP_TIME = 272
ADDR_SAMPLING_CONFIG = 276

# Stream memory - read only
ADDR_STREAM_DATA = 268435456
STREAM_MAX_SIZE = 16384

SAMPLING_CONFIG_SIZE = 68
USER_ID_SIZE = 12

#: Unlocks the protected registers. Must be written before reading or
#: writing time, button mode, advertising, or any measurement register.
PIN_VALUE = bytes((0x6C, 0x6F, 0x76, 0x65))

#: BLE Nordic UART Service, used by the Core Interface over wireless BLE.
BLE_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
BLE_RX_CHARACTERISTIC_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  # write
BLE_TX_CHARACTERISTIC_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  # notify
BLE_DEVICE_NAME = "PCardio"  # as advertised by the recorder firmware

# USB serial identification
USB_VID = 0x16D0
USB_PID = 0x06A1
SERIAL_BAUDRATE = 460800

# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------

BUTTON_MODES = {0: "no action", 1: "start logging", 2: "start and stop logging"}

ADVERTISING_MODES = {
    0: "BLE disabled",
    1: "advertise after USB disconnection",
    2: "advertise after USB disconnection or button press",
    3: "advertise always",
}
ADVERTISING_TIME_MAX_S = 180

HARDWARE_VERSIONS = {0: "V2.1", 1: "V2.2", 7: "V1.X"}
HARDWARE_VARIANTS = {0: "EMG", 1: "1 lead + respiration", 2: "6 leads"}

INPUT_ERRORS = {
    0: "no error",
    1: "read-only error",
    2: "invalid address",
    3: "invalid length",
    4: "invalid data",
    5: "invalid state",
}

#: Gain ID -> multiplier (table 27)
GAINS = {0: 1, 1: 2, 2: 3, 3: 4, 4: 6, 5: 8, 6: 12, 7: 16}

#: Sample rate ID -> Hz (table 28)
SAMPLE_RATES = {
    0: 1000, 1: 800, 2: 500, 3: 400, 4: 250,
    5: 200, 6: 100, 7: 50, 8: 25, 9: 10, 10: 5,
}

#: The recorder emits 5 data packets per second.
PACKETS_PER_SECOND = 5

#: Data packet header length in bytes (table 21).
HEADER_SIZE = 13


class DataType(NamedTuple):
    """A data type definition from table 30 / table 38."""

    units: str
    total_size: int   # bytes per sample, all elements together
    elements: int
    signed: bool
    analog_min: float
    analog_max: float
    digital_min: int
    digital_max: int

    @property
    def element_size(self) -> int:
        return self.total_size // self.elements


#: Data type ID -> definition. IDs 9-19 are experimental (table 38).
DATA_TYPES: dict[int, DataType] = {
    0: DataType("%", 1, 1, False, 0, 100, 0, 100),
    1: DataType("mV", 3, 1, True, -2420, 2420, -8388608, 8388607),
    2: DataType("ohm", 3, 1, True, -80666.67, 80666.67, -262144, 262143),
    3: DataType("mV", 6, 2, True, -2420, 2420, -8388608, 8388607),
    4: DataType("G", 6, 3, True, -16, 16, -32768, 32767),
    5: DataType("deg/s", 6, 3, True, -2000, 2000, -28571, 28570),
    6: DataType("rad/s", 6, 3, True, -34.906585, 34.906585, -28571, 28570),
    7: DataType("gauss", 6, 3, True, -49.125, 49.125, -32768, 32767),
    8: DataType("unitless", 1, 1, False, 0, 1, 0, 1),
    # Experimental - special firmware and recorder holders only
    9: DataType("degC", 2, 1, True, -256, 256, -32768, 32767),
    10: DataType("ADC counts", 6, 2, False, 0, 16777215, 0, 16777215),
    11: DataType("ADC counts", 3, 1, True, -524288, 524287, -524288, 524287),
    14: DataType("bpm", 2, 1, False, 0, 300, 0, 30000),
    15: DataType("brpm", 2, 1, False, 0, 300, 0, 30000),
    16: DataType("ms", 2, 1, False, 0, 6553.5, 0, 65535),
    17: DataType("hPa", 3, 1, True, -4096, 4096, -8388608, 8388607),
    18: DataType("%", 2, 1, False, 0, 100, 0, 10000),
    19: DataType("unitless", 2, 1, False, 0, 1, 0, 65535),
}


class Sensor(NamedTuple):
    name: str
    gain_ids: tuple[int, ...]
    sample_rate_ids: tuple[int, ...]
    data_type_ids: tuple[int, ...]
    experimental: bool = False


#: Sensor ID -> definition (table 29 and table 37).
SENSORS: dict[int, Sensor] = {
    0: Sensor("battery", (0,), (10,), (0,)),
    1: Sensor("ecg_1ch", (0, 1, 2, 4, 6), (0, 2, 4), (1,)),
    2: Sensor("respiration_bioz", (0, 1, 2, 4, 6), (0, 2, 4), (2,)),
    3: Sensor("ecg_2ch", (0, 1, 2, 4, 6), (0, 2, 4), (3,)),
    4: Sensor("emg_2ch", (0, 1, 2, 4, 6), (0, 2, 4), (3,)),
    5: Sensor("accelerometer", (0, 1, 3, 5), (1, 3, 5, 6, 7), (4,)),
    6: Sensor("gyroscope", (0, 1, 3, 5, 7), (1, 3, 5, 6, 7), (5, 6)),
    7: Sensor("magnetometer", (0,), (6, 7), (7,)),
    10: Sensor("button_marker", (0,), (10,), (8,)),
    11: Sensor("tap_marker", (0,), (10,), (8,)),
    12: Sensor("lead_off", (0,), (10,), (8,)),
    # Experimental
    13: Sensor("ppg", (0,), (3, 5, 6, 7), (10,), True),
    14: Sensor("temperature", (0,), (10,), (9,), True),
    15: Sensor("icg", (0,), (0, 1, 2, 3, 4, 5, 6), (11,), True),
    16: Sensor("heart_rate", (0,), (10,), (14,), True),
    17: Sensor("respiration_rate", (0,), (10,), (15,), True),
    18: Sensor("heart_rate_variability", (0,), (10,), (16,), True),
    19: Sensor("barometer", (0, 1), (10,), (17,), True),
    20: Sensor("spo2", (0,), (10,), (18,), True),
    21: Sensor("microphone", (0,), (0,), (19,), True),
}

# --------------------------------------------------------------------------
# Core Interface packets
# --------------------------------------------------------------------------


def read_packet(address: int, length: int) -> bytes:
    """Request `length` bytes starting at `address`."""
    return struct.pack("<BIH", OPCODE_READ, address, length)


def data_packet(address: int, data: bytes) -> bytes:
    """Write `data` to `address`."""
    return struct.pack("<BIH", OPCODE_DATA, address, len(data)) + bytes(data)


def abort_packet() -> bytes:
    """Stop an ongoing stream. Single byte, no address or length."""
    return bytes((OPCODE_ABORT,))


def stream_packet(length: int = STREAM_MAX_SIZE,
                  address: int = ADDR_STREAM_DATA) -> bytes:
    """Start continuous streaming of `length` bytes from the stream memory."""
    return struct.pack("<BIH", OPCODE_STREAM, address, length)


def unlock_packet() -> bytes:
    """Write the PIN so the protected registers become accessible."""
    return data_packet(ADDR_PIN, PIN_VALUE)


def set_time_packet(unix_seconds: int) -> bytes:
    """Set the recorder clock. Requires the PIN to have been written."""
    return data_packet(ADDR_TIME, struct.pack("<I", unix_seconds))


def set_schedule_packet(start_unix: int, stop_unix: int) -> bytes:
    """Schedule a measurement. Idle mode only, PIN required."""
    return data_packet(ADDR_START_TIME, struct.pack("<II", start_unix, stop_unix))


def set_user_id_packet(user_id: bytes) -> bytes:
    """Write the 12-byte user id field.

    The recorder stores this value as given. It is not encrypted, so do not
    write names or other identifying information in plain text.
    """
    if len(user_id) > USER_ID_SIZE:
        raise ValueError(f"user id must be at most {USER_ID_SIZE} bytes")
    return data_packet(ADDR_USER_ID, user_id.ljust(USER_ID_SIZE, b"\x00"))


@dataclass(frozen=True)
class ParsedPacket:
    opcode: int
    address: int | None
    length: int | None
    data: bytes


def parse_packet(raw: bytes) -> ParsedPacket:
    """Parse a Core Interface packet received from the recorder.

    Large messages may arrive split over several transport packets.
    Concatenate the fragments before calling this.
    """
    if not raw:
        raise ValueError("empty packet")
    opcode = raw[0]
    if opcode == OPCODE_ABORT:
        return ParsedPacket(opcode, None, None, b"")
    if len(raw) < 7:
        raise ValueError(f"packet too short for opcode 0x{opcode:02X}: {len(raw)} bytes")
    address, length = struct.unpack_from("<IH", raw, 1)
    return ParsedPacket(opcode, address, length, raw[7:])


# --------------------------------------------------------------------------
# Info memory decoding
# --------------------------------------------------------------------------


def decode_version(raw: bytes) -> str:
    """Decode the 4-byte version register as major.minor.revision (interface N)."""
    major, minor, revision, interface = raw[:4]
    return f"{major}.{minor}.{revision} (interface {interface})"


@dataclass(frozen=True)
class DeviceStatus:
    logging: bool
    streaming: bool
    docking: bool
    lead_off: bool


def decode_device_status(value: int) -> DeviceStatus:
    """Decode the device status register (table 14)."""
    return DeviceStatus(
        logging=bool(value & 0x01),
        streaming=bool(value & 0x02),
        docking=bool(value & 0x04),
        lead_off=bool(value & 0x08),
    )


# --------------------------------------------------------------------------
# Sampling configuration
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SensorConfig:
    """One entry of the sampling configuration register (table 26)."""

    sensor_id: int
    gain_id: int = 0
    sample_rate_id: int = 10
    data_type_id: int = 0

    @property
    def sensor(self) -> Sensor | None:
        return SENSORS.get(self.sensor_id)

    @property
    def data_type(self) -> DataType:
        return DATA_TYPES[self.data_type_id]

    @property
    def gain(self) -> int:
        return GAINS[self.gain_id]

    @property
    def sample_rate_hz(self) -> int:
        return SAMPLE_RATES[self.sample_rate_id]

    @property
    def samples_per_packet(self) -> int:
        return self.sample_rate_hz // PACKETS_PER_SECOND

    @property
    def bytes_per_packet(self) -> int:
        return self.data_type.total_size * self.samples_per_packet

    def validate(self) -> None:
        """Raise ValueError if this combination is not listed in the document."""
        sensor = self.sensor
        if sensor is None:
            raise ValueError(f"unknown sensor id {self.sensor_id}")
        if self.gain_id not in sensor.gain_ids:
            raise ValueError(
                f"{sensor.name}: gain id {self.gain_id} not valid, "
                f"allowed {sensor.gain_ids}")
        if self.sample_rate_id not in sensor.sample_rate_ids:
            raise ValueError(
                f"{sensor.name}: sample rate id {self.sample_rate_id} not valid, "
                f"allowed {sensor.sample_rate_ids}")
        if self.data_type_id not in sensor.data_type_ids:
            raise ValueError(
                f"{sensor.name}: data type id {self.data_type_id} not valid, "
                f"allowed {sensor.data_type_ids}")

    def to_bytes(self) -> bytes:
        return bytes((self.sensor_id, self.gain_id,
                      self.sample_rate_id, self.data_type_id))

    def scale(self, digital: int) -> float:
        """Convert a raw digital sample to its physical value."""
        return digital_to_analog(digital, self.data_type, self.gain)


MAX_SENSORS = 16


def encode_sampling_config(configs: list[SensorConfig],
                           validate: bool = True) -> bytes:
    """Build the 68-byte sampling configuration register (table 25).

    The order of the entries determines the order of the sensor data blocks
    inside every data packet.
    """
    if len(configs) > MAX_SENSORS:
        raise ValueError(f"at most {MAX_SENSORS} sensors can be enabled")
    if validate:
        for cfg in configs:
            cfg.validate()
    out = bytearray(struct.pack("<I", len(configs)))
    for cfg in configs:
        out += cfg.to_bytes()
    out += bytes(SAMPLING_CONFIG_SIZE - len(out))
    return bytes(out)


def decode_sampling_config(raw: bytes) -> list[SensorConfig]:
    """Read back the sampling configuration register."""
    if len(raw) < 4:
        raise ValueError("sampling configuration too short")
    (count,) = struct.unpack_from("<I", raw, 0)
    if count > MAX_SENSORS:
        raise ValueError(f"implausible sensor count {count}")
    configs = []
    for i in range(count):
        off = 4 + i * 4
        configs.append(SensorConfig(*raw[off:off + 4]))
    return configs


def sampling_config_packet(configs: list[SensorConfig]) -> bytes:
    """Core Interface write of a full sampling configuration. Idle mode only."""
    return data_packet(ADDR_SAMPLING_CONFIG, encode_sampling_config(configs))


# --------------------------------------------------------------------------
# Data packets
# --------------------------------------------------------------------------


def packet_layout(configs: list[SensorConfig]) -> tuple[int, list[int]]:
    """Return (packet_size, start_offset_per_sensor) for a configuration.

    Follows the pseudocode in section 7.1, with the header length taken as
    13 bytes, which is what the worked example in that section adds up to.
    """
    size = HEADER_SIZE
    starts = []
    for cfg in configs:
        starts.append(size)
        size += cfg.bytes_per_packet
    return size, starts


def crc16_ccitt(data: bytes, init: int = 0xFFFF) -> int:
    """CRC-16-CCITT, polynomial 0x1021, initial value 0xFFFF."""
    crc = init
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


BLE_STATUS = {0: "off", 1: "advertising", 2: "connected"}
BATTERY_STATUS = {0: "0-25%", 1: "25-50%", 2: "50-75%", 3: "75-100%"}


@dataclass(frozen=True)
class PacketHeader:
    """The 13-byte data packet header (table 21)."""

    time: int           # unix seconds of the last sample in the buffer
    ticks: int          # elapsed 32.768 kHz ticks to add to `time`
    status: int
    payload_size: int
    checksum: int

    TICKS_PER_SECOND = 32768

    @property
    def timestamp(self) -> float:
        return self.time + self.ticks / self.TICKS_PER_SECOND

    @property
    def ticks_100ns(self) -> int:
        """Ticks expressed in 100 ns intervals, as described in section 6.1.2."""
        return self.ticks * 10_000_000 // self.TICKS_PER_SECOND

    @property
    def logging(self) -> bool:
        return bool(self.status & 0x01)

    @property
    def streaming(self) -> bool:
        return bool(self.status & 0x02)

    @property
    def ble_status(self) -> str:
        return BLE_STATUS.get((self.status >> 2) & 0x03, "unknown")

    @property
    def battery_status(self) -> str:
        return BATTERY_STATUS.get((self.status >> 4) & 0x03, "unknown")


def parse_header(raw: bytes) -> PacketHeader:
    if len(raw) < HEADER_SIZE:
        raise ValueError(f"header needs {HEADER_SIZE} bytes, got {len(raw)}")
    time, ticks, status, payload_size, checksum = struct.unpack_from("<IIBHH", raw, 0)
    return PacketHeader(time, ticks, status, payload_size, checksum)


def _decode_samples(block: bytes, dt: DataType, gain: int) -> list[tuple[float, ...]]:
    """Decode one sensor's byte block into scaled tuples, one per sample."""
    out = []
    esize = dt.element_size
    for off in range(0, len(block) - dt.total_size + 1, dt.total_size):
        sample = []
        for e in range(dt.elements):
            raw = block[off + e * esize: off + (e + 1) * esize]
            digital = int.from_bytes(raw, "little", signed=dt.signed)
            sample.append(digital_to_analog(digital, dt, gain))
        out.append(tuple(sample))
    return out


def digital_to_analog(digital: int, dt: DataType, gain: int = 1) -> float:
    """Convert a digital sample to its physical value (section 7.1 formula).

        value_A = ((max_A - min_A) / (max_D - min_D) * (value_D - max_D) + max_A) / gain
    """
    span_a = dt.analog_max - dt.analog_min
    span_d = dt.digital_max - dt.digital_min
    return (span_a / span_d * (digital - dt.digital_max) + dt.analog_max) / gain


def parse_data_packet(raw: bytes, configs: list[SensorConfig],
                      verify_checksum: bool = True
                      ) -> tuple[PacketHeader, dict[str, list[tuple[float, ...]]]]:
    """Parse one data packet into a header and scaled samples per sensor.

    `configs` must be the sampling configuration the packet was produced
    with: the payload carries no sensor identification of its own.
    """
    header = parse_header(raw)
    size, starts = packet_layout(configs)
    if len(raw) < size:
        raise ValueError(f"packet needs {size} bytes for this configuration, got {len(raw)}")
    payload = raw[HEADER_SIZE:size]
    if verify_checksum:
        actual = crc16_ccitt(payload)
        if actual != header.checksum:
            raise ValueError(
                f"checksum mismatch: header 0x{header.checksum:04X}, computed 0x{actual:04X}")
    signals: dict[str, list[tuple[float, ...]]] = {}
    for cfg, start in zip(configs, starts):
        sensor = cfg.sensor
        name = sensor.name if sensor else f"sensor_{cfg.sensor_id}"
        block = raw[start:start + cfg.bytes_per_packet]
        signals[name] = _decode_samples(block, cfg.data_type, cfg.gain)
    return header, signals
