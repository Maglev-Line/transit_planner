# -*- coding: utf-8 -*-
"""设置对话框：常用出行城市/站点、自动保存、在线地图 API、版本信息。

设置内容通过 QSettings 持久化，关闭软件后保留。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QHBoxLayout, QGroupBox, QLabel,
    QLineEdit, QComboBox, QCheckBox, QPushButton, QFileDialog, QMessageBox,
    QScrollArea, QTextBrowser, QWidget,
)

from .. import APP_NAME, __version__
from ..core.settings import AppSettings


class SettingsDialog(QDialog):
    def __init__(self, library, parent=None):
        super().__init__(parent)
        self.lib = library
        self.setWindowTitle("设置")
        self.resize(600, 680)
        self._build_ui()
        self._load(AppSettings.load())

    # ---------------- 界面 ----------------
    def _build_ui(self):
        root = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(4, 4, 4, 4)

        # 常用出行
        gb_fav = QGroupBox("常用出行（下次规划时自动预填）")
        gf = QGridLayout(gb_fav)
        gf.addWidget(QLabel("最常出行城市："), 0, 0)
        self.cb_city = QComboBox()
        self.cb_city.setEditable(True)
        for name in self.lib.list_cities():
            self.cb_city.addItem(name)
        gf.addWidget(self.cb_city, 0, 1, 1, 2)
        gf.addWidget(QLabel("最常出行地铁站："), 1, 0)
        self.ed_metro = QLineEdit()
        self.ed_metro.setPlaceholderText("如：徐家汇")
        gf.addWidget(self.ed_metro, 1, 1, 1, 2)
        gf.addWidget(QLabel("最常出行公交站："), 2, 0)
        self.ed_bus = QLineEdit()
        self.ed_bus.setPlaceholderText("如：人民广场站")
        gf.addWidget(self.ed_bus, 2, 1, 1, 2)
        lbl_tip = QLabel("下次新建方案时，自动选择该城市，并在第一段行程中预填最常出行的地铁站。")
        lbl_tip.setWordWrap(True)
        lbl_tip.setStyleSheet("color:#666;font-size:8.5pt;")
        gf.addWidget(lbl_tip, 3, 0, 1, 3)
        v.addWidget(gb_fav)

        # 自动保存
        gb_save = QGroupBox("自动保存")
        gs = QGridLayout(gb_save)
        self.chk_auto = QCheckBox("打开自动保存（行程变更时自动写入方案 JSON）")
        gs.addWidget(self.chk_auto, 0, 0, 1, 3)
        gs.addWidget(QLabel("保存位置："), 1, 0)
        self.ed_dir = QLineEdit()
        self.ed_dir.setPlaceholderText("选择自动保存目录")
        gs.addWidget(self.ed_dir, 1, 1)
        btn_browse = QPushButton("浏览…")
        btn_browse.clicked.connect(self._browse_dir)
        gs.addWidget(btn_browse, 1, 2)
        self.chk_auto.toggled.connect(lambda on: self.ed_dir.setEnabled(on))
        v.addWidget(gb_save)

        # 在线地图 API
        gb_api = QGroupBox("在线地图 API（可选）")
        ga = QGridLayout(gb_api)
        note = QLabel("启用后，「添加行程」可按线路名从地图 API 获取经停站、首末班车等线路信息"
                      "（不获取实时状态）。未启用则完全使用本地数据/手动输入。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#666;font-size:8.5pt;")
        ga.addWidget(note, 0, 0, 1, 3)
        self._api_controls = {}
        providers = [
            ("amap", "高德地图"),
            ("baidu", "百度地图"),
            ("tencent", "腾讯地图"),
        ]
        for i, (key, label) in enumerate(providers, start=1):
            chk = QCheckBox()
            ga.addWidget(chk, i, 0)
            ga.addWidget(QLabel(f"{label} Key："), i, 1)
            ed = QLineEdit()
            ed.setPlaceholderText("粘贴 API Key（可选）")
            ga.addWidget(ed, i, 2)
            chk.toggled.connect(lambda on, e=ed: e.setEnabled(on))
            self._api_controls[key] = (chk, ed)
        v.addWidget(gb_api)

        # 地图 API 获取教程
        gb_tut = QGroupBox("地图 API 获取教程（首次使用请看这里）")
        gt = QVBoxLayout(gb_tut)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setMaximumHeight(240)
        browser.setStyleSheet("font-size:9pt;")
        browser.setHtml(
            "<p><b>① 高德地图（推荐，可查询线路经停站/首末班）：</b></p>"
            "<ol>"
            "<li>打开 <a href='https://console.amap.com/dev/key/app'>高德开放平台控制台</a>，注册并登录；</li>"
            "<li>在「应用管理」中创建一个应用；</li>"
            "<li>为应用添加 Key，服务平台选择「<b>Web服务</b>」，创建后复制生成的 Key；</li>"
            "<li>回到本窗口，勾选「高德地图」并粘贴 Key，点击下方「保存」。</li>"
            "</ol>"
            "<p><b>② 百度地图（仅用于站点名称补全）：</b></p>"
            "<ol>"
            "<li>打开 <a href='https://lbsyun.baidu.com/apiconsole/key'>百度地图开放平台</a>，注册并登录；</li>"
            "<li>创建「服务端」类型的应用，获取 <b>AK（服务端密钥）</b>；</li>"
            "<li>勾选「百度地图」并粘贴 AK。百度暂未开放稳定的线路查询接口，无法获取经停站。</li>"
            "</ol>"
            "<p><b>③ 腾讯地图（仅用于站点名称补全）：</b></p>"
            "<ol>"
            "<li>打开 <a href='https://lbs.qq.com/dev/console'>腾讯位置服务</a>，注册并登录；</li>"
            "<li>创建应用并获取 <b>Key</b>；</li>"
            "<li>勾选「腾讯地图」并粘贴 Key。腾讯同样暂未开放稳定的线路查询接口。</li>"
            "</ol>"
            "<p>提示：Key 仅保存在本机设置中，不会上传。若不确定，可只用高德一个 Key，"
            "其余留空即可。</p>")
        gt.addWidget(browser)
        v.addWidget(gb_tut)

        # 版本信息
        gb_ver = QGroupBox("版本信息")
        gv = QGridLayout(gb_ver)
        gv.addWidget(QLabel("软件名称："), 0, 0)
        gv.addWidget(QLabel(APP_NAME), 0, 1)
        gv.addWidget(QLabel("版本："), 1, 0)
        gv.addWidget(QLabel(f"v{__version__}"), 1, 1)
        gv.addWidget(QLabel("用途："), 2, 0)
        gv.addWidget(QLabel("交通迷绕路运转行程规划工具"), 2, 1)
        v.addWidget(gb_ver)

        v.addStretch(1)
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        # 按钮
        btns = QHBoxLayout()
        btns.addStretch(1)
        b_ok = QPushButton("保存")
        b_ok.setStyleSheet("font-weight:bold;min-width:88px;")
        b_ok.clicked.connect(self._accept)
        btns.addWidget(b_ok)
        b_cancel = QPushButton("取消")
        b_cancel.clicked.connect(self.reject)
        btns.addWidget(b_cancel)
        root.addLayout(btns)

    # ---------------- 加载 / 保存 ----------------
    def _load(self, s: AppSettings):
        self.cb_city.setCurrentText(s.favorite_city)
        self.ed_metro.setText(s.favorite_metro)
        self.ed_bus.setText(s.favorite_bus)
        self.chk_auto.setChecked(s.auto_save)
        self.ed_dir.setText(s.auto_save_dir)
        self.ed_dir.setEnabled(s.auto_save)
        for key, (chk, ed) in self._api_controls.items():
            chk.setChecked(getattr(s, f"{key}_enabled", False))
            ed.setText(getattr(s, f"{key}_key", ""))
            ed.setEnabled(chk.isChecked())

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择自动保存目录", self.ed_dir.text() or str(Path.cwd()))
        if d:
            self.ed_dir.setText(d)

    def _accept(self):
        if self.chk_auto.isChecked() and not self.ed_dir.text().strip():
            QMessageBox.information(self, "提示", "已打开自动保存，请选择保存位置。")
            return
        s = AppSettings(
            favorite_city=self.cb_city.currentText().strip(),
            favorite_metro=self.ed_metro.text().strip(),
            favorite_bus=self.ed_bus.text().strip(),
            auto_save=self.chk_auto.isChecked(),
            auto_save_dir=self.ed_dir.text().strip(),
        )
        for key, (chk, ed) in self._api_controls.items():
            setattr(s, f"{key}_enabled", chk.isChecked())
            setattr(s, f"{key}_key", ed.text().strip())
        s.save()
        self.settings = s
        self.accept()
