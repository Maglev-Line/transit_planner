# -*- coding: utf-8 -*-
"""行程链条面板：每段行程一张卡片，两段之间提供换乘步行配置。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QDoubleSpinBox, QScrollArea, QCheckBox,
)

from ..core import engine as E
from ..core.models import Trip, fmt_minutes


def _swatch_label(color_hex: str, color2: str = "") -> str:
    """返回一个带色块的小方块字符，供 QLabel 富文本使用。"""
    html = f'<span style="background-color:{color_hex};color:{color_hex};">&nbsp;&nbsp;&nbsp;&nbsp;</span>'
    if color2 and color2.lower() != color_hex.lower():
        html += f'<span style="background-color:{color2};color:{color2};">&nbsp;&nbsp;&nbsp;&nbsp;</span>'
    return html


class StepsPanel(QWidget):
    """展示行程卡片列表；在相邻两段之间插入「换乘步行」配置条。"""

    edit_requested = Signal(int)
    data_changed = Signal()      # 行程结构变化（增删移），需要整体重绘
    walk_changed = Signal()      # 仅换乘步行变化，只需刷新统计

    def __init__(self, parent=None):
        super().__init__(parent)
        self.trip: Trip | None = None
        self.city = None
        self._result = None
        self._eval_error: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.container = QWidget()
        self._box = QVBoxLayout(self.container)
        self._box.setContentsMargins(0, 0, 0, 0)
        self._box.addStretch(1)
        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll)

    # ---------------- 数据 ----------------
    def set_data(self, trip: Trip, city):
        self.trip = trip
        self.city = city
        self.refresh()

    def refresh(self):
        while self._box.count():
            item = self._box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if self.trip is None:
            return
        try:
            self._result = E.evaluate_trip(self.city, self.trip)
            self._eval_error = None
        except Exception as ex:
            self._result = None
            self._eval_error = str(ex)
        self._zones = {}
        if self._result is not None:
            for z in self._result.paid_zones:
                self._zones[z.index] = z
        if not self.trip.steps:
            lbl = QLabel("尚未添加行程\n\n点击上方「＋ 添加行程」开始规划")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color:#888888;font-size:12pt;padding:36px;")
            self._box.addWidget(lbl)
            self._box.addStretch(1)
            return
        for i in range(len(self.trip.steps)):
            if i > 0:
                self._box.addWidget(self._make_walk_row(i))
            self._box.addWidget(self._make_card(i))
        self._box.addStretch(1)

    # ---------------- 卡片 ----------------
    def _line_meta(self, i: int):
        s = self.trip.steps[i]
        if s.manual:
            return (s.line_name or "手动线路"), (s.color or "#888888"), (s.color2 or "")
        if self.city is not None:
            try:
                ln = self.city.line(s.line_id)
                return ln.name, (s.color or ln.color), (s.color2 or ln.color2)
            except Exception:
                pass
        return (s.line_name or s.line_id), "#888888", ""

    def _make_card(self, i: int) -> QWidget:
        s = self.trip.steps[i]
        name, color, color2 = self._line_meta(i)
        card = QFrame()
        card.setStyleSheet("QFrame{background:#ffffff;border:1px solid #cccccc;border-radius:4px;}")
        v = QVBoxLayout(card)
        v.setContentsMargins(10, 6, 6, 8)

        head = QHBoxLayout()
        title = QLabel(f"<b>第 {i + 1} 段</b>　{name}")
        title.setStyleSheet("font-size:11pt;")
        head.addWidget(title, 1)
        for text, slot in [("上移", self._move_up), ("下移", self._move_down),
                           ("编辑", self._edit), ("删除", self._delete)]:
            b = QPushButton(text)
            b.setMaximumWidth(52)
            b.clicked.connect(lambda _=False, sl=slot, idx=i: sl(idx))
            head.addWidget(b)
        v.addLayout(head)

        detail = QLabel(self._detail_html(i, name, color, color2))
        detail.setWordWrap(True)
        detail.setTextFormat(Qt.RichText)
        v.addWidget(detail)
        return card

    def _detail_html(self, i: int, name: str, color: str, color2: str) -> str:
        s = self.trip.steps[i]
        lines = []
        if self._result is not None and i < len(self._result.segments):
            seg = self._result.segments[i]
            if self.trip.paid_zone_mode:
                z = self._zones.get(seg.paid_zone_index)
                if z is not None:
                    is_entry = z.segments and z.segments[0].step is s
                    price_txt = f"　票价 ¥{z.price:.2f}" if z.price is not None else ""
                    marker = "🚇 进闸" if is_entry else "　│"
                    lines.append(f"{marker} 付费区 {z.index + 1}：{z.entry_station} → {z.exit_station}{price_txt}")
            if seg.transfer:
                lines.append("⚠ 转乘（跨付费区，需出闸/换系统）")
            lines.append(
                f"{_swatch_label(color, color2)}　"
                f"<b>{seg.step.from_station} → {seg.step.to_station}</b>"
                f"　方向：{seg.direction.label}")
            lines.append(f"车上运行 {fmt_minutes(seg.run_minutes)}　｜　经停 {seg.stop_count} 站")
            if seg.stops:
                lines.append("经停站：" + " → ".join(seg.stops))
            if seg.manual:
                if s.headway_text:
                    lines.append(f"发车班次：{s.headway_text}")
            else:
                lines.append(f"发车班次：{seg.line.headway_text}")
        else:
            lines.append(
                f"{_swatch_label(color, color2)}　"
                f"<b>{s.from_station} → {s.to_station}</b>")
            if s.direction_label:
                lines.append(f"方向：{s.direction_label}")
            if s.run_minutes:
                lines.append(f"车上运行 {fmt_minutes(s.run_minutes)}")
            if s.stops_text:
                lines.append("经停站：" + " → ".join(E.parse_stops(s.stops_text)))
        if s.note:
            lines.append(f"备注/车次：{s.note}")
        if s.use_timetable:
            lines.append("⏱ 按时刻表乘坐列车")
        if s.timetable:
            tt = "　".join(f"{t[0]} {t[1]}→{t[2]}" for t in s.timetable)
            lines.append(f"时刻表：{tt}")
        if s.price is not None:
            lines.append(f"票价：¥{s.price:.2f}")
        return "<br>".join(lines)

    # ---------------- 换乘步行 ----------------
    def _make_walk_row(self, i: int) -> QWidget:
        """第 i 段与上一段之间的换乘配置条（步行 + 是否跨付费区转乘）。"""
        s = self.trip.steps[i]
        prev_to = self.trip.steps[i - 1].to_station
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(14, 2, 14, 2)
        lbl = QLabel(f"␣ 换乘（{prev_to} → {s.from_station}）：")
        lbl.setStyleSheet("color:#555555;")
        h.addWidget(lbl)
        spin = QDoubleSpinBox()
        spin.setRange(0, 240)
        spin.setSingleStep(1)
        if s.walk_minutes is not None:
            spin.setValue(s.walk_minutes)
        else:
            spin.setValue(E.resolve_walk(s, prev_to, self.trip.transfer_walk_default, city=self.city))
        h.addWidget(spin)

        eff_transfer = E.step_is_transfer(self.city, prev_to, s)
        chk = QCheckBox("转乘")
        chk.setToolTip("跨付费区转车（需出闸/换系统，如 地铁↔国铁）。勾选后本段开始一个新的付费区；"
                       "地铁线路库中的转乘站（如 上海南站↔上海南）会自动勾选。")
        chk.blockSignals(True)
        chk.setChecked(eff_transfer)
        chk.blockSignals(False)
        chk.toggled.connect(lambda on, idx=i: self._on_transfer_changed(idx, on))
        h.addWidget(chk)

        if eff_transfer:
            note = QLabel("转乘")
            note.setStyleSheet("color:#c0392b;font-weight:bold;")
        elif E.stations_same(self.city, prev_to, s.from_station):
            note = QLabel("同站换乘")
            note.setStyleSheet("color:#999999;")
        else:
            note = QLabel("站外步行")
            note.setStyleSheet("color:#999999;")
        h.addWidget(note)
        h.addStretch(1)
        spin.valueChanged.connect(lambda val, idx=i: self._on_walk_changed(idx, val))
        return w

    def _on_walk_changed(self, i: int, value: float):
        self.trip.steps[i].walk_minutes = value
        self.walk_changed.emit()

    def _on_transfer_changed(self, i: int, on: bool):
        self.trip.steps[i].transfer = bool(on)
        self.data_changed.emit()

    # ---------------- 卡片操作 ----------------
    def _move_up(self, i: int):
        if i > 0:
            st = self.trip.steps
            st[i - 1], st[i] = st[i], st[i - 1]
            self.refresh()
            self.data_changed.emit()

    def _move_down(self, i: int):
        st = self.trip.steps
        if 0 <= i < len(st) - 1:
            st[i + 1], st[i] = st[i], st[i + 1]
            self.refresh()
            self.data_changed.emit()

    def _delete(self, i: int):
        del self.trip.steps[i]
        self.refresh()
        self.data_changed.emit()

    def _edit(self, i: int):
        self.edit_requested.emit(i)
