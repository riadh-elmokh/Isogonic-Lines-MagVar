"""Map tool: click the map to read the magnetic declination (optionally live)."""
from qgis.core import (
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject,
)
from qgis.gui import QgsMapToolEmitPoint
from qgis.PyQt.QtCore import pyqtSignal


class ClickTool(QgsMapToolEmitPoint):
    picked = pyqtSignal(float, float)       # lat, lon (EPSG:4326), on click
    moved = pyqtSignal(float, float)        # lat, lon while the cursor moves (live mode)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.last_pixel = None
        self.last_map_point = None
        self.live = False                   # follow the cursor
        self.pinned = False                 # live mode: a click freezes the card

    def _to_wgs84(self, pt):
        src = self.canvas.mapSettings().destinationCrs()
        dst = QgsCoordinateReferenceSystem("EPSG:4326")
        if src != dst:
            pt = QgsCoordinateTransform(src, dst, QgsProject.instance()).transform(pt)
        return pt

    def canvasMoveEvent(self, event):  # noqa: N802
        if not self.live or self.pinned:
            return
        self.last_pixel = event.pos()
        self.last_map_point = self.toMapCoordinates(event.pos())
        pt = self._to_wgs84(self.last_map_point)
        self.moved.emit(float(pt.y()), float(pt.x()))

    def canvasReleaseEvent(self, event):  # noqa: N802
        self.last_pixel = event.pos()
        self.last_map_point = self.toMapCoordinates(event.pos())
        if self.live:
            self.pinned = not self.pinned   # click pins, next click resumes following
        pt = self._to_wgs84(self.last_map_point)
        self.picked.emit(float(pt.y()), float(pt.x()))
