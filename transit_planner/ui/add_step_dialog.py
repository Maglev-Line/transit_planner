# -*- coding: utf-8 -*-
"""添加/编辑行程段对话框。

默认「手动输入」：线路名 + 到发站为必填，其余选填。
输入线路名时按当前城市线路库给出推荐；选中推荐后自动套用数据库全部信息。
未在本地命中时，若已配置在线地图 API，则可从地图获取线路经停站、首末班等线路信息。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QStringListModel, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QHBoxLayout, QComboBox, QLineEdit,
    QLabel, QPushButton, QDoubleSpinBox, QTableWidget, QTableWidgetItem,
    QColorDialog, QGroupBox, QMessageBox, QCompleter, QCheckBox,
    QRadioButton, QButtonGroup, QInputDialog,
)

from ..core import engine as E
from ..core.models import (
    Line, Step, TYPE_METRO, TYPE_BUS, TYPE_SUBURBAN, TYPE_TRAM,
    TYPE_MONORAIL, TYPE_CLOUDRAIL, TYPE_RAIL, TYPE_MAGLEV, TYPE_FERRY,
    TYPE_CABLEWAY,
    CityLibrary, type_display,
)
from ..core.railway import build_12306_url
from ..core.settings import AppSettings
from ..providers.online import BaseMapProvider, OnlineProviderError, build_providers

DEFAULT_COLOR = "#888888"

# 内置交通类型（单选按钮顺序）
DEFAULT_TYPE_KEYS = [TYPE_METRO, TYPE_BUS, TYPE_SUBURBAN, TYPE_TRAM,
                     TYPE_MONORAIL, TYPE_CLOUDRAIL, TYPE_RAIL, TYPE_MAGLEV,
                     TYPE_FERRY, TYPE_CABLEWAY]


def _parse_hhmm(text: str) -> int | None:
    """解析 'HH:MM' 返回当天分钟数；失败返回 None。"""
    t = (text or "").strip()
    if ":" not in t:
        return None
    parts = t.split(":")
    if len(parts) != 2:
        return None
    try:
        h, m = int(parts[0]), int(parts[1])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h * 60 + m
    except ValueError:
        pass
    return None


class AddStepDialog(QDialog):
    """添加（step=None）或编辑（step=现有）一段行程。"""

    def __init__(self, city, parent=None, step: Step | None = None,
                 settings: AppSettings | None = None, city_label: str = "",
                 prefill_favorite: bool = False):
        super().__init__(parent)
        self.city = city
        self.city_label = city_label
        self.settings = settings or AppSettings.load()
        self._prefill_favorite = prefill_favorite
        self._step = step
        self._matched_line: Line | None = None
        self._api_matched = False
        self._manual_color = DEFAULT_COLOR
        self._manual_color2 = ""
        self._providers: list[BaseMapProvider] = build_providers(self.settings)
        self._api_result_map: dict[str, Line] = {}
        self._api_timer: QTimer | None = None
        self.setWindowTitle("编辑行程" if step is not None else "添加行程")
        self.resize(640, 800)
        self._build_ui()
        if step is not None:
            self._load_step(step)
        else:
            self._populate_station_combos()
            self._favorite_prefill()

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

        # 票价
        form.addWidget(QLabel("票价(元)（选填）"), 7, 0)
        self.sp_price = QDoubleSpinBox()
        self.sp_price.setRange(0, 10000)
        self.sp_price.setDecimals(2)
        self.sp_price.setSpecialValueText("未知/未填写")
        self.sp_price.setToolTip("本段行程票价，手动输入")
        form.addWidget(self.sp_price, 7, 1)
        lbl_price_tip = QLabel("每段行程的票价；汇总时自动求和")
        lbl_price_tip.setStyleSheet("color:#999;font-size:8pt;")
        form.addWidget(lbl_price_tip, 7, 2, 1, 2)

        root.addLayout(form)

        # 交通类型（手动输入线路时选择）
        root.addWidget(self._build_type_group())

        # 时刻表
        tt_group = QGroupBox("发车方式")
        tt_v = QVBoxLayout(tt_group)

        tt_top = QHBoxLayout()
        self.chk_tt = QCheckBox("按时刻表乘坐列车（国铁等固定班次）")
        self.chk_tt.setToolTip("勾选后可编辑时刻表，并自动根据发时/到时计算运行时长")
        self.chk_tt.toggled.connect(self._on_tt_toggled)
        tt_top.addWidget(self.chk_tt)
        tt_top.addStretch(1)
        self.lbl_12306 = QLabel('<a href="#" style="color:#0066aa;">铁路12306 查询本车次</a>')
        self.lbl_12306.setTextFormat(Qt.RichText)
        self.lbl_12306.setToolTip("点击跳转到铁路12306，按本段发站/到站查询车次信息")
        self.lbl_12306.linkActivated.connect(lambda *_: self._open_12306())
        tt_top.addWidget(self.lbl_12306)
        tt_v.addLayout(tt_top)

        self.lbl_tt_hint = QLabel("未勾选时表示公交化运营（按固定间隔发车），无需填写时刻表。")
        self.lbl_tt_hint.setWordWrap(True)
        self.lbl_tt_hint.setStyleSheet("color:#666;font-size:8.5pt;")
        tt_v.addWidget(self.lbl_tt_hint)

        self.table_tt = QTableWidget(0, 3)
        self.table_tt.setHorizontalHeaderLabels(["车次", "发时", "到时"])
        self.table_tt.setEnabled(False)
        self.table_tt.itemChanged.connect(self._on_tt_edit)
        tt_v.addWidget(self.table_tt)
        tt_row = QHBoxLayout()
        b = QPushButton("＋ 添加车次")
        b.clicked.connect(lambda: self.table_tt.insertRow(self.table_tt.rowCount()))
        self.btn_tt_add = b
        tt_row.addWidget(b)
        b = QPushButton("删除选中行")
        b.clicked.connect(self._del_tt_row)
        self.btn_tt_del = b
        tt_row.addWidget(b)
        tt_row.addStretch(1)
        tt_v.addLayout(tt_row)
        self.lbl_tt_auto = QLabel("")
        self.lbl_tt_auto.setStyleSheet("color:#1a73e8;font-size:8.5pt;")
        tt_v.addWidget(self.lbl_tt_auto)
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

    # ---------------- 交通类型选择 ----------------
    def _build_type_group(self) -> QGroupBox:
        group = QGroupBox("交通类型（手动输入线路时选择）")
        self.type_grid = QGridLayout(group)
        self._type_buttons: dict[str, QRadioButton] = {}
        self._type_order: list[str] = list(DEFAULT_TYPE_KEYS)
        self._type_group_btns = QButtonGroup(self)
        self._type_group_btns.setExclusive(True)
        self._custom_types = list(self.settings.custom_transit_types or [])
        for ct in self._custom_types:
            if ct not in self._type_order:
                self._type_order.append(ct)
        self.btn_custom_type = QPushButton("自定义…")
        self.btn_custom_type.setToolTip("自定义新的交通类型（如：轮渡、缆车、观光巴士等），保存后下次仍可用")
        self.btn_custom_type.clicked.connect(self._add_custom_type)
        self.chk_irregular = QCheckBox("不定班（无固定发车间隔）")
        self.chk_irregular.setToolTip("如部分公交 / 轮渡等，勾选后发车班次标注为「不定班」")
        self.chk_irregular.toggled.connect(self._on_irregular_toggled)
        self._rebuild_type_grid()
        return group

    def _rebuild_type_grid(self):
        while self.type_grid.count():
            item = self.type_grid.takeAt(0)
            if item.widget():
                self.type_grid.removeWidget(item.widget())
        col = 0
        for key in self._type_order:
            rb = self._type_buttons.get(key)
            if rb is None:
                rb = QRadioButton(type_display(key))
                rb.setProperty("type_key", key)
                self._type_buttons[key] = rb
                self._type_group_btns.addButton(rb)
            self.type_grid.addWidget(rb, col // 4, col % 4)
            col += 1
        self.type_grid.addWidget(self.btn_custom_type, col // 4, col % 4)
        self.type_grid.setColumnStretch((col % 4) + 1, 1)
        self.type_grid.addWidget(self.chk_irregular, col // 4 + 1, 0, 1, 4)
        if self._type_group_btns.checkedButton() is None:
            self._set_type(TYPE_METRO)

    def _set_type(self, key: str):
        rb = self._type_buttons.get(key)
        if rb is not None:
            rb.setChecked(True)

    def _selected_type(self) -> str:
        rb = self._type_group_btns.checkedButton()
        if rb is not None:
            return rb.property("type_key") or TYPE_METRO
        return TYPE_METRO

    def _add_custom_type(self):
        name, ok = QInputDialog.getText(self, "自定义交通类型", "新的交通类型名称（如：轮渡、缆车）：")
        name = (name or "").strip()
        if not ok or not name:
            return
        if name in self._type_buttons:
            QMessageBox.information(self, "提示", f"交通类型「{name}」已存在")
            self._set_type(name)
            return
        self._type_order.append(name)
        if name not in self._custom_types:
            self._custom_types.append(name)
        self.settings.custom_transit_types = list(self._custom_types)
        try:
            self.settings.save()
        except Exception:
            pass
        self._rebuild_type_grid()
        self._set_type(name)

    def _on_irregular_toggled(self, checked: bool):
        if checked:
            self.ed_headway.setText("不定班")
            self.ed_headway.setEnabled(False)
        else:
            if self.ed_headway.text().strip() == "不定班":
                self.ed_headway.clear()
            self.ed_headway.setEnabled(True)

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
        self._api_result_map.clear()
        if lines:
            self._stop_api_timer()
            self._sug_model.setStringList([ln.name for ln in lines])
            return
        self._sug_model.setStringList([])
        if self._providers and len(text.strip()) >= 2:
            self._start_api_search(text)

    def _stop_api_timer(self):
        if self._api_timer is not None:
            self._api_timer.stop()
            try:
                self._api_timer.timeout.disconnect()
            except TypeError:
                pass

    def _start_api_search(self, text: str):
        if self._api_timer is None:
            self._api_timer = QTimer(self)
            self._api_timer.setSingleShot(True)
        else:
            try:
                self._api_timer.timeout.disconnect()
            except TypeError:
                pass
        self._api_timer.timeout.connect(lambda: self._api_search(text))
        self.lbl_reco.setText("本地无匹配线路，正在查询在线地图…")
        self._api_timer.start(400)

    def _api_search(self, text: str):
        if self.city is not None and CityLibrary.is_combined(self.city.name):
            city = CityLibrary.COMBINED_CITIES[self.city.name][0]  # 同城组合：用首个真实城市查询
        else:
            city = self.city.name if self.city is not None else (self.city_label or "")
        if not city:
            self.lbl_reco.setText("请先在主窗口选择城市，再使用在线地图查询线路。")
            return
        labels: list[str] = []
        for prov in self._providers:
            try:
                lines = prov.search_lines(city, text)
            except OnlineProviderError as ex:
                self.lbl_reco.setText(str(ex))
                return
            except Exception as ex:
                self.lbl_reco.setText(f"{prov.display_name}地图查询失败：{ex}")
                return
            for ln in lines:
                label = f"{ln.name}（来自{prov.display_name}地图）"
                self._api_result_map[label] = ln
                labels.append(label)
            if labels:
                break
        if labels:
            self._sug_model.setStringList(labels)
            self.lbl_reco.setText("已从在线地图获取线路，选中后自动套用经停站/首末班等信息。")
        else:
            self.lbl_reco.setText("在线地图未找到匹配线路，请核对线路名，或改用手动输入。")

    def _on_suggestion_activated(self, text: str):
        if text in self._api_result_map:
            self._apply_api_line(self._api_result_map[text])
            return
        if self.city is None:
            return
        for ln in self.city.lines:
            if ln.name == text:
                self._apply_recommendation(ln)
                return

    def _apply_api_line(self, line: Line):
        """套用在线地图获取的线路信息（未入库，保存时按手动段处理）。"""
        self._matched_line = line
        self._api_matched = True
        self.ed_name.setText(line.name)
        self._set_type(line.type)
        self._apply_color(line.color)
        self._apply_color2(line.color2)
        self.cb_dir.blockSignals(True)
        self.cb_dir.clear()
        for d in line.directions:
            self.cb_dir.addItem(d.label)
        self.cb_dir.blockSignals(False)
        self._populate_station_combos()
        meta = f"已从在线地图获取：{line.name}"
        if line.first_train or line.last_train:
            meta += f"（首班 {line.first_train} / 末班 {line.last_train}）"
        meta += f" · {line.type_label}"
        self.lbl_reco.setText(meta + "（经停站与时长已自动填写）")

    def _stops_and_minutes(self, line: Line, from_st: str, to_st: str):
        """在线线路：按起终点返回 (经停站列表, 运行分钟)。"""
        try:
            from_idx = line.station_index(from_st)
            to_idx = line.station_index(to_st)
        except Exception:
            return [from_st, to_st], None
        if from_idx == to_idx:
            return [from_st], None
        sign = 1 if from_idx < to_idx else -1
        indices = list(range(from_idx, to_idx + sign, sign))
        stops = [line.stations[i] for i in indices]
        tm = line.travel_minutes
        minutes = 0.0
        if tm:
            if sign > 0:
                minutes = sum(tm[i] for i in range(from_idx, to_idx))
            else:
                minutes = sum(tm[i] for i in range(to_idx, from_idx))
        return stops, (minutes or None)

    def _apply_recommendation(self, line: Line):
        """选中推荐线路：自动套用数据库全部信息（含发车班次）。"""
        self._matched_line = line
        self._api_matched = False
        self.ed_name.setText(line.name)
        self._set_type(line.type)
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

    # ---------------- 常用出行预填 ----------------
    def _favorite_prefill(self):
        """新建方案第一段行程时，按设置中的最常出行地铁站预填起点站。"""
        if not self._prefill_favorite:
            return
        s = self.settings
        if not s or not s.favorite_metro:
            return
        if self.city is not None and s.favorite_city and self.city.name != s.favorite_city:
            return  # 当前城市与常用城市不一致时不预填
        if not self.cb_from.currentText().strip():
            self.cb_from.setEditText(s.favorite_metro)

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

    def _on_tt_toggled(self, checked: bool):
        """勾选『按时刻表乘坐列车』后启用时刻表编辑。"""
        self.table_tt.setEnabled(checked)
        self.btn_tt_add.setEnabled(checked)
        self.btn_tt_del.setEnabled(checked)
        self.lbl_12306.setVisible(checked)
        if checked:
            self.lbl_tt_hint.setText("勾选后按固定车次乘坐；运行时长由发时/到时自动计算。")
            self._recompute_from_timetable()
        else:
            self.lbl_tt_hint.setText("未勾选时表示公交化运营（按固定间隔发车），无需填写时刻表。")
            self.lbl_tt_auto.clear()

    def _on_tt_edit(self, _item):
        if self.chk_tt.isChecked():
            self._recompute_from_timetable()

    def _cell_text(self, r: int, c: int) -> str:
        item = self.table_tt.item(r, c)
        return item.text().strip() if item else ""

    def _recompute_from_timetable(self):
        """根据时刻表首个有效行（发时+到时）自动计算运行时长。"""
        first_ok: int | None = None
        for r in range(self.table_tt.rowCount()):
            dep, arr = self._cell_text(r, 1), self._cell_text(r, 2)
            if dep and arr:
                d, a = _parse_hhmm(dep), _parse_hhmm(arr)
                if d is not None and a is not None:
                    dur = a - d
                    if dur <= 0:
                        dur += 24 * 60  # 跨零点
                    first_ok = dur
                    break
        if first_ok is not None:
            self.sp_min.setValue(float(first_ok))
            self.lbl_tt_auto.setText(f"已按发时/到时自动计算运行时长：{first_ok} 分钟（可不再手输）")
        else:
            self.lbl_tt_auto.clear()

    def _open_12306(self):
        from_st = self.cb_from.currentText().strip()
        to_st = self.cb_to.currentText().strip()
        if not from_st or not to_st:
            QMessageBox.information(self, "提示", "请先填写起点站与到达站，再查询 12306 车次。")
            return
        url = build_12306_url(from_st, to_st)
        QDesktopServices.openUrl(QUrl(url))

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
        if step.type:
            self._set_type(step.type)
        if step.headway_text:
            self.ed_headway.setText(step.headway_text)
        self.chk_irregular.blockSignals(True)
        self.chk_irregular.setChecked(step.headway_text == "不定班")
        self.chk_irregular.blockSignals(False)
        if step.headway_text == "不定班":
            self.ed_headway.setEnabled(False)
        self.ed_note.setText(step.note)
        self._apply_color(step.color or (matched.color if matched else DEFAULT_COLOR))
        self._apply_color2(step.color2 or (matched.color2 if matched else ""))
        if step.price is not None:
            self.sp_price.setValue(step.price)
        self.table_tt.setRowCount(0)
        for row in step.timetable:
            r = self.table_tt.rowCount()
            self.table_tt.insertRow(r)
            for c, val in enumerate(row[:3]):
                self.table_tt.setItem(r, c, QTableWidgetItem(str(val)))
        self.chk_tt.setChecked(step.use_timetable)
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
        use_tt = self.chk_tt.isChecked()
        if use_tt:
            self._recompute_from_timetable()  # 按时刻表自动计算运行时长
        run = self.sp_min.value() if self.sp_min.value() > 0 else None
        stops = self.ed_stops.text().strip()
        headway = self.ed_headway.text().strip()
        note = self.ed_note.text().strip()
        timetable = self._collect_timetable() if use_tt else []
        price = self.sp_price.value() if self.sp_price.value() > 0 else None
        step = Step(
            from_station=from_st, to_station=to_st,
            direction_label=direction,
            type=self._selected_type(),
            line_name=name,
            run_minutes=run,
            stops_text=stops,
            color=self._manual_color,
            color2=self._manual_color2,
            note=note,
            headway_text=headway,
            timetable=timetable,
            use_timetable=use_tt,
            price=price,
        )
        if self._matched_line is not None and self._api_matched:
            # 在线地图线路：未入库，退化为手动段，但自动套用经停站/时长/首末班
            step.manual = True
            step.line_name = self._matched_line.name
            step.type = self._matched_line.type
            step.color = self._manual_color or self._matched_line.color
            step.color2 = self._manual_color2 or self._matched_line.color2
            try:
                stops_list, minutes = self._stops_and_minutes(self._matched_line, from_st, to_st)
                step.stops_text = "、".join(stops_list)
                if minutes is not None:
                    step.run_minutes = minutes
            except Exception:
                pass
            if not note:
                info = "来自在线地图"
                if self._matched_line.first_train or self._matched_line.last_train:
                    info += f" · 首班 {self._matched_line.first_train} / 末班 {self._matched_line.last_train}"
                step.note = info
            return step
        if self._matched_line is not None:
            d = E.pick_direction(self._matched_line, from_st, to_st)
            if d is not None:
                # 数据库线路：起终点都在该线上，按数据库套用全部信息
                step.line_id = self._matched_line.id
                step.direction_label = d.label
                step.manual = False
                step.type = self._matched_line.type
                step.line_name = ""
                # 勾选了按时刻表乘坐时保留按发时/到时计算的时长，否则由数据库计算
                step.run_minutes = run if use_tt else None
                step.stops_text = ""
                # 数据库线路：颜色/副色允许单独覆盖（未手动改时即为数据库值）
                step.color = self._manual_color
                step.color2 = self._manual_color2
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
