"""Verifies the UI against the real documented setup:
  docker compose -f robocommand/RobotX_2026/docker-compose.yml up -d broker
  + the vendored rc_test/test_client.py as the RoboCommand-side peer.

Unlike the other suites (which start their own throwaway broker on 18830),
this drives localhost:1883 — the broker the README tells an operator to run.

Usage:
  docker compose -f robocommand/RobotX_2026/docker-compose.yml up -d broker
  python3 tests/test_compose_stack.py

Requires the `rc_test` container to be built (it carries the proto deps for
test_client.py), OR set PYTHONPATH so the vendored gen/python modules import.
"""

import os
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication

HOST = "127.0.0.1"
PORT = 1883
TEAM = "RNRX"
ROOT = "robocommand/robotx"

RC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "robocommand", "RobotX_2026",
)
RC_TEST = os.path.join(RC_DIR, "rc_test")
GEN = os.path.join(RC_DIR, "gen", "python")

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name} {detail}")
        failures.append(name)


def broker_port_open(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        return s.connect_ex((HOST, port)) == 0
    finally:
        s.close()


def rc_test(cmd, *args):
    """Invoke the vendored test_client.py, exactly as the README documents."""
    env = dict(os.environ)
    env["PYTHONPATH"] = GEN + os.pathsep + env.get("PYTHONPATH", "")
    env["BROKER_HOST"] = HOST
    env["BROKER_PORT"] = str(PORT)
    return subprocess.run(
        [sys.executable, os.path.join(RC_TEST, "test_client.py"),
         "--broker", HOST, "--port", str(PORT), cmd, *args],
        env=env, capture_output=True, text=True, cwd=RC_TEST, timeout=60,
    )


def main():
    print(f"=== RoboCommand compose-stack verification (broker {HOST}:{PORT}) ===")
    if not broker_port_open(PORT):
        print(f"No broker on {HOST}:{PORT}.")
        print("Start the documented stack first:")
        print("  docker compose -f robocommand/RobotX_2026/docker-compose.yml up -d broker")
        return 2
    print(f"Broker reachable on {HOST}:{PORT}")

    # Confirm the vendored publisher can drive that broker
    print("\n=== Vendored test_client.py against the same broker ===")
    r = rc_test("course", "--course-id", "ALPHA", "--pinger-freq-hz", "25000")
    check("rc-test course publish ran", r.returncode == 0, r.stderr[-300:])

    app = QApplication(["-platform", "offscreen"])
    from robocommand_ui.main_window import MainWindow

    win = MainWindow()

    def drain(seconds=1.0):
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)

    print("\n=== UI connects to the documented broker ===")
    win._on_connect(HOST, PORT, TEAM)
    drain(2.0)
    check("UI connected", win.mqtt.is_connected)
    check("connection bar shows connected", win.connection_bar._connected)
    check("connection state visible to operator",
          win.connection_bar.status_label.text().startswith("● Connected"),
          win.connection_bar.status_label.text())

    # The retained course from the earlier publish must arrive on subscribe.
    # NOTE: the vendored test_client.py defaults to a 4-corner boundary whose
    # first and last points differ, which the Team Handbook 3.4.9 rejects. The
    # UI must decode it AND flag it — silently accepting would stall RunStart.
    drain(2.0)
    corners = win.course_map._canvas._course_points
    check("retained RxCourse decoded on subscribe", len(corners) == 4,
          f"got {len(corners)} corners (vendored client default is 4)")
    check("course id shown", "ALPHA" in win.course_panel.course_id_label.text(),
          win.course_panel.course_id_label.text())
    check("open boundary flagged as invalid",
          "not a closed polygon" in win.course_panel.validation_label.text(),
          win.course_panel.validation_label.text())
    check("status bar reports invalid course",
          "INVALID" in win.statusBar().currentMessage(),
          win.statusBar().currentMessage())

    # Republish a valid closed-ring course; the UI must accept it.
    print("\n=== Valid closed-ring course is accepted ===")
    r = rc_test(
        "course", "--course-id", "ALPHA", "--pinger-freq-hz", "25000",
        "--corner-lats", "1.280329", "1.2804716", "1.2808993", "1.2807567", "1.280329",
        "--corner-lngs", "103.8556869", "103.8554529", "103.8557337", "103.8559743", "103.8556869",
    )
    check("rc-test valid course published", r.returncode == 0, r.stderr[-300:])
    drain(2.0)
    check("closed-ring course accepted",
          "Valid course configuration" in win.course_panel.validation_label.text(),
          win.course_panel.validation_label.text())
    check("5 corners drawn", len(win.course_map._canvas._course_points) == 5,
          f"got {len(win.course_map._canvas._course_points)}")
    check("status bar reports valid course",
          "valid" in win.statusBar().currentMessage(),
          win.statusBar().currentMessage())

    print("\n=== UI publishes a RunDeclaration, RC server replies RunStart ===")
    win._on_send_declaration(
        ["USV1", "UUV1", "UAV1"],
        2, 3, 2, 4,  # core, advanced, core, disruptive
        [(1.280329, 103.8556869), (1.2804716, 103.8554529),
         (1.2808993, 103.8557337), (1.2807567, 103.8559743),
         (1.280329, 103.8556869)],
    )
    drain(2.0)
    check("declaration published", len(win.log_panel._all_messages) > 0)

    # Heartbeats for all declared vehicles at STATE_AUTO
    print("\n=== 2 Hz heartbeats for all declared vehicles ===")
    for vid in ("USV1", "UUV1", "UAV1"):
        win._on_send_heartbeat(vid, 3, 1.2806, 103.8557, 0.0, 0.0, 0, 1)
    drain(2.0)

    hb = win.reports_panel.heartbeat_tab
    hb.auto_vehicles.setText("USV1, UUV1, UAV1")
    hb.auto_btn.setChecked(True)
    drain(2.0)
    hb.auto_btn.setChecked(False)
    drain(0.5)

    print("\n=== Task 4 command/response chain (RC -> OCS -> OCS -> RC) ===")
    r = rc_test("assistance-request", "--vehicle-type", "uuv",
                "--lat", "1.2806", "--lng", "103.8557")
    check("RC published assistance-request", r.returncode == 0, r.stderr[-300:])
    drain(2.0)

    cmd_log = win.commands_panel.command_log.toPlainText()
    check("UI showed the assistance request", "assistance_request" in cmd_log,
          cmd_log[-200:])
    check("command seq recorded",
          win.mqtt.seq.get_last_rx_command_seq() > 0,
          f"got {win.mqtt.seq.get_last_rx_command_seq()}")

    # OCS acknowledges, reports readiness, then RC confirms.
    cmd_seq = win.mqtt.seq.get_last_rx_command_seq()
    win._on_send_incident_ack("UUV1", cmd_seq)
    win._on_send_readiness("UUV1", cmd_seq)
    drain(2.0)

    r = rc_test("readiness-confirm", "--report-seq", "1", "--vehicle-id", "UUV1")
    check("RC published readiness-confirm", r.returncode == 0, r.stderr[-300:])
    drain(2.0)
    check("UI displayed readiness_confirm",
          "readiness_confirm" in win.commands_panel.command_log.toPlainText())

    # The read-only monitor must reflect the UUV1 activity (reports + last command)
    uuv1 = win.vehicle_monitor._veh.get("UUV1")
    check("monitor tracked UUV1 readiness report",
          uuv1 and uuv1["reports"].get("readiness") == 1,
          str(uuv1 and uuv1["reports"]))
    check("monitor tracked UUV1 incident ack",
          uuv1 and uuv1["reports"].get("incident_ack") == 1,
          str(uuv1 and uuv1["reports"]))
    check("monitor shows UUV1 last command (ReadinessConfirm)",
          uuv1 and uuv1["last_cmd"] and "ReadinessConfirm" in uuv1["last_cmd"],
          str(uuv1 and uuv1["last_cmd"]))

    print("\n=== UI reconnect to the documented broker ===")
    win._on_disconnect()
    drain(2.0)
    check("disconnected", not win.mqtt.is_connected)

    win._on_connect(HOST, PORT, TEAM)
    drain(3.0)
    check("reconnected", win.mqtt.is_connected)
    check("resubscribed to team command topic",
          any("Subscribed" in m for m in win.log_panel._all_messages[-10:]),
          str(win.log_panel._all_messages[-3:]))
    # Retained course must arrive again with no new publish.
    check("retained course restored after reconnect",
          len(win.course_map._canvas._course_points) == 5,
          f"got {len(win.course_map._canvas._course_points)}")
    check("restored course still valid",
          "Valid course configuration" in win.course_panel.validation_label.text(),
          win.course_panel.validation_label.text())

    win._on_disconnect()
    drain(1.5)
    win.mqtt.wait(3000)
    win.deleteLater()
    app.processEvents()

    print("\n" + "=" * 55)
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED (UI against the documented compose-stack broker)")
    return 0


if __name__ == "__main__":
    sys.exit(main())