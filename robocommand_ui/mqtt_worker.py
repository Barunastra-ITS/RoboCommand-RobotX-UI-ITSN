"""MQTT client QThread worker for RoboCommand RobotX 2026 OCS.

Handles:
- MQTT connect / reconnect with status signals
- Subscribe to robocommand/robotx/course and robocommand/robotx/<team_id>/command
- Publishing protobuf-serialized messages on the correct topics
- Decoding incoming payloads and emitting Qt signals
"""

import time
from typing import Optional

from PyQt5.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker

import paho.mqtt.client as mqtt

from robocommand_ui.proto_helper import (
    common_pb2, rx_reports_pb2, rx_requests_pb2, rx_commands_pb2, rx_course_pb2,
    rx_common_pb2, now_ts, parse_mqtt_payload,
)
from robocommand_ui.sequence_tracker import SequenceTracker

TOPIC_ROOT = "robocommand/robotx"


class MqttWorker(QThread):
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    connection_error = pyqtSignal(str)

    course_received = pyqtSignal(object)
    command_received = pyqtSignal(object, str)
    report_sent = pyqtSignal(str)
    request_sent = pyqtSignal(str)

    log_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._broker_host: str = "localhost"
        self._broker_port: int = 1883
        self._team_id: str = "ITSN"
        self._running: bool = False
        self._client: Optional[mqtt.Client] = None
        self._mutex = QMutex()
        self.seq = SequenceTracker()
        self._is_connected = False

    def configure(self, host: str, port: int, team_id: str) -> None:
        self._broker_host = host
        self._broker_port = port
        self._team_id = team_id

    @property
    def team_id(self) -> str:
        return self._team_id

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def run(self):
        self._running = True
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=10)

        while self._running:
            try:
                self.log_message.emit(f"Connecting to {self._broker_host}:{self._broker_port}...")
                self._client.connect(self._broker_host, self._broker_port, keepalive=30)
                self._client.loop_forever()
            except Exception as e:
                self._is_connected = False
                self.connection_error.emit(str(e))
                self.disconnected.emit()
                if self._running:
                    time.sleep(2)

    def stop(self):
        self._running = False
        self._is_connected = False
        if self._client:
            try:
                self._client.disconnect()
            except Exception:
                pass
            try:
                self._client.loop_stop()
            except Exception:
                pass

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self._is_connected = True
        course_topic = f"{TOPIC_ROOT}/course"
        cmd_topic = f"{TOPIC_ROOT}/{self._team_id}/command"
        client.subscribe(course_topic)
        client.subscribe(cmd_topic)
        self.log_message.emit(f"Connected. Subscribed to {course_topic} and {cmd_topic}")
        self.connected.emit()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self._is_connected = False
        self.log_message.emit(f"Disconnected (rc={reason_code})")
        self.disconnected.emit()

    def _on_message(self, client, userdata, msg):
        try:
            envelope_name, parsed = parse_mqtt_payload(msg.topic, msg.payload)
            if parsed is None:
                self.log_message.emit(f"[UNKNOWN] {msg.topic} ({len(msg.payload)} bytes)")
                return

            if envelope_name == "RxCourse":
                self.log_message.emit(f"[RxCourse] Received: course_id={parsed.course_id}")
                self.course_received.emit(parsed)
            elif envelope_name == "RxCommand":
                # Handbook 3.4.13: confirm the topic team id matches the decoded
                # message before acting on it.
                if parsed.team_id and parsed.team_id != self._team_id:
                    self.log_message.emit(
                        f"[ERROR] ignoring RxCommand for team '{parsed.team_id}' "
                        f"on {msg.topic} (configured team is '{self._team_id}')"
                    )
                    return
                body_name = parsed.WhichOneof("body") or "???"
                self.seq.record_rx_command_seq(parsed.seq)
                self.log_message.emit(f"[RxCommand] seq={parsed.seq} body={body_name}")
                self.command_received.emit(parsed, body_name)
            else:
                self.log_message.emit(f"[{envelope_name}] {msg.topic}")
        except Exception as e:
            self.log_message.emit(f"[ERROR] parsing {msg.topic}: {e}")

    # --- Publish helpers ---

    def _publish(self, topic: str, msg, retain: bool = False) -> bool:
        if not self._is_connected or not self._client:
            self.log_message.emit("Cannot publish: not connected")
            return False
        try:
            self._client.publish(topic, msg.SerializeToString(), retain=retain)
            return True
        except Exception as e:
            self.log_message.emit(f"Publish error: {e}")
            return False

    def publish_heartbeat(
        self, vehicle_id: str, state: int, lat: float, lng: float,
        speed: float, heading: float, vehicle_type: int,
        current_task: int = 0, roll: float = 0.0, pitch: float = 0.0,
        altitude: float = 0.0, depth: float = 0.0,
        flight_phase: int = 0,
    ) -> bool:
        report = rx_reports_pb2.RxReport(
            team_id=self._team_id,
            vehicle_id=vehicle_id,
            seq=self.seq.get_next_report_seq(vehicle_id),
            sent_at=now_ts(),
            heartbeat=rx_reports_pb2.Heartbeat(
                state=state,
                position=common_pb2.LatLng(latitude=lat, longitude=lng),
                spd_mps=speed,
                heading_deg=heading,
                roll_deg=roll,
                pitch_deg=pitch,
                altitude_hae_m=altitude,
                depth_m=depth,
                current_task=current_task,
                vehicle_type=vehicle_type,
                flight_phase=flight_phase,
            ),
        )
        topic = f"{TOPIC_ROOT}/{self._team_id}/{vehicle_id}/report"
        ok = self._publish(topic, report)
        if ok:
            self.report_sent.emit(f"Heartbeat({vehicle_id} seq={report.seq})")
        return ok

    def publish_heartbeats_multi(
        self, vehicle_ids: list, state: int, lat: float, lng: float,
        speed: float, heading: float, task: int = 0,
    ) -> int:
        """Publish one heartbeat per vehicle. Returns count successfully sent."""
        sent = 0
        for vid in vehicle_ids:
            if self.publish_heartbeat(
                vehicle_id=vid, state=state, lat=lat, lng=lng,
                speed=speed, heading=heading, vehicle_type=0, current_task=task,
            ):
                sent += 1
        return sent

    def publish_run_declaration(
        self, vehicle_ids: list, task1_tier: int, task2_tier: int,
        task3_tier: int, task4_tier: int,
        uav_geofence: list = None,
    ) -> bool:
        geofence = []
        if uav_geofence:
            geofence = [
                common_pb2.LatLng(latitude=lat, longitude=lng)
                for lat, lng in uav_geofence
            ]
        request = rx_requests_pb2.RxRequest(
            team_id=self._team_id,
            seq=self.seq.get_next_request_seq(),
            sent_at=now_ts(),
            run_declaration=rx_requests_pb2.RunDeclaration(
                vehicle_ids=vehicle_ids,
                task1_tier=task1_tier,
                task2_tier=task2_tier,
                task3_tier=task3_tier,
                task4_tier=task4_tier,
                uav_geofence=geofence,
            ),
        )
        topic = f"{TOPIC_ROOT}/{self._team_id}/request"
        ok = self._publish(topic, request)
        if ok:
            self.request_sent.emit(f"RunDeclaration(seq={request.seq}, vehicles={vehicle_ids})")
        return ok

    def publish_safe_passage_report(
        self, vehicle_id: str, entry_lat: float, entry_lng: float,
        exit_lat: float, exit_lng: float, buoys: list = None,
    ) -> bool:
        buoy_detections = []
        if buoys:
            for b in buoys:
                buoy_detections.append(rx_reports_pb2.BuoyDetection(
                    position=common_pb2.LatLng(latitude=b["lat"], longitude=b["lng"]),
                    state=b["state"],
                ))
        report = rx_reports_pb2.RxReport(
            team_id=self._team_id,
            vehicle_id=vehicle_id,
            seq=self.seq.get_next_report_seq(vehicle_id),
            sent_at=now_ts(),
            safe_passage=rx_reports_pb2.SafePassageReport(
                entry_position=common_pb2.LatLng(latitude=entry_lat, longitude=entry_lng),
                exit_position=common_pb2.LatLng(latitude=exit_lat, longitude=exit_lng),
                buoys=buoy_detections,
            ),
        )
        topic = f"{TOPIC_ROOT}/{self._team_id}/{vehicle_id}/report"
        ok = self._publish(topic, report)
        if ok:
            self.report_sent.emit(f"SafePassageReport({vehicle_id})")
        return ok

    def publish_pipeline_survey(
        self, vehicle_id: str, active_buoy_lat: float, active_buoy_lng: float,
        segments: list,
    ) -> bool:
        report = rx_reports_pb2.RxReport(
            team_id=self._team_id,
            vehicle_id=vehicle_id,
            seq=self.seq.get_next_report_seq(vehicle_id),
            sent_at=now_ts(),
            pipeline_survey=rx_reports_pb2.PipelineSurveyReport(
                active_buoy_position=common_pb2.LatLng(latitude=active_buoy_lat, longitude=active_buoy_lng),
                segments=segments,
            ),
        )
        topic = f"{TOPIC_ROOT}/{self._team_id}/{vehicle_id}/report"
        ok = self._publish(topic, report)
        if ok:
            self.report_sent.emit(f"PipelineSurveyReport({vehicle_id})")
        return ok

    def publish_resource_delivery(
        self, vehicle_id: str, task: int, resource_color: int, delivery_circle_color: int,
    ) -> bool:
        report = rx_reports_pb2.RxReport(
            team_id=self._team_id,
            vehicle_id=vehicle_id,
            seq=self.seq.get_next_report_seq(vehicle_id),
            sent_at=now_ts(),
            resource_delivery=rx_reports_pb2.ResourceDeliveryRequest(
                task=task,
                resource_color=resource_color,
                delivery_circle_color=delivery_circle_color,
            ),
        )
        topic = f"{TOPIC_ROOT}/{self._team_id}/{vehicle_id}/report"
        ok = self._publish(topic, report)
        if ok:
            self.report_sent.emit(f"ResourceDeliveryRequest({vehicle_id})")
        return ok

    def publish_docking_report(self, vehicle_id: str, bay_id: int) -> bool:
        report = rx_reports_pb2.RxReport(
            team_id=self._team_id,
            vehicle_id=vehicle_id,
            seq=self.seq.get_next_report_seq(vehicle_id),
            sent_at=now_ts(),
            docking=rx_reports_pb2.DockingReport(bay_id=bay_id),
        )
        topic = f"{TOPIC_ROOT}/{self._team_id}/{vehicle_id}/report"
        ok = self._publish(topic, report)
        if ok:
            self.report_sent.emit(f"DockingReport({vehicle_id} bay={bay_id})")
        return ok

    def publish_firefighting_report(self, vehicle_id: str, window_id: int) -> bool:
        report = rx_reports_pb2.RxReport(
            team_id=self._team_id,
            vehicle_id=vehicle_id,
            seq=self.seq.get_next_report_seq(vehicle_id),
            sent_at=now_ts(),
            firefighting=rx_reports_pb2.FirefightingReport(window_id=window_id),
        )
        topic = f"{TOPIC_ROOT}/{self._team_id}/{vehicle_id}/report"
        ok = self._publish(topic, report)
        if ok:
            self.report_sent.emit(f"FirefightingReport({vehicle_id} window={window_id})")
        return ok

    def publish_incident_ack(self, vehicle_id: str, command_seq: int) -> bool:
        report = rx_reports_pb2.RxReport(
            team_id=self._team_id,
            vehicle_id=vehicle_id,
            seq=self.seq.get_next_report_seq(vehicle_id),
            sent_at=now_ts(),
            incident_ack=rx_reports_pb2.IncidentAck(command_seq=command_seq),
        )
        topic = f"{TOPIC_ROOT}/{self._team_id}/{vehicle_id}/report"
        ok = self._publish(topic, report)
        if ok:
            self.report_sent.emit(f"IncidentAck({vehicle_id} cmd_seq={command_seq})")
        return ok

    def publish_readiness_report(self, vehicle_id: str, command_seq: int) -> bool:
        report = rx_reports_pb2.RxReport(
            team_id=self._team_id,
            vehicle_id=vehicle_id,
            seq=self.seq.get_next_report_seq(vehicle_id),
            sent_at=now_ts(),
            readiness=rx_reports_pb2.ReadinessReport(command_seq=command_seq),
        )
        topic = f"{TOPIC_ROOT}/{self._team_id}/{vehicle_id}/report"
        ok = self._publish(topic, report)
        if ok:
            self.report_sent.emit(f"ReadinessReport({vehicle_id} cmd_seq={command_seq})")
        return ok
