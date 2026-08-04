# -*- coding: utf-8 -*-
"""运转计划助手 - 入口。

用法：python app.py（源码运行）
打包：pyinstaller --onefile --windowed app.py（打包后自动使用 exe 同级 data 目录）
"""
import sys, io, shutil
from pathlib import Path

if sys.stdout is not None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr is not None:
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from PySide6.QtWidgets import QApplication

from transit_planner.core.models import CityLibrary
from transit_planner.ui.main_window import MainWindow


def _data_dir() -> Path:
    """城市线路库目录。

    源码运行：transit_planner/data（与仓库一致）。
    打包运行：exe 同级 data 目录（便携、可写）；首次运行时把内置的默认城市库复制过去，
    之后用户编辑只影响该目录，升级程序不会覆盖用户数据。
    """
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
        d = base / "data"
        bundled = Path(getattr(sys, "_MEIPASS", base)) / "transit_planner" / "data"
        d.mkdir(parents=True, exist_ok=True)
        if bundled.exists():
            for src in bundled.glob("*.json"):
                dst = d / src.name
                if not dst.exists():
                    shutil.copy2(src, dst)
        return d
    return Path(__file__).resolve().parent / "transit_planner" / "data"


DATA_DIR = _data_dir()


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
