# -*- coding: utf-8 -*-
"""Ponto de entrada do plugin: botão/menu, ferramenta de seleção e diálogo."""
import os

from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsMessageLog

from .compat import MSG_CRITICAL, MSG_INFO, MSG_WARNING, QAction
from .grid import GridError, TopodataGrid

MENU = "TOPODATA Downloader"
TITLE = "TOPODATA Downloader"
FOLDER = os.path.dirname(__file__)
HINT = "Desenhe um retângulo no mapa (clique e arraste) sobre a área de interesse. Esc cancela."


def icon():
    svg = os.path.join(FOLDER, "icons", "icon.svg")
    return QIcon(svg if os.path.exists(svg) else os.path.join(FOLDER, "icons", "icon.png"))


class TopodataDownloaderPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.tool = None
        self.dialog = None
        self.band = None
        self._grid = None
        self._previous_tool = None

    # ------------------------------------------------------------------ QGIS
    def initGui(self):
        self.action = QAction(icon(), "Baixar dados TOPODATA por área", self.iface.mainWindow())
        self.action.setObjectName("topodata_downloader_action")
        self.action.setToolTip("TOPODATA: desenhe um retângulo no mapa para baixar as "
                               "quadrículas de altitude, declividade, curvaturas e outros "
                               "produtos do INPE")
        self.action.setCheckable(True)
        self.action.triggered.connect(self.toggle_tool)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToRasterMenu(MENU, self.action)

    def unload(self):
        self._deactivate_tool()
        if self.tool is not None:
            self.tool.cleanup()
            self.tool = None
        self._clear_band()
        if self.dialog is not None:
            self.dialog.shutdown()
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None
        if self.action is not None:
            self.iface.removeToolBarIcon(self.action)
            self.iface.removePluginRasterMenu(MENU, self.action)
            self.action = None

    # ------------------------------------------------------------------ grade
    def grid(self):
        """Grade lida e indexada uma única vez por sessão."""
        if self._grid is None:
            self._grid = TopodataGrid()
            QgsMessageLog.logMessage("Grade carregada: {} folhas ({}).".format(
                len(self._grid), self._grid.path), TITLE, MSG_INFO)
        return self._grid

    # -------------------------------------------------------------- ferramenta
    def _ensure_tool(self):
        if self.tool is None:
            from .map_tool import RectangleTool
            self.tool = RectangleTool(self.iface.mapCanvas())
            self.tool.setAction(self.action)
            self.tool.selected.connect(self.on_selected)
            self.tool.invalid.connect(self.on_invalid)
            self.tool.canceled.connect(self.on_canceled)
        return self.tool

    def toggle_tool(self, checked=True):
        if checked:
            self.activate_tool()
        else:
            self._deactivate_tool()
            self._show_dialog_if_area()

    def activate_tool(self):
        canvas = self.iface.mapCanvas()
        tool = self._ensure_tool()
        if canvas.mapTool() is not tool:
            self._previous_tool = canvas.mapTool()
            canvas.setMapTool(tool)
        self.action.setChecked(True)
        if self.dialog is not None and self.dialog.isVisible() and not self.dialog.is_busy():
            self.dialog.hide()
        self.iface.messageBar().pushMessage(TITLE, HINT, MSG_INFO, 6)

    def _deactivate_tool(self):
        canvas = self.iface.mapCanvas()
        if self.tool is not None and canvas.mapTool() is self.tool:
            prev = self._previous_tool
            if prev is not None:
                canvas.setMapTool(prev)
            else:
                canvas.unsetMapTool(self.tool)
        self._previous_tool = None
        if self.action is not None:
            self.action.setChecked(False)

    def on_invalid(self, message):
        self.iface.messageBar().pushMessage(TITLE, message, MSG_WARNING, 5)

    def on_canceled(self):
        self._deactivate_tool()
        self._show_dialog_if_area()

    def _show_dialog_if_area(self):
        if self.dialog is not None and self.dialog.selection is not None:
            self.dialog.show()
            self.dialog.raise_()

    def on_selected(self, rect):
        canvas = self.iface.mapCanvas()
        dialog = self._ensure_dialog()
        if dialog.is_busy():
            self.iface.messageBar().pushMessage(
                TITLE, "Há um download em andamento. Aguarde o fim ou cancele-o antes de "
                "escolher outra área.", MSG_WARNING, 6)
            dialog.show()
            dialog.raise_()
            return
        self._deactivate_tool()
        crs = canvas.mapSettings().destinationCrs()
        dialog.set_selection(rect, crs, canvas.mapSettings().transformContext())
        self._show_band(rect)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    # ------------------------------------------------------------------ diálogo
    def _grid_or_error(self):
        try:
            return self.grid()
        except GridError as err:
            QgsMessageLog.logMessage("{} {}".format(err.message, err.detail), TITLE,
                                     MSG_CRITICAL)
            raise

    def _ensure_dialog(self):
        if self.dialog is None:
            from .dialog import DownloadDialog
            self.dialog = DownloadDialog(self._grid_or_error, self.iface.mainWindow())
            self.dialog.reselectRequested.connect(self.activate_tool)
            self.dialog.finished.connect(self._dialog_closed)
        return self.dialog

    def _dialog_closed(self, *args):
        if self.dialog is not None and not self.dialog.isVisible():
            self._clear_band()

    def _show_band(self, rect):
        from .map_tool import make_band, show_rect
        if self.band is None:
            self.band = make_band(self.iface.mapCanvas())
        show_rect(self.band, rect)

    def _clear_band(self):
        if self.band is not None:
            self.band.reset()
            scene = self.iface.mapCanvas().scene()
            if scene is not None:
                scene.removeItem(self.band)
            self.band = None
