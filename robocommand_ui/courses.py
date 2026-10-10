"""Course network table from Team Handbook §3.4 (Network Topology).

Each course has its own team network and a RoboCommand host at ``.2``. The
team OCS/GCS gets a DHCP address on that network and reports to the host;
the host runs the broker on port 1883. Qt-free so report.py can import it.
"""

import ipaddress
import socket
import struct
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

MQTT_PORT = 1883
TOPIC_ROOT = "robocommand/robotx"


class Course(NamedTuple):
    key: str
    name: str
    network: str        # team network CIDR, or "" when not fixed
    host: str           # RoboCommand broker address, or "" when not fixed


COURSES: Dict[str, Course] = {
    "alpha": Course("alpha", "Course Alpha", "192.168.65.0/24", "192.168.65.2"),
    "bravo": Course("bravo", "Course Bravo", "192.168.66.0/24", "192.168.66.2"),
    "charlie": Course("charlie", "Course Charlie", "192.168.67.0/24", "192.168.67.2"),
    "delta": Course("delta", "Course Delta", "192.168.68.0/24", "192.168.68.2"),
    # Team Village demo: address comes with the demo connection instructions.
    "demo": Course("demo", "Team Village Demo", "", ""),
    # Development: a broker on this machine.
    "local": Course("local", "Local broker", "", "127.0.0.1"),
}


def resolve_host(course_key: str, host_override: Optional[str] = None) -> str:
    """Return the RoboCommand broker address for a course.

    ``host_override`` wins when given. The demo course has no fixed address,
    so it requires an override.
    """
    if host_override:
        return host_override
    key = course_key.lower()
    if key not in COURSES:
        raise ValueError(f"unknown course '{course_key}' (choose from {', '.join(COURSES)})")
    course = COURSES[key]
    if not course.host:
        raise ValueError(f"{course.name} has no fixed RoboCommand address; pass --host")
    return course.host


def course_for_address(address: str) -> Optional[Course]:
    """Return the course whose team network contains ``address``, if any."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return None
    for course in COURSES.values():
        if course.network and ip in ipaddress.ip_network(course.network):
            return course
    return None


def course_hosts() -> List[Course]:
    """Every course with a fixed RoboCommand host, in handbook order."""
    return [c for c in COURSES.values() if c.network]


def local_ipv4_addresses() -> List[Tuple[str, str]]:
    """(interface, IPv4 address) for every interface that has an address.

    On Linux this asks each interface for its address (SIOCGIFADDR), which is
    exactly what DHCP assigned. Elsewhere it falls back to the hostname lookup.
    """
    found: List[Tuple[str, str]] = []
    try:
        import fcntl
        siocgifaddr = 0x8915
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            for _, name in socket.if_nameindex():
                req = struct.pack("256s", name[:15].encode())
                try:
                    res = fcntl.ioctl(s.fileno(), siocgifaddr, req)
                except OSError:
                    continue            # interface down or has no IPv4
                found.append((name, socket.inet_ntoa(res[20:24])))
    except (ImportError, OSError):
        pass
    if not found:
        try:
            for addr in socket.gethostbyname_ex(socket.gethostname())[2]:
                found.append(("?", addr))
        except OSError:
            pass
    return found


def tcp_reachable(host: str, port: int = MQTT_PORT, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class Detection(NamedTuple):
    course: Optional[Course]
    interface: str
    local_address: str
    log: List[str]


def detect_course(probe: Callable[[str], bool] = tcp_reachable,
                  addresses: Optional[List[Tuple[str, str]]] = None) -> Detection:
    """Find which course host this GCS is connected to.

    1. List every course host IP.
    2. Match this machine's DHCP addresses against each course network.
    3. Confirm the matching host answers on TCP 1883. When several courses
       match (unlikely) the first reachable one wins. When none match, probe
       every host so a routed setup still works.
    """
    log = ["Course hosts: " + ", ".join(f"{c.name}={c.host}" for c in course_hosts())]
    addresses = local_ipv4_addresses() if addresses is None else addresses
    log.append("Local addresses: " + (", ".join(f"{i}={a}" for i, a in addresses) or "none"))

    matches = []
    for iface, addr in addresses:
        course = course_for_address(addr)
        if course:
            matches.append((course, iface, addr))
            log.append(f"{iface} {addr} is on {course.name} network {course.network}")

    for course, iface, addr in matches:
        if probe(course.host):
            log.append(f"{course.host}:{MQTT_PORT} reachable -> using {course.name}")
            return Detection(course, iface, addr, log)
        log.append(f"{course.host}:{MQTT_PORT} not reachable from {iface}")

    if not matches:
        log.append("No DHCP address on a course network; probing every host")
        for course in course_hosts():
            if probe(course.host):
                log.append(f"{course.host}:{MQTT_PORT} reachable -> using {course.name}")
                return Detection(course, "", "", log)

    log.append("No course host found")
    return Detection(None, "", "", log)
