"""Retained RxCourse summary with its §3.4.9 validity."""

import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView, QGridLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem,
)

from robocommand_ui import theme
from robocommand_ui.course_validation import validate_course
from robocommand_ui.widgets.panel import Panel, make_chip, set_chip


class CoursePanel(Panel):
    def __init__(self, parent=None):
        super().__init__("Course", parent)
        self.valid_chip = make_chip("WAITING", theme.IDLE)
        self.actions.addWidget(self.valid_chip)
        self.corners_btn = QPushButton("Corners")
        self.corners_btn.setObjectName("Ghost")
        self.corners_btn.setCheckable(True)
        self.corners_btn.setCursor(Qt.PointingHandCursor)
        self.corners_btn.setEnabled(False)
        self.actions.addWidget(self.corners_btn)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(3)
        self.course_id_label = self._row(grid, 0, "Course ID")
        self.pinger_label = self._row(grid, 1, "Pinger")
        self.corners_label = self._row(grid, 2, "Corners")
        self.transit_label = self._row(grid, 3, "UAV transit")
        self.timestamp_label = self._row(grid, 4, "Published")
        grid.setColumnStretch(1, 1)
        self.body.addLayout(grid)

        self.validation_label = QLabel("No course")
        self.validation_label.setObjectName("Faint")
        self.validation_label.setWordWrap(True)
        self.body.addWidget(self.validation_label)

        self.corner_table = QTableWidget(0, 2)
        self.corner_table.setHorizontalHeaderLabels(["Latitude", "Longitude"])
        self.corner_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.corner_table.verticalHeader().setDefaultSectionSize(24)
        self.corner_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.corner_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.corner_table.setMaximumHeight(170)
        self.corner_table.setVisible(False)
        self.body.addWidget(self.corner_table)
        self.corners_btn.toggled.connect(self.corner_table.setVisible)

    @staticmethod
    def _row(grid, row, name):
        n = QLabel(name)
        n.setObjectName("Faint")
        v = QLabel("—")
        v.setFont(theme.mono_font(9.5))
        grid.addWidget(n, row, 0)
        grid.addWidget(v, row, 1)
        return v

    def update_course(self, course):
        self.course_id_label.setText(course.course_id or "—")
        self.pinger_label.setText(f"{course.pinger_freq_hz} Hz")
        self.corners_label.setText(str(len(course.corners)))
        self.transit_label.setText(f"{len(course.uav_transit_area)} points"
                                   if course.uav_transit_area else "none")
        if course.sent_at and course.sent_at.seconds:
            ts = datetime.datetime.fromtimestamp(course.sent_at.seconds)
            self.timestamp_label.setText(ts.strftime("%Y-%m-%d %H:%M:%S"))
        else:
            self.timestamp_label.setText("—")

        self.corner_table.setRowCount(len(course.corners))
        for i, corner in enumerate(course.corners):
            for col, val in enumerate((corner.latitude, corner.longitude)):
                item = QTableWidgetItem(f"{val:.9f}")
                item.setFont(theme.mono_font(9))
                self.corner_table.setItem(i, col, item)
        self.corners_btn.setEnabled(True)

        issues = validate_course(course)
        if issues:
            set_chip(self.valid_chip, "INVALID", theme.FAULT)
            self.validation_label.setText("INVALID: " + "; ".join(issues))
            self.validation_label.setStyleSheet(f"color: {theme.FAULT};")
        else:
            set_chip(self.valid_chip, "VALID", theme.OK)
            self.validation_label.setText("")
            self.validation_label.setStyleSheet(f"color: {theme.TEXT_FAINT};")
