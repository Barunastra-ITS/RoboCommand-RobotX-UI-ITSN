"""Unit tests for RxCourse validation (Team Handbook 3.4.9)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from robocommand_ui.proto_helper import common_pb2, rx_course_pb2
from robocommand_ui.widgets.course_panel import validate_course

CLOSED_RING = [
    common_pb2.LatLng(latitude=1.280329, longitude=103.8556869),
    common_pb2.LatLng(latitude=1.2804716, longitude=103.8554529),
    common_pb2.LatLng(latitude=1.2808993, longitude=103.8557337),
    common_pb2.LatLng(latitude=1.2807567, longitude=103.8559743),
    common_pb2.LatLng(latitude=1.280329, longitude=103.8556869),
]


def make_course(corners=None, course_id="ALPHA", pinger=25000):
    return rx_course_pb2.RxCourse(
        course_id=course_id,
        pinger_freq_hz=pinger,
        corners=list(CLOSED_RING if corners is None else corners),
    )


class TestValidateCourse(unittest.TestCase):
    def test_valid_closed_ring(self):
        self.assertEqual(validate_course(make_course()), [])

    def test_vendored_test_client_default_is_rejected(self):
        """The vendored test_client.py course default is 4 corners, first != last."""
        corners = [
            common_pb2.LatLng(latitude=21.310, longitude=-157.890),
            common_pb2.LatLng(latitude=21.310, longitude=-157.884),
            common_pb2.LatLng(latitude=21.305, longitude=-157.884),
            common_pb2.LatLng(latitude=21.305, longitude=-157.890),
        ]
        issues = validate_course(make_course(corners))
        self.assertTrue(any("not a closed polygon" in i for i in issues), issues)

    def test_open_ring_rejected(self):
        corners = CLOSED_RING[:-1]  # drop the closing point
        issues = validate_course(make_course(corners))
        self.assertTrue(any("not a closed polygon" in i for i in issues), issues)

    def test_empty_course_id(self):
        issues = validate_course(make_course(course_id=""))
        self.assertTrue(any("course_id is empty" in i for i in issues), issues)

    def test_zero_pinger_frequency(self):
        issues = validate_course(make_course(pinger=0))
        self.assertTrue(any("pinger_freq_hz is zero" in i for i in issues), issues)

    def test_too_few_corners(self):
        corners = [
            common_pb2.LatLng(latitude=1.0, longitude=2.0),
            common_pb2.LatLng(latitude=1.0, longitude=3.0),
        ]
        issues = validate_course(make_course(corners))
        self.assertTrue(any("corner" in i for i in issues), issues)

    def test_latitude_out_of_range(self):
        corners = [
            common_pb2.LatLng(latitude=91.0, longitude=103.8),
            common_pb2.LatLng(latitude=1.28, longitude=103.8),
            common_pb2.LatLng(latitude=1.28, longitude=103.9),
            common_pb2.LatLng(latitude=1.28, longitude=103.8),
            common_pb2.LatLng(latitude=91.0, longitude=103.8),
        ]
        issues = validate_course(make_course(corners))
        self.assertTrue(any("latitude" in i for i in issues), issues)

    def test_longitude_out_of_range(self):
        corners = [
            common_pb2.LatLng(latitude=1.28, longitude=200.0),
            common_pb2.LatLng(latitude=1.28, longitude=103.8),
            common_pb2.LatLng(latitude=1.29, longitude=103.8),
            common_pb2.LatLng(latitude=1.28, longitude=200.0),
        ]
        issues = validate_course(make_course(corners))
        self.assertTrue(any("longitude" in i for i in issues), issues)

    def test_multiple_problems_reported(self):
        issues = validate_course(make_course(course_id="", pinger=0))
        self.assertGreaterEqual(len(issues), 2, issues)


if __name__ == "__main__":
    unittest.main(verbosity=2)