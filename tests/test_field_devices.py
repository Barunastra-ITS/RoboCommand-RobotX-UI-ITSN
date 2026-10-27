"""Task 1 (light beacon) and Task 3 (docking bays) device clients and tabs,
against a local HTTP server that answers like the ESP firmwares. Qt runs
offscreen; device calls run inline (DeviceRunner(sync=True))."""

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["ROBOCOMMAND_MAP_TILES"] = "0"
sys.path.insert(0, ROOT)

from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication

from robocommand_ui import field_devices as fd
from robocommand_ui.widgets.device_runner import DeviceRunner
from robocommand_ui.widgets.task1_tab import Task1Tab
from robocommand_ui.widgets.task3_tab import Task3Tab

app = QApplication.instance() or QApplication(["-platform", "offscreen"])

BEACON_TEXT = {"off": "OFF / BLACK", "solid_blue": "SOLID BLUE (EXIT)",
               "flash_blue": "FLASHING BLUE (ENTRY)", "flash_red": "FLASHING RED (STARBOARD)",
               "flash_green": "FLASHING GREEN (PORT)"}


class FakeEsp:
    """One server playing both firmwares: beacon ``/set`` and dock ``/api/data``."""

    def __init__(self):
        self.beacon = "off"
        self.target = 10.0
        self.calib = 7.5
        self.litres = [0.0, 0.0]
        self.states = ["MANUAL MODE", "MANUAL MODE"]
        self.requests = []
        esp = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                url = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                esp.requests.append((url.path, q))
                code, body = esp.handle(url.path, q)
                self.send_response(code)
                self.end_headers()
                self.wfile.write(body.encode())

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.host = f"127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def handle(self, path, q):
        if path == "/":
            return 200, (f"<div class='panel'><h3>Status Saat Ini:</h3><h3 style='color:#ffeb3b;'>"
                         f"{BEACON_TEXT[self.beacon]}</h3></div>"
                         f"<input type='number' id='tVol' value='{self.target:.2f}' style='width:70px;'>")
        if path == "/set":
            self.beacon = q.get("s", "off")
            return 200, "OK"
        if path == "/api/data":
            return 200, json.dumps({"v1": self.litres[0], "v2": self.litres[1], "f1": 0.0,
                                    "f2": 1.5, "st1": self.states[0], "st2": self.states[1],
                                    "calib": self.calib})
        if path == "/start":
            i = int(q["bay"]) - 1
            self.litres[i], self.states[i] = 0.0, "FIREFIGHTING (MERAH)"
            return 200, "Started"
        if path == "/manual":
            for i in ((0, 1) if q["bay"] == "0" else (int(q["bay"]) - 1,)):
                self.litres[i], self.states[i] = 0.0, "MANUAL MODE"
            return 200, "Manual"
        if path == "/force_success":
            i = int(q["bay"]) - 1
            if not self.states[i].startswith("FIREFIGHTING"):
                return 400, "Gagal"
            self.litres[i], self.states[i] = self.target, "SUCCESS (HIJAU 5s)"
            return 200, "Forced"
        if path == "/settarget":
            self.target = float(q["val"])
            return 200, "OK"
        if path == "/setcalib":
            self.calib = float(q["val"])
            return 200, "OK"
        return 404, "Not found"


class DeviceTestCase(unittest.TestCase):
    def setUp(self):
        self.esp = FakeEsp()

    def tearDown(self):
        self.esp.close()


class TestClients(DeviceTestCase):
    def test_beacon_mode_round_trip(self):
        self.assertEqual(fd.beacon_status(self.esp.host), "OFF / BLACK")
        fd.set_beacon(self.esp.host, "flash_blue")
        self.assertEqual(fd.beacon_status(self.esp.host), "FLASHING BLUE (ENTRY)")

    def test_unknown_beacon_mode_is_not_sent(self):
        with self.assertRaises(fd.DeviceError):
            fd.set_beacon(self.esp.host, "purple")
        self.assertEqual(self.esp.requests, [])

    def test_dock_status_and_start(self):
        fd.dock_start(self.esp.host, 2, "disrupt", "green", "blue")
        self.assertEqual(self.esp.requests[-1],
                         ("/start", {"bay": "2", "tier": "disrupt", "c1": "green", "c2": "blue"}))
        status = fd.dock_status(self.esp.host)
        self.assertEqual(status.bays[1].state, "FIREFIGHTING (MERAH)")
        self.assertEqual(status.bays[1].flow_lpm, 1.5)
        self.assertEqual(status.calibration, 7.5)

    def test_force_success_outside_firefighting_explains_why(self):
        with self.assertRaisesRegex(fd.DeviceError, "not firefighting"):
            fd.dock_force_success(self.esp.host, 1)

    def test_target_is_read_from_the_page(self):
        fd.dock_set_target(self.esp.host, 12.5)
        self.assertEqual(fd.dock_target(self.esp.host), 12.5)

    def test_bad_input_never_reaches_the_device(self):
        for call in (lambda: fd.dock_start(self.esp.host, 3, "core"),
                     lambda: fd.dock_start(self.esp.host, 1, "core", "pink"),
                     lambda: fd.dock_set_target(self.esp.host, -1),
                     lambda: fd.dock_status("bad host/../x")):
            with self.assertRaises(fd.DeviceError):
                call()
        self.assertEqual(self.esp.requests, [])

    def test_unreachable_device_is_a_device_error(self):
        port = self.esp.server.server_port
        self.esp.close()
        self.esp = FakeEsp()            # tearDown closes this one
        with self.assertRaisesRegex(fd.DeviceError, "unreachable"):
            fd.dock_status(f"127.0.0.1:{port}")


class TabTestCase(DeviceTestCase):
    def setUp(self):
        super().setUp()
        self._dir = tempfile.TemporaryDirectory()
        self.settings = QSettings(os.path.join(self._dir.name, "devices.ini"), QSettings.IniFormat)
        self.logs = []

    def tearDown(self):
        self._dir.cleanup()
        super().tearDown()

    def point_at_esp(self, link):
        link.edit.setText(self.esp.host)
        link.edit.editingFinished.emit()


class TestTask1Tab(TabTestCase):
    def test_buttons_follow_the_beacon_link_and_set_the_mode(self):
        tab = Task1Tab(self.settings, DeviceRunner(sync=True))
        tab.log.connect(self.logs.append)
        beacon = tab.beacons[0]
        self.assertFalse(beacon.mode_buttons["flash_red"].isEnabled())

        self.point_at_esp(beacon.link)
        self.assertTrue(beacon.link.online)
        self.assertEqual(beacon.state_label.text(), "OFF / BLACK")
        self.assertEqual(self.settings.value("devices/beacon1"), self.esp.host)

        beacon.mode_buttons["flash_red"].click()
        self.assertEqual(self.esp.beacon, "flash_red")
        self.assertEqual(beacon.state_label.text(), "FLASHING RED (STARBOARD)")
        self.assertTrue(any("set to Flashing red" in line for line in self.logs))

    def test_offline_is_logged_once(self):
        tab = Task1Tab(self.settings, DeviceRunner(sync=True))
        tab.log.connect(self.logs.append)
        beacon = tab.beacons[1]
        beacon.link.edit.setText("127.0.0.1:1")
        beacon.link.edit.editingFinished.emit()
        beacon.poll()
        self.assertFalse(beacon.link.online)
        self.assertEqual(len([line for line in self.logs if "offline" in line]), 1)


class TestTask3Tab(TabTestCase):
    def make_tab(self):
        tab = Task3Tab(self.settings, DeviceRunner(sync=True))
        tab.log.connect(self.logs.append)
        self.point_at_esp(tab.link)
        return tab

    def test_start_force_and_stop_a_bay(self):
        tab = self.make_tab()
        bay = tab.bays[0]
        self.assertTrue(bay.start_buttons["core"].isEnabled())
        self.assertEqual(bay.state_chip.text(), "MANUAL MODE")

        bay.start_buttons["core"].click()
        self.assertEqual(bay.state_chip.text(), "FIREFIGHTING (MERAH)")
        bay.force_btn.click()
        self.assertEqual(bay.litres_label.text(), "0.25 / 0.25 L")
        tab.stop_all_btn.click()
        self.assertEqual(self.esp.states, ["MANUAL MODE", "MANUAL MODE"])
        self.assertTrue(any("Bay 1 start Core" in line for line in self.logs))

    def test_each_tier_sends_its_own_colours(self):
        tab = self.make_tab()
        bay = tab.bays[1]
        bay.adv_color.setCurrentText("green")
        bay.disrupt_color1.setCurrentText("blue")
        bay.disrupt_color2.setCurrentText("red")

        bay.start_buttons["adv"].click()
        start = [q for path, q in self.esp.requests if path == "/start"][-1]
        self.assertEqual((start["tier"], start["c1"]), ("adv", "green"))

        bay.start_buttons["disrupt"].click()
        start = [q for path, q in self.esp.requests if path == "/start"][-1]
        self.assertEqual((start["tier"], start["c1"], start["c2"]), ("disrupt", "blue", "red"))
        self.assertTrue(any("Bay 2 start Disruptive (blue / red)" in line for line in self.logs))

    def test_refused_command_is_logged_as_error(self):
        tab = self.make_tab()
        tab.bays[1].force_btn.click()
        self.assertTrue(any(line.startswith("[ERROR]") and "not firefighting" in line
                            for line in self.logs))

    def test_target_field_is_a_bare_number_starting_at_0_25(self):
        tab = self.make_tab()
        self.assertEqual(tab.target_spin.value(), 0.25)
        self.assertEqual(tab.target_spin.suffix(), "")
        self.assertEqual(tab.calib_spin.value(), 4.90)

    def test_readouts_follow_target_field_and_set_sends_it(self):
        self.esp.target = 8.0
        tab = self.make_tab()
        self.assertEqual(tab.target_spin.value(), 0.25)       # not overwritten by the ESP
        self.assertEqual(self.esp.target, 0.25)               # sent on connect
        self.assertEqual(tab.bays[0].litres_label.text(), "0.00 / 0.25 L")
        tab.target_spin.setValue(0.5)
        self.assertEqual([b.litres_label.text() for b in tab.bays],
                         ["0.00 / 0.50 L", "0.00 / 0.50 L"])
        tab.target_btn.click()
        self.assertEqual(self.esp.target, 0.5)

    def test_controls_disabled_while_offline(self):
        tab = Task3Tab(self.settings, DeviceRunner(sync=True))
        tab.link.edit.setText("127.0.0.1:1")
        tab.link.edit.editingFinished.emit()
        self.assertFalse(tab.stop_all_btn.isEnabled())
        self.assertEqual(tab.link.chip.text(), "OFFLINE")


if __name__ == "__main__":
    unittest.main()
