"""Verify the Core Interface implementation against the interface document.

Every expected value below is taken from a table or worked example in the
PCARDIO Interface document v8 (2026-10-23). No hardware needed.

    python -m pytest "Python Examples/test_pcardio_core.py" -q
    python "Python Examples/test_pcardio_core.py"
"""

from __future__ import annotations

import struct

import pcardio_core as core
import pcardio_serial as serial_if
from parse_data_file import (CONFIG_FILE_SIZE, RecorderConfig, build_config,
                             parse_config)


def test_read_packet_matches_table_4():
    # Table 4: read 4 bytes from address 16
    assert core.read_packet(16, 4) == bytes(
        (0x01, 0x10, 0x00, 0x00, 0x00, 0x04, 0x00))


def test_data_packet_matches_table_5():
    # Table 5: write 1 to the 32-bit register at address 16
    assert core.data_packet(16, struct.pack("<I", 1)) == bytes(
        (0x02, 0x10, 0x00, 0x00, 0x00, 0x04, 0x00, 0x01, 0x00, 0x00, 0x00))


def test_stream_packet_matches_table_6():
    # Table 6: request 237 bytes from the stream memory
    assert core.stream_packet(237) == bytes(
        (0x04, 0x00, 0x00, 0x00, 0x10, 0xED, 0x00))


def test_stream_address_is_little_endian():
    assert core.ADDR_STREAM_DATA == 0x10000000


def test_pin_value_matches_table_17():
    assert core.PIN_VALUE == bytes((0x6C, 0x6F, 0x76, 0x65))
    assert core.unlock_packet() == core.data_packet(core.ADDR_PIN, core.PIN_VALUE)


def test_abort_is_single_byte():
    assert len(core.abort_packet()) == 1


def test_packet_round_trip():
    original = core.data_packet(core.ADDR_TIME, struct.pack("<I", 1763600000))
    parsed = core.parse_packet(original)
    assert parsed.opcode == core.OPCODE_DATA
    assert parsed.address == core.ADDR_TIME
    assert parsed.length == 4
    assert struct.unpack("<I", parsed.data)[0] == 1763600000


# --------------------------------------------------------------------------
# Sampling configuration, section 7.1 worked example
# --------------------------------------------------------------------------

# "accelerometer, button marker and battery level, in that order"
#   accelerometer: 50 Hz (rate id 7), Gs (type 4)
#   button marker: 5 Hz  (rate id 10), unitless (type 8)
#   battery:       5 Hz  (rate id 10), percentage (type 0)
#
# Gain is the one field of this example that the document states
# inconsistently - see "Gain in the section 7.1 example" in README.md. The
# gains below follow table 29, which is the capability table: the
# accelerometer accepts gain ids 0, 1, 3 and 5, and the button marker and
# battery accept gain id 0 only.
EXAMPLE_CONFIG = [
    core.SensorConfig(sensor_id=5, gain_id=3, sample_rate_id=7, data_type_id=4),
    core.SensorConfig(sensor_id=10, gain_id=0, sample_rate_id=10, data_type_id=8),
    core.SensorConfig(sensor_id=0, gain_id=0, sample_rate_id=10, data_type_id=0),
]


def test_example_config_is_valid():
    for cfg in EXAMPLE_CONFIG:
        cfg.validate()


def test_entries_match_table_32_except_gain():
    # Table 32 sensor entries: id, gain, sample rate id, data type id
    #   sensor 0  0x05  (0x02)  0x07  0x04
    #   sensor 1  0x0A  (0x01)  0x0A  0x08
    #   sensor 2  0x00  (0x01)  0x0A  0x00
    expected = [(0x05, 0x07, 0x04), (0x0A, 0x0A, 0x08), (0x00, 0x0A, 0x00)]
    for cfg, (sensor_id, rate_id, type_id) in zip(EXAMPLE_CONFIG, expected):
        raw = cfg.to_bytes()
        assert (raw[0], raw[2], raw[3]) == (sensor_id, rate_id, type_id)


def test_every_sensor_gain_id_exists_in_the_gain_table():
    # Catches the kind of mismatch that table 32 shows: a gain byte that is
    # not a valid gain id for that sensor.
    for sensor_id, sensor in core.SENSORS.items():
        for gain_id in sensor.gain_ids:
            assert gain_id in core.GAINS, f"sensor {sensor_id} gain id {gain_id}"
        for rate_id in sensor.sample_rate_ids:
            assert rate_id in core.SAMPLE_RATES, f"sensor {sensor_id} rate id {rate_id}"
        for type_id in sensor.data_type_ids:
            assert type_id in core.DATA_TYPES, f"sensor {sensor_id} type id {type_id}"


def test_sampling_config_register_is_68_bytes():
    raw = core.encode_sampling_config(EXAMPLE_CONFIG)
    assert len(raw) == core.SAMPLING_CONFIG_SIZE == 68
    assert struct.unpack_from("<I", raw, 0)[0] == 3


def test_sampling_config_round_trip():
    raw = core.encode_sampling_config(EXAMPLE_CONFIG)
    assert core.decode_sampling_config(raw) == EXAMPLE_CONFIG


def test_packet_size_matches_table_33():
    # "This configuration will result in the following data packet, with a
    # length of 75 bytes" - 13 byte header + 10 accelerometer samples of
    # 6 bytes + 1 button marker byte + 1 battery byte.
    size, starts = core.packet_layout(EXAMPLE_CONFIG)
    assert size == 75
    assert starts == [13, 73, 74]
    assert EXAMPLE_CONFIG[0].samples_per_packet == 10
    assert EXAMPLE_CONFIG[0].bytes_per_packet == 60


def test_invalid_combinations_are_rejected():
    # Magnetometer only supports 100 Hz and 50 Hz (table 29)
    for bad in (
        core.SensorConfig(sensor_id=7, gain_id=0, sample_rate_id=0, data_type_id=7),
        core.SensorConfig(sensor_id=1, gain_id=7, sample_rate_id=0, data_type_id=1),
        core.SensorConfig(sensor_id=1, gain_id=0, sample_rate_id=0, data_type_id=4),
        core.SensorConfig(sensor_id=99),
    ):
        try:
            bad.validate()
        except ValueError:
            continue
        raise AssertionError(f"should have been rejected: {bad}")


def test_at_most_16_sensors():
    try:
        core.encode_sampling_config([core.SensorConfig(0, 0, 10, 0)] * 17)
    except ValueError:
        return
    raise AssertionError("17 sensors should be rejected")


# --------------------------------------------------------------------------
# Conversion and checksum
# --------------------------------------------------------------------------


def test_gain_8_narrows_accelerometer_range_to_2g():
    # "For a sensor gain of 8 and a default analog range of +/-16 the actual
    # range will be +/-2"
    dt = core.DATA_TYPES[4]
    assert core.digital_to_analog(dt.digital_max, dt, 8) == 2.0
    assert round(core.digital_to_analog(dt.digital_min, dt, 8), 6) == -2.0


def test_unity_gain_spans_full_analog_range():
    for type_id, dt in core.DATA_TYPES.items():
        assert round(core.digital_to_analog(dt.digital_max, dt, 1), 4) == round(
            dt.analog_max, 4), f"data type {type_id}"
        assert round(core.digital_to_analog(dt.digital_min, dt, 1), 4) == round(
            dt.analog_min, 4), f"data type {type_id}"


def test_data_type_sizes_are_consistent():
    for type_id, dt in core.DATA_TYPES.items():
        assert dt.total_size % dt.elements == 0, f"data type {type_id}"


def test_crc16_ccitt_reference_vector():
    # CRC-16/CCITT-FALSE: polynomial 0x1021, init 0xFFFF, check value 0x29B1
    assert core.crc16_ccitt(b"123456789") == 0x29B1


# --------------------------------------------------------------------------
# Header and data packet
# --------------------------------------------------------------------------


def _build_packet(configs, time=1763600000, ticks=16384, status=0b00_11_10_10):
    payload = bytearray()
    for cfg in configs:
        payload += bytes(cfg.bytes_per_packet)
    header = struct.pack("<IIBHH", time, ticks, status, len(payload),
                         core.crc16_ccitt(bytes(payload)))
    return header + bytes(payload)


def test_header_is_13_bytes():
    raw = _build_packet(EXAMPLE_CONFIG)
    assert len(raw) == 75
    header = core.parse_header(raw)
    assert header.time == 1763600000
    assert header.payload_size == 62
    assert round(header.timestamp - header.time, 3) == 0.5  # 16384 / 32768


def test_ticks_convert_to_100ns_intervals():
    header = core.parse_header(_build_packet(EXAMPLE_CONFIG, ticks=32768))
    assert header.ticks_100ns == 10_000_000


def test_data_packet_parses_and_verifies_checksum():
    raw = _build_packet(EXAMPLE_CONFIG)
    header, signals = core.parse_data_packet(raw, EXAMPLE_CONFIG)
    assert set(signals) == {"accelerometer", "button_marker", "battery"}
    assert len(signals["accelerometer"]) == 10
    assert len(signals["accelerometer"][0]) == 3
    assert len(signals["button_marker"]) == 1
    assert len(signals["battery"]) == 1
    assert header.payload_size == 62


def test_corrupted_payload_is_rejected():
    raw = bytearray(_build_packet(EXAMPLE_CONFIG))
    raw[20] ^= 0xFF
    try:
        core.parse_data_packet(bytes(raw), EXAMPLE_CONFIG)
    except ValueError as exc:
        assert "checksum" in str(exc)
        return
    raise AssertionError("corrupted packet should have been rejected")


def test_device_status_bits():
    status = core.decode_device_status(0b1011)
    assert (status.logging, status.streaming, status.docking, status.lead_off) == (
        True, True, False, True)


def test_version_decoding():
    assert core.decode_version(bytes((1, 1, 2, 8))) == "1.1.2 (interface 8)"


# --------------------------------------------------------------------------
# Serial interface framing
# --------------------------------------------------------------------------


def test_serial_frame_is_ascii_hex():
    framed = serial_if.frame(core.read_packet(16, 4))
    assert framed == b"$T01100000000400\n"


def test_serial_frame_round_trip():
    packet = core.data_packet(core.ADDR_TIME, struct.pack("<I", 1763600000))
    opcode, recovered = serial_if.unframe(serial_if.frame(packet))
    assert opcode == serial_if.OPCODE_TRANSMIT
    assert recovered == packet


def test_upgrade_and_reboot_packets_match_tables_10_and_11():
    assert serial_if.upgrade() == bytes((0x24, 0x55, 0x0A))
    assert serial_if.reboot() == bytes((0x24, 0x42, 0x0A))


# --------------------------------------------------------------------------
# Configuration file
# --------------------------------------------------------------------------


def test_config_file_round_trip():
    original = RecorderConfig(
        device_id=0x0123456789ABCDEF,
        ble_address=0xA1B2C3D4E5F6,
        firmware_version="1.1.2 (interface 8)",
        button_mode=2,
        advertising_mode=3,
        advertising_time_s=180,
        user_id=b"subject-01",
        start_time=1763600000,
        stop_time=1763686400,
        sensors=EXAMPLE_CONFIG,
    )
    raw = build_config(original)
    assert len(raw) == CONFIG_FILE_SIZE == 144
    assert raw[:8] == bytes((0x50, 0x43, 0x41, 0x52, 0x44, 0x49, 0x4F, 0x00))
    assert raw[140:144] == bytes((0x0D, 0x0A, 0x0D, 0x0A))

    back = parse_config(raw)
    assert back.device_id == original.device_id
    assert back.ble_address == original.ble_address
    assert back.button_mode == 2
    assert back.advertising_mode == 3
    assert back.advertising_time_s == 180
    assert back.user_id.rstrip(b"\x00") == b"subject-01"
    assert back.start_time == original.start_time
    assert back.stop_time == original.stop_time
    assert back.sensors == EXAMPLE_CONFIG


def test_config_file_rejects_bad_prefix():
    raw = bytearray(build_config(RecorderConfig(
        0, 0, "", 0, 0, 0, b"", 0, 0, EXAMPLE_CONFIG)))
    raw[0] = 0x00
    try:
        parse_config(bytes(raw))
    except ValueError:
        return
    raise AssertionError("bad prefix should have been rejected")


def test_sampling_config_sits_inside_the_144_byte_file():
    # config.txt offset 72 + 68 bytes of sampling configuration = 140, which
    # is exactly where the postfix starts.
    assert 72 + core.SAMPLING_CONFIG_SIZE == 140


def test_advertising_time_limit_documented():
    assert core.ADVERTISING_TIME_MAX_S == 180


if __name__ == "__main__":
    passed = failed = 0
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"FAIL {name}: {type(exc).__name__}: {exc}")
            else:
                passed += 1
                print(f"ok   {name}")
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
