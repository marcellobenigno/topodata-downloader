"""
Fluxo do plugin com um ``iface`` mínimo: botão -> ferramenta de seleção -> diálogo ->
refazer seleção -> descarregar. Usa a grade real (local); nenhum produto marcado, então
nenhuma consulta de rede é feita.

    QT_QPA_PLATFORM=offscreen <python do QGIS> -m pytest -v tests/test_plugin.py
"""
import pytest

from qgis_env import APP  # noqa: F401  (QGIS headless com perfil isolado)
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY,
                       QgsProject, QgsRectangle)
from qgis.gui import QgsMapCanvas, QgsMapToolPan, QgsMessageBar
from qgis.PyQt.QtWidgets import QMainWindow

from topodata_downloader import classFactory
from topodata_downloader import dialog as G


class FakeIface:
    def __init__(self):
        self.window = QMainWindow()
        self.canvas = QgsMapCanvas(self.window)
        self.canvas.resize(500, 500)
        self.canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
        self.bar = QgsMessageBar()
        self.toolbar, self.menu = [], []

    def mainWindow(self):
        return self.window

    def mapCanvas(self):
        return self.canvas

    def messageBar(self):
        return self.bar

    def addToolBarIcon(self, action):
        self.toolbar.append(action)

    def removeToolBarIcon(self, action):
        self.toolbar.remove(action)

    def addPluginToRasterMenu(self, menu, action):
        self.menu.append((menu, action))

    def removePluginRasterMenu(self, menu, action):
        self.menu.remove((menu, action))


@pytest.fixture
def plugin():
    iface = FakeIface()
    pan = QgsMapToolPan(iface.canvas)
    iface.canvas.setMapTool(pan)
    p = classFactory(iface)
    p.initGui()
    yield p, iface, pan
    p.unload()


def mercator_rect(w, s, e, n):
    t = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"),
                               QgsCoordinateReferenceSystem("EPSG:3857"), QgsProject.instance())
    return QgsRectangle(t.transform(QgsPointXY(w, s)), t.transform(QgsPointXY(e, n)), True)


def test_action_activates_rectangle_tool(plugin):
    p, iface, pan = plugin
    assert iface.toolbar == [p.action] and iface.menu[0][1] is p.action
    p.action.trigger()
    assert iface.canvas.mapTool() is p.tool and p.action.isChecked()
    p.tool.canceled.emit()                                   # Esc
    assert iface.canvas.mapTool() is pan and not p.action.isChecked()


def test_selection_opens_dialog_in_wgs84_and_restores_tool(plugin):
    p, iface, pan = plugin
    p.action.trigger()
    p.tool.selected.emit(mercator_rect(-36.4, -7.5, -35.6, -6.6))
    dlg = p.dialog
    assert dlg is not None and dlg.isVisible()
    assert iface.canvas.mapTool() is pan                     # ferramenta anterior de volta
    assert [t.scene for t in dlg.tiles] == ["06S36_", "06S375", "07S36_", "07S375"]
    assert dlg.west.text().startswith("-36,4") and dlg.north.text().startswith("-6,6")
    assert dlg.state == G.INCOMPLETE                         # falta produto e pasta
    assert len(dlg.plan) == 0 and dlg.probe_task is None     # nada consultado na rede
    assert p.band is not None


def test_reselect_keeps_configuration(plugin, tmp_path):
    p, iface, pan = plugin
    p.action.trigger()
    p.tool.selected.emit(mercator_rect(-36.4, -7.5, -35.6, -6.6))
    dlg = p.dialog
    dlg.folder.setFilePath(str(tmp_path))
    dlg.load_check.setChecked(False)
    dlg.reselect_button.click()
    assert iface.canvas.mapTool() is p.tool and not dlg.isVisible()
    p.tool.canceled.emit()                                   # desistiu: volta ao diálogo
    assert dlg.isVisible() and iface.canvas.mapTool() is pan
    dlg.reselect_button.click()
    p.tool.selected.emit(mercator_rect(-35.5, -7.6, -35.2, -7.3))
    assert p.dialog is dlg
    assert [t.scene for t in dlg.tiles] == ["07S36_"]
    assert dlg.folder_path() == str(tmp_path) and not dlg.load_check.isChecked()


def test_invalid_click_shows_message(plugin):
    p, iface, pan = plugin
    p.action.trigger()
    p.tool.invalid.emit("Retângulo muito pequeno")
    assert iface.canvas.mapTool() is p.tool and p.dialog is None


def test_unload_removes_everything():
    iface = FakeIface()
    p = classFactory(iface)
    p.initGui()
    p.action.trigger()
    p.tool.selected.emit(mercator_rect(-36.4, -7.5, -35.6, -6.6))
    p.unload()
    assert iface.toolbar == [] and iface.menu == []
    assert p.dialog is None and p.tool is None and p.band is None
