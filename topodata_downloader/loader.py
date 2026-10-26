# -*- coding: utf-8 -*-
"""Carrega os GeoTIFF baixados como camadas raster separadas, sem mosaico, recorte nem
reprojeção. Arquivos já presentes no projeto (mesmo caminho) não são duplicados."""
import os

from qgis.core import QgsProject, QgsRasterLayer

from .catalog import PRODUCT_BY_CODE

GROUP = "TOPODATA"


def _key(path):
    return os.path.normcase(os.path.realpath(path))


def layer_name(path):
    """'07S36_ZN' -> '07S36_ZN — Altitude' (o nome original é preservado)."""
    stem = os.path.splitext(os.path.basename(path))[0]
    product = PRODUCT_BY_CODE.get(stem[-2:])
    return "{} — {}".format(stem, product.label) if product else stem


def loaded_paths(project=None):
    project = project or QgsProject.instance()
    keys = set()
    for layer in project.mapLayers().values():
        if isinstance(layer, QgsRasterLayer):
            keys.add(_key(layer.source().split("|")[0]))
    return keys


def add_rasters(paths, project=None, group_name=GROUP):
    """Retorna (adicionados, já carregados, falhas[(caminho, motivo)])."""
    project = project or QgsProject.instance()
    present = loaded_paths(project)
    added, skipped, failed = [], [], []
    group = None
    for path in paths:
        if _key(path) in present:
            skipped.append(path)
            continue
        if not os.path.isfile(path):
            failed.append((path, "Arquivo não encontrado no disco."))
            continue
        layer = QgsRasterLayer(path, layer_name(path), "gdal")
        if not layer.isValid():
            reason = layer.error().summary() or "formato não reconhecido"
            failed.append((path, "O QGIS/GDAL não conseguiu abrir o arquivo: {}".format(reason)))
            continue
        if group is None:
            root = project.layerTreeRoot()
            group = root.findGroup(group_name) or root.insertGroup(0, group_name)
        project.addMapLayer(layer, False)
        group.addLayer(layer)
        added.append(path)
        present.add(_key(path))
    return added, skipped, failed
