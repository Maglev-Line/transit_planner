"""PDF 导出：基于 reportlab 生成可直接持图运转的 A4 中文文档。

特性：线路标志色色带、分段时间轴、完整经停站列表、发车班次、换乘节点、全程汇总。
支持在导出时指定字体（常规体 + 粗体）。
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

from ..core.engine import evaluate_trip, TripResult, SegmentResult, price_total
from ..core.models import City, Trip, fmt_minutes

DEFAULT_FONT_REGISTRY = [
    ("YaHei", r"C:\Windows\Fonts\msyh.ttc"),
    ("YaHei-Bold", r"C:\Windows\Fonts\msyhbd.ttc"),
]
DEFAULT_FONT = "YaHei"
DEFAULT_FONT_BOLD = "YaHei-Bold"


def register_fonts(registry: list) -> None:
    for name, path in registry:
        if name in pdfmetrics.getRegisteredFontNames():
            continue
        p = Path(path)
        if p.exists():
            pdfmetrics.registerFont(TTFont(name, str(p), subfontIndex=0))
        else:
            pdfmetrics.registerFont(TTFont(name, str(p)))  # 可能失败则抛错


def _ensure_fonts(registry: list) -> None:
    try:
        register_fonts(registry)
    except Exception:
        # 回退到内置 Helvetica（中文会乱码，但避免崩溃）
        pass


def text_color_for_bg(hex_color: str) -> colors.Color:
    """按背景色亮度返回白或黑文字。"""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return colors.white if lum < 0.6 else colors.black


def to_color(hex_color: str) -> colors.Color:
    try:
        return colors.HexColor(hex_color)
    except Exception:
        return colors.grey


class PDFExporter:
    def __init__(self, font_registry: list | None = None,
                 font: str = DEFAULT_FONT, font_bold: str = DEFAULT_FONT_BOLD) -> None:
        self._registry = list(font_registry) if font_registry else list(DEFAULT_FONT_REGISTRY)
        self.font = font
        self.font_bold = font_bold
        _ensure_fonts(self._registry)

    # ---------- 样式 ----------
    def _styles(self):
        return {
            "title": ParagraphStyle("title", fontName=self.font_bold, fontSize=20, leading=26,
                                    alignment=TA_CENTER, textColor=colors.HexColor("#1a1a2e")),
            "subtitle": ParagraphStyle("subtitle", fontName=self.font, fontSize=10, leading=15,
                                       alignment=TA_CENTER, textColor=colors.HexColor("#555555")),
            "h2": ParagraphStyle("h2", fontName=self.font_bold, fontSize=13, leading=18,
                                 textColor=colors.HexColor("#1a1a2e"), spaceBefore=6, spaceAfter=4),
            "body": ParagraphStyle("body", fontName=self.font, fontSize=9, leading=13),
            "body_sm": ParagraphStyle("body_sm", fontName=self.font, fontSize=8, leading=11),
            "band_name": ParagraphStyle("band_name", fontName=self.font_bold, fontSize=11, leading=14),
            "band_sub": ParagraphStyle("band_sub", fontName=self.font, fontSize=8.5, leading=12),
        }

    # ---------- 页面 ----------
    def _page_deco(self, canvas, doc, trip_name: str):
        canvas.saveState()
        canvas.setFont(self.font, 8)
        canvas.setFillColor(colors.HexColor("#888888"))
        canvas.drawString(15 * mm, 8 * mm, "运转计划助手 · 交通迷绕路运转 · 数据仅供参考，请以运营方实时信息为准")
        canvas.drawRightString(A4[0] - 15 * mm, 8 * mm, f"第 {doc.page} 页")
        canvas.restoreState()

    # ---------- 分段卡 ----------
    def _step_flowables(self, seg: SegmentResult, idx: int, st: dict,
                        paid_mode: bool = False, zones: dict | None = None):
        line = seg.line
        eff_color = seg.step.color or line.color
        eff_color2 = seg.step.color2 or line.color2
        bg = to_color(eff_color)
        fg = text_color_for_bg(eff_color)

        name_para = Paragraph(
            f"{line.name}　<font color='white'>█</font>　"
            f"<font name='{self.font_bold}'>{line.short_name}</font>"
            f"　<font color='#555555' size='8'>（{line.type_label}）</font>",
            st["band_name"])
        # 区块内容
        inner = []
        if paid_mode and zones is not None:
            z = zones.get(seg.paid_zone_index)
            if z is not None:
                is_entry = z.segments and z.segments[0].step is seg.step
                price_txt = f"　票价 ¥{z.price:.2f}" if z.price is not None else ""
                marker = "🛂 进闸" if is_entry else "　│"
                inner.append(Paragraph(
                    f"{marker} 付费区 {z.index + 1}：{z.entry_station} → {z.exit_station}{price_txt}",
                    st["band_sub"]))
        if seg.transfer:
            inner.append(Paragraph("⚠ 转乘（跨付费区，需出闸/换系统）", st["band_sub"]))
        inner.append(Paragraph(
            f"{seg.step.from_station} <font color='{eff_color}'>→</font> {seg.step.to_station}"
            f"　|　方向：<b>{seg.direction.label}</b>　|　<font color='{eff_color}'><b>{fmt_minutes(seg.run_minutes)}</b></font>"
            f"　|　{seg.stop_count} 站",
            st["band_sub"]))
        if seg.manual:
            parts = ["手动填写行程"]
            head_txt = (seg.step.headway_text or "").strip()
            if head_txt:
                parts.append(f"发车班次：{head_txt}")
            if seg.step.note:
                parts.append(f"备注/车次：{seg.step.note}")
            inner.append(Paragraph("　|　".join(parts), st["band_sub"]))
        else:
            inner.append(Paragraph(
                f"发车班次：{line.headway_text}" +
                (f"　|　首班 {line.first_train} / 末班 {line.last_train}" if line.first_train else ""),
                st["band_sub"]))
        if seg.step.use_timetable:
            inner.append(Paragraph("⏱ 按时刻表乘坐列车", st["band_sub"]))
            if seg.step.timetable:
                inner.append(self._timetable_flowable(seg.step, st))
        if seg.step.price is not None:
            inner.append(Paragraph(f"票价：<b>¥{seg.step.price:.2f}</b>", st["band_sub"]))
        stops_txt = '  →  '.join(seg.stops) if seg.stops else '（未填写经停站）'
        inner.append(Paragraph(f"经停站：{stops_txt}", st["body_sm"]))
        inner_tbl = Table([[inner]], colWidths=[170 * mm])
        inner_tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ]))

        # 左色带（双色：副色作为底部色条）+ 内容（仅保留阿拉伯数字序号）
        band_rows = [
            [Paragraph(f"{idx}", ParagraphStyle("idx", fontName=self.font_bold, fontSize=16, leading=20,
                                                alignment=TA_CENTER, textColor=fg))],
        ]
        color2 = to_color(eff_color2) if eff_color2 else None
        if color2 is not None:
            band_rows.append([Paragraph("", ParagraphStyle("stripe", fontName=self.font, fontSize=4))])
        band_tbl = Table(band_rows, colWidths=[12 * mm])
        band_style = [
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 1),
            ("RIGHTPADDING", (0, 0), (-1, -1), 1),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        if color2 is not None:
            n = len(band_rows)
            band_style.append(("BACKGROUND", (0, n - 1), (-1, n - 1), color2))
            band_style.append(("MINIMUMHEIGHT", (0, n - 1), (-1, n - 1), 7))
            band_style.append(("TOPPADDING", (0, n - 1), (-1, n - 1), 0))
            band_style.append(("BOTTOMPADDING", (0, n - 1), (-1, n - 1), 0))
        band_tbl.setStyle(TableStyle(band_style))

        outer = Table([[band_tbl, inner_tbl]], colWidths=[12 * mm, 178 * mm])
        outer.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ]))
        return outer

    def _timetable_flowable(self, step, st: dict) -> Table:
        """时刻表：车次 / 本站发时 / 到达站到时。"""
        head = ParagraphStyle("tt_h", fontName=self.font_bold, fontSize=8, leading=11,
                              alignment=TA_CENTER, textColor=colors.white)
        cell = ParagraphStyle("tt_b", fontName=self.font, fontSize=8, leading=11, alignment=TA_CENTER)
        rows = [[Paragraph("车次", head), Paragraph(f"本站({step.from_station})发时", head),
                 Paragraph(f"到达站({step.to_station})到时", head)]]
        for t in step.timetable:
            if not t or len(t) < 3:
                continue
            rows.append([Paragraph(str(t[0]), cell), Paragraph(str(t[1]), cell),
                         Paragraph(str(t[2]), cell)])
        tbl = Table(rows, colWidths=[34 * mm, 68 * mm, 68 * mm])
        style = [
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#445566")),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        for i in range(1, len(rows)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#eef2f7")))
        tbl.setStyle(TableStyle(style))
        return tbl

    def _transfer_flowable(self, seg: SegmentResult, prev: SegmentResult | None, st: dict):
        if prev is None:
            return None
        # 换乘提示：上一段到达站 → 本段起点
        from_st = seg.step.from_station
        prev_to = prev.step.to_station
        if seg.transfer:
            note = "转乘（跨付费区，需出闸/换系统）"
        elif seg.walk_minutes > 0:
            note = f"换乘步行约 {fmt_minutes(seg.walk_minutes)}"
        elif prev.line.id != seg.line.id:
            note = "站内换乘"
        else:
            note = "同线续乘"
        if seg.transfer or prev.line.id != seg.line.id or prev_to != from_st:
            return Paragraph(
                f"<b>↓ 换乘</b>　{prev_to} → <b>{from_st}</b>　({note})　"
                f"从 {prev.line.name} 换至 {seg.line.name}",
                ParagraphStyle("trans", fontName=self.font, fontSize=8.5, leading=12,
                               textColor=colors.HexColor("#0066aa"),
                               leftIndent=2, spaceBefore=4, spaceAfter=4))
        return None

    # ---------- 时间轴 ----------
    def _timeline(self, result: TripResult, st: dict) -> Table:
        total = result.total_run or 1
        seg_cols = []
        cells = []
        stripe = []
        for i, seg in enumerate(result.segments):
            eff_color = seg.step.color or seg.line.color
            fg = text_color_for_bg(eff_color)
            cells.append(Paragraph(f"{seg.line.short_name}\n{fmt_minutes(seg.run_minutes)}",
                                   ParagraphStyle("tl", fontName=self.font, fontSize=7, leading=9,
                                                  alignment=TA_CENTER, textColor=fg)))
            stripe.append(Paragraph("", ParagraphStyle("tl_stripe", fontName=self.font, fontSize=3)))
            seg_cols.append(max(20, 4 + int(seg.run_minutes / total * 900)))  # 按时长成比例
        rows = [cells, stripe]
        tbl = Table(rows, colWidths=seg_cols)
        style = [
            ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, 0), 4),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
            ("TOPPADDING", (0, 1), (-1, 1), 0),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 0),
            ("MINIMUMHEIGHT", (0, 1), (-1, 1), 4),
        ]
        for i, seg in enumerate(result.segments):
            eff_color = seg.step.color or seg.line.color
            eff_color2 = seg.step.color2 or seg.line.color2
            bg = to_color(eff_color)
            fg = text_color_for_bg(eff_color)
            style.append(("TEXTCOLOR", (i, 0), (i, 0), fg))
            style.append(("BACKGROUND", (i, 0), (i, 0), bg))
            if eff_color2:
                style.append(("BACKGROUND", (i, 1), (i, 1), to_color(eff_color2)))
            else:
                style.append(("BACKGROUND", (i, 1), (i, 1), bg))
        tbl.setStyle(TableStyle(style))
        return tbl

    # ---------- 主流程 ----------
    def export(self, city: City, trip: Trip, path: str | Path, open_then: bool = False) -> str:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        result = evaluate_trip(city, trip)
        st = self._styles()

        doc = BaseDocTemplate(
            str(path), pagesize=A4,
            leftMargin=15 * mm, rightMargin=15 * mm,
            topMargin=15 * mm, bottomMargin=15 * mm,
            title=f"{trip.name} - 运转方案",
            author="运转计划助手",
        )
        frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
        doc.addPageTemplates([PageTemplate(id="p", frames=[frame],
                                           onPage=lambda c, d: self._page_deco(c, d, trip.name))])

        flow: list = []

        # 标题
        flow.append(Paragraph(trip.name, st["title"]))
        flow.append(Paragraph(
            f"{trip.city} · {trip.date or '日期：________'}" +
            (f" · 备注：{trip.note}" if trip.note else ""),
            st["subtitle"]))
        flow.append(Spacer(1, 4))

        # 汇总表
        price_total_val = price_total(trip, result)
        price_cell = f"¥{price_total_val:.2f}" if price_total_val else "—"
        summary = Table([
            ["全程总时长", "车上运行", "换乘步行", "换乘次数", "线路数", "总站数", "总票价"],
            [fmt_minutes(result.total_minutes), fmt_minutes(result.total_run),
             fmt_minutes(result.total_walk), f"{result.transfer_count} 次",
             f"{result.line_count} 条", f"{sum(s.stop_count for s in result.segments)} 站", price_cell],
        ], colWidths=[doc.width / 7] * 7)
        summary.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), self.font),
            ("FONTNAME", (0, 1), (-1, 1), self.font_bold),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        flow.append(summary)
        flow.append(Spacer(1, 6))

        # 付费区汇总（付费区模式下）
        zones = {z.index: z for z in result.paid_zones}
        if trip.paid_zone_mode and zones:
            flow.append(Paragraph("付费区计费（进闸站 → 出闸站，绕路只收一次费）", st["h2"]))
            zrows = [["付费区", "进闸站", "出闸站", "票价"]]
            for idx in sorted(zones):
                z = zones[idx]
                zrows.append([f"#{z.index + 1}", z.entry_station, z.exit_station,
                              f"¥{z.price:.2f}" if z.price is not None else "—"])
            ztbl = Table(zrows, colWidths=[doc.width / 8, doc.width / 3, doc.width / 3, doc.width / 5])
            zstyle = [
                ("FONTNAME", (0, 0), (-1, -1), self.font),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
            for i in range(1, len(zrows)):
                if i % 2 == 0:
                    zstyle.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f4f8fc")))
            ztbl.setStyle(TableStyle(zstyle))
            flow.append(ztbl)
            flow.append(Spacer(1, 8))

        if result.segments:
            flow.append(Paragraph("全程时间轴（按实际运行时长成比例）", st["h2"]))
            flow.append(self._timeline(result, st))
            flow.append(Spacer(1, 8))

        # 分段
        flow.append(Paragraph("分段行程明细", st["h2"]))
        prev: SegmentResult | None = None
        for i, seg in enumerate(result.segments, start=1):
            tf = self._transfer_flowable(seg, prev, st)
            if tf is not None:
                flow.append(tf)
            flow.append(self._step_flowables(seg, i, st, paid_mode=trip.paid_zone_mode, zones=zones))
            flow.append(Spacer(1, 6))
            prev = seg

        flow.append(Spacer(1, 10))
        flow.append(Paragraph(
            "说明：① 发车班次仅作参考，请以运营方实时信息为准；② 站间时长为常态估算值；"
            "③ 换乘步行时间为默认估算，请按现场实际调整；④ 交通迷运转请务必注意安全、遵守乘车规则。",
            ParagraphStyle("foot", fontName=self.font, fontSize=7.5, leading=11,
                           textColor=colors.HexColor("#888888"))))

        doc.build(flow)
        return str(path)


def export_pdf(city: City, trip: Trip, path: str | Path,
               font_path: str | None = None, font_bold_path: str | None = None) -> str:
    """导出 PDF。可指定自定义中文字体（常规体/粗体）路径。"""
    if font_path:
        registry = [("ExportFont", str(font_path))]
        if font_bold_path and str(font_bold_path) != str(font_path):
            registry.append(("ExportFont-Bold", str(font_bold_path)))
            font_bold = "ExportFont-Bold"
        else:
            font_bold = "ExportFont"
        exporter = PDFExporter(font_registry=registry, font="ExportFont", font_bold=font_bold)
    else:
        exporter = PDFExporter()
    return exporter.export(city, trip, path)
