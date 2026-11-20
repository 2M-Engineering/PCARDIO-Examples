# PCARDIO Python examples

Reference implementations of parts of the [PCARDIO Interface](../PCARDIO-Interface-v8.pdf) document (v8). They are examples rather than a supported SDK, but they are complete enough to configure a recorder, stream from it and parse what it logs.

Firmware supported: v1.1.2 or higher.

| File | What it does |
| --- | --- |
| `pcardio_core.py` | Core Interface packets, the memory map, the sampling configuration register, the sensor and data type tables, CRC-16-CCITT, packet layout and digital-to-analog conversion. Pure Python, no dependencies, no I/O. |
| `pcardio_serial.py` | The Serial Interface ASCII framing (`$T`, `$R`, `$U`, `$B`) and a request/response session over USB. Needs `pyserial`. |
| `parse_data_file.py` | Decodes `config.txt` and converts a `data_*.txt` file from the recorder's mass storage into one CSV per signal. No dependencies. |
| `stream_ble_example.py` | Connects over wireless BLE through the Nordic UART Service and parses a live stream. Needs `bleak` and a recorder in range. |
| `test_pcardio_core.py` | Checks the implementation against the worked examples and tables in the interface document. No hardware needed. |

## Install

```bash
pip install pyserial bleak      # only for the two hardware examples
```

`pcardio_core.py` and `parse_data_file.py` need nothing beyond Python 3.10 or later.

## Use

Run the tests:

```bash
python test_pcardio_core.py
```

Convert a recording to CSV:

```bash
python parse_data_file.py data_20261023091500.txt --out-dir ./csv
```

Stream live over wireless BLE for 30 seconds:

```bash
python stream_ble_example.py --seconds 30
```

Build a measurement configuration and the packets that apply it:

```python
import pcardio_core as core

configs = [
    core.SensorConfig(sensor_id=1,  gain_id=2, sample_rate_id=4, data_type_id=1),  # ECG 1ch, x3, 250 Hz
    core.SensorConfig(sensor_id=2,  gain_id=2, sample_rate_id=4, data_type_id=2),  # respiration BioZ
    core.SensorConfig(sensor_id=5,  gain_id=0, sample_rate_id=7, data_type_id=4),  # accelerometer, 50 Hz
    core.SensorConfig(sensor_id=10, gain_id=0, sample_rate_id=10, data_type_id=8), # button marker
]

packets = [
    core.unlock_packet(),                    # the PIN must come first
    core.set_time_packet(1763600000),        # keep the recorder clock accurate
    core.sampling_config_packet(configs),    # idle mode only
]

size, offsets = core.packet_layout(configs)
print(size, "bytes per data packet, sensor data starts at", offsets)
```

`SensorConfig.validate()` rejects any gain, sample rate or data type that table 29 does not list for that sensor, so a configuration can be checked before it reaches the recorder.

## Order of operations

The recorder handles one operation at a time. Wait for each reply before sending the next request, and do not read or write while a stream is running: send an abort packet, do the read or write, then restart the stream.

1. Write the PIN. The time, button, advertising and all measurement registers stay inaccessible until it has been written.
2. Read the time register and correct it if it differs from the host clock by more than a second. This matters most for scheduled measurements.
3. Write the measurement configuration, either through these registers or by editing `config.txt` over mass storage. The measurement registers accept writes in idle mode only; attempting them while the recorder is logging returns input error 5, invalid state.
4. Read the battery level and the data file size periodically. The recorder stops responding in low power mode until it has charged, and will not start or continue a recording with no storage left.
5. After downloading, delete the data and log files and leave only `config.txt` on the recorder. `config.txt` must always be present: without it the recorder enters an error state until the file is restored.

## Implementation notes

A few places in v8 of the interface document are ambiguous or state two different things. The choices made here, and why:

**Data packet header length.** Section 7.1's pseudocode starts with `packet_size = 9`, but tables 20 and 21 define a 13-byte header, and the worked example in the same section adds up to 75 bytes only with a 13-byte header: 13 + (10 accelerometer samples x 6 bytes) + 1 + 1. Table 33 also places the first accelerometer sample at byte 13. `HEADER_SIZE` is therefore 13, and `packet_layout()` starts from 13 rather than 9.

**Gain in the section 7.1 example.** The text says the accelerometer uses "a gain of 3", while table 29 lists gain ids 0, 1, 3 and 5 for the accelerometer, which are the multipliers x1, x2, x4 and x8 — the multiplier x3 is gain id 2, which that sensor does not accept. Table 32 then shows a gain byte of 0x02 for the accelerometer and 0x01 for the button marker and the battery, although table 29 allows those two sensors gain id 0 only. The gain column of table 32 cannot be read as a gain id consistently. These examples follow table 29, the capability table, and `validate()` enforces it.

**Status field bit widths.** Table 22 lists the data packet status field as logging on bit 0, streaming on bit 1, BLE status on bit 2 and battery status on bit 3. The accompanying tables 23 and 24 give BLE status the values 0 to 2 and battery status the values 0 to 3, which need two bits each. `PacketHeader` therefore reads BLE status from bits 2 to 3 and battery status from bits 4 to 5. The device status register in table 14 is unambiguous and is read as four single bits.

**Abort opcode.** Read, data and stream packets use opcodes 0x01, 0x02 and 0x04. Section 3.3 describes the abort packet as a single byte but does not give its value; `OPCODE_ABORT` is set to 0x03 by elimination. Confirm it against your firmware before relying on it.

**Cross references.** Section 5.1.6 points to section 8 for input errors, which are in section 9. Section 5.3.4 points to section 5 for the sampling configuration structure, which is in section 7. Section 8.2 points to section 5 for data packet parsing, which is in section 6.

## Links

- [PCARDIO Interface document, HTML](../docs/index.html)
- [Developers API](https://pcardiowearables.com/support/developers-api/)
- [Integration guide](https://pcardiowearables.com/support/integration-guide/)
- [Real-time biosignal streaming](https://pcardiowearables.com/real-time-biosignal-streaming/)
- [Support and documentation](https://pcardiowearables.com/support/documentation/)
