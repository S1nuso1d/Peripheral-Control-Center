"""Окно «Настроить устройства»: показывать/скрывать, своё название, тип значка."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHeaderView, QLabel,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from i18n import tr

KINDS = ["device", "headphones", "mouse", "keyboard", "gamepad", "phone"]


class DevicesDialog(QDialog):
    def __init__(self, devices, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("dlg_title"))
        self.resize(660, 380)

        names, kinds = settings["names"], settings["kinds"]
        hidden = set(settings["hidden"])
        self.auto = {d["orig"]: d.get("auto_kind", d["kind"]) for d in devices}
        self.rows = sorted(set(self.auto) | set(names) | set(kinds) | hidden,
                           key=str.lower)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("dlg_hint")))

        self.table = QTableWidget(len(self.rows), 4)
        self.table.setHorizontalHeaderLabels(
            [tr("col_show"), tr("col_device"), tr("col_name"), tr("col_type")])
        self.table.verticalHeader().setVisible(False)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.Stretch)
        head.setSectionResizeMode(2, QHeaderView.Stretch)
        head.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        for r, orig in enumerate(self.rows):
            show = QTableWidgetItem()
            show.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            show.setCheckState(Qt.Unchecked if orig in hidden else Qt.Checked)
            self.table.setItem(r, 0, show)

            name = QTableWidgetItem(orig)
            name.setFlags(Qt.ItemIsEnabled)  # исходное имя не редактируется
            self.table.setItem(r, 1, name)

            self.table.setItem(r, 2, QTableWidgetItem(names.get(orig, "")))

            combo = QComboBox()
            for k in KINDS:
                combo.addItem(tr("kind_" + k), k)
            current = kinds.get(orig) or self.auto.get(orig, "device")
            combo.setCurrentIndex(max(combo.findData(current), 0))
            self.table.setCellWidget(r, 3, combo)
        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr("ok"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_data(self):
        """(names, kinds, hidden): храним только то, что отличается от автоопределения."""
        names, kinds, hidden = {}, {}, []
        for r, orig in enumerate(self.rows):
            if self.table.item(r, 0).checkState() != Qt.Checked:
                hidden.append(orig)
            custom = self.table.item(r, 2).text().strip()
            if custom and custom != orig:
                names[orig] = custom
            kind = self.table.cellWidget(r, 3).currentData()
            if kind != self.auto.get(orig, "device"):
                kinds[orig] = kind
        return names, kinds, hidden
