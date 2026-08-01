# -*- coding: utf-8 -*-
"""运转计划助手 - 入口。

用法：python app.py
"""
import sys, io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from PySide6.QtWidgets import QApplication

from transit_planner.core.models import CityLibrary
from transit_planner.ui.main_window import MainWindow

DATA_DIR = Path(__file__).resolve().parent / "transit_planner" / "data"


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("运转计划助手")
    library = CityLibrary(DATA_DIR)
    if not library.list_cities():
        print("提示：data 目录下暂无城市线路库，请先在“数据编辑”中创建。")
    win = MainWindow(library)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
