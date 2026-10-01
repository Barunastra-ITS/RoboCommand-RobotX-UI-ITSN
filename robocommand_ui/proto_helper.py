import os
import sys
from typing import Tuple, Any, Optional, Dict
from google.protobuf.timestamp_pb2 import Timestamp

# Find generated python proto directory
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_WORKSPACE_ROOT = os.path.dirname(_SCRIPT_DIR)
_PROTO_GEN_DIR = os.path.join(_WORKSPACE_ROOT, "robocommand", "RobotX_2026", "gen", "python")

if os.path.exists(_PROTO_GEN_DIR) and _PROTO_GEN_DIR not in sys.path:
    sys.path.insert(0, _PROTO_GEN_DIR)

try:
    import common_pb2
    from robotx import rx_common_pb2, rx_reports_pb2, rx_requests_pb2, rx_commands_pb2, rx_course_pb2
except ImportError as e:
    raise ImportError(
        f"Failed to import RobotX protobuf generated modules from {_PROTO_GEN_DIR}: {e}"
    ) from e


def now_ts() -> Timestamp:
    ts = Timestamp()
    ts.GetCurrentTime()
    return ts


# Map string names to Enum values
TIER_STR_MAP = {
    "TIER_UNKNOWN": common_pb2.TIER_UNKNOWN,
    "TIER_NONE": common_pb2.TIER_NONE,
    "TIER_CORE": common_pb2.TIER_CORE,
    "TIER_ADVANCED": common_pb2.TIER_ADVANCED,
    "TIER_DISRUPTIVE": common_pb2.TIER_DISRUPTIVE,
}

STATE_STR_MAP = {
    "STATE_UNKNOWN": common_pb2.STATE_UNKNOWN,
    "STATE_KILLED": common_pb2.STATE_KILLED,
    "STATE_MANUAL": common_pb2.STATE_MANUAL,
    "STATE_AUTO": common_pb2.STATE_AUTO,
}

TYPE_STR_MAP = {
    "TYPE_UNKNOWN": rx_common_pb2.TYPE_UNKNOWN,
    "TYPE_USV": rx_common_pb2.TYPE_USV,
    "TYPE_UUV": rx_common_pb2.TYPE_UUV,
    "TYPE_UAV": rx_common_pb2.TYPE_UAV,
}

TASK_STR_MAP = {
    "TASK_UNKNOWN": rx_common_pb2.TASK_UNKNOWN,
    "TASK_NONE": rx_common_pb2.TASK_NONE,
    "TASK_SAFE_PASSAGE": rx_common_pb2.TASK_SAFE_PASSAGE,
    "TASK_INFRA_SURVEY_REPAIR": rx_common_pb2.TASK_INFRA_SURVEY_REPAIR,
    "TASK_COORDINATED_LOGISTICS": rx_common_pb2.TASK_COORDINATED_LOGISTICS,
    "TASK_DYNAMIC_INCIDENT": rx_common_pb2.TASK_DYNAMIC_INCIDENT,
}

COLOR_STR_MAP = {
    "COLOR_UNKNOWN": rx_common_pb2.COLOR_UNKNOWN,
    "COLOR_RED": rx_common_pb2.COLOR_RED,
    "COLOR_GREEN": rx_common_pb2.COLOR_GREEN,
    "COLOR_BLUE": rx_common_pb2.COLOR_BLUE,
    "COLOR_ANY": rx_common_pb2.COLOR_ANY,
}

BEACON_STR_MAP = {
    "BEACON_STATE_UNKNOWN": rx_common_pb2.BEACON_STATE_UNKNOWN,
    "BEACON_STATE_OFF": rx_common_pb2.BEACON_STATE_OFF,
    "BEACON_STATE_FLASHING_RED": rx_common_pb2.BEACON_STATE_FLASHING_RED,
    "BEACON_STATE_FLASHING_GREEN": rx_common_pb2.BEACON_STATE_FLASHING_GREEN,
    "BEACON_STATE_FLASHING_BLUE": rx_common_pb2.BEACON_STATE_FLASHING_BLUE,
    "BEACON_STATE_STEADY_BLUE": rx_common_pb2.BEACON_STATE_STEADY_BLUE,
}

SEGMENT_STR_MAP = {
    "PIPELINE_SEGMENT_UNKNOWN": rx_common_pb2.PIPELINE_SEGMENT_UNKNOWN,
    "PIPELINE_SEGMENT_INTACT": rx_common_pb2.PIPELINE_SEGMENT_INTACT,
    "PIPELINE_SEGMENT_DAMAGED": rx_common_pb2.PIPELINE_SEGMENT_DAMAGED,
}

FLIGHT_STR_MAP = {
    "FLIGHT_PHASE_UNKNOWN": rx_common_pb2.FLIGHT_PHASE_UNKNOWN,
    "FLIGHT_PHASE_GROUNDED": rx_common_pb2.FLIGHT_PHASE_GROUNDED,
    "FLIGHT_PHASE_AIRBORNE": rx_common_pb2.FLIGHT_PHASE_AIRBORNE,
}


def robot_state_name(val: int) -> str:
    return common_pb2.RobotState.Name(val).replace("STATE_", "")


def task_tier_name(val: int) -> str:
    return common_pb2.TaskTier.Name(val).replace("TIER_", "")


def vehicle_type_name(val: int) -> str:
    return rx_common_pb2.VehicleType.Name(val).replace("TYPE_", "")


def rx_task_name(val: int) -> str:
    return rx_common_pb2.RxTask.Name(val).replace("TASK_", "")


def color_name(val: int) -> str:
    return rx_common_pb2.Color.Name(val).replace("COLOR_", "")


def beacon_state_name(val: int) -> str:
    return rx_common_pb2.BeaconState.Name(val).replace("BEACON_STATE_", "")


def pipeline_segment_name(val: int) -> str:
    return rx_common_pb2.PipelineSegmentStatus.Name(val).replace("PIPELINE_SEGMENT_", "")


def flight_phase_name(val: int) -> str:
    return rx_common_pb2.FlightPhase.Name(val).replace("FLIGHT_PHASE_", "")


def parse_mqtt_payload(topic: str, payload: bytes) -> Tuple[Optional[str], Optional[Any]]:
    """Determines envelope type from topic or payload and parses the binary protobuf."""
    parts = topic.strip("/").split("/")
    if not parts:
        return None, None

    last = parts[-1]
    try:
        if last == "course":
            msg = rx_course_pb2.RxCourse()
            msg.ParseFromString(payload)
            return "RxCourse", msg
        elif last == "report":
            msg = rx_reports_pb2.RxReport()
            msg.ParseFromString(payload)
            return "RxReport", msg
        elif last == "request":
            msg = rx_requests_pb2.RxRequest()
            msg.ParseFromString(payload)
            return "RxRequest", msg
        elif last == "command":
            msg = rx_commands_pb2.RxCommand()
            msg.ParseFromString(payload)
            return "RxCommand", msg
    except Exception as e:
        # If parsing fails, try guessing envelope from message content
        for cls, name in [
            (rx_course_pb2.RxCourse, "RxCourse"),
            (rx_reports_pb2.RxReport, "RxReport"),
            (rx_requests_pb2.RxRequest, "RxRequest"),
            (rx_commands_pb2.RxCommand, "RxCommand"),
        ]:
            try:
                msg = cls()
                msg.ParseFromString(payload)
                return name, msg
            except Exception:
                pass

    return None, None
