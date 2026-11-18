import contextlib
import datetime
import os

import numpy as np

from qgis.core import (
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry,
    QgsMapLayerProxyModel, QgsPointXY, QgsProject, QgsRectangle, QgsSettings,
    QgsWkbTypes,
)
from qgis.gui import QgsExtentGroupBox, QgsFieldComboBox, QgsFileWidget, QgsMapLayerComboBox
from qgis.PyQt.QtCore import QDate, QElapsedTimer, Qt, pyqtSlot
from qgis.PyQt.QtGui import QIcon, QKeySequence
try:
    from qgis.PyQt.QtWidgets import QShortcut
except ImportError:  # Qt6 moved it
    from qgis.PyQt.QtGui import QShortcut
from qgis.PyQt.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateEdit, QDialog, QDoubleSpinBox, QFormLayout,
    QGroupBox, QLabel, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QTabWidget, QVBoxLayout, QWidget,
)

from . import compare, isogonic, layers, wmm
from .card import ResultCard
from .maptool import ClickTool
from .styling import style_isogonic
from .task import FuncTask

SETTINGS = "isogonic_magvar/"
DISCLAIMER = (
    "Values come from the model you select (World Magnetic Model WMM, WMMHR or "
    "IGRF) for the date you choose. These are global models with "
    "limited accuracy (typically about 0.5° error, more near the magnetic "
    "poles). For official use, check them against the authority's data (for "
    "aviation, the AIP). Not affiliated with ICAO or NOAA.")


class MagVarDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.task = None
        self.tool = None
        self._prev_tool = None
        self._resetting = False
        self._last_text = ""
        self.card = None
        self._tool_watch = False
        self._esc = None
        self._live_clock = QElapsedTimer()
        self._live_clock.start()
        self.setWindowTitle("Isogonic Lines & MagVar")
        icon_file = os.path.join(os.path.dirname(__file__), "icon.png")
        if os.path.exists(icon_file):
            self.setWindowIcon(QIcon(icon_file))
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint)
        self.resize(640, 760)
        self.setSizeGripEnabled(True)
        s = QgsSettings()
        root = QVBoxLayout(self)

        # --- common: date and altitude ------------------------------------
        box = QGroupBox("Date and altitude (used by all tabs)")
        f = QFormLayout(box)
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.alt = QDoubleSpinBox()
        self.alt.setRange(-1.0, 1000.0)
        self.alt.setDecimals(0)
        self.alt.setSuffix(" m")
        self.alt.setToolTip("Height above the WGS84 ellipsoid. 0 for chart work at sea level.")
        self.model_combo = QComboBox()
        self.model_combo.addItem("Automatic (model valid for the date)", wmm.AUTO)
        for key, m in wmm.MODELS.items():
            self.model_combo.addItem(m["label"], key)
        self.model_combo.setToolTip(
            "Magnetic model. Lines drawn by someone else often use another model or "
            "year: use the Compare tab to find which one.")
        self.model_combo.currentIndexChanged.connect(self._check_range)
        f.addRow("Model", self.model_combo)
        f.addRow("Date", self.date)
        f.addRow("Altitude", self.alt)
        self.range_note = QLabel("")
        self.range_note.setWordWrap(True)
        f.addRow(self.range_note)
        self.date.dateChanged.connect(self._check_range)
        root.addWidget(box)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_layer_tab(), "Layer")
        self.tabs.addTab(self._build_click_tab(), "Click tool")
        self.tabs.addTab(self._build_iso_tab(), "Isogonic lines")
        self.tabs.addTab(self._build_compare_tab(), "Compare with my lines")
        root.addWidget(self.tabs, 1)

        # --- output + progress ----------------------------------------------
        box = QGroupBox("Output")
        f = QFormLayout(box)
        self.folder = QgsFileWidget()
        self.folder.setStorageMode(QgsFileWidget.StorageMode.GetDirectory)
        self.folder.setFilePath(str(s.value(SETTINGS + "folder", "")))
        self.fmt = QComboBox()
        self.fmt.addItems(["GeoPackage", "Shapefile"])
        self.fmt.setCurrentIndex(int(s.value(SETTINGS + "fmt", 0)))
        f.addRow("Folder", self.folder)
        f.addRow("Format", self.fmt)
        root.addWidget(box)

        self.bar = QProgressBar()
        root.addWidget(self.bar)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(110)
        root.addWidget(self.log_view)
        note = QLabel(DISCLAIMER)
        note.setWordWrap(True)
        note.setStyleSheet("color: #666;")
        root.addWidget(note)
        self._check_range()

    # ---------------------------------------------------------------- tabs
    def _build_layer_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        f = QFormLayout()
        self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setFilters(
            QgsMapLayerProxyModel.Filter.PointLayer
            | QgsMapLayerProxyModel.Filter.LineLayer
            | QgsMapLayerProxyModel.Filter.PolygonLayer)
        self.ref_combo = QComboBox()
        self.ref_combo.addItems(["Centroid", "First vertex", "Last vertex"])
        self.ref_combo.setToolTip("Reference point for line layers. Points use their own "
                                  "position, polygons use the centroid.")
        self.dec_combo = QComboBox()
        self.dec_combo.addItems(["Nearest degree (5\u00b0E)", "0.1\u00b0 (5.2\u00b0E)", "0.01\u00b0 (5.23\u00b0E)"])
        self.dec_combo.setToolTip("Rounding of decl_label. Annex 4 charts show whole degrees.")
        self.layer_run = QPushButton("Add declination fields to a new layer")
        self.layer_run.clicked.connect(self.run_layer)
        f.addRow("Layer", self.layer_combo)
        f.addRow("Reference point (lines)", self.ref_combo)
        f.addRow("Label rounding", self.dec_combo)
        v.addLayout(f)
        info = QLabel("Fields added: decl_deg (decimal degrees, east positive), decl_label "
                      "(nearest degree, for example 5°E), ann_change (degrees per year) "
                      "and decl_date. The source layer is never changed.")
        info.setWordWrap(True)
        v.addWidget(info)
        v.addWidget(self.layer_run)
        v.addStretch(1)
        return w

    def _build_click_tool_labels(self):
        self.res_decl = QLabel("-")
        self.res_change = QLabel("-")
        self.res_incl = QLabel("-")
        self.res_total = QLabel("-")
        self.res_pos = QLabel("-")

    def _build_click_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.click_btn = QPushButton("Activate click tool, then click the map")
        self.click_btn.setCheckable(True)
        self.click_btn.toggled.connect(self._toggle_tool)
        v.addWidget(self.click_btn)
        self.live_chk = QCheckBox("Live mode: the card follows the cursor, click to pin it")
        self.live_chk.toggled.connect(self._toggle_live)
        v.addWidget(self.live_chk)
        self._build_click_tool_labels()
        f = QFormLayout()
        f.addRow("Position", self.res_pos)
        f.addRow("Declination", self.res_decl)
        f.addRow("Annual change", self.res_change)
        f.addRow("Inclination", self.res_incl)
        f.addRow("Total field", self.res_total)
        v.addLayout(f)
        self.copy_btn = QPushButton("Copy values")
        self.copy_btn.clicked.connect(self._copy_values)
        v.addWidget(self.copy_btn)
        v.addStretch(1)
        return w

    def _build_compare_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        info = QLabel(
            "Your client's isogonic lines do not fit? Choose their line layer and the field "
            "holding each line's declination (a number like -2.5 or text like 2\u00b030'W). "
            "The plugin tests every model and date from 1900 to 2030 and shows which one "
            "reproduces your lines.")
        info.setWordWrap(True)
        v.addWidget(info)
        f = QFormLayout()
        self.cmp_layer = QgsMapLayerComboBox()
        self.cmp_layer.setFilters(QgsMapLayerProxyModel.Filter.LineLayer
                                  | QgsMapLayerProxyModel.Filter.PointLayer)
        self.cmp_field = QgsFieldComboBox()
        self.cmp_field.setLayer(self.cmp_layer.currentLayer())
        self.cmp_layer.layerChanged.connect(self.cmp_field.setLayer)
        f.addRow("Line layer", self.cmp_layer)
        f.addRow("Declination field", self.cmp_field)
        v.addLayout(f)
        self.cmp_run = QPushButton("Find the model and date that match")
        self.cmp_run.clicked.connect(self.run_compare)
        v.addWidget(self.cmp_run)
        self.cmp_out = QPlainTextEdit()
        self.cmp_out.setReadOnly(True)
        v.addWidget(self.cmp_out, 1)
        self.cmp_apply = QPushButton("Use the best match (sets model and date above)")
        self.cmp_apply.setEnabled(False)
        self.cmp_apply.clicked.connect(self._apply_best)
        v.addWidget(self.cmp_apply)
        self._best = None
        return w

    def run_compare(self):
        if self.task is not None:
            return
        src = self.cmp_layer.currentLayer()
        fname = self.cmp_field.currentField()
        if src is None or not fname:
            QMessageBox.warning(self, "Isogonic Lines & MagVar",
                                "Choose a line layer and its declination field.")
            return
        to_ll = QgsCoordinateTransform(
            src.crs(), QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance())
        lats, lons, given, group, bad = [], [], [], [], 0
        for f in src.getFeatures():
            val = compare.parse_declination(f[fname])
            g = f.geometry()
            if val is None or g is None or g.isNull() or g.isEmpty():
                bad += 1
                continue
            g = QgsGeometry(g)
            g.transform(to_ll)
            if QgsWkbTypes.geometryType(g.wkbType()) == QgsWkbTypes.GeometryType.LineGeometry:
                g = g.densifyByDistance(0.25)
            for p in g.vertices():
                lats.append(p.y())
                lons.append(p.x())
                given.append(val)
                group.append(f.id())
        if len(lats) < 2:
            QMessageBox.warning(self, "Isogonic Lines & MagVar",
                                "No usable values. Check the field: it must contain numbers or "
                                "text like 2.5, -2.5, 2\u00b030'W.")
            return
        alt = self.alt.value() / 1000.0
        cur_year, cur_key = self._year(), self._model_key()
        self.cmp_out.setPlainText("Working...")
        self.cmp_apply.setEnabled(False)

        def work(task):
            res = compare.best_fit(lats, lons, given, group, alt, is_canceled=task.isCanceled)
            if not res:
                return None
            import numpy as np
            la, lo, gv = np.array(lats), np.array(lons), np.array(given)
            d = compare.diffs(la, lo, gv, cur_year, cur_key, alt)
            cur = {"model": cur_key, "year": cur_year,
                   "rms": float(np.sqrt(np.mean(d ** 2))), "bias": float(np.mean(d)),
                   "max": float(np.max(np.abs(d)))}
            lines = compare.per_group(la, lo, gv, np.array(group), res[0]["year"], res[0]["model"], alt)
            return res, cur, lines

        def done(task, ok):
            self._finish_task()
            if task.error:
                self.cmp_out.setPlainText("Error: %s" % task.error)
                return
            if not ok or task.result is None:
                self.cmp_out.setPlainText("Cancelled.")
                return
            res, cur, lines = task.result
            text = compare.report(res, cur, lines)
            if bad:
                text += "\n\n%d feature(s) skipped (no readable value or no geometry)." % bad
            self.cmp_out.setPlainText(text)
            self._best = res[0]
            self.cmp_apply.setEnabled(True)
        self._start(FuncTask("Isogonic Lines & MagVar: compare", work, done))

    def _apply_best(self):
        b = self._best
        if not b:
            return
        i = self.model_combo.findData(b["model"])
        if i >= 0:
            self.model_combo.setCurrentIndex(i)
        yr = int(b["year"])
        day = int(round((b["year"] - yr) * 365.25)) + 1
        d = datetime.date(yr, 1, 1) + datetime.timedelta(days=min(day, 365) - 1)
        self.date.setDate(QDate(d.year, d.month, d.day))
        self.log("Model and date set to %s, %s." % (b["model"], d.isoformat()))

    def _build_iso_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        canvas = self.iface.mapCanvas()
        self.extent_box = QgsExtentGroupBox()
        self.extent_box.setTitle("Extent")
        self.extent_box.setMapCanvas(canvas)
        self.extent_box.setOutputCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        self.refresh_extent(set_output=True)
        v.addWidget(self.extent_box)
        f = QFormLayout()
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.01, 10.0)
        self.interval.setSingleStep(0.25)
        self.interval.setDecimals(2)
        self.interval.setValue(1.0)
        self.interval.setSuffix(" \u00b0")
        self.interval.setToolTip("Declination step between lines, any value from 0.01\u00b0 to 10\u00b0 "
                                 "(for example 0.25, 0.5, 1, 2.5).")
        self.step = QComboBox()
        self.step.addItem("Automatic", None)
        for val in ("0.01", "0.05", "0.1", "0.25", "0.5", "1.0"):
            self.step.addItem(val + " \u00b0", float(val))
        self.step.setToolTip("Spacing of the calculation grid. Automatic adapts to the "
                             "size of the extent (finer for small areas).")
        self.refine = QCheckBox("If no line crosses the extent, retry with a finer interval")
        self.refine.setChecked(True)
        self.iso_run = QPushButton("Draw isogonic lines")
        self.iso_run.clicked.connect(self.run_iso)
        f.addRow("Contour interval", self.interval)
        f.addRow("Grid spacing", self.step)
        v.addLayout(f)
        v.addWidget(self.refine)
        info = QLabel("Lines of equal declination, labelled like 5°E. The zero line "
                      "(agonic line), if it crosses the extent, has its own style.")
        info.setWordWrap(True)
        v.addWidget(info)
        v.addWidget(self.iso_run)
        v.addStretch(1)
        return w

    # ------------------------------------------------------------ helpers
    def refresh_extent(self, set_output=False):
        canvas = self.iface.mapCanvas()
        crs = canvas.mapSettings().destinationCrs()
        self.extent_box.setOriginalExtent(canvas.extent(), crs)
        self.extent_box.setCurrentExtent(canvas.extent(), crs)
        if set_output:
            self.extent_box.setOutputExtentFromCurrent()

    def _year(self):
        d = self.date.date()
        return wmm.decimal_year(datetime.date(d.year(), d.month(), d.day()))

    def _model(self):
        return self.model_combo.currentData()

    def _model_key(self):
        return wmm.resolve(self._model(), self._year())

    def _check_range(self):
        y = self._year()
        key = self._model_key()
        lo, hi = wmm.MODELS[key]["range"]
        if wmm.in_valid_range(y, self._model()):
            self.range_note.setText("Model used: %s" % wmm.MODELS[key]["label"])
            self.range_note.setStyleSheet("color: #666;")
        else:
            self.range_note.setText(
                "\u26a0 This date is outside the validity of %s (%d to %d). Values are an "
                "extrapolation and less reliable." % (key, lo, hi))
            self.range_note.setStyleSheet("color: #b45309;")

    @pyqtSlot(float)
    def _on_progress(self, value):
        # QgsTask reports a float, from its worker thread; as a slot of this
        # dialog it is delivered on the GUI thread.
        self.bar.setValue(int(value))

    def log(self, text):
        self.log_view.appendPlainText(text)

    def _busy(self, on):
        for b in (self.layer_run, self.iso_run, self.cmp_run):
            b.setEnabled(not on)

    def _check_output(self):
        folder = self.folder.filePath()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "Isogonic Lines & MagVar", "Choose an existing output folder.")
            return None
        s = QgsSettings()
        s.setValue(SETTINGS + "folder", folder)
        s.setValue(SETTINGS + "fmt", self.fmt.currentIndex())
        return folder

    def _fmt(self):
        return "gpkg" if self.fmt.currentIndex() == 0 else "shp"

    # ---------------------------------------------------------- click tool
    def _toggle_tool(self, on):
        canvas = self.iface.mapCanvas()
        if on:
            if self.tool is None:
                self.tool = ClickTool(canvas)
                self.tool.picked.connect(self._on_pick)
                self.tool.moved.connect(self._on_move)
            if self.card is None:
                self.card = ResultCard(canvas)
                self.card.copy_requested.connect(self._copy_values)
                self.card.plugin_requested.connect(self._bring_back)
                self.card.user_closed.connect(self._leave_click_tool)
            self.tool.live = self.live_chk.isChecked()
            self.tool.pinned = False
            self._prev_tool = canvas.mapTool()
            canvas.setMapTool(self.tool)
            if not self._tool_watch:
                canvas.mapToolSet.connect(self._on_map_tool_set)
                self._tool_watch = True
            if self._esc is None:
                self._esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self.iface.mainWindow())
                self._esc.activated.connect(self._on_escape)
            self._esc.setEnabled(True)
            canvas.setFocus()
            self.showMinimized()          # get out of the way so the map can be clicked
        else:
            self._release_tool()

    def _leave_click_tool(self):
        """Popup closed (x or Esc): stop the click tool and go back to the plugin window."""
        self.live_chk.setChecked(False)
        self.click_btn.setChecked(False)
        self._bring_back()

    def _bring_back(self):
        """Show the plugin window again (the click tool stays active)."""
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_map_tool_set(self, new_tool, old_tool):
        """Another map tool was chosen: stop the click tool and bring the window back."""
        if old_tool is self.tool and new_tool is not self.tool and self.click_btn.isChecked():
            self.click_btn.setChecked(False)
            self._bring_back()

    def _on_escape(self):
        if self.click_btn.isChecked():
            if self.card is not None:
                self.card.dismiss()
            self._leave_click_tool()

    def _release_tool(self):
        canvas = self.iface.mapCanvas()
        if self._esc is not None:
            self._esc.setEnabled(False)
        if self.card is not None:
            self.card.dismiss()
        if self.tool is not None and canvas.mapTool() is self.tool:
            if self._prev_tool is not None:
                canvas.setMapTool(self._prev_tool)
            else:
                canvas.unsetMapTool(self.tool)
        self._prev_tool = None

    def _compute(self, lat, lon):
        """All values for one point, as a dict (also used by the live mode)."""
        y, alt = self._year(), self.alt.value() / 1000.0
        mk = self._model()
        key = wmm.resolve(mk, y)             # one model for the whole trend curve
        fld = wmm.field(lat, lon, y, alt, key)
        d = float(fld["d"][0])
        ac = float(wmm.annual_change(lat, lon, y, alt, key)[0])
        years = [y + k for k in range(-5, 6)]
        vals = [d if k == 0 else float(wmm.declination(np.array([lat]), np.array([lon]),
                                                      y + k, alt, key)[0])
                for k in range(-5, 6)]
        lat_dms, lon_dms = wmm.format_position_dms(lat, lon)
        return {"decl": d, "label": wmm.format_label(d), "dm": wmm.format_dm(d),
                "change": ac, "incl": float(fld["i"][0]), "total": float(fld["f"][0]),
                "lat": lat, "lon": lon, "lat_dms": lat_dms, "lon_dms": lon_dms,
                "model": self._model_key(),
                "date": self.date.date().toString("yyyy-MM-dd"),
                "alt_m": self.alt.value(), "series": (years, vals), "now": y,
                "valid": wmm.in_valid_range(y, mk)}

    def _show_values(self, v, mode):
        self.res_pos.setText("%s  %s" % (v["lat_dms"], v["lon_dms"]))
        self.res_decl.setText("%.2f° %s  (%s, chart label %s)" % (abs(v["decl"]), "E" if v["decl"] >= 0 else "W", v["dm"], v["label"]))
        self.res_change.setText("%+.4f° / year" % v["change"])
        self.res_incl.setText("%.2f°" % v["incl"])
        self.res_total.setText("%.0f nT" % v["total"])
        if self.card is not None and self.tool is not None and self.tool.last_pixel is not None:
            self.card.show_result(v, self.tool.last_map_point, self.tool.last_pixel, mode)
        self._last_text = (
            "lat %s lon %s (%.8f, %.8f) date %s alt %d m: declination %.4f deg (%s), "
            "annual change %+.4f deg/yr, inclination %.2f deg, total field %.0f nT (%s)"
            % (v["lat_dms"], v["lon_dms"], v["lat"], v["lon"], v["date"], v["alt_m"],
               v["decl"], v["label"], v["change"], v["incl"], v["total"], v["model"]))

    def _on_pick(self, lat, lon):
        mode = "pinned" if (self.tool is not None and self.tool.live and self.tool.pinned) else "click"
        self._show_values(self._compute(lat, lon), mode)

    def _on_move(self, lat, lon):
        if self._live_clock.elapsed() < 90:      # throttle: smooth, never heavy
            return
        self._live_clock.restart()
        self._show_values(self._compute(lat, lon), "live")

    def _toggle_live(self, on):
        if self.tool is not None:
            self.tool.live = bool(on)
            self.tool.pinned = False
        if not on and self.card is not None:
            self.card.dismiss()

    def _copy_values(self):
        if self._last_text:
            QApplication.clipboard().setText(self._last_text)

    # ----------------------------------------------------------- layer run
    def run_layer(self):
        if self.task is not None:
            return
        src = self.layer_combo.currentLayer()
        if src is None:
            QMessageBox.warning(self, "Isogonic Lines & MagVar", "Choose a layer.")
            return
        folder = self._check_output()
        if folder is None:
            return
        year, alt = self._year(), self.alt.value() / 1000.0
        mk, mkey = self._model(), self._model_key()
        date_txt = self.date.date().toString("yyyy-MM-dd")
        geom_type = QgsWkbTypes.geometryType(src.wkbType())
        mode = self.ref_combo.currentIndex()
        ndec = self.dec_combo.currentIndex()
        to_ll = QgsCoordinateTransform(
            src.crs(), QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance())
        feats, lons, lats, skipped = [], [], [], 0
        for f in src.getFeatures():
            g = f.geometry()
            if g is None or g.isNull() or g.isEmpty():
                skipped += 1
                continue
            if geom_type == QgsWkbTypes.GeometryType.LineGeometry and mode in (1, 2):
                verts = list(g.vertices())
                p = verts[0] if mode == 1 else verts[-1]
                pt = QgsPointXY(p.x(), p.y())
            elif geom_type == QgsWkbTypes.GeometryType.PointGeometry:
                pt = QgsPointXY(g.asPoint()) if not g.isMultipart() else QgsPointXY(g.asMultiPoint()[0])
            else:
                pt = g.centroid().asPoint()
            pt = to_ll.transform(pt)
            feats.append(f)
            lons.append(pt.x())
            lats.append(pt.y())
        if not feats:
            QMessageBox.warning(self, "Isogonic Lines & MagVar", "The layer has no usable features.")
            return

        def work(task):
            import numpy as np
            la, lo = np.array(lats), np.array(lons)
            out_d = np.empty(len(la))
            out_a = np.empty(len(la))
            n = len(la)
            for a in range(0, n, 20000):
                if task.isCanceled():
                    return None
                b = min(n, a + 20000)
                out_d[a:b] = wmm.declination(la[a:b], lo[a:b], year, alt, mk)
                out_a[a:b] = wmm.annual_change(la[a:b], lo[a:b], year, alt, mk)
                task.setProgress(100.0 * b / n)
            return out_d, out_a

        def done(task, ok):
            self._finish_task()
            if not ok or task.result is None:
                self.log("Cancelled." if task.error is None else "Error: %s" % task.error)
                return
            try:
                dec, ach = task.result
                names = layers.unique_names(
                    [fl.name() for fl in src.fields()],
                    ["decl_deg", "decl_label", "ann_change", "decl_date", "decl_model"],
                    self._fmt() == "shp")
                out = layers.new_memory_layer(
                    QgsWkbTypes.displayString(src.wkbType()), src.crs().authid(),
                    "%s_decl" % src.name(), [])
                dp = out.dataProvider()
                dp.addAttributes(list(src.fields())
                                 + [layers.make_field(names[0], "dbl"),
                                    layers.make_field(names[1], "str"),
                                    layers.make_field(names[2], "dbl"),
                                    layers.make_field(names[3], "str"),
                                    layers.make_field(names[4], "str")])
                out.updateFields()
                rows = []
                for f, d, a in zip(feats, dec, ach):
                    rows.append((f.geometry(), list(f.attributes())
                                 + [round(float(d), 3), wmm.format_label(d, ndec),
                                    round(float(a), 2), date_txt, mkey]))
                layers.add_features(out, rows)
                base = "%s_declination" % _safe(src.name())
                uri = layers.save_layer(out, folder, base, self._fmt(), layers.run_stamp())
                layers.load_layer(uri, "%s (declination)" % src.name())
                self.log("Done: %d features%s." % (len(rows), (", %d skipped (empty geometry)" % skipped) if skipped else ""))
            except Exception as exc:
                self.log("Error: %s" % exc)
                QMessageBox.warning(self, "Isogonic Lines & MagVar", str(exc))
        self._start(FuncTask("Isogonic Lines & MagVar: declination", work, done))

    # ---------------------------------------------------------- iso run
    def run_iso(self):
        if self.task is not None:
            return
        ext = self.extent_box.outputExtent()
        if ext.isNull() or ext.isEmpty():
            QMessageBox.warning(self, "Isogonic Lines & MagVar", "Set a valid extent.")
            return
        folder = self._check_output()
        if folder is None:
            return
        year, alt = self._year(), self.alt.value() / 1000.0
        date_txt = self.date.date().toString("yyyy-MM-dd")
        interval, step = self.interval.value(), self.step.currentData()
        refine = self.refine.isChecked()
        mk = self._model()
        w, s_, e, n = ext.xMinimum(), ext.yMinimum(), ext.xMaximum(), ext.yMaximum()
        if max(abs(s_), abs(n)) >= 85:
            self.log("Note: near the magnetic poles declination changes very fast; "
                     "results there are not reliable.")

        def work(task):
            return isogonic.isogonic_lines(
                w, s_, e, n, year, interval, step, alt,
                is_canceled=task.isCanceled, progress=task.setProgress, refine=refine, model=mk)

        def done(task, ok):
            self._finish_task()
            if task.error:
                self.log("Error: %s" % task.error)
                QMessageBox.warning(self, "Isogonic Lines & MagVar", task.error)
                return
            if not ok or task.result is None:
                self.log("Cancelled.")
                return
            lines, info = task.result
            if info:
                self.log("Model %s. Declination in this extent: %.3f\u00b0 to %.3f\u00b0 (grid %.3f\u00b0)."
                         % (info["model"], info["dmin"], info["dmax"], info["step"]))
            if not lines:
                msg = ("No isogonic line falls inside this extent at an interval of %.2f\u00b0. "
                       "Try a smaller interval or a larger extent." % interval)
                self.log(msg)
                QMessageBox.information(self, "Isogonic Lines & MagVar", msg)
                return
            used = info["interval"]
            if abs(used - interval) > 1e-9:
                self.log("No %.2f\u00b0 line crosses this extent, so the interval was refined to %.2f\u00b0."
                         % (interval, used))
            ndec = wmm.decimals_for(used)
            try:
                clip = QgsGeometry.fromRect(QgsRectangle(w, s_, e, n))
                names = ["decl_deg", "decl_label", "decl_date", "ann_change", "is_zero", "decl_model"]
                specs = [(names[0], "dbl"), (names[1], "str"), (names[2], "str"),
                         (names[3], "dbl"), (names[4], "int"), (names[5], "str")]
                out = layers.new_memory_layer("MultiLineString", "EPSG:4326", "isogonic", specs)
                rows = []
                for L in lines:
                    pts = [QgsPointXY(x, y) for x, y in L["coords"]]
                    g = QgsGeometry.fromPolylineXY(pts)
                    g = g.intersection(clip)
                    if g is None or g.isNull() or g.isEmpty():
                        continue
                    g.convertToMultiType()
                    lv = L["level"]
                    rows.append((g, [float(lv), wmm.format_label(lv, ndec), date_txt,
                                     round(L["ann_change"], 4), 1 if abs(lv) < 1e-9 else 0,
                                     info["model"]]))
                if not rows:
                    self.log("No isogonic line falls inside this extent.")
                    return
                layers.add_features(out, rows)
                uri = layers.save_layer(out, folder, "isogonic_lines", self._fmt(),
                                        layers.run_stamp())
                vl = layers.load_layer(uri, "Isogonic lines %s" % date_txt)
                style_isogonic(vl)
                self.log("Done: %d isogonic lines." % len(rows))
            except Exception as exc:
                self.log("Error: %s" % exc)
                QMessageBox.warning(self, "Isogonic Lines & MagVar", str(exc))
        self._start(FuncTask("Isogonic Lines & MagVar: isogonic lines", work, done))

    # ------------------------------------------------------------- tasks
    def _start(self, task):
        from qgis.core import QgsApplication
        self.task = task
        self._busy(True)
        self.bar.setValue(0)
        task.progressChanged.connect(self._on_progress)
        QgsApplication.taskManager().addTask(task)
        self.log("Working...")

    def _finish_task(self):
        self.task = None
        self._busy(False)
        self.bar.setValue(100)

    # ------------------------------------------------------------- reset
    def closeEvent(self, event):
        self.reset_state()
        super().closeEvent(event)

    def reject(self):
        self.reset_state()
        super().reject()

    def reset_state(self):
        if self._resetting:
            return
        self._resetting = True
        try:
            task = self.task
            if task is not None:
                with contextlib.suppress(Exception):
                    task.cancel()
                with contextlib.suppress(Exception):
                    task.progressChanged.disconnect()
                self.task = None
            self.live_chk.setChecked(False)
            self.click_btn.setChecked(False)
            self._release_tool()
            if self.card is not None:
                self.card.dismiss()
            self.bar.setValue(0)
            self.log_view.clear()
            for lab in (self.res_pos, self.res_decl, self.res_change, self.res_incl, self.res_total):
                lab.setText("-")
            self._last_text = ""
            self.cmp_out.clear()
            self._best = None
            self.cmp_apply.setEnabled(False)
            self.date.setDate(QDate.currentDate())
            self._busy(False)
        except Exception as exc:  # reset must never raise on close
            self._reset_error = str(exc)
        finally:
            self._resetting = False


def _safe(name):
    keep = "".join(c if (c.isalnum() or c in "-_") else "_" for c in name)
    return keep.strip("_") or "layer"
