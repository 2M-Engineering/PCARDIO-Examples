"""Parse a PCARDIO data file from the recorder's mass storage into CSV.

Through the docking station the recorder appears as a USB mass storage
device holding config.txt, data_YYYYMMddHHmmss.txt and log.txt.

A data file starts with a 144-byte copy of config.txt, then the file start
and stop time, then back-to-back data packets:

    0    config.txt copy (144 bytes)
    144  file start time (uint32, unix seconds)
    148  file stop time  (uint32, unix seconds)
    152  data packets

The sampling configuration inside the file header is the one the packets
were recorded with, so the file is self-describing.

Usage:
    python parse_data_file.py data_20261023091500.txt
    python parse_data_file.py data_20261023091500.txt --out-dir ./csv
"""

from __future__ import annotations

import argparse
import csv
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pcardio_core as core

CONFIG_FILE_SIZE = 144
CONFIG_PREFIX = bytes((0x50, 0x43, 0x41, 0x52, 0x44, 0x49, 0x4F, 0x00))
CONFIG_POSTFIX = bytes((0x0D, 0x0A, 0x0D, 0x0A))

# Offsets inside config.txt (table 34)
CFG_ID = 8
CFG_BLE_ADDRESS = 16
CFG_VERSION = 24
CFG_BUTTON_MODE = 28
CFG_ADVERTISING_MODE = 32
CFG_ADVERTISING_TIME = 36
CFG_USER_ID = 52
CFG_START_TIME = 64
CFG_STOP_TIME = 68
CFG_SAMPLING_CONFIG = 72

DATA_FILE_START_TIME = 144
DATA_FILE_STOP_TIME = 148
DATA_FILE_PACKETS = 152


@dataclass(frozen=True)
class RecorderConfig:
    """The decoded contents of config.txt."""

    device_id: int
    ble_address: int
    firmware_version: str
    button_mode: int
    advertising_mode: int
    advertising_time_s: int
    user_id: bytes
    start_time: int
    stop_time: int
    sensors: list[core.SensorConfig]

    @property
    def qr_code(self) -> str:
        """The QR code on the back of the recorder: MAC address and id prefix."""
        return f"{self.ble_address:012X}-{self.device_id & 0xFFFF:04X}"

    def describe(self) -> str:
        lines = [
            f"device id          {self.device_id}",
            f"BLE address        {self.ble_address:012X}",
            f"firmware           {self.firmware_version}",
            f"button mode        {core.BUTTON_MODES.get(self.button_mode, self.button_mode)}",
            f"advertising        {core.ADVERTISING_MODES.get(self.advertising_mode, self.advertising_mode)}"
            f", {self.advertising_time_s} s",
            f"user id            {self.user_id.rstrip(chr(0).encode()).hex() or '(empty)'}",
            f"scheduled start    {_fmt_time(self.start_time)}",
            f"scheduled stop     {_fmt_time(self.stop_time)}",
            "sensors:",
        ]
        for cfg in self.sensors:
            sensor = cfg.sensor
            name = sensor.name if sensor else f"sensor_{cfg.sensor_id}"
            lines.append(
                f"  {name:<24} x{cfg.gain} @ {cfg.sample_rate_hz} Hz, "
                f"{cfg.data_type.units}, {cfg.bytes_per_packet} B/packet")
        return "\n".join(lines)


def _fmt_time(unix_seconds: int) -> str:
    if unix_seconds in (0, 0xFFFFFFFF):
        return "not set"
    return datetime.fromtimestamp(unix_seconds, timezone.utc).isoformat()


def parse_config(raw: bytes, strict: bool = True) -> RecorderConfig:
    """Decode a 144-byte config.txt image."""
    if len(raw) < CONFIG_FILE_SIZE:
        raise ValueError(f"config needs {CONFIG_FILE_SIZE} bytes, got {len(raw)}")
    if strict and raw[:8] != CONFIG_PREFIX:
        raise ValueError(f"unexpected prefix {raw[:8].hex()}, expected {CONFIG_PREFIX.hex()}")
    if strict and raw[140:144] != CONFIG_POSTFIX:
        raise ValueError(f"unexpected postfix {raw[140:144].hex()}")
    return RecorderConfig(
        device_id=int.from_bytes(raw[CFG_ID:CFG_ID + 8], "little"),
        ble_address=int.from_bytes(raw[CFG_BLE_ADDRESS:CFG_BLE_ADDRESS + 8], "little"),
        firmware_version=core.decode_version(raw[CFG_VERSION:CFG_VERSION + 4]),
        button_mode=int.from_bytes(raw[CFG_BUTTON_MODE:CFG_BUTTON_MODE + 4], "little"),
        advertising_mode=int.from_bytes(
            raw[CFG_ADVERTISING_MODE:CFG_ADVERTISING_MODE + 4], "little"),
        advertising_time_s=int.from_bytes(
            raw[CFG_ADVERTISING_TIME:CFG_ADVERTISING_TIME + 4], "little"),
        user_id=raw[CFG_USER_ID:CFG_USER_ID + core.USER_ID_SIZE],
        start_time=int.from_bytes(raw[CFG_START_TIME:CFG_START_TIME + 4], "little"),
        stop_time=int.from_bytes(raw[CFG_STOP_TIME:CFG_STOP_TIME + 4], "little"),
        sensors=core.decode_sampling_config(
            raw[CFG_SAMPLING_CONFIG:CFG_SAMPLING_CONFIG + core.SAMPLING_CONFIG_SIZE]),
    )


def build_config(config: RecorderConfig) -> bytes:
    """Build a 144-byte config.txt image.

    Writing config.txt onto the recorder has the same effect as writing the
    corresponding memory registers. The new configuration is read when the
    recorder leaves the docking station. The file must always be present: if
    it is missing the recorder enters an error state until it is restored.
    """
    raw = bytearray(CONFIG_FILE_SIZE)
    raw[0:8] = CONFIG_PREFIX
    raw[CFG_ID:CFG_ID + 8] = config.device_id.to_bytes(8, "little")
    raw[CFG_BLE_ADDRESS:CFG_BLE_ADDRESS + 8] = config.ble_address.to_bytes(8, "little")
    struct.pack_into("<I", raw, CFG_BUTTON_MODE, config.button_mode)
    struct.pack_into("<I", raw, CFG_ADVERTISING_MODE, config.advertising_mode)
    struct.pack_into("<I", raw, CFG_ADVERTISING_TIME, config.advertising_time_s)
    raw[CFG_USER_ID:CFG_USER_ID + core.USER_ID_SIZE] = config.user_id.ljust(
        core.USER_ID_SIZE, b"\x00")[:core.USER_ID_SIZE]
    struct.pack_into("<I", raw, CFG_START_TIME, config.start_time)
    struct.pack_into("<I", raw, CFG_STOP_TIME, config.stop_time)
    raw[CFG_SAMPLING_CONFIG:CFG_SAMPLING_CONFIG + core.SAMPLING_CONFIG_SIZE] = (
        core.encode_sampling_config(config.sensors, validate=False))
    raw[140:144] = CONFIG_POSTFIX
    return bytes(raw)


def read_data_file(path: Path, verify_checksum: bool = True):
    """Yield (header, signals) for every data packet in a recorder data file.

    The first item yielded is the decoded RecorderConfig, so:

        stream = read_data_file(path)
        config = next(stream)
        for header, signals in stream:
            ...
    """
    raw = path.read_bytes()
    config = parse_config(raw[:CONFIG_FILE_SIZE])
    yield config

    packet_size, _ = core.packet_layout(config.sensors)
    if packet_size <= core.HEADER_SIZE:
        raise ValueError("file header enables no sensors, nothing to parse")

    offset = DATA_FILE_PACKETS
    while offset + packet_size <= len(raw):
        chunk = raw[offset:offset + packet_size]
        yield core.parse_data_packet(chunk, config.sensors,
                                     verify_checksum=verify_checksum)
        offset += packet_size


def to_csv(path: Path, out_dir: Path, verify_checksum: bool = True) -> list[Path]:
    """Write one CSV per enabled sensor next to a summary of the file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stream = read_data_file(path, verify_checksum=verify_checksum)
    config = next(stream)

    print(config.describe())
    print()

    writers: dict[str, csv.writer] = {}
    handles = []
    written: dict[str, int] = {}
    paths: list[Path] = []
    packets = 0
    try:
        for cfg in config.sensors:
            sensor = cfg.sensor
            name = sensor.name if sensor else f"sensor_{cfg.sensor_id}"
            out_path = out_dir / f"{path.stem}_{name}.csv"
            handle = out_path.open("w", newline="")
            handles.append(handle)
            writer = csv.writer(handle)
            labels = (["x", "y", "z"][:cfg.data_type.elements]
                      if cfg.data_type.elements == 3
                      else ([f"ch{i + 1}" for i in range(cfg.data_type.elements)]
                            if cfg.data_type.elements > 1 else ["value"]))
            writer.writerow(["timestamp_s"] + [f"{c}_{cfg.data_type.units}" for c in labels])
            writers[name] = writer
            written[name] = 0
            paths.append(out_path)

        for header, signals in stream:
            packets += 1
            for name, samples in signals.items():
                cfg = next(c for c in config.sensors
                           if (c.sensor.name if c.sensor else f"sensor_{c.sensor_id}") == name)
                step = 1.0 / cfg.sample_rate_hz
                # The header timestamp is the last sample in the buffer.
                base = header.timestamp - (len(samples) - 1) * step
                for i, sample in enumerate(samples):
                    writers[name].writerow([f"{base + i * step:.6f}",
                                            *(f"{v:.6f}" for v in sample)])
                    written[name] += 1
    finally:
        for handle in handles:
            handle.close()

    print(f"{packets} packets parsed")
    for out_path in paths:
        name = out_path.stem.replace(f"{path.stem}_", "")
        print(f"  {out_path}  ({written.get(name, 0)} samples)")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", type=Path, help="data_YYYYMMddHHmmss.txt from the recorder")
    parser.add_argument("--out-dir", type=Path, default=Path("."),
                        help="where to write the CSV files (default: current directory)")
    parser.add_argument("--no-checksum", action="store_true",
                        help="do not verify the CRC-16-CCITT of each packet")
    args = parser.parse_args()
    to_csv(args.file, args.out_dir, verify_checksum=not args.no_checksum)


if __name__ == "__main__":
    main()
