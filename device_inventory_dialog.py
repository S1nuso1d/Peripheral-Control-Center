"""Read-only HID and Windows PnP inventory window."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QDialog, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from device_inventory import discover_hid_interfaces
from device_correlator import correlate_hid_to_pnp
from i18n import tr
from windows_device_inventory import discover_windows_devices


class DeviceInventoryDialog(QDialog):
    """Show HID interfaces and Windows PnP nodes without issuing device commands."""

    HID_COLUMNS = (
        "inventory_device", "inventory_manufacturer", "inventory_vid_pid",
        "inventory_interface", "inventory_usage_page", "inventory_usage",
        "inventory_transport", "inventory_pnp_matches", "inventory_protocol",
    )
    WINDOWS_COLUMNS = (
        "inventory_device", "inventory_manufacturer", "inventory_vid_pid",
        "inventory_class", "inventory_transport", "inventory_battery",
        "inventory_battery_source", "inventory_charging", "inventory_status",
    )

    def __init__(self, parent=None, discover_fn=None, discover_windows_fn=None):
        super().__init__(parent)
        self._discover = discover_fn or discover_hid_interfaces
        self._discover_windows = discover_windows_fn or discover_windows_devices
        self._devices = []
        self._windows_devices = []
        self._pnp_matches = {}

        self.setWindowTitle(tr("inventory_title"))
        self.resize(1320, 600)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        hid_page = QWidget()
        hid_layout = QVBoxLayout(hid_page)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        hid_layout.addWidget(self.summary)
        self.table = self._make_table(self.HID_COLUMNS)
        hid_layout.addWidget(self.table)
        self.hid_hint = QLabel(tr("inventory_hint"))
        self.hid_hint.setWordWrap(True)
        hid_layout.addWidget(self.hid_hint)
        self.tabs.addTab(hid_page, tr("inventory_tab_hid"))

        windows_page = QWidget()
        windows_layout = QVBoxLayout(windows_page)
        self.windows_summary = QLabel()
        self.windows_summary.setWordWrap(True)
        windows_layout.addWidget(self.windows_summary)
        self.windows_table = self._make_table(self.WINDOWS_COLUMNS)
        windows_layout.addWidget(self.windows_table)
        self.windows_hint = QLabel(tr("windows_inventory_hint"))
        self.windows_hint.setWordWrap(True)
        windows_layout.addWidget(self.windows_hint)
        self.tabs.addTab(windows_page, tr("inventory_tab_windows"))

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

    @staticmethod
    def _make_table(columns):
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels([tr(key) for key in columns])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(False)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setMinimumSectionSize(82)
        return table

    @staticmethod
    def _fill_table(table, devices, values_fn):
        table.setRowCount(len(devices))
        for row, device in enumerate(devices):
            for column, value in enumerate(values_fn(device)):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, device["id"])
                table.setItem(row, column, item)
        table.resizeColumnsToContents()

    def refresh(self):
        hid_error = None
        windows_error = None
        try:
            self._devices = list(self._discover())
        except Exception as exc:
            self._devices = []
            hid_error = str(exc)
        try:
            self._windows_devices = list(self._discover_windows())
        except Exception as exc:
            self._windows_devices = []
            windows_error = str(exc)

        self._pnp_matches = correlate_hid_to_pnp(self._devices, self._windows_devices)
        self._fill_table(
            self.table, self._devices,
            lambda device: (
                device["product"], device["manufacturer"],
                f'{device["vendor_id"]:04X}:{device["product_id"]:04X}',
                device["interface_number"],
                f'0x{device["usage_page"]:04X} · {device["usage_page_name"]}',
                f'0x{device["usage"]:04X}', device["transport"],
                len(self._pnp_matches.get(device["id"], [])),
                device["protocol_hint"],
            ),
        )
        self._fill_table(
            self.windows_table, self._windows_devices,
            lambda device: (
                device["name"], device["manufacturer"], device["vid_pid"],
                device["device_class"], device["transport"],
                (f'≈{device["battery"]}%' if device.get("battery_precision") == "coarse"
                 else f'{device["battery"]}%') if device["battery"] is not None else "—",
                device.get("battery_source") or "—",
                tr("charging") if device.get("charging_known") and device.get("charging")
                else tr("not_charging") if device.get("charging_known") else "—",
                device["status"],
            ),
        )

        hid_count = len(self._devices)
        windows_count = len(self._windows_devices)
        self.summary.setText(
            tr("inventory_error", hid_error) if hid_error else
            tr("inventory_count", hid_count) if hid_count else tr("inventory_empty")
        )
        self.windows_summary.setText(
            tr("windows_inventory_error", windows_error) if windows_error else
            tr("windows_inventory_count", windows_count) if windows_count else
            tr("windows_inventory_empty")
        )

    def report_text(self) -> str:
        """Return both inventories without raw HID/PnP instance paths or serial numbers."""
        lines = [tr("inventory_report_title"),
                 tr("inventory_count", len(self._devices)), ""]
        for device in self._devices:
            candidates = self._pnp_matches.get(device["id"], [])
            lines.append(
                f'HID | {device["product"]} | {device["manufacturer"]} | '
                f'{device["vendor_id"]:04X}:{device["product_id"]:04X} | '
                f'interface {device["interface_number"]} | '
                f'usage page 0x{device["usage_page"]:04X} | '
                f'usage 0x{device["usage"]:04X} | {device["transport"]} | '
                f'PnP candidates: {len(candidates)} | '
                f'{device["protocol_hint"]} | id {device["id"]}'
            )
            for candidate in candidates:
                lines.append(
                    f'  candidate only (not merged): {candidate["name"]} | '
                    f'{candidate["device_class"]} | {candidate["transport"]} | '
                    f'id {candidate["id"]}'
                )

        lines.extend(["", tr("windows_inventory_count", len(self._windows_devices))])
        for device in self._windows_devices:
            battery = f'{device["battery"]}%' if device["battery"] is not None else "unknown"
            lines.append(
                f'PnP | {device["name"]} | {device["manufacturer"]} | '
                f'{device["vid_pid"]} | {device["device_class"]} | '
                f'{device["transport"]} | battery {battery} | '
                f'precision {device.get("battery_precision", "reported")} | '
                f'battery source {device.get("battery_source") or "unknown"} | '
                f'charging {device.get("charging") if device.get("charging_known") else "unknown"} | '
                f'status {device["status"]} | id {device["id"]}'
            )
        return "\n".join(lines)

    def copy_report(self):
        QApplication.clipboard().setText(self.report_text())
        active_summary = self.windows_summary if self.tabs.currentIndex() == 1 else self.summary
        active_summary.setText(tr("inventory_copied"))
