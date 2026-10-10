"""Course Configuration display widget."""

from PyQt5.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView,
)
from PyQt5.QtCore import Qt

from robocommand_ui.course_validation import validate_course


class CoursePanel(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Course Configuration (RxCourse)", parent)
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 6px;
                margin-top: 8px;
                padding: 12px 8px 8px 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
            }
            QLabel {
                color: #cdd6f4;
            }
        """)

        layout = QVBoxLayout(self)

        info_layout = QHBoxLayout()
        self.course_id_label = QLabel("Course ID: ---")
        self.course_id_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #89b4fa;")
        info_layout.addWidget(self.course_id_label)

        self.pinger_label = QLabel("Pinger Freq: --- Hz")
        self.pinger_label.setStyleSheet("font-size: 14px; color: #f9e2af;")
        info_layout.addWidget(self.pinger_label)

        self.timestamp_label = QLabel("Received: ---")
        self.timestamp_label.setStyleSheet("font-size: 12px; color: #6c7086;")
        info_layout.addWidget(self.timestamp_label)
        info_layout.addStretch()
        layout.addLayout(info_layout)

        self.corner_table = QTableWidget(0, 2)
        self.corner_table.setHorizontalHeaderLabels(["Latitude", "Longitude"])
        self.corner_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.corner_table.setMaximumHeight(160)
        self.corner_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.corner_table.setStyleSheet("""
            QTableWidget {
                background-color: #1e1e2e;
                color: #cdd6f4;
                gridline-color: #45475a;
            }
            QHeaderView::section {
                background-color: #313244;
                color: #cdd6f4;
                font-weight: bold;
                border: 1px solid #45475a;
            }
        """)
        layout.addWidget(self.corner_table)

        self.validation_label = QLabel("Awaiting RxCourse from broker...")
        self.validation_label.setWordWrap(True)
        self.validation_label.setStyleSheet("color: #6c7086; font-style: italic; font-size: 12px; padding: 2px;")
        layout.addWidget(self.validation_label)

        self._no_data_label = QLabel("Awaiting RxCourse from broker...")
        self._no_data_label.setAlignment(Qt.AlignCenter)
        self._no_data_label.setStyleSheet("color: #6c7086; font-style: italic;")
        layout.addWidget(self._no_data_label)

    def update_course(self, course):
        import datetime
        self._no_data_label.hide()
        self.course_id_label.setText(f"Course ID: {course.course_id}")
        self.pinger_label.setText(f"Pinger Freq: {course.pinger_freq_hz} Hz")

        if course.sent_at and course.sent_at.seconds:
            ts = datetime.datetime.fromtimestamp(course.sent_at.seconds)
            self.timestamp_label.setText(f"Received: {ts.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            self.timestamp_label.setText("Received: now")

        self.corner_table.setRowCount(len(course.corners))
        for i, corner in enumerate(course.corners):
            self.corner_table.setItem(i, 0, QTableWidgetItem(f"{corner.latitude:.7f}"))
            self.corner_table.setItem(i, 1, QTableWidgetItem(f"{corner.longitude:.7f}"))

        issues = validate_course(course)
        self.validation_label.setText("Valid course configuration" if not issues
                                     else "INVALID: " + "; ".join(issues))
        if issues:
            self.validation_label.setStyleSheet(
                "color: #f38ba8; font-weight: bold; font-size: 12px; padding: 2px;")
        else:
            self.validation_label.setStyleSheet(
                "color: #a6e3a1; font-size: 12px; padding: 2px;")

