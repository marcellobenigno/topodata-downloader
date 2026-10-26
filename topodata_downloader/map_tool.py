# -*- coding: utf-8 -*-
"""
Ferramenta de seleção retangular no mapa (inspirada no fluxo do OSMDownloader: clicar,
arrastar e soltar desenha o retângulo). Emite o retângulo no SRC do mapa; a conversão para
EPSG:4326 fica em grid.selection_to_wgs84.

Esc cancela. Um clique sem arrasto (menos de MIN_DRAG_PX pixels) não é aceito como área.
"""
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsPointXY, QgsRectangle
from qgis.gui import QgsMapTool, QgsRubberBand

from .compat import CROSS_CURSOR, GEOM_POLYGON, KEY_ESCAPE, LEFT

MIN_DRAG_PX = 4
FILL = QColor(255, 140, 0, 50)
STROKE = QColor(200, 90, 0, 220)


def make_band(canvas):
    band = QgsRubberBand(canvas, GEOM_POLYGON)
    band.setFillColor(FILL)
    band.setStrokeColor(STROKE)
    band.setWidth(2)
    return band


def show_rect(band, rect):
    band.reset(GEOM_POLYGON)
    if rect is None or rect.isEmpty():
        return
    points = [QgsPointXY(rect.xMinimum(), rect.yMinimum()),
              QgsPointXY(rect.xMinimum(), rect.yMaximum()),
              QgsPointXY(rect.xMaximum(), rect.yMaximum()),
              QgsPointXY(rect.xMaximum(), rect.yMinimum())]
    for i, p in enumerate(points):
        band.addPoint(p, i == len(points) - 1)
    band.show()


class RectangleTool(QgsMapTool):
    selected = pyqtSignal(QgsRectangle)       # retângulo no SRC do mapa
    invalid = pyqtSignal(str)
    canceled = pyqtSignal()

    def __init__(self, canvas):
        super().__init__(canvas)
        self.setCursor(CROSS_CURSOR)
        self.band = make_band(canvas)
        self._start_px = None
        self._start = None

    def _rect(self, end):
        return QgsRectangle(self._start, end, True)          # normalizado

    def canvasPressEvent(self, e):
        if e.button() != LEFT:
            return
        self._start_px = e.pos()
        self._start = self.toMapCoordinates(e.pos())
        self.band.reset(GEOM_POLYGON)

    def canvasMoveEvent(self, e):
        if self._start is None:
            return
        show_rect(self.band, self._rect(self.toMapCoordinates(e.pos())))

    def canvasReleaseEvent(self, e):
        if e.button() != LEFT or self._start is None:
            return
        moved = e.pos() - self._start_px
        rect = self._rect(self.toMapCoordinates(e.pos()))
        self._start = self._start_px = None
        self.band.reset(GEOM_POLYGON)
        if abs(moved.x()) < MIN_DRAG_PX or abs(moved.y()) < MIN_DRAG_PX:
            self.invalid.emit("Retângulo muito pequeno: clique e arraste para desenhar a área "
                              "de interesse.")
            return
        self.selected.emit(rect)

    def keyPressEvent(self, e):
        if e.key() == KEY_ESCAPE:
            self._start = self._start_px = None
            self.band.reset(GEOM_POLYGON)
            self.canceled.emit()

    def deactivate(self):
        self._start = self._start_px = None
        self.band.reset(GEOM_POLYGON)
        super().deactivate()

    def cleanup(self):
        self.band.reset(GEOM_POLYGON)
        scene = self.canvas().scene()
        if scene is not None:
            scene.removeItem(self.band)
