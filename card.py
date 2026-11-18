"""Floating result card shown on the map canvas by the click tool."""
import math

from qgis.core import QgsPointXY
from qgis.gui import QgsVertexMarker
from qgis.PyQt.QtCore import (
    QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation, pyqtSignal,
)
from qgis.PyQt.QtGui import (
    QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF,
)
from qgis.PyQt.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

EAST = QColor("#1f6feb")
WEST = QColor("#e8590c")
ZERO = QColor("#2f9e44")
INK = QColor("#14181f")
MUTED = QColor("#6b7380")
CARD_W = 480


def accent_for(decl):
    if abs(decl) < 0.05:
        return ZERO
    return EAST if decl > 0 else WEST


def _font(widget, px, bold=False):
    f = QFont(widget.font())
    f.setPixelSize(px)
    f.setBold(bold)
    return f


class Dial(QWidget):
    """Variation diagram to true scale, with an animated magnetic-north needle."""

    SIZE = 176

    def __init__(self, parent=None):
        super().__init__(parent)
        self.decl = 0.0
        self.label = ""
        self.setFixedSize(self.SIZE, self.SIZE)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(420)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)

    def _on_anim(self, v):
        self.decl = float(v)
        self.update()

    def set_decl(self, decl, label="", animate=True):
        self.label = label
        self._anim.stop()
        if animate and abs(float(decl) - self.decl) > 1e-6:
            self._anim.setStartValue(self.decl)
            self._anim.setEndValue(float(decl))
            self._anim.start()
        else:
            self.decl = float(decl)
            self.update()

    @staticmethod
    def _pt(c, radius, ang_deg):
        a = math.radians(ang_deg)
        return QPointF(c.x() + radius * math.sin(a), c.y() - radius * math.cos(a))

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c = QPointF(self.width() / 2.0, self.height() / 2.0 + 7)
        r = min(self.width(), self.height()) / 2.0 - 13
        col = accent_for(self.decl)

        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0, QColor("#ffffff"))
        grad.setColorAt(1, QColor("#eef1f6"))
        p.setPen(QPen(QColor("#cfd6e0"), 1.4))
        p.setBrush(grad)
        p.drawEllipse(c, r, r)

        for k in range(-180, 180):
            near = abs(k) <= 20
            if not near and k % 10:
                continue
            ten = (k % 10 == 0)
            major = ten or (near and k % 5 == 0)
            length = 9 if ten else (6 if major else 3.5)
            p.setPen(QPen(QColor("#4b5563" if ten else "#a3acb9"), 1.2 if ten else 0.8))
            p.drawLine(self._pt(c, r, k), self._pt(c, r - length, k))

        p.setFont(_font(self, 9, True))
        p.setPen(MUTED)
        for ang, txt in ((90, "E"), (180, "S"), (270, "W")):
            q = self._pt(c, r - 19, ang)
            p.drawText(QRectF(q.x() - 8, q.y() - 7, 16, 14), Qt.AlignmentFlag.AlignCenter, txt)

        wedge_r = r - 24
        if abs(self.decl) > 0.01:
            path = QPainterPath()
            path.moveTo(c)
            steps = max(2, int(abs(self.decl) * 2) + 2)
            for i in range(steps + 1):
                path.lineTo(self._pt(c, wedge_r, self.decl * i / steps))
            path.closeSubpath()
            fill = QColor(col)
            fill.setAlpha(60)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawPath(path)

        tn_end = self._pt(c, r - 4, 0)
        p.setPen(QPen(INK, 1.8))
        p.drawLine(c, tn_end)
        self._star(p, QPointF(tn_end.x(), tn_end.y() + 11))
        p.setFont(_font(self, 10, True))
        p.setPen(INK)
        p.drawText(QRectF(c.x() - 40, c.y() - r - 12, 80, 13), Qt.AlignmentFlag.AlignCenter, "TN")

        mn_end = self._pt(c, r - 4, self.decl)
        p.setPen(QPen(col, 2.6))
        p.drawLine(c, mn_end)
        side = 1 if self.decl >= 0 else -1
        head_base = self._pt(c, r - 18, self.decl)
        a = math.radians(self.decl)
        off = QPointF(math.cos(a) * 6.5 * side, math.sin(a) * 6.5 * side)
        p.setBrush(col)
        p.drawPolygon(QPolygonF([mn_end, head_base,
                                 QPointF(head_base.x() + off.x(), head_base.y() + off.y())]))
        p.setPen(col)
        mn_lab = self._pt(c, r + 3, self.decl)
        mx = max(4, min(self.width() - 30, mn_lab.x() - 13 + (15 if self.decl >= 0 else -15)))
        p.drawText(QRectF(mx, 1, 26, 13), Qt.AlignmentFlag.AlignCenter, "MN")

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(INK)
        p.drawEllipse(c, 3.2, 3.2)

        txt = self.label or ""
        if txt:
            p.setFont(_font(self, 11, True))
            w = p.fontMetrics().horizontalAdvance(txt) + 16
            box = QRectF(c.x() - w / 2.0, c.y() + r * 0.40, w, 19)
            p.setBrush(QColor("#ffffff"))
            p.setPen(QPen(col, 1.3))
            p.drawRoundedRect(box, 9, 9)
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, txt)
        p.end()

    @staticmethod
    def _star(p, centre, size=5.0):
        pts = []
        for i in range(10):
            ang = math.radians(i * 36)
            rad = size if i % 2 == 0 else size * 0.45
            pts.append(QPointF(centre.x() + rad * math.sin(ang), centre.y() - rad * math.cos(ang)))
        p.setBrush(INK)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF(pts))


class Spark(QWidget):
    """Declination over time (model), with the chosen date marked."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.years = []
        self.values = []
        self.now = 0.0
        self.color = EAST
        self.setFixedHeight(78)

    def set_series(self, years, values, now, color):
        self.years, self.values, self.now, self.color = list(years), list(values), now, color
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if len(self.values) < 2:
            p.end()
            return
        w, h = self.width(), self.height()
        left, right, top, bottom = 6, 6, 14, 20
        vmin, vmax = min(self.values), max(self.values)
        span = max(vmax - vmin, 0.05)
        y0, y1 = self.years[0], self.years[-1]

        def xy(yr, v):
            return QPointF(left + (yr - y0) / (y1 - y0) * (w - left - right),
                           top + (1 - (v - vmin) / span) * (h - top - bottom))

        pts = [xy(a, b) for a, b in zip(self.years, self.values)]
        area = QPainterPath()
        area.moveTo(pts[0].x(), h - bottom)
        for q in pts:
            area.lineTo(q)
        area.lineTo(pts[-1].x(), h - bottom)
        area.closeSubpath()
        fill = QColor(self.color)
        fill.setAlpha(34)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawPath(area)
        p.setPen(QPen(self.color, 2.2))
        for i in range(len(pts) - 1):
            p.drawLine(pts[i], pts[i + 1])
        cur = xy(self.now, self._interp(self.now))
        p.setPen(QPen(QColor(self.color), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(cur.x(), top - 2), QPointF(cur.x(), h - bottom))
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.setBrush(self.color)
        p.drawEllipse(cur, 4.5, 4.5)
        p.setFont(_font(self, 10))
        p.setPen(MUTED)
        p.drawText(QRectF(left, h - 16, 60, 14), Qt.AlignmentFlag.AlignLeft, "%d" % round(y0))
        p.drawText(QRectF(w - right - 60, h - 16, 60, 14), Qt.AlignmentFlag.AlignRight, "%d" % round(y1))
        p.drawText(QRectF(left, 0, 70, 12), Qt.AlignmentFlag.AlignLeft, "%+.2f°" % self.values[0])
        p.drawText(QRectF(w - right - 70, 0, 70, 12), Qt.AlignmentFlag.AlignRight,
                   "%+.2f°" % self.values[-1])
        p.end()

    def _interp(self, yr):
        for i in range(len(self.years) - 1):
            if self.years[i] <= yr <= self.years[i + 1]:
                t = (yr - self.years[i]) / (self.years[i + 1] - self.years[i])
                return self.values[i] + t * (self.values[i + 1] - self.values[i])
        return self.values[len(self.values) // 2]


class Tile(QFrame):
    def __init__(self, caption, parent=None):
        super().__init__(parent)
        self.setObjectName("tile")
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 7, 10, 8)
        v.setSpacing(1)
        self.cap = QLabel(caption.upper())
        self.cap.setObjectName("cap")
        self.val = QLabel("-")
        self.val.setObjectName("tileval")
        self.sub = QLabel("")
        self.sub.setObjectName("tilesub")
        v.addWidget(self.cap)
        v.addWidget(self.val)
        v.addWidget(self.sub)


class ResultCard(QFrame):
    """Card placed next to the clicked point. Parent: the map canvas."""

    copy_requested = pyqtSignal()
    closed = pyqtSignal()
    plugin_requested = pyqtSignal()
    user_closed = pyqtSignal()

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.marker = None
        self.setObjectName("magvarCard")
        self.setFixedWidth(CARD_W)
        self.setCursor(Qt.CursorShape.ArrowCursor)    # normal arrow over the card, not the map cross
        self.setStyleSheet(
            "#magvarCard{background:#ffffff;border:1px solid #c5cdd9;border-radius:12px;}"
            "#magvarCard QLabel{color:#14181f;background:transparent;font-size:12px;}"
            "#head{border-top-left-radius:11px;border-top-right-radius:11px;}"
            "#head QLabel{color:#ffffff;font-weight:bold;font-size:11px;}"
            "#chip{background:rgba(255,255,255,0.22);border-radius:9px;color:#ffffff;"
            "padding:1px 8px;font-size:11px;font-weight:bold;}"
            "#cap{color:#6b7380;font-size:10px;font-weight:bold;}"
            "#tile{background:#f4f6fa;border:1px solid #e3e7ee;border-radius:9px;}"
            "#tileval{font-size:16px;font-weight:bold;}"
            "#tilesub{color:#6b7380;font-size:10px;}"
            "#panel{background:#f9fafc;border:1px solid #e3e7ee;border-radius:9px;}"
            "#coord{font-family:Consolas,'DejaVu Sans Mono',monospace;font-size:13px;font-weight:bold;}"
            "#dirchip{border-radius:9px;padding:2px 9px;font-size:11px;font-weight:bold;color:#ffffff;}"
            "#warn{background:#fff4e0;color:#8a5200;border-radius:8px;padding:4px 8px;font-size:11px;}"
            "#magvarCard QPushButton{background:#f3f5f9;border:1px solid #cdd4df;border-radius:7px;"
            "padding:6px 12px;color:#14181f;font-weight:bold;font-size:13px;}"
            "#magvarCard QPushButton:hover{background:#e7ebf2;}"
            "#magvarCard QPushButton#primaryBtn{background:#1d6fe8;color:white;border:1px solid #1859bd;}"
            "#magvarCard QPushButton#primaryBtn:hover{background:#1859bd;}"
            "#closeb{background:rgba(255,255,255,0.2);border:none;color:#ffffff;border-radius:11px;"
            "padding:0;font-size:15px;}"
            "#closeb:hover{background:rgba(255,255,255,0.38);}")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(26)
        shadow.setOffset(0, 5)
        shadow.setColor(QColor(0, 0, 0, 90))
        self.setGraphicsEffect(shadow)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.head = QFrame()
        self.head.setObjectName("head")
        hl = QHBoxLayout(self.head)
        hl.setContentsMargins(14, 8, 10, 8)
        self.title = QLabel("MAGNETIC VARIATION")
        hl.addWidget(self.title)
        hl.addStretch(1)
        self.mode_chip = QLabel("")
        self.mode_chip.setObjectName("chip")
        hl.addWidget(self.mode_chip)
        self.model_chip = QLabel("")
        self.model_chip.setObjectName("chip")
        hl.addWidget(self.model_chip)
        self.close_btn = QPushButton("×")
        self.close_btn.setObjectName("closeb")
        self.close_btn.setFixedSize(22, 22)
        self.close_btn.setToolTip("Close")
        self.close_btn.clicked.connect(self._close_clicked)
        hl.addWidget(self.close_btn)
        outer.addWidget(self.head)

        body = QVBoxLayout()
        body.setContentsMargins(14, 12, 14, 14)
        body.setSpacing(10)
        outer.addLayout(body)

        top = QHBoxLayout()
        top.setSpacing(10)
        self.dial = Dial()
        top.addWidget(self.dial)
        col = QVBoxLayout()
        col.setSpacing(2)
        cap = QLabel("DECLINATION")
        cap.setObjectName("cap")
        col.addWidget(cap)
        self.big = QLabel("-")
        self.big.setFont(_font(self, 34, True))
        col.addWidget(self.big)
        self.sub = QLabel("")
        self.sub.setStyleSheet("font-size:14px;color:#374151;")
        self.sub.setWordWrap(True)
        col.addWidget(self.sub)
        self.dirchip = QLabel("")
        self.dirchip.setObjectName("dirchip")
        chip_row = QHBoxLayout()
        chip_row.addWidget(self.dirchip)
        chip_row.addStretch(1)
        col.addLayout(chip_row)
        self.dirword = QLabel("")
        self.dirword.setWordWrap(True)
        self.dirword.setStyleSheet("color:#6b7380;font-size:11px;")
        col.addWidget(self.dirword)
        col.addStretch(1)
        top.addLayout(col, 1)
        body.addLayout(top)

        tiles = QHBoxLayout()
        tiles.setSpacing(8)
        self.t_change = Tile("Annual change")
        self.t_incl = Tile("Inclination")
        self.t_total = Tile("Total field")
        for t in (self.t_change, self.t_incl, self.t_total):
            tiles.addWidget(t)
        body.addLayout(tiles)

        self.spark_panel = QFrame()
        self.spark_panel.setObjectName("panel")
        sp = QVBoxLayout(self.spark_panel)
        sp.setContentsMargins(10, 7, 10, 6)
        sp.setSpacing(2)
        self.spark_cap = QLabel("DECLINATION TREND (MODEL)")
        self.spark_cap.setObjectName("cap")
        sp.addWidget(self.spark_cap)
        self.spark = Spark()
        sp.addWidget(self.spark)
        body.addWidget(self.spark_panel)

        pos = QFrame()
        pos.setObjectName("panel")
        pl = QVBoxLayout(pos)
        pl.setContentsMargins(10, 7, 10, 8)
        pl.setSpacing(2)
        pcap = QLabel("POSITION")
        pcap.setObjectName("cap")
        pl.addWidget(pcap)
        self.lat_lbl = QLabel("-")
        self.lat_lbl.setObjectName("coord")
        self.lon_lbl = QLabel("-")
        self.lon_lbl.setObjectName("coord")
        self.dec_lbl = QLabel("-")
        self.dec_lbl.setStyleSheet("color:#6b7380;font-size:11px;")
        self.meta_lbl = QLabel("-")
        self.meta_lbl.setStyleSheet("color:#6b7380;font-size:11px;")
        for w in (self.lat_lbl, self.lon_lbl, self.dec_lbl, self.meta_lbl):
            pl.addWidget(w)
        body.addWidget(pos)

        self.warn = QLabel("")
        self.warn.setObjectName("warn")
        self.warn.setStyleSheet("background:#fff4e0;color:#8a5200;border-radius:8px;"
                                "padding:5px 9px;font-size:11px;")
        self.warn.setWordWrap(True)
        body.addWidget(self.warn)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.copy_btn = QPushButton("Copy values")
        self.copy_btn.setObjectName("primaryBtn")
        self.copy_btn.clicked.connect(self.copy_requested.emit)
        btns.addWidget(self.copy_btn, 1)
        self.plugin_btn = QPushButton("Settings && layers")
        self.plugin_btn.setToolTip("Back to the Isogonic Lines & MagVar window (date, model, isogonic lines)")
        self.plugin_btn.clicked.connect(self.plugin_requested.emit)
        btns.addWidget(self.plugin_btn, 1)
        body.addLayout(btns)
        self.hide()

    # ------------------------------------------------------------------
    def show_result(self, data, map_point, pixel, mode="click", animate=True):
        """data keys: decl, label, dm, change, incl, total, lat, lon, lat_dms, lon_dms,
        model, date, alt_m, series (years, values), now, valid."""
        d = data["decl"]
        col = accent_for(d)
        self.head.setStyleSheet("#head{background:%s;}" % col.name())
        big = "%.2f° %s" % (abs(d), "E" if d >= 0 else "W")
        self.dial.set_decl(d, big, animate and self.isVisible())
        self.big.setText(big)
        self.big.setStyleSheet("color:%s;font-size:40px;font-weight:bold;" % col.name())
        self.sub.setText("%s  •  %+.4f°<br><b>Chart label: %s</b>" % (data["dm"], d, data["label"]))
        if abs(d) < 0.05:
            chip, word = "ZERO", "Magnetic north = true north"
        elif d > 0:
            chip, word = "EAST", "Magnetic north is east of true north"
        else:
            chip, word = "WEST", "Magnetic north is west of true north"
        self.dirchip.setText(chip)
        self.dirchip.setStyleSheet("background:%s;" % col.name())
        self.dirword.setText(word)

        ac = data["change"]
        self.t_change.val.setText("%s %+.4f°" % ("▲" if ac > 0 else "▼", ac))
        self.t_change.val.setStyleSheet("color:%s;" % (EAST if ac > 0 else WEST).name())
        self.t_change.sub.setText("per year  (%+.2f° in 5 yr)" % (ac * 5))
        self.t_incl.val.setText("%.2f°" % data["incl"])
        self.t_incl.sub.setText("dip, %s" % ("down" if data["incl"] >= 0 else "up"))
        self.t_total.val.setText("{:,.0f} nT".format(data["total"]).replace(",", " "))
        self.t_total.sub.setText("total intensity")

        years, vals = data["series"]
        self.spark.set_series(years, vals, data["now"], col)
        self.spark_cap.setText("DECLINATION TREND %d → %d  (%s)" % (
            round(years[0]), round(years[-1]), data["model"]))

        self.lat_lbl.setText("LAT   " + data["lat_dms"])
        self.lon_lbl.setText("LON  " + data["lon_dms"])
        self.dec_lbl.setText("%.8f°, %.8f°" % (data["lat"], data["lon"]))
        self.meta_lbl.setText("%s   •   altitude %d m" % (data["date"], data["alt_m"]))
        self.model_chip.setText(data["model"])
        self.mode_chip.setText({"live": "● LIVE", "pinned": "■ PINNED"}.get(mode, ""))
        self.mode_chip.setVisible(bool(self.mode_chip.text()))
        if data["valid"]:
            self.warn.hide()
        else:
            self.warn.setText("⚠ This date is outside the model's validity period: "
                              "the value is an extrapolation.")
            self.warn.show()

        self._set_marker(map_point, col)
        self.adjustSize()
        self.move_near(pixel)
        self.show()
        self.raise_()

    def move_near(self, pixel):
        cw, ch = self.canvas.width(), self.canvas.height()
        w, h = self.width(), self.height()
        x, y = int(pixel.x()) + 18, int(pixel.y()) + 18
        if x + w > cw - 6:
            x = int(pixel.x()) - w - 18
        if y + h > ch - 6:
            y = int(pixel.y()) - h - 18
        self.move(max(6, min(x, cw - w - 6)), max(6, min(y, ch - h - 6)))

    def _set_marker(self, map_point, col):
        if self.marker is None:
            self.marker = QgsVertexMarker(self.canvas)
            icon = getattr(QgsVertexMarker, "ICON_CIRCLE", None)
            if icon is None:
                icon = QgsVertexMarker.IconType.ICON_CIRCLE
            self.marker.setIconType(icon)
            self.marker.setIconSize(14)
            self.marker.setPenWidth(3)
        self.marker.setColor(col)
        self.marker.setCenter(QgsPointXY(map_point))

    def clear_marker(self):
        if self.marker is not None:
            self.canvas.scene().removeItem(self.marker)
            self.marker = None

    def _close_clicked(self):
        self.dismiss()
        self.user_closed.emit()

    def dismiss(self):
        self.clear_marker()
        self.hide()
        self.closed.emit()
