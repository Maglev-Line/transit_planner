# -*- coding: utf-8 -*-
"""添加/编辑行程段对话框。

默认「手动输入」：线路名 + 到发站为必填，其余选填。
输入线路名时按当前城市线路库给出推荐；选中推荐后自动套用数据库全部信息。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QStringListModel
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QHBoxLayout, QComboBox, QLineEdit,
    QLabel, QPushButton, QDoubleSpinBox, QTableWidget, QTableWidgetItem,
    QColorDialog, QGroupBox, QMessageBox, QCompleter,
)

from ..core import engine as E
from ..core.models import Line, Step

DEFAULT_COLOR = "#888888"


class AddStepDialog(QDialog):
    """添加（step=None）或编辑（step=现有）一段行程。"""

    def __init__(self, city, parent=None, step: Step | None = None):
        super().__init__(parent)
        self.city = city
        self._step = step
        self._matched_line: Line | None = None
        self._manual_color = DEFAULT_COLOR
        self._manual_color2 = ""
        self.setWindowTitle("编辑行程" if step is not None else "添加行程")
        self.resize(620, 660)
        self._build_ui()
        if step is not None:
            self._load_step(step)
        else:
            self._populate_station_combos()

    # ---------------- 界面 ----------------
    def _build_ui(self):
        root = QVBoxLayout(self)

        form = QGridLayout()

        # 线路名称（必填）
        form.addWidget(QLabel("线路名称 *"), 0, 0)
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("如：上海地铁1号线 / 京沪高铁 G123")
        self.ed_name.textChanged.connect(self._update_suggestions)
        form.addWidget(self.ed_name, 0, 1, 1, 3)

        # 线路名下拉推荐（QCompleter 弹窗）
        self._sug_model = QStringListModel(self)
        self.completer = QCompleter(self._sug_model, self.ed_name)
        self.completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        self.completer.activated.connect(self._on_suggestion_activated)
        self.ed_name.setCompleter(self.completer)

        # 推荐提示
        self.lbl_reco = QLabel("手动输入线路名，下方会弹出数据库推荐；选中推荐后自动套用颜色/方向/班次等全部信息。")
        self.lbl_reco.setWordWrap(True)
        self.lbl_reco.setStyleSheet("color:#666;font-size:8.5pt;")
        form.addWidget(self.lbl_reco, 1, 0, 1, 4)

        # 到发站（必填）
        form.addWidget(QLabel("起点站 *"), 2, 0)
        self.cb_from = QComboBox()
        self.cb_from.setEditable(True)
        self.cb_from.currentTextChanged.connect(self._on_station_changed)
        form.addWidget(self.cb_from, 2, 1)
        form.addWidget(QLabel("到达站 *"), 2, 2)
        self.cb_to = QComboBox()
        self.cb_to.setEditable(True)
        self.cb_to.currentTextChanged.connect(self._on_station_changed)
        form.addWidget(self.cb_to, 2, 3)

        # 方向（选填）
        form.addWidget(QLabel("方向（选填）"), 3, 0)
        self.cb_dir = QComboBox()
        self.cb_dir.setEditable(True)
        self.cb_dir.setPlaceholderText("如：富锦路方向 / 北京南方向")
        form.addWidget(self.cb_dir, 3, 1, 1, 3)

        # 运行时长 / 经停站
        form.addWidget(QLabel("运行时长(分)"), 4, 0)
        self.sp_min = QDoubleSpinBox()
        self.sp_min.setRange(0, 1440)
        self.sp_min.setSpecialValueText("未知/自动")
        form.addWidget(self.sp_min, 4, 1)
        form.addWidget(QLabel("经停站（选填）"), 4, 2)
        self.ed_stops = QLineEdit()
        self.ed_stops.setPlaceholderText("用 、 分隔，如：上海虹桥、苏州北、南京南")
        form.addWidget(self.ed_stops, 4, 3)

        # 发车班次 / 备注
        form.addWidget(QLabel("发车班次（选填）"), 5, 0)
        self.ed_headway = QLineEdit()
        self.ed_headway.setPlaceholderText("如：高峰8/平峰15 分钟一班；30分钟一班")
        form.addWidget(self.ed_headway, 5, 1)
        form.addWidget(QLabel("备注/车次（选填）"), 5, 2)
        self.ed_note = QLineEdit()
        form.addWidget(self.ed_note, 5, 3)

        # 线路颜色 / 副色
        form.addWidget(QLabel("线路颜色（选填）"), 6, 0)
        self.btn_color = QPushButton()
        self.btn_color.setFixedWidth(80)
        self.btn_color.clicked.connect(self._pick_color)
        form.addWidget(self.btn_color, 6, 1)
        form.addWidget(QLabel("副色（选填）"), 6, 2)
        self.btn_color2 = QPushButton()
        self.btn_color2.setFixedWidth(80)
        self.btn_color2.clicked.connect(self._pick_color2)
        form.addWidget(self.btn_color2, 6, 3)

        root.addLayout(form)

        # 时刻表
        tt_group = QGroupBox("时刻表（选填，如国铁车次发到时刻）")
        tt_v = QVBoxLayout(tt_group)
        self.table_tt = QTableWidget(0, 3)
        self.table_tt.setHorizontalHeaderLabels(["车次", "发时", "到时"])
        tt_v.addWidget(self.table_tt)
        tt_row = QHBoxLayout()
        b = QPushButton("＋ 添加车次")
        b.clicked.connect(lambda: self.table_tt.insertRow(self.table_tt.rowCount()))
        tt_row.addWidget(b)
        b = QPushButton("删除选中行")
        b.clicked.connect(self._del_tt_row)
        tt_row.addWidget(b)
        tt_row.addStretch(1)
        tt_v.addLayout(tt_row)
        root.addWidget(tt_group, 1)

        # 确定 / 取消
        btns = QHBoxLayout()
        btns.addStretch(1)
        b_ok = QPushButton("确定")
        b_ok.clicked.connect(self._accept)
        b_ok.setStyleSheet("font-weight:bold;min-width:88px;")
        btns.addWidget(b_ok)
        b_cancel = QPushButton("取消")
        b_cancel.clicked.connect(self.reject)
        btns.addWidget(b_cancel)
        root.addLayout(btns)

        self._apply_color(DEFAULT_COLOR)
        self._apply_color2("")

    # ---------------- 线路名推荐 ----------------
    def _line_matches(self, text: str) -> list[Line]:
        if not text or self.city is None:
            return []
        t = text.lower()
        out = []
        for ln in self.city.lines:
            if t in ln.name.lower() or t in ln.short_name.lower() or t in ln.id.lower():
                out.append(ln)
        return out[:8]

    def _update_suggestions(self, text: str):
        lines = self._line_matches(text)
        self._sug_model.setStringList([ln.name for ln in lines])

    def _on_suggestion_activated(self, text: str):
        if self.city is None:
            return
        for ln in self.city.lines:
            if ln.name == text:
                self._apply_recommendation(ln)
                return

    def _apply_recommendation(self, line: Line):
        """选中推荐线路：自动套用数据库全部信息（含发车班次）。"""
        self._matched_line = line
        self.ed_name.setText(line.name)
        self._apply_color(line.color)
        self._apply_color2(line.color2)
        # 发车班次
        self.ed_headway.setText(line.headway_text)
        # 方向
        self.cb_dir.blockSignals(True)
        self.cb_dir.clear()
        for d in line.directions:
            self.cb_dir.addItem(d.label)
        self.cb_dir.blockSignals(False)
        # 站点
        self._populate_station_combos()
        self.lbl_reco.setText(f"已套用数据库线路：{line.name}（{line.type_label}，班次：{line.headway_text}）")

    def preselect(self, line: Line):
        """外部预选线路（如双击线路库条目）：直接套用该线路信息。"""
        self._apply_recommendation(line)

    # ---------------- 站点 / 方向联动 ----------------
    def _all_stations(self) -> list[str]:
        if self.city is None:
            return []
        seen: dict[str, None] = {}
        for ln in self.city.lines:
            for s in ln.stations:
                seen.setdefault(s)
        return list(seen)

    def _populate_station_combos(self):
        if self._matched_line is not None:
            stations = self._matched_line.stations
        else:
            stations = self._all_stations()
        for cb in (self.cb_from, self.cb_to):
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems(stations)
            if cur:
                cb.setEditText(cur)
            cb.blockSignals(False)
        self._auto_pick_direction()

    def _on_station_changed(self, *_):
        self._auto_pick_direction()

    def _auto_pick_direction(self):
        if self._matched_line is None:
            return
        from_st = self.cb_from.currentText().strip()
        to_st = self.cb_to.currentText().strip()
        d = E.pick_direction(self._matched_line, from_st, to_st)
        if d is not None:
            idx = self.cb_dir.findText(d.label)
            if idx >= 0:
                self.cb_dir.blockSignals(True)
                self.cb_dir.setCurrentIndex(idx)
                self.cb_dir.blockSignals(False)
                self.sp_min.setSpecialValueText(f"自动（按 {d.label} 计算）")
            else:
                self.sp_min.setSpecialValueText("未知/自动")
        else:
            self.sp_min.setSpecialValueText("未知/自动")

    # ---------------- 颜色 ----------------
    def _pick_color(self):
        color = QColorDialog.getColor(QColor(self._manual_color))
        if color.isValid():
            self._apply_color(color.name())

    def _pick_color2(self):
        color = QColorDialog.getColor(QColor(self._manual_color2 or "#ffffff"))
        if color.isValid():
            self._apply_color2(color.name())

    def _apply_color(self, hex_color: str):
        self._manual_color = hex_color
        self.btn_color.setText(hex_color)
        self.btn_color.setStyleSheet(f"background:{hex_color};")

    def _apply_color2(self, hex_color: str):
        self._manual_color2 = hex_color or ""
        if self._manual_color2:
            self.btn_color2.setText(self._manual_color2)
            self.btn_color2.setStyleSheet(f"background:{self._manual_color2};")
        else:
            self.btn_color2.setText("（无）")
            self.btn_color2.setStyleSheet("")

    # ---------------- 时刻表 ----------------
    def _del_tt_row(self):
        r = self.table_tt.currentRow()
        if r >= 0:
            self.table_tt.removeRow(r)

    def _collect_timetable(self) -> list:
        out = []
        for r in range(self.table_tt.rowCount()):
            vals = []
            for c in range(self.table_tt.columnCount()):
                item = self.table_tt.item(r, c)
                vals.append(item.text().strip() if item else "")
            if any(vals):
                out.append(vals)
        return out

    # ---------------- 载入编辑 ----------------	
    def _load_step(self, step: Step):
        self._step = step
        matched = None
        if not step.manual and step.line_id and self.city is not None:
            try:
                matched = self.city.line(step.line_id)
            except Exception:
                pass
        elif step.line_name and self.city is not None:
            for ln in self.city.lines:
                if ln.name == step.line_name:
                    matched = ln
                    break
        if matched is not None:
            self._apply_recommendation(matched)
            if step.manual:
                # 手动段：仅套用颜色/站点供参考，保持手动语义（除非用户重新选推荐）
                self._matched_line = None
        self.ed_name.setText(step.line_name or (matched.name if matched else ""))
        self.cb_from.setEditText(step.from_station)
        self.cb_to.setEditText(step.to_station)
        if step.direction_label:
            idx = self.cb_dir.findText(step.direction_label)
            if idx >= 0:
                self.cb_dir.setCurrentIndex(idx)
            else:
                self.cb_dir.setEditText(step.direction_label)
        if step.run_minutes:
            self.sp_min.setValue(step.run_minutes)
        self.ed_stops.setText(step.stops_text)
        if step.headway_text:
            self.ed_headway.setText(step.headway_text)
        self.ed_note.setText(step.note)
        self._apply_color(step.color or (matched.color if matched else DEFAULT_COLOR))
        self._apply_color2(step.color2 or (matched.color2 if matched else ""))
        self.table_tt.setRowCount(0)
        for row in step.timetable:
            r = self.table_tt.rowCount()
            self.table_tt.insertRow(r)
            for c, val in enumerate(row[:3]):
                self.table_tt.setItem(r, c, QTableWidgetItem(str(val)))
        self._auto_pick_direction()

    # ---------------- 确定 ----------------
    def _accept(self):
        name = self.ed_name.text().strip()
        from_st = self.cb_from.currentText().strip()
        to_st = self.cb_to.currentText().strip()
        if not name:
            QMessageBox.information(self, "提示", "请填写线路名称。")
            return
        if not from_st or not to_st:
            QMessageBox.information(self, "提示", "请填写起点站与到达站。")
            return
        if from_st == to_st:
            QMessageBox.information(self, "提示", "起点与到达站相同，无法加入。")
            return
        step = self._build_step()
        if self._step is not None:
            # 编辑模式：保留步行时间等原字段
            step.walk_minutes = self._step.walk_minutes
        self._step = step
        self.accept()

    def _build_step(self) -> Step:
        name = self.ed_name.text().strip()
        from_st = self.cb_from.currentText().strip()
        to_st = self.cb_to.currentText().strip()
        direction = self.cb_dir.currentText().strip()
        run = self.sp_min.value() if self.sp_min.value() > 0 else None
        stops = self.ed_stops.text().strip()
        headway = self.ed_headway.text().strip()
        note = self.ed_note.text().strip()
        timetable = self._collect_timetable()
        step = Step(
            from_station=from_st, to_station=to_st,
            direction_label=direction,
            line_name=name,
            run_minutes=run,
            stops_text=stops,
            color=self._manual_color,
            color2=self._manual_color2,
            note=note,
            headway_text=headway,
            timetable=timetable,
        )
        if self._matched_line is not None:
            d = E.pick_direction(self._matched_line, from_st, to_st)
            if d is not None:
                # 数据库线路：起终点都在该线上，按数据库套用全部信息
                step.line_id = self._matched_line.id
                step.direction_label = d.label
                step.manual = False
                step.line_name = ""
                step.run_minutes = None
                step.stops_text = ""
                step.color = ""
                step.color2 = ""
                step.headway_text = ""
                return step
            # 推荐命中但起终点不在该线上 → 退化为手动，套用该线路名称与颜色
            step.manual = True
            step.line_name = self._matched_line.name
            if not step.color:
                step.color = self._matched_line.color
            if not step.color2:
                step.color2 = self._matched_line.color2
            if not note:
                step.note = f"参考线路：{self._matched_line.name}"
            return step
        step.manual = True
        step.line_name = name or "手动线路"
        return step

    def result_step(self) -> Step:
        return self._step
