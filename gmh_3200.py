#!/usr/bin/env python3

import os
import sys
import re
import numpy as np

from daemon import SimpleFactory, SerialUSBProtocol
from command import Command
from daemon import catch


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
            (254, 0, 61),  # Channel A read request
            (253, 0, 2),  # Channel B read request
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
            print("self.commands", self.commands)
        # Request the hardware state from the device
        if len(self.commands):
            SimpleProtocol.message(self, self.commands[0]["cmd"])
            if not self.commands[0]["keep"]:
                self.commands.pop(0)
        else:
            for k in self.status_commands:
                self.commands.append({"cmd": k, "source": "itself", "keep": True})

    @catch
    def message(self, string, keep=False, source="itself"):
        """
        Send the message to the controller. If keep=True, expect reply
        """
        self.commands.append({"cmd": string, "source": source, "keep": keep})


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
    proto = GMHProtocol(serial_num=options.serial_num, obj=obj, debug=options.debug)

    daemon.name = options.name

    obj["daemon"] = daemon
    obj["hw"] = proto

    if options.debug:
        daemon._protocol._debug = True

    if options.simulator:
        daemon._protocol._simulator = True

    # Incoming connections
    daemon.listen(options.port)

    daemon._reactor.run()
