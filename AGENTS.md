# AGENTS.md — 运转计划助手

面向交通迷的绕路运转行程规划工具（Python 3.10+ · PySide6 · reportlab，Windows 优先）。**不做自动寻路**，采用「链条式手动规划 + 智能提示」。完整功能与用法见 [README.md](README.md)。

## 常用命令

- 安装依赖：`pip install -r requirements.txt`（仅 PySide6、reportlab 两个依赖）
- 运行（源码）：`python app.py`
- 打包：`pyinstaller 运转计划助手.spec`（输出 `dist/运转计划助手.exe`）
- 种子数据：`python -m transit_planner.tools.gen_seed`（⚠️ 会覆盖 `data/*.json`，运行前先备份）
- **无任何测试基建**（无 pytest/unittest）。改核心逻辑后请 `python app.py` 手工冒烟验证。

## 架构与数据流（改动前必读）

- `core/`（纯逻辑，无 UI 依赖）与 `ui/`（PySide6 界面）完全解耦：UI 只通过 `core/engine.py` 的纯函数与 `core/models.py` 的 dataclass 交互。
- **`engine.evaluate_trip()` 是唯一权威计算入口**（分段时长、经停站、换乘判定、付费区分组、全程统计）。不要在 UI 或 exporter 中重复实现这些计算。
- 数据流：`data/*.json → CityLibrary.load → City`，界面录入生成 `Step` 加入 `Trip.steps`，经 `evaluate_trip` 得 `TripResult / SegmentResult`，由 `StepsPanel` 展示、`PDFExporter` 导出。
- **`Step` 字段增删必须四处同步**：`core/models.py` 的 `to_dict/from_dict`、`ui/add_step_dialog.py`、`ui/steps_panel.py` 的 `_detail_html`、`pdf/exporter.py`。漏一处会导致序列化/展示/导出不一致。
- 组合城市（上海-苏州 / 广州-佛山 / 珠江三角洲）由 `CityLibrary._load_combined` 在内存合并为**只读虚拟城市**，不落盘；不要为它们单独创建 JSON。

## 领域概念（三个易混淆概念，改前先读 `core/engine.py` 头部）

- **同站异名 `aliases`**：同一车站、同一付费系统，仅名称不同（如 广州西塱↔广佛线西朗）→ 按同站换乘、步行 0。
- **转乘 `transfers`**：跨付费区、需出闸/换系统（如 地铁↔国铁、上海南站↔上海南）→ 自动标记「转乘」，本段开始新付费区。
- **付费区 `paid_zone_mode`**：勾选后不出闸的连续行程为一段付费区，票价按进闸段一次计费；`step_is_transfer` 优先级：用户强制指定 > 库中 `transfers` 自动判定。
- 换乘步行：每段间可单独配置 `walk_minutes`（同站自动 0，默认 5 分钟）。

## 数据文件约定（`transit_planner/data/<城市>.json`）

完整 JSON 结构见 [README.md#城市库-json-结构](README.md)。关键约束：

- `travel_minutes` 长度 = 站点数 − 1（环线 `ring: true` 再多 1 个首尾闭合段）。
- `directions` 留空则自动按两端终点生成；`headway_rush / headway_normal` 填 0 表示不定班。
- 线路 `id` 建议 `<城市前缀>_<线号>`（如 `sh_m1`）。
- 新增城市/线路只改 `data/*.json` 或 `tools/gen_seed.py`，不要动组合城市。

## 约定与坑

- docstring / 注释 / 用户可见错误用**中文**；规划错误抛 `LineError`、在线 API 抛 `OnlineProviderError`，异常须能被 UI 捕获并显示，不可裸奔崩溃。
- 全面使用类型注解 + `from __future__ import annotations`；dataclass 序列化手写 `to_dict / from_dict`（不用 `asdict`）。
- `CityLibrary.save` 用 `.tmp` 原子替换、`ensure_ascii=False, indent=2`。
- 打包（frozen）后数据目录在 **exe 同级 `data/`**，不要往 `_MEIPASS` 写用户数据；改动路径逻辑须同时验证源码与打包两种模式（`app.py::_data_dir`）。
- PDF 中文字体：reportlab 默认微软雅黑（`exporter.py::DEFAULT_FONT_REGISTRY`），`.ttc` 用 `subfontIndex=0`；字体注册失败会静默回退 Helvetica（中文乱码）。
- 两套 QSettings：设置类 `ORG="运转计划助手" APP="settings"`；PDF 导出 `APP="pdf_export"`。`AppSettings.load` 处理了 QSettings 空列表以空串返回的坑。
- 改 UI 时注意 `blockSignals(True/False)` 避免 QComboBox 等信号重入。
