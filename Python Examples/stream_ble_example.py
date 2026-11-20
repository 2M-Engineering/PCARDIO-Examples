"""Stream live data from a PCARDIO recorder over wireless BLE.

The recorder exposes the Nordic UART Service. Core Interface packets are
written to the RX characteristic and replies arrive as notifications on the
TX characteristic. This example:

  1. scans for a recorder and connects
  2. writes the PIN to unlock the protected registers
  3. reads the firmware version, battery level and sampling configuration
  4. requests a stream and parses the incoming data packets
  5. sends an abort packet on exit

Requires bleak (`pip install bleak`) and a recorder in range that is
advertising. A BLE 5.0 or higher central is recommended: the recorder uses
the 2 Mbps PHY, and a large ATT MTU together with Data Length Extension
keeps most Core Interface requests inside a single transaction.

Usage:
    python stream_ble_example.py
    python stream_ble_example.py --seconds 30
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib

import pcardio_core as core

try:
    from bleak import BleakClient, BleakScanner
except ImportError:  # pragma: no cover - hardware example
    raise SystemExit("this example needs bleak: pip install bleak")


class CoreLink:
    """Reassembles Core Interface messages arriving over BLE notifications.

    A message larger than the negotiated MTU is split over several
    notifications, so fragments are buffered until the declared length has
    arrived. The recorder handles one operation at a time.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._queue: asyncio.Queue[core.ParsedPacket] = asyncio.Queue()
        self.stream_packets: asyncio.Queue[bytes] = asyncio.Queue()
        self.streaming = False

    def feed(self, _sender, data: bytearray) -> None:
        self._buffer += data
        while True:
            if len(self._buffer) < 7:
                return
            length = int.from_bytes(self._buffer[5:7], "little")
            total = 7 + length
            if len(self._buffer) < total:
                return
            message = bytes(self._buffer[:total])
            del self._buffer[:total]
            parsed = core.parse_packet(message)
            if self.streaming and parsed.opcode == core.OPCODE_DATA:
                self.stream_packets.put_nowait(parsed.data)
            else:
                self._queue.put_nowait(parsed)

    async def reply(self, timeout: float = 5.0) -> core.ParsedPacket:
        return await asyncio.wait_for(self._queue.get(), timeout)


async def request(client: BleakClient, link: CoreLink, packet: bytes,
                  expect_reply: bool = True) -> bytes:
    await client.write_gatt_char(core.BLE_RX_CHARACTERISTIC_UUID, packet,
                                 response=False)
    if not expect_reply:
        return b""
    return (await link.reply()).data


async def run(seconds: float) -> None:
    print("scanning for a PCARDIO recorder...")
    device = await BleakScanner.find_device_by_filter(
        lambda d, ad: (d.name or "").lower().startswith("pcardio")
        or core.BLE_SERVICE_UUID.lower() in [u.lower() for u in ad.service_uuids],
        timeout=15.0,
    )
    if device is None:
        raise SystemExit("no recorder found - check that it is advertising")

    print(f"connecting to {device.name} [{device.address}]")
    link = CoreLink()
    async with BleakClient(device) as client:
        await client.start_notify(core.BLE_TX_CHARACTERISTIC_UUID, link.feed)

        # The PIN must be written before the protected registers can be used.
        await request(client, link, core.unlock_packet(), expect_reply=False)
        await asyncio.sleep(0.2)

        version = core.decode_version(
            await request(client, link, core.read_packet(core.ADDR_VERSION, 4)))
        battery = int.from_bytes(
            await request(client, link, core.read_packet(core.ADDR_BATTERY, 4)),
            "little")
        status = core.decode_device_status(int.from_bytes(
            await request(client, link, core.read_packet(core.ADDR_DEVICE_STATUS, 4)),
            "little"))
        raw_config = await request(
            client, link,
            core.read_packet(core.ADDR_SAMPLING_CONFIG, core.SAMPLING_CONFIG_SIZE))
        configs = core.decode_sampling_config(raw_config)

        print(f"firmware {version}, battery {battery}%, "
              f"logging={status.logging} docking={status.docking}")
        packet_size, _ = core.packet_layout(configs)
        print(f"{len(configs)} sensors enabled, {packet_size} bytes per packet:")
        for cfg in configs:
            sensor = cfg.sensor
            name = sensor.name if sensor else f"sensor_{cfg.sensor_id}"
            print(f"  {name:<24} x{cfg.gain} @ {cfg.sample_rate_hz} Hz "
                  f"[{cfg.data_type.units}]")
        if not configs:
            raise SystemExit("no sensors enabled - configure a measurement first")

        print(f"\nstreaming for {seconds:g} s (Ctrl-C to stop early)\n")
        link.streaming = True
        await request(client, link, core.stream_packet(packet_size),
                      expect_reply=False)

        received = 0
        bad_checksums = 0
        loop = asyncio.get_running_loop()
        deadline = loop.time() + seconds
        try:
            while loop.time() < deadline:
                remaining = deadline - loop.time()
                try:
                    raw = await asyncio.wait_for(link.stream_packets.get(), remaining)
                except asyncio.TimeoutError:
                    break
                received += 1
                try:
                    header, signals = core.parse_data_packet(raw, configs)
                except ValueError as exc:
                    bad_checksums += 1
                    print(f"  packet {received}: {exc}")
                    continue
                summary = ", ".join(
                    f"{name}={samples[-1][0]:.3f}" for name, samples in signals.items()
                    if samples)
                print(f"  t={header.timestamp:.3f}  battery {header.battery_status}"
                      f"  ble {header.ble_status}  {summary}")
        finally:
            link.streaming = False
            with contextlib.suppress(Exception):
                await client.write_gatt_char(core.BLE_RX_CHARACTERISTIC_UUID,
                                             core.abort_packet(), response=False)
            await asyncio.sleep(0.2)
            with contextlib.suppress(Exception):
                await client.stop_notify(core.BLE_TX_CHARACTERISTIC_UUID)

        print(f"\n{received} packets received, {bad_checksums} rejected")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=float, default=10.0,
                        help="how long to stream (default: 10)")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.seconds))
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
