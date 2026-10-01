"""End-to-end integration test for the RoboCommand Qt UI against a live broker."""

import sys
import os
import time
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer

import paho.mqtt.client as mqtt

from robocommand_ui.proto_helper import (
    common_pb2, rx_common_pb2, rx_reports_pb2, rx_requests_pb2,
    rx_commands_pb2, rx_course_pb2, now_ts, parse_mqtt_payload,
)

HOST = "127.0.0.1"
PORT = 18830
TEAM = "ITSN"
ROOT = "robocommand/robotx"

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name} {detail}")
        failures.append(name)


def main():
    app = QApplication(["-platform", "offscreen"])
    from robocommand_ui.main_window import MainWindow

    win = MainWindow()

    # Start a broker on the test port so the test is self-contained
    conf = f"/tmp/rc_test_{os.getpid()}.conf"
    with open(conf, "w") as f:
        f.write(f"listener {PORT} 127.0.0.1\nallow_anonymous true\npersistence false\n")
    broker = subprocess.Popen(["mosquitto", "-c", conf], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    time.sleep(1.5)

    received = {"course": [], "command": [], "report": [], "request": []}
    watchdog = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    def on_msg(_c, _u, m):
        name, parsed = parse_mqtt_payload(m.topic, m.payload)
        if name:
            received[name.replace("Rx", "").lower()].append((m.topic, parsed))

    def on_connect(_c, _u, _f, _rc, _p):
        _c.subscribe(f"{ROOT}/#", qos=0)

    watchdog.on_message = on_msg
    watchdog.on_connect = on_connect
    watchdog.connect(HOST, PORT, 60)
    watchdog.loop_start()
    time.sleep(1.0)

    def drain(seconds=1.5):
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)

    results = {}
    steps = [
        ("connect", lambda: win._on_connect(HOST, PORT, TEAM)),
        ("verify_connected", lambda: results.update(
            connected=win.connection_bar._connected)),
        ("publish_course", lambda: results.update(
            course_ok=win.mqtt._publish(
                f"{ROOT}/course",
                rx_course_pb2.RxCourse(
                    course_id="ALPHA", pinger_freq_hz=25000, sent_at=now_ts(),
                    corners=[common_pb2.LatLng(latitude=a, longitude=b) for a, b in [
                        (1.280329, 103.8556869), (1.2804716, 103.8554529),
                        (1.2808993, 103.8557337), (1.2807567, 103.8559743),
                        (1.280329, 103.8556869)]]), retain=True))),
        ("publish_run_start", lambda: results.update(
            runstart_ok=win.mqtt._publish(
                f"{ROOT}/{TEAM}/command",
                rx_commands_pb2.RxCommand(
                    team_id=TEAM, seq=1, sent_at=now_ts(),
                    run_start=rx_commands_pb2.RunStart(declaration_seq=1, run_id=42))))),
        ("publish_keep_out", lambda: results.update(
            koz_ok=win.mqtt._publish(
                f"{ROOT}/{TEAM}/command",
                rx_commands_pb2.RxCommand(
                    team_id=TEAM, seq=2, sent_at=now_ts(),
                    keep_out_zone=rx_commands_pb2.KeepOutZone(
                        center=common_pb2.LatLng(latitude=1.2806, longitude=103.8557),
                        radius_m=15.0, vehicle_type=rx_common_pb2.TYPE_USV))))),
        ("send_declaration", lambda: win._on_send_declaration(
            ["USV1", "UUV1", "UAV1"],
            common_pb2.TIER_CORE, common_pb2.TIER_ADVANCED,
            common_pb2.TIER_CORE, common_pb2.TIER_DISRUPTIVE,
            [(1.280329, 103.8556869), (1.2804716, 103.8554529),
             (1.2808993, 103.8557337), (1.2807567, 103.8559743),
             (1.280329, 103.8556869)])),
        ("send_heartbeat", lambda: win._on_send_heartbeat(
            "USV1", common_pb2.STATE_AUTO, 1.2806, 103.8557,
            1.5, 90.0, rx_common_pb2.TYPE_USV, rx_common_pb2.TASK_SAFE_PASSAGE,
            2.0, -1.0, 5.0, 0.0, rx_common_pb2.FLIGHT_PHASE_UNKNOWN)),
        ("send_heartbeats_multi", lambda: win._on_send_heartbeats_multi(
            ["USV1", "UUV1", "UAV1"], common_pb2.STATE_AUTO, 1.2806, 103.8557,
            0.0, 0.0, rx_common_pb2.TASK_NONE, 0.0, 0.0, 30.0, 0.0,
            rx_common_pb2.FLIGHT_PHASE_AIRBORNE)),
        ("send_safe_passage", lambda: win._on_send_safe_passage(
            "USV1", 1.2806, 103.8557, 1.2807, 103.8558,
            [{"lat": 1.28061, "lng": 103.85571, "state": rx_common_pb2.BEACON_STATE_FLASHING_BLUE},
             {"lat": 1.28062, "lng": 103.85572, "state": rx_common_pb2.BEACON_STATE_FLASHING_RED}])),
        ("send_pipeline_survey", lambda: win._on_send_pipeline_survey(
            "UUV1", 1.2806, 103.8557,
            [rx_common_pb2.PIPELINE_SEGMENT_INTACT,
             rx_common_pb2.PIPELINE_SEGMENT_DAMAGED,
             rx_common_pb2.PIPELINE_SEGMENT_INTACT])),
        ("send_incident_ack", lambda: win._on_send_incident_ack("USV1", 2)),
        ("send_readiness", lambda: win._on_send_readiness("USV1", 2)),
        ("send_docking", lambda: win._on_send_docking("USV1", 1)),
        ("send_firefighting", lambda: win._on_send_firefighting("USV1", 1)),
        ("send_resource_delivery", lambda: win._on_send_resource_delivery(
            "UAV1", rx_common_pb2.TASK_COORDINATED_LOGISTICS,
            rx_common_pb2.COLOR_ANY, rx_common_pb2.COLOR_RED)),
    ]

    print("\n=== UI integration test ===")
    for name, fn in steps:
        fn()
        drain(0.35)

    print("\n=== Connection ===")
    check("worker connected to broker", results.get("connected") is True)
    check("connection bar shows connected", win.connection_bar._connected)

    print("\n=== RxCourse (retained) ===")
    check("course received by UI", len(win.course_map._canvas._course_points) == 5,
          f"got {len(win.course_map._canvas._course_points)} corners")
    check("course panel shows id", win.course_panel.course_id_label.text().endswith("ALPHA"),
          win.course_panel.course_id_label.text())
    check("course_id label", "ALPHA" in win.course_panel.course_id_label.text())

    print("\n=== RxCommand ===")
    check("2 commands received", len(received["command"]) == 2,
          f"got {len(received['command'])}")
    bodies = [c.WhichOneof("body") for _, c in received["command"]]
    check("run_start decoded", "run_start" in bodies, str(bodies))
    check("keep_out_zone decoded", "keep_out_zone" in bodies, str(bodies))
    check("command seq tracked", win.mqtt.seq.get_last_rx_command_seq() == 2,
          f"got {win.mqtt.seq.get_last_rx_command_seq()}")
    check("run state ACTIVE", win._run_state == "ACTIVE", win._run_state)
    check("run id recorded", win.commands_panel.run_id == 42, str(win.commands_panel.run_id))

    print("\n=== RxRequest ===")
    check("run declaration received", len(received["request"]) == 1,
          f"got {len(received['request'])}")
    if received["request"]:
        topic, req = received["request"][0]
        decl = req.run_declaration
        check("request topic correct", topic == f"{ROOT}/{TEAM}/request", topic)
        check("team id", req.team_id == TEAM, req.team_id)
        check("3 vehicles", list(decl.vehicle_ids) == ["USV1", "UUV1", "UAV1"],
              str(list(decl.vehicle_ids)))
        check("geofence closed", len(decl.uav_geofence) >= 4
              and decl.uav_geofence[0].latitude == decl.uav_geofence[-1].latitude
              and decl.uav_geofence[0].longitude == decl.uav_geofence[-1].longitude)
        check("tiers applied", decl.task1_tier == common_pb2.TIER_CORE
              and decl.task4_tier == common_pb2.TIER_DISRUPTIVE)
        check("request seq incremented", win.mqtt.seq.get_request_seq() == 1,
              f"got {win.mqtt.seq.get_request_seq()}")

    print("\n=== RxReport topics & seq ===")
    report_topics = [t for t, _ in received["report"]]
    check("11 reports sent", len(received["report"]) == 11, f"got {len(received['report'])}")

    # Per-vehicle wire sequence numbers must start at 1 and increase monotonically
    per_vehicle_seqs = {}
    for _, rep in received["report"]:
        per_vehicle_seqs.setdefault(rep.vehicle_id, []).append(rep.seq)
    for vid in ("USV1", "UUV1", "UAV1"):
        seqs = per_vehicle_seqs.get(vid, [])
        check(f"{vid} seq starts at 1", seqs and seqs[0] == 1, str(seqs))
        check(f"{vid} seq monotonic", all(b > a for a, b in zip(seqs, seqs[1:])), str(seqs))
        check(f"{vid} tracker matches wire",
              win.mqtt.seq.get_report_seq(vid) == max(seqs) if seqs else False,
              f"tracker={win.mqtt.seq.get_report_seq(vid)} wire={max(seqs) if seqs else None}")

    check("USV1 sent 7 reports", len(per_vehicle_seqs.get("USV1", [])) == 7,
          f"got {len(per_vehicle_seqs.get('USV1', []))}")
    check("USV1 topic prefix",
          all(t.startswith(f"{ROOT}/{TEAM}/USV1/report") for t in report_topics
              if "/USV1/" in t))
    check("vehicle_id matches topic",
          all(r.vehicle_id in t for t, r in received["report"]))
    check("every report carries team_id",
          all(r.team_id == TEAM for _, r in received["report"]))
    check("every report has sent_at",
          all(r.sent_at.seconds > 0 for _, r in received["report"]))

    print("\n=== Report bodies ===")
    by_vehicle = {}
    for topic, rep in received["report"]:
        by_vehicle.setdefault(rep.vehicle_id, []).append(rep.WhichOneof("body"))
    check("USV1 sent heartbeat", "heartbeat" in by_vehicle.get("USV1", []))
    check("USV1 sent safe_passage", "safe_passage" in by_vehicle.get("USV1", []))
    check("USV1 sent docking", "docking" in by_vehicle.get("USV1", []))
    check("USV1 sent firefighting", "firefighting" in by_vehicle.get("USV1", []))
    check("USV1 sent incident_ack", "incident_ack" in by_vehicle.get("USV1", []))
    check("USV1 sent readiness", "readiness" in by_vehicle.get("USV1", []))
    check("UUV1 sent pipeline_survey", "pipeline_survey" in by_vehicle.get("UUV1", []))
    check("UAV1 sent resource_delivery", "resource_delivery" in by_vehicle.get("UAV1", []))

    for _, rep in received["report"]:
        bodies_seen = rep.WhichOneof("body")
        if bodies_seen is None:
            check(f"exactly one body on seq {rep.seq}", False)
            break
    else:
        check("every report has exactly one oneof body", True)

    print("\n=== Monitor & map ===")
    check("3 vehicle cards", len(win.vehicle_monitor._cards) == 3,
          f"got {len(win.vehicle_monitor._cards)}")
    check("USV1 card exists", "USV1" in win.vehicle_monitor._cards)
    check("map has 3 vehicles", len(win.course_map._canvas._vehicles) == 3,
          f"got {len(win.course_map._canvas._vehicles)}")
    check("map geofence drawn", len(win.course_map._canvas._geofence_points) == 5)
    check("monitor tracked USV1 heartbeat",
          win.vehicle_monitor._veh["USV1"]["last_hb"] is not None
          and win.vehicle_monitor._veh["USV1"]["seq"] > 0,
          str(win.vehicle_monitor._veh.get("USV1")))
    card = win.vehicle_monitor._cards.get("USV1")
    if card:
        # Last heartbeat for USV1 came from the multi-vehicle broadcast (TASK_NONE)
        check("card shows latest task", card.task_label.text() == "NONE",
              card.task_label.text())
        check("card state AUTO", "AUTO" in card.state_label.text(),
              card.state_label.text())
        check("card shows type USV", card.type_label.text() == "USV",
              card.type_label.text())
    uav_card = win.vehicle_monitor._cards.get("UAV1")
    if uav_card:
        check("UAV card flight phase", uav_card.flight_label.text() == "AIRBORNE",
              uav_card.flight_label.text())
        check("UAV card type", uav_card.type_label.text() == "UAV",
              uav_card.type_label.text())

    usv1_reports = win.vehicle_monitor._veh["USV1"]["reports"]
    check("monitor counts USV1 safe_passage", usv1_reports.get("safe_passage") == 1,
          str(usv1_reports))
    check("monitor counts USV1 docking", usv1_reports.get("docking") == 1,
          str(usv1_reports))
    uav1_reports = win.vehicle_monitor._veh["UAV1"]["reports"]
    check("monitor counts UAV1 resource_delivery",
          uav1_reports.get("resource_delivery") == 1, str(uav1_reports))

    print("\n=== Log panel ===")
    check("log has entries", len(win.log_panel._all_messages) > 10,
          f"got {len(win.log_panel._all_messages)}")

    print("\n=== Broker death detection (§3.4.13) ===")
    # Kill the broker out from under the worker; the UI must notice and show it.
    broker.kill()
    broker.wait(timeout=10)
    deadline = time.time() + 12
    while time.time() < deadline and win.mqtt.is_connected:
        drain(0.3)
    drain(1.0)  # let the queued Qt signal reach the UI thread
    check("worker detected broker loss", not win.mqtt.is_connected,
          "still reported connected after broker was killed")
    check("connection bar reflects loss", not win.connection_bar._connected)
    check("status bar reports disconnect", "Disconnected" in win.statusBar().currentMessage(),
          win.statusBar().currentMessage())

    print("\n=== Automatic recovery after broker returns ===")
    # Restart the broker and confirm the worker reconnects on its own.
    conf2 = f"/tmp/rc_recovery_{os.getpid()}.conf"
    with open(conf2, "w") as f:
        f.write(f"listener {PORT} 127.0.0.1\nallow_anonymous true\npersistence false\n")
    subprocess.Popen(["mosquitto", "-c", conf2], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
    deadline = time.time() + 25
    while time.time() < deadline and not win.mqtt.is_connected:
        drain(0.3)
    drain(1.0)  # let the queued Qt signal reach the UI thread
    check("worker reconnected automatically", win.mqtt.is_connected,
          "did not reconnect within 25s")
    check("connection bar restored", win.connection_bar._connected)
    if win.mqtt.is_connected:
        win.mqtt._publish(
            f"{ROOT}/{TEAM}/command",
            rx_commands_pb2.RxCommand(
                team_id=TEAM, seq=5, sent_at=now_ts(),
                all_clear=rx_commands_pb2.AllClear(vehicle_type=rx_common_pb2.TYPE_UUV),
            ))
        drain(1.5)
        check("subscriptions restored after auto-reconnect",
              win.mqtt.seq.get_last_rx_command_seq() == 5,
              f"got {win.mqtt.seq.get_last_rx_command_seq()}")
    subprocess.run(["pkill", "-f", f"mosquitto -c {conf2}"], capture_output=True)
    for f in (conf, conf2):
        try:
            os.remove(f)
        except OSError:
            pass

    print("\n=== Disconnect ===")
    win._on_disconnect()
    drain(1.5)
    check("disconnected cleanly", not win.mqtt.is_connected)

    watchdog.loop_stop()
    watchdog.disconnect()
    win.mqtt.wait(3000)
    win.deleteLater()
    app.processEvents()

    print("\n" + "=" * 50)
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())