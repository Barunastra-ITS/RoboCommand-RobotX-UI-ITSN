"""Live check against a real MQTT broker: report.py -> broker -> host UI.

Needs a broker, e.g. on the RoboCommand host or a dev box:
  ./scripts/dev_broker.sh start            # mosquitto on 127.0.0.1:1883
  docker compose -f robocommand/RobotX_2026/docker-compose.yml up -d broker
Then:
  python3 tests/test_live_broker.py        # BROKER_HOST / BROKER_PORT to override

Skips (exit 0) when nothing is listening, so the suite still runs offline.
"""

import os
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import paho.mqtt.client as mqtt
from PyQt5.QtWidgets import QApplication

from robocommand_ui.proto_helper import (
    common_pb2, now_ts, parse_mqtt_payload, rx_commands_pb2, rx_course_pb2,
)

HOST = os.environ.get("BROKER_HOST", "127.0.0.1")
PORT = int(os.environ.get("BROKER_PORT", "1883"))
TEAM = "ITSN"
TOPIC_ROOT = "robocommand/robotx"
CORNERS = [(1.280329, 103.8556869), (1.2804716, 103.8554529), (1.2808993, 103.8557337),
           (1.2807567, 103.8559743), (1.280329, 103.8556869)]

failures = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name} {'' if cond else detail}")
    if not cond:
        failures.append(name)


def port_open():
    try:
        with socket.create_connection((HOST, PORT), timeout=1):
            return True
    except OSError:
        return False


def main():
    if not port_open():
        print(f"SKIP: no broker on {HOST}:{PORT}. Start one with ./scripts/dev_broker.sh start")
        return 0

    app = QApplication(["-platform", "offscreen"])
    from robocommand_ui.main_window import MainWindow

    def drain(seconds):
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)

    # RoboCommand stand-in: retained course, and RunStart once declared
    rc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    declarations = []

    def rc_on_message(_c, _u, m):
        name, parsed = parse_mqtt_payload(m.topic, m.payload)
        if name == "RxRequest" and parsed.WhichOneof("body") == "run_declaration":
            declarations.append(parsed.seq)

    rc.on_message = rc_on_message
    rc.on_connect = lambda c, *_: c.subscribe(f"{TOPIC_ROOT}/{TEAM}/request")
    rc.connect(HOST, PORT, 30)
    rc.loop_start()
    course = rx_course_pb2.RxCourse(
        course_id="ALPHA", pinger_freq_hz=25000, sent_at=now_ts(),
        corners=[common_pb2.LatLng(latitude=a, longitude=b) for a, b in CORNERS])
    rc.publish(f"{TOPIC_ROOT}/course", course.SerializeToString(), retain=True)

    print(f"=== Host UI monitoring {HOST}:{PORT} ===")
    win = MainWindow()
    win._on_connect(HOST, PORT)
    drain(1.5)
    check("host connected", win.mqtt.is_connected)
    check("retained course shown", len(win.course_map._canvas._course_points) == 5)

    print("=== report.py --simulate reports to the broker ===")
    gcs = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "report.py"), "--course", "local", "--host", HOST,
         "--port", str(PORT), "--team", TEAM, "--vehicle", "USV1", "--vehicle", "UUV1",
         "--tiers", "CORE,NONE,NONE,NONE", "--simulate"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        drain(4.0)
        check("RunDeclaration reached the broker", len(declarations) == 1, str(declarations))
        win.refresh_views()
        usv = win.fleet.vehicles.get((TEAM, "USV1"))
        check("host sees USV1", usv is not None)
        check("USV1 trail is growing", usv is not None and len(usv.trail) >= 4,
              str(usv and len(usv.trail)))
        check("USV1 at ~2 Hz", usv is not None and 1.5 <= usv.rate_hz(time.time()) <= 2.5,
              str(usv and usv.rate_hz(time.time())))
        check("team DECLARED", win.teams_panel.row_text(TEAM)[1] == "DECLARED",
              str(win.teams_panel.row_text(TEAM)))

        if declarations:
            cmd = rx_commands_pb2.RxCommand(team_id=TEAM, seq=1, sent_at=now_ts(),
                                            run_start=rx_commands_pb2.RunStart(
                                                declaration_seq=declarations[0], run_id=5))
            rc.publish(f"{TOPIC_ROOT}/{TEAM}/command", cmd.SerializeToString())
            drain(1.5)
            win.refresh_views()
            check("team ACTIVE after RunStart", win.teams_panel.row_text(TEAM)[1] == "ACTIVE",
                  str(win.teams_panel.row_text(TEAM)))

        print("=== host reconnect ===")
        win._on_disconnect()
        drain(1.0)
        win.mqtt.wait(3000)
        win._on_connect(HOST, PORT)
        drain(2.5)
        win.refresh_views()
        check("host reconnected", win.mqtt.is_connected)
        check("retained course restored", len(win.course_map._canvas._course_points) == 5)
        check("movement resumes after reconnect", (TEAM, "USV1") in win.fleet.vehicles)
    finally:
        gcs.terminate()
        out, _ = gcs.communicate(timeout=5)
        if failures:
            print("--- report.py output ---\n" + out[-2000:])
        win._on_disconnect()
        win.mqtt.wait(3000)
        rc.publish(f"{TOPIC_ROOT}/course", b"", retain=True)    # clear retained course
        rc.loop_stop()
        rc.disconnect()

    print("FAILED: " + ", ".join(failures) if failures else "ALL LIVE CHECKS PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
