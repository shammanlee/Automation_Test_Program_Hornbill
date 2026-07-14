"""User-facing table and controls for pending test runs."""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QGridLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class TestQueueWidget(QGroupBox):
    run_requested = pyqtSignal()
    remove_requested = pyqtSignal(str)
    move_requested = pyqtSignal(str, int)
    clear_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Test Queue", parent)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "DUT", "Tests", "Status"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setMinimumHeight(190)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        self.run_button = QPushButton("Run Queue")
        self.remove_button = QPushButton("Remove")
        self.up_button = QPushButton("Move Up")
        self.down_button = QPushButton("Move Down")
        self.clear_button = QPushButton("Clear Pending")
        self.run_button.setToolTip("Start pending tests in displayed order")
        self.remove_button.setToolTip("Remove the selected pending test")
        self.up_button.setToolTip("Move the selected pending test earlier")
        self.down_button.setToolTip("Move the selected pending test later")
        self.clear_button.setToolTip("Remove every test that has not started")

        controls = QGridLayout()
        controls.addWidget(self.run_button, 0, 0, 1, 2)
        controls.addWidget(self.clear_button, 0, 2, 1, 2)
        controls.addWidget(self.remove_button, 1, 0)
        controls.addWidget(self.up_button, 1, 1)
        controls.addWidget(self.down_button, 1, 2, 1, 2)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(controls)

        self.run_button.clicked.connect(self.run_requested)
        self.remove_button.clicked.connect(self._request_remove)
        self.up_button.clicked.connect(lambda: self._request_move(-1))
        self.down_button.clicked.connect(lambda: self._request_move(1))
        self.clear_button.clicked.connect(self.clear_requested)

    def add_request(self, request):
        row = self.table.rowCount()
        self.table.insertRow(row)
        selected = [name for name, enabled in request.checkbox_states.items() if enabled]
        values = (
            request.label,
            str(request.configuration.get("DUT", "")),
            ", ".join(selected),
            "Pending",
        )
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setData(Qt.UserRole, request.run_id)
            self.table.setItem(row, column, item)

    def update_status(self, request, status):
        row = self._row_for(request.run_id)
        if row is None:
            return
        status_item = self.table.item(row, 3)
        status_item.setText(status)
        status_colors = {
            "Pending": QColor("#805500"),
            "Running": QColor("#0057b8"),
            "Completed": QColor("#167c2f"),
            "Failed": QColor("#b00020"),
            "Aborted": QColor("#8a3b12"),
        }
        if status in status_colors:
            status_item.setForeground(QBrush(status_colors[status]))
        if status == "Removed":
            self.table.removeRow(row)

    def reorder(self, requests):
        order = {request.run_id: index for index, request in enumerate(requests)}
        rows = []
        while self.table.rowCount():
            rows.append([self.table.takeItem(0, column) for column in range(4)])
            self.table.removeRow(0)
        rows.sort(
            key=lambda items: order.get(items[0].data(Qt.UserRole), len(order))
        )
        for items in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for column, item in enumerate(items):
                self.table.setItem(row, column, item)

    def selected_run_id(self):
        row = self.table.currentRow()
        if row < 0 or not self.table.item(row, 0):
            return None
        return self.table.item(row, 0).data(Qt.UserRole)

    def _row_for(self, run_id):
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.UserRole) == run_id:
                return row
        return None

    def _request_remove(self):
        run_id = self.selected_run_id()
        if run_id:
            self.remove_requested.emit(run_id)

    def _request_move(self, offset):
        run_id = self.selected_run_id()
        if run_id:
            self.move_requested.emit(run_id, offset)
