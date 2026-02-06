#!/usr/bin/env python3

import os
import sys
import re
import numpy as np

from daemon import SimpleFactory, SerialUSBProtocol, SimpleProtocol
from command import Command
from daemon import catch


def value(response):
    """
    Return displayed measuring value.
    """

    def decode_u16(bytea: int, byteb: int) -> int:
        data = (255 - bytea) << 8
        data = data | byteb
        return data

    def decode_u32(inputa: int, inputb: int) -> int:
        data = (inputa << 16) | inputb
        return data

    def crop_u32(value: int) -> int:
        size = sys.getsizeof(value)
        result = value

        if size > 32:
            result = value & 0x00000000FFFFFFFF
        return result

    def to_signed32(value):
        value = value & 0xFFFFFFFF
        return (value ^ 0x80000000) - 0x80000000

    if response == "":
        return "Error: No value read."
    byte3, byte4 = response[3], response[4]
    byte6, byte7 = response[6], response[7]
    u16_integer1 = decode_u16(byte3, byte4)
    u16_integer2 = decode_u16(byte6, byte7)
    u32_integer = decode_u32(u16_integer1, u16_integer2)

    float_pos = 0xFF - byte3
    float_pos = (float_pos >> 3) - 15

    u32_integer = crop_u32(u32_integer & 0x07FFFFFF)

    if (100000000 + 0x2000000) > u32_integer:
        compare = crop_u32(u32_integer & 0x04000000)

        if 0x04000000 == compare:
            u32_integer = crop_u32(u32_integer | 0xF8000000)

        u32_integer = crop_u32(u32_integer + 0x02000000)
    else:
        error_num = u32_integer - 0x02000000 - 100000000
        return self.error_msg(error_num)

    i32_integer = to_signed32(u32_integer)
    temp_value = float(i32_integer) / float(float(10.0) ** float_pos)

    return temp_value


class DaemonProtocol(SimpleProtocol):
    _debug = False  # Display all traffic for debug purposes
    _simulator = False

    @catch
    def processMessage(self, string):
        # It will handle some generic messages and return pre-parsed Command object
        cmd = SimpleProtocol.processMessage(self, string)
        if cmd is None:
            return

        obj = self.object  # Object holding the state
        hw = obj["hw"]  # HW factory
        string = string.strip()
        STRING = string.upper()
        if cmd.name == "get_status":
            self.message(
                f'status hw_connected={self.object["hw_connected"]} status={self.object["status"]} temperatureA={self.object["temperatureA"]} temperatureB={self.object["temperatureB"]}'
            )


class GMHProtocol(SerialUSBProtocol):
    _binary_length = 9

    @catch
    def __init__(self, serial_num, obj, debug=False):
        self.commands = (
            []
        )  # Queue of command sent to the device which will provide replies, each entry is a dict with keys "cmd","source"
        self.name = "hw"
        self.type = "hw"
        self.status_commands = [
            b"\xfe\x00\x3d",  # Channel A read request
            b"\xfd\x00\x02",  # Channel B read request
        ]
        super().__init__(
            obj=obj,
            serial_num=serial_num,
            refresh=1,
            baudrate=4800,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=400,
            debug=debug,
        )

    @catch
    def connectionMade(self):
        self.commands = []
        super().connectionMade()
        self.object["hw_connected"] = 1

    @catch
    def connectionLost(self, reason):
        super().connectionLost(self, reason)
        self.object["hw_connected"] = 0
        self.object["status"] = "----"
        self.object["temperatureA"] = "nan"
        self.object["temperatureB"] = "nan"

    @catch
    def processMessage(self, string):
        # Process the device reply
        if self._debug:
            print("hw cc > %s" % string)
        self.commands.pop(0)

    @catch
    def update(self):
        if self._debug:
            print("----------------------- command queue ----------------------------")
            for k in self.commands:
                print(k["cmd"], k["source"], k["status"])
            print("===================== command queue end ==========================")

        if len(self.commands) and obj["hw_connected"]:
            self.message(self.commands[0]["cmd"])
        else:
            for k in self.status_commands:
                self.commands.append({"cmd": k, "source": "itself", "status": "status"})

    def processBinary(self, bstring):
        # Process the device reply
        self._bs = bstring
        result = value(self._bs)
        if self._debug:
            print("hw bb > %s" % self._bs)
            print(f"{result=}")
        match self._bs[0]:
            case 254:
                self.object["temperatureA"] = result
            case 253:
                self.object["temperatureB"] = result
        self.commands.pop(0)


if __name__ == "__main__":
    from optparse import OptionParser

    parser = OptionParser(usage="usage: %prog [options] arg")

    parser.add_option(
        "-s",
        "--serial-num",
        help="Serial number of the device to connect to.",
        action="store",
        dest="serial_num",
        type="str",
        default="A50285BI",
    )
    parser.add_option(
        "-p",
        "--port",
        help="Daemon port",
        action="store",
        dest="port",
        type="int",
        default=7040,
    )
    parser.add_option(
        "-n",
        "--name",
        help="Daemon name",
        action="store",
        dest="name",
        default="gmh3200",
    )
    parser.add_option(
        "-D", "--debug", help="Debug mode", action="store_true", dest="debug"
    )
    parser.add_option(
        "-S",
        "--simulator",
        help="Simulator mode",
        action="store_true",
        dest="simulator",
    )

    (options, args) = parser.parse_args()

    # Object holding actual state and work logic.
    # May be anything that will be passed by reference - list, dict, object etc
    obj = {"hw_connected": 0, "status": "----", "temperatureA": 0, "temperatureB": 0}
    # Factories for daemon and hardware connections
    # We need two different factories as the protocols are different
    daemon = SimpleFactory(DaemonProtocol, obj)

    daemon.name = options.name
    obj["daemon"] = daemon

    proto = GMHProtocol(serial_num=options.serial_num, obj=obj, debug=options.debug)
    obj["hw"] = proto
    if options.debug:
        daemon._protocol._debug = True

    if options.simulator:
        daemon._protocol._simulator = True

    # Incoming connections
    daemon.listen(options.port)

    daemon._reactor.run()
