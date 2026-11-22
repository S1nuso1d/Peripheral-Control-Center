"""Dialog that lists every HID interface, including devices without battery data."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from device_inventory import discover_hid_interfaces
from i18n import tr


class DeviceInventoryDialog(QDialog):
    """Read-only inventory of HID interfaces visible to hidapi."""

    COLUMNS = (
        "inventory_device",
        "inventory_manufacturer",
        "inventory_vid_pid",
        "inventory_interface",
        "inventory_usage_page",
        "inventory_usage",
        "inventory_transport",
        "inventory_protocol",
    )

    def __init__(self, parent=None, discover_fn=None):
        super().__init__(parent)
        self._discover = discover_fn or discover_hid_interfaces
        self._devices = []

        self.setWindowTitle(tr("inventory_title"))
        self.resize(1120, 520)

        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([tr(key) for key in self.COLUMNS])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setMinimumSectionSize(82)
        layout.addWidget(self.table)

        hint = QLabel(tr("inventory_hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        self.refresh_button = QPushButton(tr("inventory_refresh"))
        self.copy_button = QPushButton(tr("inventory_copy"))
        close_button = QPushButton(tr("close"))
        self.refresh_button.clicked.connect(self.refresh)
        self.copy_button.clicked.connect(self.copy_report)
        close_button.clicked.connect(self.accept)
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.copy_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self.refresh()

    def refresh(self):
        try:
            devices = self._discover()
        except Exception as exc:
            self._devices = []
            self.table.setRowCount(0)
            self.summary.setText(tr("inventory_error", str(exc)))
            return

        self._devices = list(devices)
        self.table.setRowCount(len(self._devices))
        for row, device in enumerate(self._devices):
            values = (
                device["product"],
                device["manufacturer"],
                f'{device["vendor_id"]:04X}:{device["product_id"]:04X}',
                str(device["interface_number"]),
                f'0x{device["usage_page"]:04X} · {device["usage_page_name"]}',
                f'0x{device["usage"]:04X}',
                device["transport"],
                device["protocol_hint"],
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, device["id"])
                self.table.setItem(row, column, item)

        count = len(self._devices)
        self.summary.setText(
            tr("inventory_count", count) if count else tr("inventory_empty")
        )
        self.table.resizeColumnsToContents()

    def report_text(self) -> str:
        """Return a copyable report without raw HID paths or serial numbers."""
        lines = [tr("inventory_report_title"), tr("inventory_count", len(self._devices)), ""]
        for device in self._devices:
            lines.append(
                f'{device["product"]} | {device["manufacturer"]} | '
                f'{device["vendor_id"]:04X}:{device["product_id"]:04X} | '
                f'interface {device["interface_number"]} | '
                f'usage page 0x{device["usage_page"]:04X} | '
                f'usage 0x{device["usage"]:04X} | {device["transport"]} | '
                f'{device["protocol_hint"]} | id {device["id"]}'
            )
        return "\n".join(lines)

    def copy_report(self):
        QApplication.clipboard().setText(self.report_text())
        self.summary.setText(tr("inventory_copied"))
