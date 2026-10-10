"""RxCourse validation (Team Handbook §3.4.9). Qt-free so report.py can use it."""


def validate_course(course):
    """Check RxCourse against the Team Handbook 3.4.9 before a run begins.

    Returns a list of human-readable problems; empty means the course is
    usable. RoboCommand validates the UAV geofence against the course
    boundary, so an unusable boundary would stall the run at RunStart.
    """
    issues = []
    if not course.course_id:
        issues.append("course_id is empty")

    if not course.pinger_freq_hz:
        issues.append("pinger_freq_hz is zero")

    corners = course.corners
    if len(corners) < 3:
        issues.append(f"boundary has only {len(corners)} corner(s) (need >= 3)")

    for i, c in enumerate(corners):
        if not (-90.0 <= c.latitude <= 90.0):
            issues.append(f"corner {i + 1} latitude {c.latitude} out of range")
        if not (-180.0 <= c.longitude <= 180.0):
            issues.append(f"corner {i + 1} longitude {c.longitude} out of range")

    if len(corners) >= 2:
        first, last = corners[0], corners[-1]
        if first.latitude != last.latitude or first.longitude != last.longitude:
            issues.append(
                "boundary is not a closed polygon "
                f"(first corner {first.latitude:.7f},{first.longitude:.7f} "
                f"!= last corner {last.latitude:.7f},{last.longitude:.7f})"
            )

    return issues
