#!/usr/bin/env python3
__author__ = "Tim Brooks"
__email__ = "brooks@skoorb.net"
__date__ = "2024-04-23"

import datetime
from enum import Enum, Flag
import logging
import serial
import serial.tools.list_ports as list_ports
import struct

logging.addLevelName(5, "TRACE")
logging.TRACE = 5

COMMAND = {
    "set_time": b"\x01",
    "read_dose_curve": b"\x03",
    "set_rate_limit": b"\x04",
    "set_dose_limit": b"\x05",
    "get_version": b"\x06",
    "get_dose": b"\x07",
    "set_alert": b"\x08",
    "set_display": b"\x09",
    "set_mode": b"\x0a",
    "set_language": b"\x0b",
    "timer_duration": b"\x0c",
    "clear_dose": b"\x0d",
    "read": b"\x0e",
    "read_rate_curve": b"\x0f",
    "read_alarms": b"\x10",
}
RESPONSE = {
    "readback": b"\x04",
    "success": b"\x06",
    "read_starting": b"\x0e\x06\x01",
    "read_stopping": b"\x0e\x06\x00",
}

VID_PID = (0x1A86, 0x7523)


class FS5000:
    def __init__(self, port):
        self.port = serial.Serial(port, 115200, timeout=2)
        self.log = logging.getLogger("FS5000")

    def log_bytes(self, data, purpose, level=logging.DEBUG):
        """Log raw hex bytes"""
        # The stacklevel arg sets funcName to the caller, not this frame
        if self.log.getEffectiveLevel() <= level:
            title = f"{len(data)} bytes {purpose}: "
            if len(title) + len(data) * 3 < 80:
                for b in data:
                    title += f"{b:02x} "
                self.log.log(level, title, stacklevel=2)
                return

            self.log.log(level, title, stacklevel=2)
            string = ""
            for b in data:
                string += f"{b:02x} "
                if len(string) >= 48:
                    self.log.log(level, string, stacklevel=2)
                    string = ""
            if string:
                self.log.log(level, string, stacklevel=2)

    def write(self, data):
        self.log_bytes(data, "written", logging.TRACE)
        return self.port.write(data)

    def read(self, length):
        response = self.port.read(length)
        self.log_bytes(response, "read", logging.TRACE)
        return response

    def checksum(self, data: bytes) -> bytes:
        return bytes([sum(data) % 256])

    def packet(self, payload: bytes):
        self.log.log(logging.TRACE, f"{len(payload)=}")
        data = b"\xaa"
        # Length + checksum and trailer byte to follow:
        data += bytes([len(payload) + 3])
        data += payload
        data += self.checksum(data)
        data += b"\x55"
        return data

    def send(self, command: bytes):
        data = self.packet(command)
        self.write(data)

    def recv(self):
        header = self.read(2)
        if len(header) == 0:
            return None
        if header[0] != 0xAA:
            raise IOError(f"Read header 0x{header[0]:02x} not 0xaa")
        length = header[1]

        data = self.read(length - 1)
        if data[-1] != 0x55:
            raise IOError(f"Read trailer 0x{data[-1]:02x} not 0x55")
        checksum = self.checksum(header + data[:-2])[0]
        if checksum != data[-2]:
            msg_checksum = data[-2]
            self.log_bytes(data, "failed to verify")
            raise IOError(f"Checksum failure {checksum:02x} != {msg_checksum:02x}")
        return data[:-2]

    def check_success(self, command):
        response = self.recv()
        expectation = bytes([command[0]]) + RESPONSE["success"]
        if response[:2] != expectation:
            raise RuntimeError(f"Received {response=}, expected {expectation}")
        return response[2:]

    def set_time(self, time: datetime.datetime = None):
        if time is None:
            time = datetime.datetime.now()
        command = COMMAND["set_time"]
        command += bytes([time.year % 100, time.month, time.day])
        command += bytes([time.hour, time.minute, time.second])
        self.send(command)
        self.check_success(command)

    def read_dose_log(self):
        """Fetch log of total dose"""
        self.send(COMMAND["read_dose_curve"])
        response = self.check_success(COMMAND["read_dose_curve"])
        packets, records = struct.unpack("!BH", response)
        log = b""
        for packet in range(1, packets + 1):
            response = self.recv()
            if response[0] != COMMAND["read_dose_curve"][0]:
                raise RuntimeError(f"Received {response[0]=} not {COMMAND['read_dose_curve'][0]}")
            if response[1] != packet:
                raise RuntimeError(f"Received {response[1]=} not {packet=}")
            log += response[2:]
        self.log_bytes(log, "logged")
        raise NotImplementedError("TODO: Parse dose curve")

    DIGITS = ".0123456789"
    MSV_H = b"mSvh"
    USV_H = b"uSvh"
    RATE_UNIT = {
        MSV_H: "mSv/h",
        USV_H: "μSv/h",
    }

    def set_rate_limit(self, value: str, unit: bytes = b"uSvh"):
        if type(value) is not str:
            raise TypeError("Rate limit must be 4 characters e.g. '2.50'")
        if len(value) != 4:
            raise ValueError("Rate limit must be 4 characters e.g. '2.50'")
        if any(c not in self.DIGITS for c in value):
            raise ValueError(f"Rate limit must be of characters {self.DIGITS}")
        if unit not in self.RATE_UNIT:
            raise ValueError("Rate limit must have unit 'uSvh' or 'mSvh'")
        self.log.debug(f"{value=} {self.RATE_UNIT[unit]}")
        command = COMMAND["set_rate_limit"]
        command += value.encode("ascii") + unit
        self.send(command)
        self.check_success(command)

    SV = b" Sv"
    MSV = b"mSv"
    USV = b"uSv"
    DOSE_UNIT = {
        SV: "Sv",
        MSV: "mSv",
        USV: "μSv",
    }

    def set_dose_limit(self, limit: str, unit: bytes = b"uSv"):
        # raise NotImplementedError("Dose rate limit unit not yet understood.")
        if type(limit) is not str:
            raise TypeError("Dose limit must be 4 characters e.g. '2.50'")
        if len(limit) != 4:
            raise ValueError("Dose limit must be 4 characters e.g. '2.50'")
        if any(c not in self.DIGITS for c in limit):
            raise ValueError(f"Dose limit must be of characters {self.DIGITS}")
        if unit not in self.DOSE_UNIT:
            raise ValueError("Dose limit must have unit 'uSv', 'mSv' or ' Sv'")
        self.log.debug(limit.encode("ascii") + unit)
        command = COMMAND["set_dose_limit"]
        command += limit.encode("ascii") + unit
        self.send(command)
        self.check_success(command)

    def get_version(self):
        self.send(COMMAND["get_version"])
        response = self.recv()
        return response

    def get_dose(self):
        """Fetch current total dose"""
        self.send(COMMAND["get_dose"])
        response = self.check_success(COMMAND["get_dose"])
        _, dose, *date = struct.unpack("!II5B", response)
        dose *= 0.01  # Convert to μSv
        year, month, day, hour, minute = date
        year += 2000  # We saved an extra byte! This will surely never cause problems...
        date = datetime.datetime(year, month, day, hour, minute)
        self.log.info(f"{dose:.2f} μSv starting {date}")
        return (dose, date)

    class Notify(Flag):
        LAMP = 0x01
        SOUND = 0x02
        VIBE = 0x04
        CLICK = 0x08

    def set_alert(self, value: Notify):
        if type(value) is not self.Notify:
            raise ValueError("Alert setting must be of type Notify")
        command = COMMAND["set_alert"]
        command += bytes([value.value])
        self.send(command)
        self.check_success(command)

    def set_display(self, brightness: int, timeout: int):
        if brightness < 0 or brightness > 5:
            raise ValueError("Brightness must be in range [0-5]")
        if timeout < 0 or timeout > 9999:
            raise ValueError("Timeout must be in range [0-9999]")
        command = COMMAND["set_display"]
        command += bytes([brightness, timeout // 256, timeout % 256])
        self.send(command)
        self.check_success(command)

    def set_mode(self, mode=bool):
        """Set True to enable long endurance mode"""
        command = COMMAND["set_mode"]
        command += bytes([mode])
        self.send(command)
        self.check_success(command)

    class Language(Enum):
        CHINESE = 0x00
        ENGLISH = 0x01

    def set_language(self, value: Language):
        if type(value) is not self.Language:
            raise ValueError("Language setting must be of type Language")
        command = COMMAND["set_language"]
        command += bytes([value.value])
        self.send(command)
        self.check_success(command)

    def get_duration(self):
        """Get the period of a 'timed dose' measurement"""
        # This seems like a rejected command, but the current value gets read back
        command = COMMAND["timer_duration"] + b"\x01"
        self.send(command)
        response = self.recv()
        expectation = COMMAND["timer_duration"] + RESPONSE["readback"] + b"\x00"
        if response[:3] != expectation:
            raise RuntimeError(f"Received {response=}, expected {expectation}")
        seconds = struct.unpack("!I", response[3:])[0]
        self.log.info(f"Got timed duration {seconds} s")
        return seconds

    def set_duration(self, seconds):
        """Set the period of a 'timed dose' measurement in seconds"""
        command = COMMAND["timer_duration"]
        command += struct.pack("!BI", 0, seconds)  # 0 to set value, non-zero gets it
        self.send(command)
        self.check_success()

    def clear_dose(self):
        """Clear the accumulated dose total, returns date-time of reset"""
        command = COMMAND["clear_dose"]
        self.send(command)
        response = self.check_success()
        date = struct.unpack("!6B", response)
        year, month, day, hour, minute = date
        year += 2000  # We saved an extra byte! This will surely never cause problems...
        date = datetime.datetime(year, month, day, hour, minute)
        return date

    def start_read(self):
        """Command start of continuous data readout"""
        self.send(COMMAND["read"] + b"\x01")
        message = self.recv()
        if message != RESPONSE["read_starting"]:
            raise RuntimeError(f"Expected start of counts, got {message}")

    def stop_read(self):
        """Wait until the stop response is read back"""
        self.send(COMMAND["read"] + b"\x00")
        while True:
            try:
                message = self.recv()
                if message != RESPONSE["read_stopping"]:
                    raise RuntimeError(f"Expected stopping of counts, got {message}")
                break
            except IOError:
                pass

    def yield_data(self):
        """Continuously yield a semicolon separated record of date-time, instantaneous dose rate, total dose,
        counts per second, counts per minute, average dose rate, timer, timed dose and alarm status"""
        self.start_read()
        try:
            while True:
                message = self.recv()
                if message is None:
                    continue
                now = datetime.datetime.now()
                if message[0] != COMMAND["read"][0]:
                    raise RuntimeError(f"Unexpected datum marker: {message[0]=} != {COMMAND['read'][0]}")
                now = now.isoformat(timespec="seconds")
                yield now + ";" + message[1:].decode()
        finally:
            self.stop_read()

    def read_out(self):
        """Read out data continuously"""
        try:
            for datum in self.yield_data():
                self.log.info(datum)
        except KeyboardInterrupt:
            pass

    def read_rate_log(self):
        """Fetch log of dose rate"""
        self.send(COMMAND["read_rate_curve"])
        response = self.check_success(COMMAND["read_rate_curve"])
        # No idea why there's a null in the centre here:
        packets, _, records = struct.unpack("!HBH", response)
        log = b""
        for packet in range(1, packets + 1):
            response = self.recv()
            command, packet_id = struct.unpack("!BH", response[:3])
            if command != COMMAND["read_rate_curve"][0]:
                raise RuntimeError(f"Received {command=} not {COMMAND['read_rate_curve'][0]}")
            if packet_id != packet:
                raise RuntimeError(f"Received {packet_id=} not {packet=}")
            log += response[3:]
        self.log_bytes(log, "logged")
        raise NotImplementedError("TODO: Parse dose rate curve")

    def read_alarms(self):
        self.send(COMMAND["read_alarms"])
        response = self.check_success(COMMAND["read_alarms"])
        _, packets, _, records = struct.unpack("!BBBH", response)
        log = b""
        for packet in range(1, packets + 1):
            response = self.recv()
            if response[0] != COMMAND["read_alarms"][0]:
                raise RuntimeError(f"Received {response[0]=} not {COMMAND['read_alarms'][0]}")
            if response[2] != packet:
                raise RuntimeError(f"Received {response[2]=} not {packet=}")
            log += response[3:]
        self.log_bytes(log, "logged")
        for record in range(records):
            data = log[record * 16 : (record + 1) * 16]
            values = struct.unpack("!BH5B4s4s", data)
            alarm = values[0]
            date = datetime.datetime(*values[1:7])
            limit, unit = values[7:9]
            if alarm == 0x01:
                UNIT = self.RATE_UNIT
            elif alarm == 0x02:
                unit = unit[1:]  # The log has an extra space in this case
                UNIT = self.DOSE_UNIT
            if unit not in UNIT:
                self.log.error(f"Unknown unit: {unit}")
                continue
            self.log.log(logging.TRACE, f"{limit=} {unit=}")
            self.log.info(f"#{record+1} {date} >={limit.decode()} {UNIT[unit]}")


class MockFS5000(FS5000):
    def __init__(self, port):
        self.last = None
        self.log = logging.getLogger("MockFS5000")
        self.outbox = b""

    def write(self, value):
        self.log_bytes(value, "written", logging.TRACE)
        length = value[1]
        self.last = command = value[2]
        return len(value)

    def read(self, length):
        """Just report that the previous command succeeded"""
        if self.last is None:
            return b""
        # Partial message still waiting to be read
        outbox = self.outbox
        if len(outbox):
            self.outbox = outbox[length:]
            self.log_bytes(outbox[:length], "read", logging.TRACE)
            return outbox[:length]
        # Craft a new message to return to reader
        response = self.packet(bytes([self.last]) + RESPONSE["success"])
        self.outbox = response[length:]
        response = response[:length]
        self.log_bytes(response, "read", logging.TRACE)
        return response


def get_port():
    ports = list_ports.comports()
    for port in ports:
        if (port.vid, port.pid) == VID_PID:
            return port.device
    else:
        raise FileNotFoundError()


def main():
    form = "%(levelname)s:%(name)s:%(funcName)s: %(message)s"
    logging.basicConfig(level=logging.INFO, format=form)
    # logging.basicConfig(level=logging.TRACE, format=form)
    port = get_port()
    dev = FS5000(port)
    # dev = MockFS5000('/dev/null')

    # dev.set_time()

    # dev.read_dose_log()

    # dev.set_rate_limit("0.50", "uSvh")
    # dev.set_rate_limit("0.50", FS5000.USV_H)

    # dev.set_dose_limit("0.01", " Sv")
    # dev.set_dose_limit("2.50", FS5000.USV)

    # version = dev.get_version()
    # version = version.split(b'\x00')
    # logging.info(f"{version=}")

    # dev.get_dose()

    # dev.set_alert(FS5000.Notify.LAMP | FS5000.Notify.VIBE)

    # dev.set_display(0, 60)

    # dev.set_mode(False)

    # dev.set_language(FS5000.Language.ENGLISH)

    # dev.get_duration()
    # dev.set_duration(2 * 60 * 60)

    # dev.clear_dose()

    # now = datetime.datetime.now().isoformat(timespec="minutes").translate({58:45})
    # with open(f"fs5000_{now}.log", "w") as file:
    #     try:
    #         for datum in dev.yield_data():
    #             print(datum, file=file, flush=True)
    #     except KeyboardInterrupt:
    #         pass

    dev.read_out()

    # dev.read_rate_log()

    # dev.read_alarms()

    # dev.send(COMMAND['set_dose_limit'])
    # dev.send(b'\x0c\x02')
    # while True:
    #     response = dev.recv()
    #     if response is None:
    #         break
    #     if len(response) == 0:
    #         break


if __name__ == "__main__":
    main()
