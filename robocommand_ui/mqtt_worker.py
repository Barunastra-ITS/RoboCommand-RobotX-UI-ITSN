"""Passive MQTT monitor for the RoboCommand host (e.g. 192.168.65.2).

The host UI only listens. It subscribes to everything under
``robocommand/robotx/#`` and emits each decoded envelope with the team and
vehicle taken from the topic. It never publishes, so it cannot inject
messages into a live run.
"""

import threading
from typing import Optional

import paho.mqtt.client as mqtt
from PyQt5.QtCore import QThread, pyqtSignal

from robocommand_ui.courses import TOPIC_ROOT
from robocommand_ui.fleet_state import parse_topic
from robocommand_ui.proto_helper import parse_mqtt_payload

EXPECTED_ENVELOPE = {
    "course": "RxCourse",
    "report": "RxReport",
    "request": "RxRequest",
    "command": "RxCommand",
}


class MqttWorker(QThread):
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    connection_error = pyqtSignal(str)

    course_received = pyqtSignal(object)
    report_received = pyqtSignal(str, str, object)    # team_id, vehicle_id, RxReport
    request_received = pyqtSignal(str, object)        # team_id, RxRequest
    command_received = pyqtSignal(str, object)        # team_id, RxCommand

    log_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._broker_host: str = "localhost"
        self._broker_port: int = 1883
        self._running: bool = False
        self._client: Optional[mqtt.Client] = None
        self._client_lock = threading.Lock()
        self._wake = threading.Event()
        self._is_connected = False

    def configure(self, host: str, port: int) -> None:
        self._broker_host = host
        self._broker_port = port

    def start_monitoring(self, host: str, port: int) -> None:
        """(Re)start listening. Waits for a previous run to finish first;
        QThread.start() is a silent no-op while the thread is still running."""
        if self.isRunning():
            self.stop()
            self.wait(5000)
        self.configure(host, port)
        self._running = True            # set before start() so a stop() can't be lost
        self._wake.clear()
        self.start()

    @property
    def broker(self) -> str:
        return f"{self._broker_host}:{self._broker_port}"

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def run(self):
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.reconnect_delay_set(min_delay=1, max_delay=10)
        with self._client_lock:
            self._client = client

        while self._running:
            try:
                self.log_message.emit(f"Connecting to {self.broker}...")
                client.connect(self._broker_host, self._broker_port, keepalive=30)
                client.loop_forever(retry_first_connection=True)
            except Exception as e:
                self._is_connected = False
                self.connection_error.emit(str(e))
                self.disconnected.emit()
                self._wake.wait(2.0)        # interruptible by stop()

        with self._client_lock:
            self._client = None

    def stop(self):
        self._running = False
        self._is_connected = False
        self._wake.set()
        with self._client_lock:
            client = self._client
        if client:
            try:
                client.disconnect()
            except Exception as e:
                self.log_message.emit(f"disconnect error: {e}")

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if getattr(reason_code, "is_failure", False):
            self.connection_error.emit(f"broker refused connection: {reason_code}")
            return
        self._is_connected = True
        topic = f"{TOPIC_ROOT}/#"
        client.subscribe(topic)
        self.log_message.emit(f"Connected to {self.broker}. Monitoring {topic}")
        self.connected.emit()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self._is_connected = False
        self.log_message.emit(f"Disconnected (rc={reason_code})")
        self.disconnected.emit()

    def _on_message(self, client, userdata, msg):
        # Runs on the paho thread: only decode and emit; the GUI thread owns state.
        try:
            route = parse_topic(msg.topic)
            if route is None:
                self.log_message.emit(f"[IGNORED] unexpected topic {msg.topic}")
                return
            kind, team_id, vehicle_id = route
            name, parsed = parse_mqtt_payload(msg.topic, msg.payload)
            if parsed is None or name != EXPECTED_ENVELOPE[kind]:
                self.log_message.emit(
                    f"[ERROR] malformed payload on {msg.topic} ({len(msg.payload)} bytes)")
                return
            if kind == "course":
                self.course_received.emit(parsed)
            elif kind == "report":
                self.report_received.emit(team_id, vehicle_id, parsed)
            elif kind == "request":
                self.request_received.emit(team_id, parsed)
            elif kind == "command":
                self.command_received.emit(team_id, parsed)
        except Exception as e:
            self.log_message.emit(f"[ERROR] handling {msg.topic}: {e}")
