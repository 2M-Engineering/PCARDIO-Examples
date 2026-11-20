# PCARDIO-Examples

This repository contains documentation, APIs and code examples to help you integrate the **PCARDIO wearable biosignal recorder platform** into your solution.

PCARDIO recorders capture ECG, bioimpedance (respiration), EMG and 9-DOF motion, with an expansion interface for additional biosignal sensors. They log to onboard memory, stream over wireless BLE, and can compute derived values on-device. Full product information is available at [pcardiowearables.com](https://pcardiowearables.com/).

## Interface Doc

The **PCARDIO Interface** document ([PCARDIO-Interface-v8.pdf](PCARDIO-Interface-v8.pdf)) provides a complete reference for integrating PCARDIO recorders into software applications through both wireless BLE and USB serial communication.
It describes the device communication protocols, the packet-based **Core and Serial interfaces**, the memory map structure, configuration registers, sampling configuration, and the mass storage file interface.

The guide also details how to configure sensors, gains, sample rates and data types, how to schedule and control a measurement, and how to parse the data packets streamed over wireless BLE or logged to the recorder's onboard memory, including the digital-to-analog conversion for every data type.
This document serves as the primary developer reference for accessing, configuring, streaming and downloading data from PCARDIO recorders.

The full reference is also published as HTML at [pcardiowearables.com/support/documentation/interface](https://pcardiowearables.com/support/documentation/interface/), covering the BLE service and characteristic UUIDs, the Core Interface packet types, the complete memory map, the sampling configuration register, the data packet layout, and the configuration, data and log file formats. The same page is mirrored in [docs/index.html](docs/index.html).

Firmware version supported: **v1.1.2 or higher**.

## Communication interfaces

A PCARDIO recorder can be reached three ways, and the document covers all of them:

- **Wireless BLE** — the recorder exposes the Nordic UART Service (NUS) with service UUID `6E400001-B5A3-F393-E0A9-E50E24DCCA9E`, an RX characteristic for writes and a TX characteristic for notifications. The Core Interface packets are carried over this link. The recorder uses the 2 Mbps PHY introduced in BLE 5.0, so a BLE 5.0 or higher central is recommended.
- **USB serial** — a micro-USB connection exposes the Serial Interface, which wraps Core Interface packets in ASCII-encoded messages and adds firmware upgrade and reboot commands. VID `16D0`, PID `06A1`, 460800 baud, no parity, one stop bit, DTR enabled.
- **USB mass storage** — through the docking station the recorder presents `config.txt`, `data_YYYYMMddHHmmss.txt` and `log.txt`, which allows configuration and data download without writing any protocol code.

## Python examples

The [Python Examples](Python%20Examples) folder demonstrates how to implement parts of the PCARDIO Interface:

- **pcardio_core.py** – Core Interface packet building and parsing, the memory map, the sampling configuration register, the data type table, CRC-16-CCITT validation, packet size calculation and digital-to-analog conversion.
- **pcardio_serial.py** – the Serial Interface ASCII framing (`$T`, `$R`, `$U`, `$B`) on top of the Core Interface.
- **parse_data_file.py** – reads a `data_*.txt` file from the recorder's mass storage and exports the enabled signals to CSV.
- **stream_ble_example.py** – streams live data over wireless BLE using the Nordic UART Service.
- **test_pcardio_core.py** – unit tests that verify the implementation against the worked examples in the interface document.

These are reference examples, not a supported SDK. They are intended to remove the need to implement the packet protocols from scratch.

## Platform capabilities

The PCARDIO platform currently supports:

- Simultaneous ECG, bioimpedance respiration and 9-DOF motion recording, with configurable sensors, gains, sample rates and data types per measurement
- 32 GB of onboard memory on all current recorder models
- Single-lead ECG recording at 250 Hz over 10 days, at 500 Hz over 8 days, and at 1 kHz over 5 days
- Live streaming over wireless BLE, raw or compressed, fully accessible through the interface described in this repository
- On-device computation of derived values, and scheduled measurements with a programmable start and stop time
- An expansion interface for additional biosignal sensors, including EDA/GSR, skin and ambient temperature, barometric pressure, sound exposure, heart and lung sounds, PPG/SpO2, multi-wavelength BIS bioimpedance for ICG, and universal strain

The 24-bit biopotential front end is shared between ECG and EMG, so a channel is configured as one or the other within a single measurement. The onboard bioimpedance channel is used for respiration; impedance cardiography and thoracic fluid content are measured with the external multi-wavelength BIS bioimpedance sensor on the expansion interface.

Sensor IDs 13 to 21 in the interface document (PPG, temperature, ICG, heart rate, respiration rate, heart rate variability, barometer, SpO2, microphone) are experimental and are available only with specific firmware and recorder holders.

## More about PCARDIO

- [Platform overview](https://pcardiowearables.com/)
- [ECG recorders and models](https://pcardiowearables.com/products-ecg-recorders/)
- [Developers API](https://pcardiowearables.com/support/developers-api/)
- [Integration guide](https://pcardiowearables.com/support/integration-guide/)
- [Real-time biosignal streaming](https://pcardiowearables.com/real-time-biosignal-streaming/)
- [Sensors and signals](https://pcardiowearables.com/wearable-biosignal-sensors/)
- [Derived cardiac parameters](https://pcardiowearables.com/derived-cardiac-parameters/)
- [Wearable medical device development platform](https://pcardiowearables.com/wearable-medical-device-development-platform/)
- [Quick start](https://pcardiowearables.com/support/quick-start/)
- [Interface reference (HTML)](https://pcardiowearables.com/support/documentation/interface/)
- [Support and documentation](https://pcardiowearables.com/support/documentation/)
- [Downloads](https://pcardiowearables.com/support/downloads/)

### Recorder models

| Model | Product page |
| --- | --- |
| HP201 — 1-lead ECG and respiration recorder | [1-lead wearable ECG recorder](https://pcardiowearables.com/product/1-lead-wearable-ecg-recorder/) |
| HP202 — 6-lead ECG and activity recorder | [6-lead wearable ECG monitor](https://pcardiowearables.com/product/6-lead-wearable-ecg-monitor-activity/) |
| HP208 — 12-lead ECG recorder (prototype) | [HP208 wearable 12-lead ECG recorder](https://pcardiowearables.com/product/hp208-wearable-12-lead-ecg-recorder/) |
| HP212 — wireless EMG system | [HP212 wireless EMG system](https://pcardiowearables.com/product/hp212-wireless-emg-system/) |
| HP215 — Motion Pro motion logger | [HP215 Motion Pro motion logger](https://pcardiowearables.com/product/hp215-motion-pro-motion-logger/) |
| HP262 — wireless BLE dongle | [HP262 wireless BLE dongle](https://pcardiowearables.com/product/hp262-wireless-ble-dongle/) |
| Evaluation kit | [PCARDIO Wearables evaluation kit](https://pcardiowearables.com/pcardio-wearables-evaluation-kit/) |

PCARDIO is a wearable biosignal recorder platform developed by [2M Engineering](https://www.2mel.nl) for medical research, sports science, occupational health and defence applications. It is also used as an OEM recorder platform inside third-party products.

HP201, HP202, HP212 and HP215 are CE marked and tested to IEC 60601-1 and EN 60601-1-2; they are not medical devices. IP67 applies to the recorder with the recorder holder. HP208 is a prototype and is not CE marked.

## Citing PCARDIO

If you use PCARDIO in published research, please cite it using the metadata in [CITATION.cff](CITATION.cff), or through the Cite this repository button on this repository page.

## License

The documentation and examples in this repository are released under the [MIT License](LICENSE).
