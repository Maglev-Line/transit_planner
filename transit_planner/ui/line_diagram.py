# -*- coding: utf-8 -*-
"""线路图风格的可视化线路编辑控件。

以 o-o-o-o 形式展示一条线路及其支线，供用户可视化增删改车站与区间：
- 圆圈 = 车站（圆圈内写站名，使用线路标志色），单击选中、双击改名
- 线段 = 区间（线段下方标注 travel_minutes），单击选中、双击改时长
- 线段上方、线路两端的「+」按钮用于在区间中间 / 两端加站
- 环线以上下两行 + 左右裸拐角竖线的矩形环展示（去掉首尾重复站，拐点不放车站）
- 支线与主线合并显示为同一线路图：支线从主支分离点向一侧延伸

数据直接修改传入的 Line 对象（支线即城市库中独立的 Line 对象）；
任何修改都会发出 sig_changed 信号，由外部（数据编辑器）刷新列表并落盘。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QInputDialog, QMenu, QMessageBox, QWidget

from ..core.models import City, Line

COL_W = 160        # 相邻车站圆心水平间距
R = 20             # 车站圆圈半径
MAIN_Y = 90        # 主线车站圆心纵坐标
BRANCH_GAP = 130   # 主线与支线、支线之间的行距
RING_GAP = 150     # 环线上行与下行两行之间的行距
CORNER_INSET = 36  # 环线车站圆心到拐角竖线的距离（拐角处不放车站）
PAD_X = 80         # 左右留白
PAD_TOP = 40
PAD_BOTTOM = 70
BTN_R = 11         # 加号按钮半径


def _branch_base(name: str) -> str:
    """去掉名称末尾的『支线』与编号，得到线路基名（如 上海地铁5号线支线2 → 上海地铁5号线）。"""
    s = name
    while s.endswith("支线"):
        s = s[:-2]
    while s and s[-1].isdigit():
        s = s[:-1]
    return s


def is_branch_line(city: City | None, main: Line | None, ln: Line) -> bool:
    """判断 ln 是否为 main 的支线。

    规则（均需与主线共站）：
    - ID 遵循 <主线ID>b 命名约定（如 sh_m5 → sh_m5b）；或
    - 名称含『支线』且线路基名与主线相同（如 上海地铁5号线支线 ↔ 上海地铁5号线）。
    """
    if city is None or main is None or ln.id == main.id:
        return False
    if not (set(ln.stations) & set(main.stations)):
        return False
    if main.id and (ln.id.startswith(main.id + "b") or ln.id.startswith(main.id + "_b")):
        return True
    return "支线" in ln.name and _branch_base(ln.name) == _branch_base(main.name)


def find_branch_lines(city: City | None, main: Line | None) -> list[Line]:
    """返回 main 的全部支线（保持城市库中的顺序）。"""
    if city is None or main is None:
        return []
    return [ln for ln in city.lines if is_branch_line(city, main, ln)]


def _fmt_min(m: float) -> str:
    """区间时长短格式：3 / 3.5 / 4.5 分。"""
    return f"{m:g}分"


def _contrast(hex_color: str) -> QColor:
    """按背景亮度返回黑色或白色文字色。"""
    c = QColor(hex_color or "#888888")
    lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
    return QColor("#222222") if lum > 150 else QColor("#ffffff")


class LineDiagramWidget(QWidget):
    """线路图可视化编辑控件。"""

    sig_changed = Signal()             # 数据发生变化（站/区间/支线增删改）
    sig_split_picked = Signal(str)     # 添加支线时选定了分离点车站名

    def __init__(self, parent=None):
        super().__init__(parent)
        self._city: City | None = None
        self._main: Line | None = None
        self._branches: list[Line] = []
        self._main_nodes: list[dict] = []
        self._nodes: list[dict] = []
        self._segs: list[dict] = []
        self._btns: list[dict] = []
        self._split_main: set = set()
        self._sel: object = None
        self._pick_mode = False
        self.default_minutes = 3.0
        self.setMouseTracking(True)
        self.setMinimumSize(220, 140)

    # ---------------- 对外接口 ----------------
    def set_line(self, city: City | None, line: Line | None) -> None:
        """绑定要编辑的线路（含其支线）。"""
        self._city = city
        self._main = line
        self._branches = find_branch_lines(city, line)
        self._sel = None
        self._pick_mode = False
        self._layout()
        self.update()

    def start_branch_pick(self) -> None:
        """进入『添加支线』模式：等待点击主线车站作为分离点。"""
        if self._main is None:
            return
        self._pick_mode = True
        self.update()

    def cancel_branch_pick(self) -> None:
        """取消『添加支线』模式。"""
        if not self._pick_mode:
            return
        self._pick_mode = False
        self.update()

    # ---------------- 布局 ----------------
    def _layout(self) -> None:
        self._nodes, self._segs, self._btns = [], [], []
        self._main_nodes = []
        self._split_main = set()
        if self._main is None:
            self.setMinimumSize(220, 140)
            return
        ln = self._main
        if len(ln.stations) == 0:
            self.setMinimumSize(220, 140)
            return
        if ln.ring:
            self._branch_base = MAIN_Y + RING_GAP
            self._layout_ring()
        else:
            self._branch_base = MAIN_Y
            self._layout_straight()
        # 支线
        for bi, br in enumerate(self._branches):
            self._layout_branch(bi, br)
        # 左溢出修正（向左延伸的支线可能越界）
        minx = min((nd["x"] for nd in self._nodes), default=PAD_X)
        for sg in self._segs:
            if "pts" in sg:
                minx = min(minx, min(p.x() for p in sg["pts"]))
        for bt in self._btns:
            minx = min(minx, bt["rect"].left())
        if minx < PAD_X:
            dx = PAD_X - minx
            for nd in self._nodes:
                nd["x"] += dx
            for sg in self._segs:
                if "pts" in sg:
                    sg["pts"] = [p + QPointF(dx, 0) for p in sg["pts"]]
                    sg["label_pos"] += QPointF(dx, 0)
                else:
                    sg["p1"] += QPointF(dx, 0)
                    sg["p2"] += QPointF(dx, 0)
                sg["hit"].translate(dx, 0)
            for bt in self._btns:
                bt["rect"].translate(dx, 0)
        # 内容尺寸
        maxx = max((nd["x"] for nd in self._nodes), default=PAD_X)
        maxy = MAIN_Y
        for bt in self._btns:
            maxx = max(maxx, bt["rect"].right())
            maxy = max(maxy, bt["rect"].bottom())
        for sg in self._segs:
            maxx = max(maxx, sg["hit"].right())
            maxy = max(maxy, sg["hit"].bottom())
        for nd in self._nodes:
            maxy = max(maxy, nd["y"] + R + 22)
        self.setMinimumSize(int(maxx + PAD_X), int(maxy + PAD_BOTTOM))

    def _mk_seg(self, ref, line: Line, tm_idx: int, p1=None, p2=None,
                pts=None, label_pos=None) -> dict:
        """新建一个区间条目。ref 用于选中；tm_idx 指向 travel_minutes 下标。"""
        tm = line.travel_minutes
        sg = {"ref": ref, "line": line, "tm_idx": tm_idx,
              "minutes": tm[tm_idx] if tm_idx < len(tm) else 0.0}
        if pts is not None:
            sg["pts"] = pts
            sg["label_pos"] = label_pos
        else:
            sg["p1"] = p1
            sg["p2"] = p2
        sg["hit"] = self._seg_hit_rect(sg)
        self._segs.append(sg)
        return sg

    def _layout_straight(self) -> None:
        """非环线：单行直链布局（含区间上方与两端的加号按钮）。"""
        ln = self._main
        n = len(ln.stations)
        for i, s in enumerate(ln.stations):
            nd = {"ref": ("main", i), "label": s,
                  "x": PAD_X + i * COL_W, "y": MAIN_Y}
            self._main_nodes.append(nd)
            self._nodes.append(nd)
        for i in range(n - 1):
            a, b = self._main_nodes[i], self._main_nodes[i + 1]
            self._mk_seg(("main", i), ln, i,
                         p1=QPointF(a["x"], a["y"]), p2=QPointF(b["x"], b["y"]))
        for i in range(n - 1):
            a, b = self._main_nodes[i], self._main_nodes[i + 1]
            self._add_btn(("main_seg", i), QPointF((a["x"] + b["x"]) / 2, MAIN_Y - 26),
                          ln, i + 1, i + 1)
        if n >= 1:
            first, last = self._main_nodes[0], self._main_nodes[-1]
            self._add_btn(("main_end", "left"), QPointF(first["x"] - 34, first["y"]), ln, 0)
            self._add_btn(("main_end", "right"), QPointF(last["x"] + 34, last["y"]),
                          ln, len(ln.stations))

    def _layout_ring(self) -> None:
        """环线：上下两行 + 左右裸拐角竖线的矩形环。

        - 去掉首尾重复站（如 上海4号线 stations[0] 与 stations[-1] 均为『宜山路』，只画一次）；
        - 上行 = 前半段站（左→右），下行 = 后半段站（右→左）；
        - 左竖线 = 首尾闭合段（下行末站 → 上行首站），右竖线 = 上下行连接段；
        - 四个拐角均为裸折线（不放车站）。
        """
        ln = self._main
        has_dup = len(ln.stations) >= 2 and ln.stations[0] == ln.stations[-1]
        U = ln.stations[:-1] if has_dup else ln.stations
        m = len(U)
        if m == 0:
            return
        tm = ln.travel_minutes
        top_count = (m + 1) // 2
        bot_count = m - top_count
        ext = (top_count - 1) * COL_W
        ring_left = PAD_X + 50
        ring_right = ring_left + ext + 2 * CORNER_INSET
        top_y = MAIN_Y
        bot_y = MAIN_Y + RING_GAP
        # 车站节点：上行（左→右）、下行（右→左）
        top_nodes, bot_nodes = [], []
        for i in range(top_count):
            nd = {"ref": ("main", i), "label": U[i],
                  "x": ring_left + CORNER_INSET + i * COL_W, "y": top_y}
            self._main_nodes.append(nd)
            self._nodes.append(nd)
            top_nodes.append(nd)
        for j in range(bot_count):
            i = top_count + j
            if bot_count == 1:
                x = (ring_left + ring_right) / 2
            else:
                x = ring_left + CORNER_INSET + ext * (bot_count - 1 - j) / (bot_count - 1)
            nd = {"ref": ("main", i), "label": U[i], "x": x, "y": bot_y}
            self._main_nodes.append(nd)
            self._nodes.append(nd)
            bot_nodes.append(nd)
        # 上行区间
        for i in range(top_count - 1):
            a, b = top_nodes[i], top_nodes[i + 1]
            self._mk_seg(("main", i), ln, i,
                         p1=QPointF(a["x"], a["y"]), p2=QPointF(b["x"], b["y"]))
        # 下行区间
        for i in range(top_count, m - 1):
            a = bot_nodes[i - top_count]
            b = bot_nodes[i + 1 - top_count]
            self._mk_seg(("main", i), ln, i,
                         p1=QPointF(a["x"], a["y"]), p2=QPointF(b["x"], b["y"]))
        # 右竖线：上行末站 → 下行首站
        if bot_count >= 1:
            a, b = top_nodes[-1], bot_nodes[0]
            mid_y = (top_y + bot_y) / 2
            pts = [QPointF(a["x"], a["y"]), QPointF(ring_right, a["y"]),
                   QPointF(ring_right, b["y"]), QPointF(b["x"], b["y"])]
            self._mk_seg(("ring_right",), ln, top_count - 1, pts=pts,
                         label_pos=QPointF(ring_right, mid_y))
            self._add_btn(("ring_seg_add", "right"), QPointF(ring_right + 44, mid_y),
                          ln, top_count, top_count)
        # 左竖线：下行末站 → 上行首站（首尾闭合段）
        if m >= 2:
            a, b = bot_nodes[-1], top_nodes[0]
            mid_y = (top_y + bot_y) / 2
            pts = [QPointF(a["x"], a["y"]), QPointF(ring_left, a["y"]),
                   QPointF(ring_left, b["y"]), QPointF(b["x"], b["y"])]
            self._mk_seg(("ring_close",), ln, len(tm) - 1, pts=pts,
                         label_pos=QPointF(ring_left, mid_y))
            self._add_btn(("ring_seg_add", "left"), QPointF(ring_left - 44, mid_y),
                          ln, m, m - 1)
        # 加号按钮：区间上方（上行在环外上方、下行在环内上方）
        for i in range(top_count - 1):
            a, b = top_nodes[i], top_nodes[i + 1]
            self._add_btn(("main_seg", i), QPointF((a["x"] + b["x"]) / 2, top_y - 26),
                          ln, i + 1, i + 1)
        for i in range(top_count, m - 1):
            a, b = bot_nodes[i - top_count], bot_nodes[i + 1 - top_count]
            self._add_btn(("main_seg", i), QPointF((a["x"] + b["x"]) / 2, bot_y - 26),
                          ln, i + 1, i + 1)

    def _layout_branch(self, bi: int, br: Line) -> None:
        """计算一条支线的节点与区间（含支线内的加号按钮）。"""
        ln = self._main
        row_y = self._branch_base + (bi + 1) * BRANCH_GAP
        shared = set(br.stations) & set(ln.stations)
        m = len(br.stations)
        split_i, side = None, "right"
        if shared and m >= 2:
            pre = 0
            while pre < m and br.stations[pre] not in shared:
                pre += 1
            suf = 0
            while suf < m and br.stations[m - 1 - suf] not in shared:
                suf += 1
            if suf >= pre and suf > 0:
                split_i, side = m - 1 - suf, "right"
            elif pre > 0:
                split_i, side = pre, "left"
        if split_i is None:
            # 与主线不共站 / 无法判定分离点：作为独立链展示，仍可编辑
            self._layout_branch_standalone(bi, br, row_y)
            return
        split_name = br.stations[split_i]
        try:
            midx = ln.stations.index(split_name)
        except ValueError:
            self._layout_branch_standalone(bi, br, row_y)
            return
        # 在已布局的主线节点中定位分离点（直线/环线通用）
        split_x = None
        for nd in self._nodes:
            if nd["ref"] == ("main", midx):
                split_x = nd["x"]
                break
        if split_x is None:
            self._layout_branch_standalone(bi, br, row_y)
            return
        self._split_main.add(("main", midx))
        if side == "right":
            ext_idx = list(range(split_i + 1, m))   # 支线唯一站索引（沿站表）
            base_seg = split_i
        else:
            ext_idx = list(range(split_i - 1, -1, -1))  # 逆序：从分离点向外
            base_seg = split_i - 1
        # 支线车站节点
        node_refs = []
        for j, bi_ in enumerate(ext_idx):
            x = split_x + (j + 1) * COL_W if side == "right" else split_x - (j + 1) * COL_W
            nd = {"ref": ("branch", bi, bi_), "label": br.stations[bi_],
                  "x": x, "y": row_y}
            self._nodes.append(nd)
            node_refs.append(nd)
        if not node_refs:
            return
        # 分离点 → 首个支线站 的区间
        first = node_refs[0]
        seg_idx = base_seg
        self._mk_seg(("branch", bi, seg_idx), br, seg_idx,
                     p1=QPointF(split_x, row_y), p2=QPointF(first["x"], row_y))
        self._add_btn(("branch_seg", bi, seg_idx),
                      QPointF((split_x + first["x"]) / 2, row_y - 26),
                      br, seg_idx + 1)
        # 支线站之间的区间
        for j in range(len(node_refs) - 1):
            a, b = node_refs[j], node_refs[j + 1]
            if side == "right":
                seg_idx = base_seg + 1 + j
            else:
                seg_idx = base_seg - 1 - j
            self._mk_seg(("branch", bi, seg_idx), br, seg_idx,
                         p1=QPointF(a["x"], a["y"]), p2=QPointF(b["x"], b["y"]))
            self._add_btn(("branch_seg", bi, seg_idx),
                          QPointF((a["x"] + b["x"]) / 2, row_y - 26),
                          br, seg_idx + 1)
        # 支线远端加号（分离点为共享站，不提供加站）
        far = node_refs[-1]
        if side == "right":
            self._add_btn(("branch_end", bi, "right"), QPointF(far["x"] + 34, row_y),
                          br, len(br.stations))
        else:
            self._add_btn(("branch_end", bi, "left"), QPointF(far["x"] - 34, row_y),
                          br, 0)

    def _layout_branch_standalone(self, bi: int, br: Line, row_y: float) -> None:
        """支线与主线不共站时的兜底：作为独立链展示。"""
        node_refs = []
        for i, s in enumerate(br.stations):
            nd = {"ref": ("branch", bi, i), "label": s,
                  "x": PAD_X + i * COL_W, "y": row_y}
            self._nodes.append(nd)
            node_refs.append(nd)
        for i in range(len(node_refs) - 1):
            a, b = node_refs[i], node_refs[i + 1]
            self._mk_seg(("branch", bi, i), br, i,
                         p1=QPointF(a["x"], a["y"]), p2=QPointF(b["x"], b["y"]))
            self._add_btn(("branch_seg", bi, i),
                          QPointF((a["x"] + b["x"]) / 2, row_y - 26), br, i + 1)
        if node_refs:
            self._add_btn(("branch_end", bi, "left"), QPointF(node_refs[0]["x"] - 34, row_y), br, 0)
            self._add_btn(("branch_end", bi, "right"), QPointF(node_refs[-1]["x"] + 34, row_y),
                          br, len(br.stations))

    def _add_btn(self, ref, center: QPointF, line: Line, insert_idx: int,
                 tm_idx: int | None = None) -> None:
        """记录一个加号按钮。insert_idx=站表插入位置；tm_idx=时长表插入位置。"""
        self._btns.append({
            "ref": ref,
            "rect": QRectF(center.x() - BTN_R, center.y() - BTN_R, 2 * BTN_R, 2 * BTN_R),
            "line": line,
            "insert_idx": insert_idx,
            "tm_idx": insert_idx if tm_idx is None else tm_idx,
        })

    @staticmethod
    def _seg_hit_rect(sg: dict) -> QRectF:
        if "pts" in sg:
            xs = [p.x() for p in sg["pts"]]
            ys = [p.y() for p in sg["pts"]]
            return QRectF(min(xs) - 8, min(ys) - 8,
                          max(xs) - min(xs) + 16, max(ys) - min(ys) + 16)
        p1, p2 = sg["p1"], sg["p2"]
        return QRectF(min(p1.x(), p2.x()) - 8, min(p1.y(), p2.y()) - 8,
                      abs(p2.x() - p1.x()) + 16, abs(p2.y() - p1.y()) + 16)

    # ---------------- 命中检测 ----------------
    def _node_rect(self, nd: dict) -> QRectF:
        return QRectF(nd["x"] - R, nd["y"] - R, 2 * R, 2 * R)

    def _item_at(self, pos: QPointF):
        """返回 (kind, item)；kind ∈ btn/node/seg。

        命中优先级与绘制顺序一致：按钮 → 车站 → 线段。
        车站圆圈覆盖在线段上方，若先测线段，点击圆心会命中下方的线段而非车站，
        导致添加支线时点分离点『没反应』。
        """
        for bt in self._btns:
            if bt["rect"].contains(pos):
                return ("btn", bt)
        for nd in self._nodes:
            if self._node_rect(nd).contains(pos):
                return ("node", nd)
        for sg in self._segs:
            if sg["hit"].contains(pos):
                return ("seg", sg)
        return None

    # ---------------- 交互 ----------------
    def mouseMoveEvent(self, ev):
        hit = self._item_at(ev.position())
        self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)
        super().mouseMoveEvent(ev)

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return super().mousePressEvent(ev)
        pos = ev.position()
        hit = self._item_at(pos)
        if hit is None:
            self._sel = None
            self.update()
            return
        kind, item = hit
        if kind == "btn":
            if self._pick_mode:
                return
            self._add_station(item)
            return
        if kind == "node":
            if self._pick_mode:
                if item["ref"][0] == "main":
                    self.sig_split_picked.emit(item["label"])
                return
            self._sel = item["ref"]
            self.update()
            return
        if kind == "seg":
            if self._pick_mode:
                return  # 添加支线模式下点击线段无效，仅车站可作为分离点
            self._sel = item["ref"]
            self.update()

    def mouseDoubleClickEvent(self, ev):
        if ev.button() != Qt.LeftButton or self._pick_mode:
            return super().mouseDoubleClickEvent(ev)
        hit = self._item_at(ev.position())
        if hit is None:
            return
        kind, item = hit
        if kind == "node":
            self._edit_station(item)
        elif kind == "seg":
            self._edit_seg(item)
        elif kind == "btn":
            self._add_station(item)

    def contextMenuEvent(self, ev):
        if self._main is None:
            return
        hit = self._item_at(ev.position())
        if hit is None:
            return
        kind, item = hit
        menu = QMenu(self)
        if kind == "node":
            ref = item["ref"]
            if ref[0] == "main":
                menu.addAction("编辑站名", lambda: self._edit_station(item))
                menu.addAction("删除该站", lambda: self._del_main_station(item))
            else:
                menu.addAction("编辑站名", lambda: self._edit_station(item))
                menu.addAction("删除该支线", lambda: self._del_branch(ref[1]))
        elif kind == "seg":
            menu.addAction("编辑区间时长", lambda: self._edit_seg(item))
        elif kind == "btn":
            menu.addAction("在此处加站", lambda: self._add_station(item))
        menu.exec(ev.globalPos())

    # ---------------- 数据操作 ----------------
    def _ensure_minutes(self, line: Line) -> None:
        """补齐 travel_minutes 到应有长度（环线含首尾闭合段）。"""
        need = len(line.stations) - 1
        if line.ring and line.stations:
            need += 1
        need = max(need, 0)
        while len(line.travel_minutes) < need:
            line.travel_minutes.append(self.default_minutes)

    def _edit_station(self, item: dict) -> None:
        ref, old = item["ref"], item["label"]
        name, ok = QInputDialog.getText(self, "编辑车站", "车站名称：", text=old)
        if not ok or not name.strip() or name.strip() == old:
            return
        new = name.strip()
        # 同名站全库同步，保证主线/支线共享站名一致
        if self._city is not None:
            for ln in self._city.lines:
                if old in ln.stations:
                    ln.stations = [new if s == old else s for s in ln.stations]
        self._changed()

    def _edit_seg(self, item: dict) -> None:
        line = item["line"]
        idx = item["tm_idx"]
        self._ensure_minutes(line)
        cur = line.travel_minutes[idx] if idx < len(line.travel_minutes) else 3.0
        val, ok = QInputDialog.getDouble(self, "编辑区间", "区间运行时长（分钟）：",
                                         cur, 0.5, 120.0, 1)
        if not ok:
            return
        self._ensure_minutes(line)
        line.travel_minutes[idx] = val
        self._changed()

    def _add_station(self, btn: dict) -> None:
        line = btn["line"]
        idx = btn["insert_idx"]
        tm_idx = btn["tm_idx"]
        name, ok = QInputDialog.getText(self, "添加车站", "车站名称：", text="新站")
        if not ok or not name.strip():
            return
        self._ensure_minutes(line)  # 先按旧站数补齐，再插入站与时长
        line.stations.insert(idx, name.strip())
        line.travel_minutes.insert(min(tm_idx, len(line.travel_minutes)), self.default_minutes)
        self._changed()

    def _del_main_station(self, item: dict) -> None:
        ln = self._main
        idx = item["ref"][1]
        if len(ln.stations) <= 2:
            QMessageBox.information(self, "提示", "至少保留 2 个站点")
            return
        if QMessageBox.question(self, "删除车站",
                                f"确定删除车站「{item['label']}」？") != QMessageBox.Yes:
            return
        del ln.stations[idx]
        if idx < len(ln.travel_minutes):
            del ln.travel_minutes[idx]
        self._changed()

    def _del_branch(self, bi: int) -> None:
        br = self._branches[bi]
        if QMessageBox.question(self, "删除支线",
                                f"确定删除支线「{br.name}」？") != QMessageBox.Yes:
            return
        if self._city is not None and br in self._city.lines:
            self._city.lines.remove(br)
        self._changed()

    def _changed(self) -> None:
        self._layout()
        self.update()
        self.sig_changed.emit()

    # ---------------- 绘制 ----------------
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#fafafa"))
        if self._main is None:
            p.setPen(QColor("#999999"))
            p.drawText(self.rect(), Qt.AlignCenter, "请选择或新建一条线路")
            return
        color = self._main.color or "#888888"
        for sg in self._segs:
            self._draw_seg(p, sg, color)
        for nd in self._nodes:
            self._draw_node(p, nd, color)
        for bt in self._btns:
            self._draw_btn(p, bt, color)
        if self._pick_mode:
            p.setPen(QColor("#c0392b"))
            f = QFont(self.font().family(), 9)
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRectF(0, 6, self.width(), 22), Qt.AlignHCenter,
                       "▶ 请点击主线上的车站作为主支分离点")

    def _draw_seg(self, p: QPainter, sg: dict, color: str) -> None:
        sel = self._sel == sg["ref"]
        if "pts" in sg:
            path = QPainterPath(sg["pts"][0])
            for pt in sg["pts"][1:]:
                path.lineTo(pt)
        else:
            path = QPainterPath(sg["p1"])
            path.lineTo(sg["p2"])
        if sel:
            p.setPen(QPen(QColor("#ffffff"), 11, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)
        p.setPen(QPen(QColor(color), 6 if sel else 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)
        # 区间时长标签（线段下方；环线竖线标签居中于线上）
        if "pts" in sg:
            lp = sg["label_pos"]
        else:
            lp = QPointF((sg["p1"].x() + sg["p2"].x()) / 2,
                         max(sg["p1"].y(), sg["p2"].y()) + 16)
        p.setPen(QColor("#555555"))
        p.setFont(QFont(self.font().family(), 8))
        p.drawText(QRectF(lp.x() - 30, lp.y() - 8, 60, 16), Qt.AlignCenter,
                   _fmt_min(sg["minutes"]))

    def _draw_node(self, p: QPainter, nd: dict, color: str) -> None:
        sel = self._sel == nd["ref"]
        cx, cy = nd["x"], nd["y"]
        rect = self._node_rect(nd)
        if sel:
            p.setPen(QPen(QColor("#ffffff"), 6))
            p.setBrush(QBrush(QColor(color)))
            p.drawEllipse(rect.adjusted(-4, -4, 4, 4))
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.setBrush(QBrush(QColor(color)))
        p.drawEllipse(rect)
        # 主支分离点：虚线外圈
        if nd["ref"] in self._split_main:
            p.setPen(QPen(QColor(color), 1.5, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(rect.adjusted(-5, -5, 5, 5))
        # 站名：短名写在圆圈内（白字），长名写在圆圈下方
        name = nd["label"]
        font = QFont(self.font().family(), 8)
        font.setBold(True)
        fm = QFontMetrics(font)
        if fm.horizontalAdvance(name) <= 2 * R - 8:
            p.setFont(font)
            p.setPen(_contrast(color))
            p.drawText(rect, Qt.AlignCenter, name)
        else:
            font.setBold(False)
            p.setFont(font)
            p.setPen(QColor("#333333"))
            p.drawText(QRectF(cx - 70, cy + R + 2, 140, 18), Qt.AlignHCenter | Qt.AlignTop, name)
        # 添加支线模式：主线车站红色提示圈
        if self._pick_mode and nd["ref"][0] == "main":
            p.setPen(QPen(QColor("#e74c3c"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(rect.adjusted(-3, -3, 3, 3))

    def _draw_btn(self, p: QPainter, bt: dict, color: str) -> None:
        r = bt["rect"]
        p.setPen(QPen(QColor(color), 2))
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(r)
        f = QFont(self.font().family(), 10)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(color))
        p.drawText(r, Qt.AlignCenter, "+")
