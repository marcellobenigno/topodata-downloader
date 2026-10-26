# -*- coding: utf-8 -*-
"""
Grade TOPODATA e consulta espacial.

* A grade é lida uma vez (GeoJSON, CRS84 = EPSG:4326 lon/lat) e indexada com
  QgsSpatialIndex. A consulta usa o índice só para pré-selecionar candidatas pela caixa
  envolvente e confirma cada uma com ``QgsGeometry.intersects`` sobre a geometria real.
* Regra de borda: relação ``intersects`` do modelo OGC. Uma folha apenas tocada pelo limite
  do retângulo (borda ou vértice em comum) **é incluída**. Observação: as folhas da grade
  têm meio pixel de margem (~0,000139°) além do limite nominal de 1° × 1,5°, então folhas
  vizinhas se sobrepõem levemente; um retângulo que termina exatamente num meridiano ou
  paralelo de articulação (ex.: −36°) inclui as duas folhas daquele limite.
* A seleção do mapa é feita no SRC do projeto. Ela é convertida em polígono, adensada
  (vértices extras em cada lado) e transformada para EPSG:4326. Assim, num SRC projetado
  (UTM, Web Mercator...), a consulta usa a forma real do retângulo em coordenadas
  geográficas, e não apenas a caixa envolvente transformada.
"""
import os

from qgis.core import (QgsCoordinateTransform, QgsCsException, QgsFeatureRequest,
                       QgsGeometry, QgsProject, QgsRectangle, QgsSpatialIndex,
                       QgsVectorLayer)

from .catalog import Tile
from .compat import WGS84

DEFAULT_GRID = os.path.join(os.path.dirname(__file__), "data", "grade_topodata.geojson")
REQUIRED_FIELDS = ("scene", "url")
DENSIFY = 32                                     # vértices extras por lado na transformação


class GridError(Exception):
    """Falha ao ler a grade (mensagem amigável + detalhe)."""

    def __init__(self, message, detail=""):
        super().__init__(message)
        self.message = message
        self.detail = detail


class SelectionError(Exception):
    """Retângulo inválido ou impossível de transformar para EPSG:4326."""


def _is_wgs84(crs):
    return crs.isValid() and (crs == WGS84 or crs.authid() in ("EPSG:4326", "OGC:CRS84"))


class TopodataGrid:
    def __init__(self, path=DEFAULT_GRID):
        self.path = path
        if not os.path.isfile(path):
            raise GridError("A grade TOPODATA não foi encontrada.", path)
        layer = QgsVectorLayer(path, "grade_topodata", "ogr")
        if not layer.isValid():
            raise GridError("Não foi possível abrir a grade TOPODATA.",
                            "{}: {}".format(path, layer.error().summary()))
        names = layer.fields().names()
        missing = [f for f in REQUIRED_FIELDS if f not in names]
        if missing:
            raise GridError("A grade não tem os campos esperados ({}).".format(
                ", ".join(missing)), "Campos encontrados: {}".format(", ".join(names)))
        transform = None
        if not _is_wgs84(layer.crs()):
            if not layer.crs().isValid():
                raise GridError("A grade não informa o sistema de referência.", path)
            transform = QgsCoordinateTransform(layer.crs(), WGS84, QgsProject.instance())

        self.tiles = {}
        self.geometries = {}
        self.invalid = []                       # [(scene, motivo)]
        self.index = QgsSpatialIndex()
        for feat in layer.getFeatures(QgsFeatureRequest()):
            scene = str(feat["scene"] or "").strip()
            url = str(feat["url"] or "").strip()
            geom = QgsGeometry(feat.geometry())
            if not scene or not url:
                self.invalid.append((scene or "#{}".format(feat.id()), "sem scene/url"))
                continue
            if geom.isNull() or geom.isEmpty():
                self.invalid.append((scene, "geometria vazia"))
                continue
            if transform is not None:
                geom.transform(transform)
            if not geom.isGeosValid():
                geom = geom.makeValid()
                if geom.isNull() or geom.isEmpty():
                    self.invalid.append((scene, "geometria inválida"))
                    continue
            fid = feat.id()
            self.tiles[fid] = Tile(scene, url)
            self.geometries[fid] = geom
            self.index.addFeature(fid, geom.boundingBox())
        if not self.tiles:
            raise GridError("A grade TOPODATA está vazia.", path)

    def __len__(self):
        return len(self.tiles)

    def extent(self):
        boxes = [g.boundingBox() for g in self.geometries.values()]
        rect = QgsRectangle(boxes[0])
        for box in boxes[1:]:
            rect.combineExtentWith(box)
        return rect

    def query(self, geom):
        """Folhas cuja geometria intersecta ``geom`` (EPSG:4326), ordenadas pelo nome."""
        if geom is None or geom.isNull() or geom.isEmpty():
            return []
        engine = QgsGeometry.createGeometryEngine(geom.constGet())
        engine.prepareGeometry()
        found = []
        for fid in self.index.intersects(geom.boundingBox()):
            if engine.intersects(self.geometries[fid].constGet()):
                found.append(self.tiles[fid])
        return sorted(found, key=lambda t: t.scene)


def selection_to_wgs84(rect, crs, context=None):
    """Retângulo do mapa (no SRC ``crs``) -> polígono em EPSG:4326.

    Lança SelectionError para retângulo vazio, SRC inválido ou falha de transformação."""
    if rect is None or rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
        raise SelectionError("O retângulo selecionado não tem área. Clique e arraste para "
                             "desenhar uma área.")
    if not crs.isValid():
        raise SelectionError("O sistema de referência do mapa é inválido; defina o SRC do "
                             "projeto e selecione de novo.")
    geom = QgsGeometry.fromRect(rect)
    if not _is_wgs84(crs):
        geom = geom.densifyByCount(DENSIFY)
        transform = QgsCoordinateTransform(crs, WGS84, context or QgsProject.instance())
        try:
            geom.transform(transform)
        except QgsCsException as err:
            raise SelectionError("Não foi possível converter a seleção para coordenadas "
                                 "geográficas (EPSG:4326): {}".format(err))
    box = geom.boundingBox()
    values = (box.xMinimum(), box.yMinimum(), box.xMaximum(), box.yMaximum())
    if any(v != v or abs(v) == float("inf") for v in values):        # NaN / infinito
        raise SelectionError("A conversão da seleção para EPSG:4326 gerou coordenadas "
                             "inválidas. Selecione uma área menor ou mude o SRC do mapa.")
    if box.xMinimum() < -180 or box.xMaximum() > 180 or box.yMinimum() < -90 \
            or box.yMaximum() > 90:
        raise SelectionError("A seleção sai dos limites do globo (longitude −180° a 180°, "
                             "latitude −90° a 90°).")
    return geom
