# -*- coding: utf-8 -*-
"""数据编辑器：可视化增删改城市、线路、车站、站间时长、班次等。"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QSplitter,
    QComboBox, QLineEdit, QListWidget, QListWidgetItem, QLabel, QPushButton,
    QDoubleSpinBox, QColorDialog, QCheckBox, QMessageBox, QInputDialog,
    QPlainTextEdit,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

from ..core.models import (
    City, Line, Direction, TYPE_LABELS,
    TYPE_METRO, TYPE_SUBURBAN, TYPE_TRAM, TYPE_BUS, TYPE_RAIL, TYPE_MAGLEV,
)

TYPE_CHOICES = [(TYPE_METRO, "地铁"), (TYPE_SUBURBAN, "市域铁路"), (TYPE_TRAM, "有轨电车"),
                (TYPE_BUS, "公交"), (TYPE_RAIL, "国家铁路"), (TYPE_MAGLEV, "磁浮")]


def swatch(color_hex: str, color2: str = "", size: int = 16) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(color_hex))
    if color2 and color2.lower() != color_hex.lower():
        p = QPainter(pm)
        p.fillRect(0, int(size * 0.62), size, size - int(size * 0.62), QColor(color2))
        p.end()
    return QIcon(pm)


class DataEditor(QDialog):
    def __init__(self, library, parent=None):
        super().__init__(parent)
        self.lib = library
        self.cities: dict[str, City] = {}
        self.current_city: City | None = None
        self.current_line: Line | None = None
        self._line_color = "#888888"
        self._line_color2 = ""
        self.setWindowTitle("数据编辑器")
        self.resize(1100, 700)
        self._build_ui()
        self._reload_cities()

    def _build_ui(self):
        root = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("城市："))
        self.cb_city = QComboBox()
        self.cb_city.currentTextChanged.connect(self._on_city_changed)
        top.addWidget(self.cb_city)
        self.btn_new_city = QPushButton("新建城市")
        self.btn_new_city.clicked.connect(self._new_city)
        top.addWidget(self.btn_new_city)
        self.btn_del_city = QPushButton("删除城市")
        self.btn_del_city.clicked.connect(self._del_city)
        top.addWidget(self.btn_del_city)
        top.addStretch(1)
        self.btn_save = QPushButton("保存全部")
        self.btn_save.clicked.connect(self._save_all)
        top.addWidget(self.btn_save)
        btn_close = QPushButton("保存并关闭")
        btn_close.clicked.connect(self._save_and_close)
        top.addWidget(btn_close)
        root.addLayout(top)

        split = QSplitter(Qt.Horizontal)

        # 左：线路列表
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel("线路："))
        self.list_lines = QListWidget()
        self.list_lines.currentItemChanged.connect(self._on_line_selected)
        lv.addWidget(self.list_lines)
        row = QHBoxLayout()
        b = QPushButton("新增线路")
        b.clicked.connect(self._new_line)
        row.addWidget(b)
        b = QPushButton("删除线路")
        b.clicked.connect(self._del_line)
        row.addWidget(b)
        lv.addLayout(row)
        split.addWidget(left)

        # 右：线路编辑
        right = QWidget()
        rv = QVBoxLayout(right)
        form = QGridLayout()

        form.addWidget(QLabel("线路ID"), 0, 0)
        self.ed_id = QLineEdit()
        form.addWidget(self.ed_id, 0, 1)
        form.addWidget(QLabel("名称"), 0, 2)
        self.ed_name = QLineEdit()
        form.addWidget(self.ed_name, 0, 3)
        form.addWidget(QLabel("简称"), 0, 4)
        self.ed_short = QLineEdit()
        form.addWidget(self.ed_short, 0, 5)

        form.addWidget(QLabel("类型"), 1, 0)
        self.cb_type = QComboBox()
        for key, label in TYPE_CHOICES:
            self.cb_type.addItem(label, key)
        form.addWidget(self.cb_type, 1, 1)
        form.addWidget(QLabel("标志色"), 1, 2)
        self.btn_color = QPushButton()
        self.btn_color.clicked.connect(self._pick_color)
        self.btn_color.setFixedWidth(70)
        form.addWidget(self.btn_color, 1, 3)
        form.addWidget(QLabel("副色(双色)"), 1, 4)
        self.btn_color2 = QPushButton()
        self.btn_color2.clicked.connect(self._pick_color2)
        self.btn_color2.setFixedWidth(70)
        form.addWidget(self.btn_color2, 1, 5)
        self.chk_clear_color2 = QCheckBox("清除副色")
        self.chk_clear_color2.setToolTip("国铁可设黑白双色、上海磁浮等双色线路")
        form.addWidget(self.chk_clear_color2, 2, 6, 1, 2)
        form.addWidget(QLabel("运营方"), 1, 6)
        self.ed_operator = QLineEdit()
        form.addWidget(self.ed_operator, 1, 7)

        form.addWidget(QLabel("高峰间隔(分)"), 2, 0)
        self.sp_rush = QDoubleSpinBox()
        self.sp_rush.setRange(1, 240)
        form.addWidget(self.sp_rush, 2, 1)
        form.addWidget(QLabel("平峰间隔(分)"), 2, 2)
        self.sp_normal = QDoubleSpinBox()
        self.sp_normal.setRange(1, 240)
        form.addWidget(self.sp_normal, 2, 3)
        form.addWidget(QLabel("首班"), 2, 4)
        self.ed_first = QLineEdit()
        self.ed_first.setPlaceholderText("05:30")
        form.addWidget(self.ed_first, 2, 5)

        form.addWidget(QLabel("末班"), 3, 4)
        self.ed_last = QLineEdit()
        self.ed_last.setPlaceholderText("22:30")
        form.addWidget(self.ed_last, 3, 5)
        self.chk_ring = QCheckBox("环线（首尾相连）")
        form.addWidget(self.chk_ring, 3, 0, 1, 2)
        rv.addLayout(form)

        # 方向覆盖
        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("方向标签（每行一个，留空=自动按两端终点站）"))
        self.ed_directions = QPlainTextEdit()
        self.ed_directions.setMaximumHeight(60)
        dir_row.addWidget(self.ed_directions, 1)
        rv.addLayout(dir_row)

        # 站点编辑
        st_box = QVBoxLayout()
        st_box.addWidget(QLabel("站点（按行车顺序）："))
        st_row = QHBoxLayout()
        self.list_stations = QListWidget()
        st_row.addWidget(self.list_stations, 1)
        st_btns = QVBoxLayout()
        for text, slot in [("添加站", self._add_station), ("编辑站名", self._edit_station),
                           ("上移", self._station_up), ("下移", self._station_down),
                           ("删除站", self._del_station)]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            st_btns.addWidget(b)
        st_btns.addStretch(1)
        st_row.addLayout(st_btns)
        st_box.addLayout(st_row)

        mt = QHBoxLayout()
        mt.addWidget(QLabel("选中站→下一站时长(分)："))
        self.sp_seg = QDoubleSpinBox()
        self.sp_seg.setRange(0.5, 120)
        self.sp_seg.valueChanged.connect(self._on_seg_changed)
        mt.addWidget(self.sp_seg)
        mt.addWidget(QLabel("默认站间时长(分)："))
        self.sp_default_seg = QDoubleSpinBox()
        self.sp_default_seg.setRange(0.5, 120)
        self.sp_default_seg.setValue(3.0)
        mt.addWidget(self.sp_default_seg)
        b = QPushButton("套用默认到全线")
        b.clicked.connect(self._apply_default_seg)
        mt.addWidget(b)
        st_box.addLayout(mt)
        rv.addLayout(st_box)

        split.addWidget(right)
        split.setSizes([260, 800])
        root.addWidget(split, 1)

    # ---------------- 城市 ----------------
    def _reload_cities(self):
        self.cities.clear()
        for name in self.lib.list_cities():
            try:
                self.cities[name] = self.lib.load(name)
            except Exception:
                pass
        self.cb_city.blockSignals(True)
        self.cb_city.clear()
        self.cb_city.addItems(sorted(self.cities))
        self.cb_city.blockSignals(False)
        if self.cities:
            self._select_city(sorted(self.cities)[0])

    def _on_city_changed(self, name):
        self._select_city(name)

    def _select_city(self, name):
        if not name or name not in self.cities:
            self.current_city = None
            self.list_lines.clear()
            return
        self.current_city = self.cities[name]
        self._reload_lines()

    def _new_city(self):
        name, ok = QInputDialog.getText(self, "新建城市", "城市名称：")
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in self.cities:
            QMessageBox.information(self, "提示", "该城市已存在")
            return
        city = City(name=name)
        self.cities[name] = city
        self.cb_city.addItem(name)
        self.cb_city.setCurrentText(name)
        self._save_all()

    def _del_city(self):
        if not self.current_city:
            return
        name = self.current_city.name
        if QMessageBox.question(self, "删除城市", f"确定删除城市 {name} 的线路库？") == QMessageBox.Yes:
            self.cities.pop(name, None)
            self.lib.delete(name)
            self._reload_cities()

    # ---------------- 线路 ----------------
    def _reload_lines(self):
        self.list_lines.blockSignals(True)
        self.list_lines.clear()
        for ln in self.current_city.lines:
            item = QListWidgetItem(swatch(ln.color, ln.color2), ln.name)
            item.setData(Qt.UserRole, ln.id)
            self.list_lines.addItem(item)
        self.list_lines.blockSignals(False)
        self._load_line_to_form(None)

    def _selected_line(self):
        item = self.list_lines.currentItem()
        if item is None or self.current_city is None:
            return None
        return self.current_city.line(item.data(Qt.UserRole))

    def _on_line_selected(self, cur, prev):
        if cur is None:
            self._load_line_to_form(None)
            return
        self._load_line_to_form(self.current_city.line(cur.data(Qt.UserRole)))

    def _new_line(self):
        if not self.current_city:
            return
        lid, ok = QInputDialog.getText(self, "新增线路", "线路ID（如 sh_m14）：")
        if not ok or not lid.strip():
            return
        lid = lid.strip()
        if any(l.id == lid for l in self.current_city.lines):
            QMessageBox.information(self, "提示", "ID 已存在")
            return
        line = Line(id=lid, name=lid)
        self.current_city.lines.append(line)
        self._reload_lines()
        for i in range(self.list_lines.count()):
            if self.list_lines.item(i).data(Qt.UserRole) == lid:
                self.list_lines.setCurrentRow(i)
                break

    def _del_line(self):
        line = self._selected_line()
        if line is None:
            return
        if QMessageBox.question(self, "删除线路", f"确定删除 {line.name}？") == QMessageBox.Yes:
            self.current_city.lines.remove(line)
            self._reload_lines()

    # ---------------- 线路表单 ----------------
    def _load_line_to_form(self, line: Line | None):
        self.current_line = line
        if line is None:
            for w in (self.ed_id, self.ed_name, self.ed_short, self.ed_operator,
                      self.ed_first, self.ed_last):
                w.clear()
            self.btn_color.setText("")
            self.btn_color.setStyleSheet("background:#cccccc;")
            self.btn_color2.setText("")
            self.btn_color2.setStyleSheet("background:#cccccc;")
            self.chk_clear_color2.setChecked(False)
            self.cb_type.setCurrentIndex(0)
            self.sp_rush.setValue(5)
            self.sp_normal.setValue(10)
            self.chk_ring.setChecked(False)
            self.ed_directions.clear()
            self.list_stations.clear()
            self.sp_seg.setEnabled(False)
            return
        self.ed_id.setText(line.id)
        self.ed_name.setText(line.name)
        self.ed_short.setText(line.short_name)
        self.ed_operator.setText(line.operator)
        self.ed_first.setText(line.first_train)
        self.ed_last.setText(line.last_train)
        idx = self.cb_type.findData(line.type)
        self.cb_type.setCurrentIndex(max(0, idx))
        self._apply_color(line.color)
        self._apply_color2(line.color2)
        self.chk_clear_color2.setChecked(False)
        self.sp_rush.setValue(line.headway_rush)
        self.sp_normal.setValue(line.headway_normal)
        self.chk_ring.setChecked(line.ring)
        self.ed_directions.setPlainText("\n".join(d.label for d in line.directions))
        self._reload_stations()
        self.sp_seg.setEnabled(True)

    def _apply_color(self, hex_color: str):
        self._line_color = hex_color
        self.btn_color.setText(hex_color)
        self.btn_color.setStyleSheet(f"background:{hex_color};")

    def _apply_color2(self, hex_color: str):
        self._line_color2 = hex_color or ""
        if self._line_color2:
            self.btn_color2.setText(self._line_color2)
            self.btn_color2.setStyleSheet(f"background:{self._line_color2};")
        else:
            self.btn_color2.setText("（无）")
            self.btn_color2.setStyleSheet("")

    def _pick_color(self):
        color = QColorDialog.getColor(QColor(self._line_color))
        if color.isValid():
            self._apply_color(color.name())
            if self.current_line:
                self.current_line.color = color.name()

    def _pick_color2(self):
        color = QColorDialog.getColor(QColor(self._line_color2 or "#ffffff"))
        if color.isValid():
            self._apply_color2(color.name())
            if self.current_line:
                self.current_line.color2 = color.name()

    def _capture_fields(self):
        if self.current_line is None:
            return
        ln = self.current_line
        ln.id = self.ed_id.text().strip() or ln.id
        ln.name = self.ed_name.text().strip() or ln.id
        ln.short_name = self.ed_short.text().strip() or ln.name
        ln.operator = self.ed_operator.text().strip()
        ln.type = self.cb_type.currentData()
        ln.color = getattr(self, "_line_color", "#888888")
        if self.chk_clear_color2.isChecked():
            ln.color2 = ""
        else:
            ln.color2 = getattr(self, "_line_color2", "")
        ln.headway_rush = self.sp_rush.value()
        ln.headway_normal = self.sp_normal.value()
        ln.first_train = self.ed_first.text().strip()
        ln.last_train = self.ed_last.text().strip()
        ln.ring = self.chk_ring.isChecked()
        self._capture_directions(ln)

    def _capture_directions(self, ln: Line):
        labels = [x.strip() for x in self.ed_directions.toPlainText().splitlines() if x.strip()]
        if len(labels) >= 2:
            dirs = []
            for lab in labels:
                terminal = lab[:-2] if lab.endswith("方向") else None
                dirs.append(Direction(label=lab, terminal=terminal))
            ln.directions = dirs
        else:
            # 自动按两端终点站生成
            if len(ln.stations) >= 2:
                first, last = ln.stations[0], ln.stations[-1]
                ln.directions = [
                    Direction(label=f"{last}方向", terminal=last),
                    Direction(label=f"{first}方向", terminal=first),
                ]
            else:
                ln.directions = []

    # ---------------- 站点 ----------------
    def _reload_stations(self):
        self.list_stations.blockSignals(True)
        self.list_stations.clear()
        if self.current_line:
            for i, s in enumerate(self.current_line.stations):
                item = QListWidgetItem(f"{i + 1}. {s}")
                self.list_stations.addItem(item)
        self.list_stations.blockSignals(False)

    def _add_station(self):
        if not self.current_line:
            return
        name, ok = QInputDialog.getText(self, "添加站点", "站点名称：")
        if not ok or not name.strip():
            return
        r = self.list_stations.currentRow()
        idx = r + 1 if r >= 0 else len(self.current_line.stations)
        self.current_line.stations.insert(idx, name.strip())
        self.current_line.travel_minutes.insert(idx, self.sp_default_seg.value())
        self._reload_stations()
        self.list_stations.setCurrentRow(idx)
        self._sync_seg_spin(idx)

    def _edit_station(self):
        r = self.list_stations.currentRow()
        if r < 0 or not self.current_line:
            return
        name, ok = QInputDialog.getText(self, "编辑站点", "站点名称：",
                                        text=self.current_line.stations[r])
        if ok and name.strip():
            self.current_line.stations[r] = name.strip()
            self._reload_stations()
            self.list_stations.setCurrentRow(r)

    def _del_station(self):
        r = self.list_stations.currentRow()
        if r < 0 or not self.current_line:
            return
        if len(self.current_line.stations) <= 2:
            QMessageBox.information(self, "提示", "至少保留 2 个站点")
            return
        del self.current_line.stations[r]
        if r < len(self.current_line.travel_minutes):
            del self.current_line.travel_minutes[r]
        self._reload_stations()

    def _station_up(self):
        self._swap_station(-1)

    def _station_down(self):
        self._swap_station(1)

    def _swap_station(self, d):
        r = self.list_stations.currentRow()
        if r < 0 or not self.current_line:
            return
        n = len(self.current_line.stations)
        j = r + d
        if not (0 <= j < n):
            return
        st = self.current_line.stations
        tm = self.current_line.travel_minutes
        st[r], st[j] = st[j], st[r]
        # 交换相邻站间时长（保持对应关系）
        lo, hi = min(r, j), max(r, j)
        if lo < len(tm) and hi - 1 < len(tm):
            tm[lo], tm[hi - 1] = tm[hi - 1], tm[lo]
        self._reload_stations()
        self.list_stations.setCurrentRow(j)

    def _sync_seg_spin(self, r):
        ln = self.current_line
        if ln and 0 <= r < len(ln.travel_minutes):
            self.sp_seg.blockSignals(True)
            self.sp_seg.setValue(ln.travel_minutes[r])
            self.sp_seg.blockSignals(False)

    def _on_seg_changed(self, value):
        r = self.list_stations.currentRow()
        ln = self.current_line
        if ln and 0 <= r < len(ln.travel_minutes):
            ln.travel_minutes[r] = value

    def _apply_default_seg(self):
        if self.current_line and len(self.current_line.travel_minutes) >= len(self.current_line.stations) - 1:
            self.current_line.travel_minutes = [self.sp_default_seg.value()] * (len(self.current_line.stations) - 1)
            self._reload_stations()
            self._sync_seg_spin(self.list_stations.currentRow())

    # ---------------- 保存 ----------------
    def _save_all(self):
        if self.current_line:
            self._capture_fields()
        for city in self.cities.values():
            try:
                self.lib.save(city)
            except Exception as ex:
                QMessageBox.warning(self, "保存失败", f"{city.name}: {ex}")

    def _save_and_close(self):
        self._save_all()
        self.accept()
