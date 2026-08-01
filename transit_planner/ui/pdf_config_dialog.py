# -*- coding: utf-8 -*-
"""PDF 导出配置对话框：选择导出目录与字体（在导出 PDF 之前弹出）。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLineEdit, QLabel,
    QPushButton, QComboBox, QFileDialog, QMessageBox,
)

ORG = "运转计划助手"
APP = "pdf_export"

# 常用中文字体预设（名称, 常规体路径, 粗体路径）
FONT_PRESETS = [
    ("微软雅黑", r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc"),
    ("黑体", r"C:\Windows\Fonts\simhei.ttf", ""),
    ("宋体", r"C:\Windows\Fonts\simsun.ttc", ""),
    ("楷体", r"C:\Windows\Fonts\simkai.ttf", ""),
    ("仿宋", r"C:\Windows\Fonts\simfang.ttf", ""),
]

CUSTOM_LABEL = "自定义字体（浏览…）"


@dataclass
class PdfConfig:
    directory: str
    file_name: str
    font_path: str
    font_bold_path: str

    @property
    def output_path(self) -> str:
        return str(Path(self.directory) / self.file_name)


class PdfConfigDialog(QDialog):
    def __init__(self, trip_name: str = "运转方案", parent=None):
        super().__init__(parent)
        self.setWindowTitle("PDF 导出设置")
        self.resize(520, 200)
        self.settings = QSettings(ORG, APP)
        self.trip_name = trip_name

        self._custom_path = ""
        self._custom_bold = ""

        root = QVBoxLayout(self)
        form = QGridLayout()

        form.addWidget(QLabel("导出目录："), 0, 0)
        self.ed_dir = QLineEdit()
        self.ed_dir.setPlaceholderText("选择 PDF 保存目录")
        form.addWidget(self.ed_dir, 0, 1)
        btn_browse = QPushButton("浏览…")
        btn_browse.clicked.connect(self._browse_dir)
        form.addWidget(btn_browse, 0, 2)

        form.addWidget(QLabel("文件名："), 1, 0)
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("如：我的运转方案.pdf")
        form.addWidget(self.ed_name, 1, 1, 1, 2)

        form.addWidget(QLabel("字体："), 2, 0)
        self.cb_font = QComboBox()
        for name, path, bold in FONT_PRESETS:
            self.cb_font.addItem(name, (path, bold))
        self.cb_font.addItem(CUSTOM_LABEL, None)
        self.cb_font.currentIndexChanged.connect(self._on_font_changed)
        form.addWidget(self.cb_font, 2, 1, 1, 2)

        self.lbl_font_path = QLabel("")
        self.lbl_font_path.setStyleSheet("color:#888888;font-size:8.5pt;")
        self.lbl_font_path.setWordWrap(True)
        form.addWidget(self.lbl_font_path, 3, 0, 1, 3)

        root.addLayout(form)

        btns = QHBoxLayout()
        btns.addStretch(1)
        b_ok = QPushButton("确定并导出")
        b_ok.clicked.connect(self._accept)
        b_ok.setStyleSheet("font-weight:bold;min-width:100px;")
        btns.addWidget(b_ok)
        b_cancel = QPushButton("取消")
        b_cancel.clicked.connect(self.reject)
        btns.addWidget(b_cancel)
        root.addLayout(btns)

        self._load_settings()

    # ---------------- 设置持久化 ----------------
    def _load_settings(self):
        default_dir = self.settings.value("dir", str(Path.cwd()), type=str)
        self.ed_dir.setText(default_dir)
        self.ed_name.setText(self.settings.value("file", f"{self.trip_name}.pdf", type=str))
        font_path = self.settings.value("font_path", FONT_PRESETS[0][1], type=str)
        font_bold = self.settings.value("font_bold_path", FONT_PRESETS[0][2], type=str)
        idx = 0
        for i, (_, p, _) in enumerate(FONT_PRESETS):
            if Path(p).resolve() == Path(font_path).resolve():
                idx = i
                break
        else:
            idx = self.cb_font.count() - 1
            self._custom_path = font_path
            self._custom_bold = font_bold
        self.cb_font.setCurrentIndex(idx)
        self._refresh_font_label()

    def _save_settings(self):
        self.settings.setValue("dir", self.ed_dir.text().strip())
        self.settings.setValue("file", self.ed_name.text().strip())
        fp, fb = self._selected_font()
        if fp:
            self.settings.setValue("font_path", fp)
        if fb:
            self.settings.setValue("font_bold_path", fb)

    # ---------------- 交互 ----------------
    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择导出目录", self.ed_dir.text() or str(Path.cwd()))
        if d:
            self.ed_dir.setText(d)

    def _selected_font(self):
        data = self.cb_font.currentData()
        if data is None:
            return self._custom_path, self._custom_bold
        return data[0], data[1]

    def _on_font_changed(self, _):
        if self.cb_font.currentData() is None:
            self._browse_custom_font()
        self._refresh_font_label()

    def _browse_custom_font(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择中文字体文件", r"C:\Windows\Fonts", "字体文件 (*.ttf *.ttc *.otf)")
        if path:
            self._custom_path = path
            self._custom_bold = ""
            # 尝试自动找粗体变体
            p = Path(path)
            for cand in ("bd", "bold", "Bold", "bdBold"):
                alt = p.with_name(p.stem + cand + p.suffix)
                if alt.exists():
                    self._custom_bold = str(alt)
                    break
        self._refresh_font_label()

    def _refresh_font_label(self):
        fp, fb = self._selected_font()
        if fp:
            txt = f"常规体：{fp}"
            if fb:
                txt += f"\n粗体：{fb}"
            else:
                txt += "\n（未找到粗体变体，将以常规体代替）"
            self.lbl_font_path.setText(txt)
        else:
            self.lbl_font_path.setText("")

    def _accept(self):
        directory = self.ed_dir.text().strip()
        file_name = self.ed_name.text().strip()
        if not directory:
            QMessageBox.information(self, "提示", "请选择导出目录。")
            return
        if not file_name.lower().endswith(".pdf"):
            file_name += ".pdf"
            self.ed_name.setText(file_name)
        if not Path(directory).is_dir():
            QMessageBox.information(self, "提示", "导出目录不存在，请重新选择。")
            return
        fp, fb = self._selected_font()
        if not fp or not Path(fp).exists():
            QMessageBox.information(self, "提示", "所选字体文件不存在，请重新选择字体。")
            return
        self.config = PdfConfig(directory=directory, file_name=file_name,
                                font_path=fp, font_bold_path=fb)
        self._save_settings()
        self.accept()
