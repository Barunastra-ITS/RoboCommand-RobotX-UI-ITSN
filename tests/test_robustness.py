"""Robustness tests: malformed payloads, wrong-team topics, reconnect, 2Hz rate."""

import sys
import os
import time
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer

import paho.mqtt.client as mqtt

from robocommand_ui.proto_helper import (
    common_pb2, rx_common_pb2, rx_course_pb2, rx_commands_pb2, now_ts,
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
    conf = f"/tmp/rc_robust_{os.getpid()}.conf"
    with open(conf, "w") as f:
        f.write(f"listener {PORT} 127.0.0.1\nallow_anonymous true\npersistence false\n")
    broker = subprocess.Popen(["mosquitto", "-c", conf], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    time.sleep(1.5)

    def drain(seconds=1.0):
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)

    attacker = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    attacker.connect(HOST, PORT, 60)
    attacker.loop_start()
    time.sleep(0.5)

    win._on_connect(HOST, PORT, TEAM)
    drain(1.5)
    check("connected", win.mqtt.is_connected)

    print("\n=== Malformed payloads must not crash the app ===")
    before = len(win.log_panel._all_messages)

    attacker.publish(f"{ROOT}/course", b"\xff\xfe\xfd\xfc not a protobuf")
    attacker.publish(f"{ROOT}/{TEAM}/command", b"\x08\x96 garbage bytes \x01")
    attacker.publish(f"{ROOT}/{TEAM}/USV1/report", bytes(range(60)))
    attacker.publish(f"{ROOT}/bogus/topic/name", b"anything at all")
    attacker.publish(f"{ROOT}/course", b"")
    drain(2.0)

    check("app still alive after bad payloads", True)
    check("app still connected", win.mqtt.is_connected)
    check("errors were logged", len(win.log_panel._all_messages) > before,
          f"{before} -> {len(win.log_panel._all_messages)}")

    # A valid message published after the bad ones must still be processed
    attacker.publish(
        f"{ROOT}/{TEAM}/command",
        rx_commands_pb2.RxCommand(
            team_id=TEAM, seq=98, sent_at=now_ts(),
            run_start=rx_commands_pb2.RunStart(declaration_seq=1, run_id=42),
        ).SerializeToString())
    drain(1.5)
    check("valid command after bad payloads processed",
          "run_start" in win.commands_panel.command_log.toPlainText(),
          win.commands_panel.command_log.toPlainText()[-200:])
    check("valid run_start adopted run_id 42", win.commands_panel.run_id == 42,
          f"got {win.commands_panel.run_id}")
    check("command seq advanced to 98",
          win.mqtt.seq.get_last_rx_command_seq() == 98,
          f"got {win.mqtt.seq.get_last_rx_command_seq()}")

    print("\n=== Wrong-team command must be ignored by the UI ===")
    attacker.publish(
        f"{ROOT}/OTHERTEAM/command",
        rx_commands_pb2.RxCommand(
            team_id="OTHERTEAM", seq=100, sent_at=now_ts(),
            run_start=rx_commands_pb2.RunStart(declaration_seq=1, run_id=999),
        ).SerializeToString())
    drain(1.5)
    check("other team's RunStart ignored (run_id still 42)",
          win.commands_panel.run_id == 42, f"got {win.commands_panel.run_id}")
    check("other team's seq not adopted",
          win.mqtt.seq.get_last_rx_command_seq() == 98,
          f"got {win.mqtt.seq.get_last_rx_command_seq()}")

    print("\n=== 2 Hz auto heartbeat (handbook 3.4.11) ===")
    counter = {"n": 0}
    original = win.mqtt.publish_heartbeat

    def counting(*args, **kwargs):
        counter["n"] += 1
        return original(*args, **kwargs)

    win.mqtt.publish_heartbeat = counting

    hb_tab = win.reports_panel.heartbeat_tab
    hb_tab.auto_vehicles.setText("USV1, UUV1, UAV1")
    hb_tab.auto_btn.setChecked(True)
    drain(3.0)
    hb_tab.auto_btn.setChecked(False)
    win.mqtt.publish_heartbeat = original

    # 3s at 2Hz x 3 vehicles, allowing one timer tick of slack at the boundary
    check("auto heartbeat published for all vehicles", 15 <= counter["n"] <= 24,
          f"got {counter['n']} in 3s across 3 vehicles (~expected 18)")
    check("auto heartbeat timer stopped", not hb_tab._auto_timer.isActive())

    print("\n=== Reconnect restores subscriptions ===")
    win._on_disconnect()
    drain(1.5)
    check("disconnected", not win.mqtt.is_connected)

    win._on_connect(HOST, PORT, TEAM)
    drain(2.0)
    check("reconnected", win.mqtt.is_connected)

    # Retained course must arrive again on reconnect without a new publish
    attacker.publish(
        f"{ROOT}/{TEAM}/command",
        rx_commands_pb2.RxCommand(
            team_id=TEAM, seq=101, sent_at=now_ts(),
            all_clear=rx_commands_pb2.AllClear(vehicle_type=rx_common_pb2.TYPE_UUV),
        ).SerializeToString())
    drain(1.5)
    check("subscriptions restored after reconnect",
          win.mqtt.seq.get_last_rx_command_seq() == 101,
          f"got {win.mqtt.seq.get_last_rx_command_seq()}")

    print("\n=== Sequence counters reset on new connection ===")
    check("request seq reset", win.mqtt.seq.get_request_seq() == 0,
          f"got {win.mqtt.seq.get_request_seq()}")
    check("vehicle seqs reset", win.mqtt.seq.get_all_vehicle_seqs() == {},
          str(win.mqtt.seq.get_all_vehicle_seqs()))

    print("\n=== Shutdown ===")
    win._on_disconnect()
    drain(1.0)
    check("survived disconnect without exception", True)

    attacker.loop_stop()
    attacker.disconnect()
    broker.terminate()
    try:
        broker.wait(timeout=10)
    except subprocess.TimeoutExpired:
        broker.kill()
    try:
        os.remove(conf)
    except OSError:
        pass

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