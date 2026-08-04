# -*- coding: utf-8 -*-
"""主窗口：城市线路库 + 行程链条（卡片 + 段间换乘步行）+ 换乘提示 + 统计 + PDF 导出。

设计：
- 主界面不直接摆放「添加行程」表单，而是一个醒目的「＋ 添加行程」大按钮；
  点击后在弹窗（AddStepDialog）中输入线路信息，默认手动输入，线路名有数据库推荐。
- 每段行程以卡片展示；两段之间提供「换乘步行」配置（不全是同站换乘）。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QComboBox, QLineEdit, QListWidget, QListWidgetItem, QLabel,
    QPushButton, QMessageBox, QFileDialog, QGroupBox, QCheckBox,
)

from ..core.models import CityLibrary, Trip, Step, TYPE_LABELS, fmt_minutes
from ..core import engine as E
from ..core.settings import AppSettings
from ..pdf.exporter import export_pdf
from .. import APP_NAME, __version__
from .data_editor import DataEditor
from .add_step_dialog import AddStepDialog
from .steps_panel import StepsPanel
from .pdf_config_dialog import PdfConfigDialog
from .settings_dialog import SettingsDialog

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def swatch_icon(color_hex: str, color2: str = "", size: int = 16) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(color_hex))
    if color2 and color2.lower() != color_hex.lower():
        p = QPainter(pm)
        p.fillRect(0, int(size * 0.62), size, size - int(size * 0.62), QColor(color2))
        p.end()
    return QIcon(pm)


class TimelineWidget(QWidget):
    """按运行时长比例绘制的彩色分段时间轴。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.segments: list[tuple[str, str, float]] = []  # (short_name, color, minutes)
        self.setMinimumHeight(46)

    def set_segments(self, segments):
        self.segments = segments
        self.update()

    def paintEvent(self, event):
        if not self.segments:
            return
        p = QPainter(self)
        total = sum(m for _, _, m in self.segments) or 1
        w = self.width() - 8
        x = 4
        h = 22
        for name, color, m in self.segments:
            seg_w = max(18, int(m / total * w))
            rect = (x, 6, seg_w, h)
            p.setBrush(QColor(color))
            p.setPen(Qt.NoPen)
            p.drawRect(*rect)
            c = QColor(color)
            txt = QColor("white") if c.lightness() < 128 else QColor("black")
            p.setPen(txt)
            p.drawText(*rect, Qt.AlignCenter, f"{name}")
            x += seg_w
        p.setPen(QColor("#888888"))
        p.drawText(4, 38, f"总运行 {total:.0f} 分钟 · 色块宽度与运行时长成比例")
        p.end()


class MainWindow(QMainWindow):
    def __init__(self, library: CityLibrary):
        super().__init__()
        self.lib = library
        self.trip = Trip()
        self.city = None
        self.result = None
        self.current_pos: str | None = None
        self.app_settings = AppSettings.load()

        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        self.resize(1280, 800)
        self._build_ui()
        self._reload_cities()
        self._preselect_favorite()
        self._try_load_autosave()

    # ---------------- 界面构建 ----------------
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)

        # 顶部工具条
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("城市/范围："))
        self.cb_city = QComboBox()
        self.cb_city.setEditable(True)
        self.cb_city.setToolTip("可选内置城市线路库，也可直接输入自定义范围（如：上海—北京）")
        self.cb_city.currentTextChanged.connect(self._on_city_changed)
        toolbar.addWidget(self.cb_city)
        toolbar.addSpacing(12)
        toolbar.addWidget(QLabel("方案名："))
        self.ed_name = QLineEdit("我的运转方案")
        self.ed_name.setFixedWidth(150)
        self.ed_name.textChanged.connect(self._auto_save)
        toolbar.addWidget(self.ed_name)
        toolbar.addWidget(QLabel("日期："))
        self.ed_date = QLineEdit()
        self.ed_date.setFixedWidth(100)
        self.ed_date.setPlaceholderText("如 2026-08-01")
        self.ed_date.textChanged.connect(self._auto_save)
        toolbar.addWidget(self.ed_date)
        self.chk_paid = QCheckBox("付费区模式")
        self.chk_paid.setToolTip("按「进闸站→出闸站」计费：不出闸的连续行程视为一段付费区（即使绕路也只收一次费）；"
                                 "跨付费区转车（转乘，需出闸/换系统）在段间勾选「转乘」。")
        self.chk_paid.toggled.connect(self._on_paid_mode_toggled)
        toolbar.addWidget(self.chk_paid)
        toolbar.addStretch(1)
        btn_new = QPushButton("新建")
        btn_new.clicked.connect(self._new_trip)
        toolbar.addWidget(btn_new)
        btn_save = QPushButton("保存方案")
        btn_save.clicked.connect(self._save_trip)
        toolbar.addWidget(btn_save)
        btn_load = QPushButton("载入方案")
        btn_load.clicked.connect(self._load_trip)
        toolbar.addWidget(btn_load)
        btn_edit = QPushButton("数据编辑")
        btn_edit.clicked.connect(self._open_editor)
        toolbar.addWidget(btn_edit)
        btn_settings = QPushButton("设置")
        btn_settings.clicked.connect(self._open_settings)
        toolbar.addWidget(btn_settings)
        btn_pdf = QPushButton("导出 PDF")
        btn_pdf.clicked.connect(self._export_pdf)
        btn_pdf.setStyleSheet("font-weight:bold;")
        toolbar.addWidget(btn_pdf)
        root.addLayout(toolbar)

        # 主分割
        splitter = QSplitter(Qt.Horizontal)

        # 左：线路库
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel("线路库（点击查看 · 双击快速添加）"))
        self.list_lines = QListWidget()
        self.list_lines.itemClicked.connect(self._on_line_clicked)
        self.list_lines.itemDoubleClicked.connect(self._on_line_dblclicked)
        lv.addWidget(self.list_lines)
        self.lbl_line_info = QLabel("")
        self.lbl_line_info.setWordWrap(True)
        self.lbl_line_info.setStyleSheet("background:#f5f5f5;padding:6px;")
        lv.addWidget(self.lbl_line_info)
        splitter.addWidget(left)

        # 中：行程链条
        mid = QWidget()
        mv = QVBoxLayout(mid)

        self.btn_add = QPushButton("＋ 添加行程")
        self.btn_add.setMinimumHeight(52)
        self.btn_add.setStyleSheet(
            "font-size:15pt;font-weight:bold;padding:10px;"
            "background:#1a73e8;color:white;border-radius:8px;")
        self.btn_add.setToolTip("点击后在新窗口输入线路信息（线路名 + 到发站为必填，其余选填）")
        self.btn_add.clicked.connect(lambda: self._open_add_step())
        mv.addWidget(self.btn_add)

        self.panel = StepsPanel()
        self.panel.edit_requested.connect(self._edit_step)
        self.panel.data_changed.connect(self._after_steps_changed)
        self.panel.walk_changed.connect(self._update_hints_and_stats)
        mv.addWidget(self.panel, 1)

        btn_row = QHBoxLayout()
        b = QPushButton("清空全部")
        b.clicked.connect(self._clear_steps)
        btn_row.addWidget(b)
        btn_row.addStretch(1)
        mv.addLayout(btn_row)
        splitter.addWidget(mid)

        # 右：信息
        right = QWidget()
        rv = QVBoxLayout(right)
        box_hint = QGroupBox("当前位置 · 换乘提示")
        hh = QVBoxLayout(box_hint)
        self.lbl_pos = QLabel("尚未开始")
        self.lbl_pos.setStyleSheet("font-weight:bold;")
        hh.addWidget(self.lbl_pos)
        self.list_hints = QListWidget()
        hh.addWidget(self.list_hints)
        rv.addWidget(box_hint)

        box_stat = QGroupBox("统计")
        sv = QVBoxLayout(box_stat)
        self.lbl_stat = QLabel("")
        self.lbl_stat.setWordWrap(True)
        self.lbl_stat.setStyleSheet("font-size:12pt;")
        sv.addWidget(self.lbl_stat)
        self.timeline = TimelineWidget()
        sv.addWidget(self.timeline)
        rv.addWidget(box_stat)
        splitter.addWidget(right)

        splitter.setSizes([260, 640, 360])
        root.addWidget(splitter, 1)
        self.setCentralWidget(central)

        # 角落署名
        lbl_credit = QLabel("制作：磁浮线")
        lbl_credit.setStyleSheet("color:#999999;padding-right:6px;")
        self.statusBar().addPermanentWidget(lbl_credit)

    # ---------------- 数据加载 ----------------
    def _reload_cities(self):
        current = self.cb_city.currentText()
        cities = self.lib.list_cities()
        self.cb_city.blockSignals(True)
        self.cb_city.clear()
        self.cb_city.addItems(cities)
        if current in cities:
            self.cb_city.setCurrentText(current)
        elif current:
            self.cb_city.setEditText(current)
        self.cb_city.blockSignals(False)
        if current in cities:
            self._load_city(current)
        elif current:
            self._set_city_none(current)
        elif cities:
            self._load_city(cities[0])

    def _load_city(self, name: str):
        try:
            self.city = self.lib.load(name)
        except FileNotFoundError:
            self._set_city_none(name)
            return
        self.trip.city = name
        self._populate_line_list()
        self._sync_panel()

    # ---------------- 设置 / 自动保存 ----------------
    def _preselect_favorite(self):
        fav = self.app_settings.favorite_city
        if fav and fav in self.lib.list_cities() and self.cb_city.currentText() != fav:
            self.cb_city.setCurrentText(fav)

    def _try_load_autosave(self):
        if not self.app_settings.auto_save or not self.app_settings.auto_save_dir:
            return
        d = Path(self.app_settings.auto_save_dir)
        if not d.is_dir():
            return
        files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return
        try:
            self.trip = Trip.load(files[0])
        except Exception:
            return
        self.ed_name.setText(self.trip.name)
        self.ed_date.setText(self.trip.date)
        self.cb_city.setCurrentText(self.trip.city)
        self._sync_paid_mode_ui()
        self._fix_current_pos()
        self._sync_panel()
        self.statusBar().showMessage(f"已载入最近自动保存的方案：{files[0].name}", 4000)

    def _auto_save(self, *_):
        if not self.app_settings.auto_save or not self.app_settings.auto_save_dir:
            return
        if not self.trip.steps:
            return
        d = Path(self.app_settings.auto_save_dir)
        try:
            d.mkdir(parents=True, exist_ok=True)
            self._sync_trip_fields()
            name = self.trip.name or "我的运转方案"
            for ch in '\\/:*?"<>|':
                name = name.replace(ch, "_")
            self.trip.save(d / f"{name}.json")
        except Exception:
            pass

    def _open_settings(self):
        dlg = SettingsDialog(self.lib, self)
        if dlg.exec():
            self.app_settings = dlg.settings
            self._reload_cities()
            self._preselect_favorite()

    def _on_paid_mode_toggled(self, on: bool):
        self.trip.paid_zone_mode = bool(on)
        self._after_steps_changed()

    def _sync_paid_mode_ui(self):
        self.chk_paid.blockSignals(True)
        self.chk_paid.setChecked(self.trip.paid_zone_mode)
        self.chk_paid.blockSignals(False)

    def closeEvent(self, event):
        self._auto_save()
        super().closeEvent(event)

    def _set_city_none(self, label: str):
        """自定义城市/范围：不关联线路库，纯手动规划。"""
        self.city = None
        self.trip.city = label
        self.list_lines.clear()
        self.lbl_line_info.setText("自定义城市/范围：未关联线路库，请使用「＋ 添加行程」手动输入线路。")
        self._sync_panel()

    def _populate_line_list(self):
        self.list_lines.clear()
        for ln in self.city.lines:
            item = QListWidgetItem(swatch_icon(ln.color, ln.color2), f"{ln.name}（{ln.type_label}）")
            item.setData(Qt.UserRole, ln.id)
            item.setToolTip(
                f"{ln.name}\n类型：{ln.type_label}\n方向：{' / '.join(d.label for d in ln.directions)}\n"
                f"班次：{ln.headway_text}\n站点数：{len(ln.stations)}")
            self.list_lines.addItem(item)

    def _sync_panel(self):
        self.panel.set_data(self.trip, self.city)
        self._update_hints_and_stats()

    # ---------------- 线路库 ----------------
    def _on_line_clicked(self, item):
        if self.city is None:
            return
        lid = item.data(Qt.UserRole)
        ln = self.city.line(lid)
        info = (f"<b>{ln.name}</b>　[{ln.color}]\n"
                f"类型：{ln.type_label}　{ln.operator}\n"
                f"方向：{' / '.join(d.label for d in ln.directions)}\n"
                f"发车班次：{ln.headway_text}\n"
                f"首末班：{ln.first_train or '—'} ~ {ln.last_train or '—'}\n"
                f"站点数：{len(ln.stations)}\n\n双击可将该线路预填到「添加行程」窗口。")
        self.lbl_line_info.setText(info)

    def _on_line_dblclicked(self, item):
        if self.city is None:
            return
        lid = item.data(Qt.UserRole)
        self._open_add_step(self.city.line(lid))

    # ---------------- 添加 / 编辑行程 ----------------
    def _open_add_step(self, line=None):
        # line 仅来自「双击线路库」传入的 Line 对象；其余情况（如按钮 click 信号）忽略
        if not (line is None or hasattr(line, "id")):
            line = None
        dlg = AddStepDialog(self.city, self, settings=self.app_settings,
                            city_label=self.cb_city.currentText(),
                            prefill_favorite=not self.trip.steps)
        if line is not None:
            dlg.preselect(line)
        if dlg.exec():
            step = dlg.result_step()
            if step is not None:
                self.trip.steps.append(step)
                self._after_steps_changed()

    def _edit_step(self, i: int):
        if not (0 <= i < len(self.trip.steps)):
            return
        dlg = AddStepDialog(self.city, self, step=self.trip.steps[i],
                            settings=self.app_settings, city_label=self.cb_city.currentText())
        if dlg.exec():
            step = dlg.result_step()
            if step is not None:
                self.trip.steps[i] = step
                self._after_steps_changed()

    def _after_steps_changed(self):
        self._fix_current_pos()
        self.panel.refresh()
        self._update_hints_and_stats()
        self._auto_save()

    def _clear_steps(self):
        self.trip.steps.clear()
        self.current_pos = None
        self._after_steps_changed()

    def _fix_current_pos(self):
        self.current_pos = self.trip.steps[-1].to_station if self.trip.steps else None

    # ---------------- 信息面板 ----------------
    def _update_hints_and_stats(self):
        if self.current_pos and self.city:
            self.lbl_pos.setText(f"当前在站：{self.current_pos}")
            self.list_hints.clear()
            for ln, dirs in E.transfer_hints(self.city, self.current_pos):
                item = QListWidgetItem(swatch_icon(ln.color, ln.color2),
                                       f"{ln.name}　{' / '.join(d.label for d in dirs)}")
                self.list_hints.addItem(item)
        else:
            self.lbl_pos.setText("尚未开始（请先添加行程）")
            self.list_hints.clear()

        if self.trip.steps:
            try:
                self.result = E.evaluate_trip(self.city, self.trip)
                r = self.result
                price_total = E.price_total(self.trip, r)
                price_txt = f"<br>总票价：<b>¥{price_total:.2f}</b>" if price_total else ""
                zone_txt = ""
                if self.trip.paid_zone_mode:
                    parts = []
                    for z in r.paid_zones:
                        p = f"¥{z.price:.2f}" if z.price is not None else "未填"
                        parts.append(f"付费区{z.index + 1}：{z.entry_station} → {z.exit_station}（{p}）")
                    if parts:
                        zone_txt = "<br>付费区：<span style='color:#0066aa;'>" + "　·　".join(parts) + "</span>"
                transfer_txt = f" ｜ 转乘 {r.fare_transfer_count} 次" if self.trip.paid_zone_mode else ""
                self.lbl_stat.setText(
                    f"<b>全程总时长：{r.total_minutes:.0f} 分钟</b><br>"
                    f"车上运行 {r.total_run:.0f} 分钟 ｜ 站外/换乘步行 {r.total_walk:.0f} 分钟<br>"
                    f"换乘 {r.transfer_count} 次{transfer_txt} ｜ {r.line_count} 条线路 ｜ "
                    f"共 {sum(s.stop_count for s in r.segments)} 站"
                    f"{zone_txt}{price_txt}")
                self.timeline.set_segments(
                    [(s.line.short_name, s.step.color or s.line.color, s.run_minutes)
                     for s in r.segments])
                return
            except Exception as ex:
                self.lbl_stat.setText(f"方案存在问题：{ex}")
        else:
            self.lbl_stat.setText("尚未添加行程")
        self.timeline.set_segments([])

    # ---------------- 方案管理 ----------------
    def _sync_trip_fields(self):
        self.trip.name = self.ed_name.text().strip() or "我的运转方案"
        self.trip.date = self.ed_date.text().strip()
        self.trip.city = self.cb_city.currentText()

    def _new_trip(self):
        if self.trip.steps:
            ret = QMessageBox.question(
                self, "新建方案", "是否先将当前方案保存为 JSON 文件？",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes)
            if ret == QMessageBox.Cancel:
                return
            if ret == QMessageBox.Yes:
                self._save_trip()
        self.trip.name = "我的运转方案"
        self.trip.date = ""
        self.trip.city = self.cb_city.currentText()
        self.trip.note = ""
        self.trip.transfer_walk_default = 5.0
        self.trip.paid_zone_mode = False
        self.trip.steps.clear()
        self.current_pos = None
        self.ed_name.setText("我的运转方案")
        self.ed_date.clear()
        self._sync_paid_mode_ui()
        self._after_steps_changed()

    def _save_trip(self):
        self._sync_trip_fields()
        default = f"{self.trip.name}.json"
        path, _ = QFileDialog.getSaveFileName(self, "保存方案", default, "行程方案 (*.json)")
        if path:
            self.trip.save(path)
            self.statusBar().showMessage(f"已保存：{path}", 4000)

    def _load_trip(self):
        path, _ = QFileDialog.getOpenFileName(self, "载入方案", "", "行程方案 (*.json)")
        if not path:
            return
        try:
            self.trip = Trip.load(path)
        except Exception as ex:
            QMessageBox.warning(self, "载入失败", str(ex))
            return
        self.ed_name.setText(self.trip.name)
        self.ed_date.setText(self.trip.date)
        self.cb_city.setCurrentText(self.trip.city)
        self._sync_paid_mode_ui()
        self._fix_current_pos()
        self._sync_panel()

    def _on_city_changed(self, name: str):
        if not name:
            return
        cities = self.lib.list_cities()
        if name in cities:
            self._load_city(name)
        elif self.city is not None:
            self._set_city_none(name)
        else:
            self.trip.city = name
        if self.trip.steps:
            self._after_steps_changed()

    # ---------------- 导出 ----------------
    def _export_pdf(self):
        if not self.trip.steps:
            QMessageBox.information(self, "提示", "行程为空，请先添加行程段。")
            return
        self._sync_trip_fields()
        try:
            self.result = E.evaluate_trip(self.city, self.trip)
        except Exception as ex:
            QMessageBox.warning(self, "方案有误", f"无法导出：\n{ex}")
            return
        # 1) 配置窗口：导出目录 + 字体
        cfg_dlg = PdfConfigDialog(self.trip.name, self)
        if not cfg_dlg.exec():
            return
        cfg = cfg_dlg.config
        # 2) 导出
        try:
            out = export_pdf(self.city, self.trip, cfg.output_path,
                             font_path=cfg.font_path, font_bold_path=cfg.font_bold_path)
            QMessageBox.information(self, "完成", f"已导出：\n{out}")
        except Exception as ex:
            QMessageBox.critical(self, "导出失败", str(ex))

    def _open_editor(self):
        dlg = DataEditor(self.lib, self)
        if dlg.exec() and self.cb_city.currentText():
            self._reload_cities()
