# -*- coding: utf-8 -*-
"""
Diálogo do TOPODATA Downloader.

Duas páginas, para não iniciar downloads por acidente:
  1. Configuração: área selecionada, pasta, produtos, opções e resumo (contagem e tamanho).
  2. Execução: progresso geral e do arquivo, situação de cada arquivo e ações finais.

Uma faixa de situação no topo mostra sempre o estado atual (aguardando seleção, consultando,
pronto, baixando, cancelado, concluído, parcial...) e, quando houver, um detalhe técnico que
pode ser expandido e copiado.
"""
import os

from qgis.PyQt.QtCore import QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (QApplication, QDialog,
                                 QFormLayout, QGroupBox, QHBoxLayout, QLabel, QListWidget,
                                 QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar,
                                 QPushButton, QScrollArea, QStackedWidget, QTableWidget,
                                 QTableWidgetItem, QToolButton, QVBoxLayout, QCheckBox,
                                 QWidget)
from qgis.core import QgsApplication, QgsSettings
from qgis.gui import QgsFileWidget

from . import catalog as C
from . import downloader as D
from .compat import (ALIGN_RIGHT, ALIGN_VCENTER, CHECKED, DIRECTORY_MODE,
                     ITEM_CHECKABLE, ITEM_ENABLED, ITEM_SELECTABLE, MB_NO, MB_YES, NO_EDIT,
                     PLAIN_TEXT, RESIZE_TO_CONTENTS, SELECT_ROWS, SINGLE_SELECTION, STRETCH,
                     TEXT_KEYBOARD, TEXT_SELECTABLE, UNCHECKED, USER_ROLE)
from .grid import GridError, SelectionError, selection_to_wgs84
from .loader import add_rasters
from .tasks import DownloadTask, SizeProbeTask
from .translation import N_, tr

SETTINGS = "topodata_downloader/"

# Estados visíveis (textos traduzidos com tr() em _set_state)
WAITING, QUERYING, NO_TILES, ERROR, INCOMPLETE, READY = range(6)
DOWNLOADING, CANCELING, CANCELED, DONE, PARTIAL = range(6, 11)
BUSY = (DOWNLOADING, CANCELING)
STATE_TEXT = {
    WAITING: N_("Waiting for a selection on the map"),
    QUERYING: N_("Querying the TOPODATA grid…"),
    NO_TILES: N_("No TOPODATA tile in the selected area"),
    ERROR: N_("Could not query the area"),
    INCOMPLETE: N_("The download is not fully set up"),
    READY: N_("Ready to download"),
    DOWNLOADING: N_("Downloading…"),
    CANCELING: N_("Canceling… waiting for the current block of data to finish"),
    CANCELED: N_("Download canceled"),
    DONE: N_("Completed successfully"),
    PARTIAL: N_("Partially completed"),
}
STATE_MARK = {NO_TILES: "⚠", ERROR: "✖", INCOMPLETE: "•", READY: "✔", CANCELED: "■",
              DONE: "✔", PARTIAL: "⚠"}


def _label(text="", selectable=False, wrap=True):
    lab = QLabel(text)
    lab.setWordWrap(wrap)
    lab.setTextFormat(PLAIN_TEXT)
    if selectable:
        lab.setTextInteractionFlags(TEXT_SELECTABLE | TEXT_KEYBOARD)
    return lab


def _item(text, align_right=False):
    it = QTableWidgetItem(text)
    it.setFlags(ITEM_ENABLED | ITEM_SELECTABLE)
    if align_right:
        it.setTextAlignment(int(ALIGN_RIGHT | ALIGN_VCENTER))
    return it


class DownloadDialog(QDialog):
    reselectRequested = pyqtSignal()

    def __init__(self, grid_provider, parent=None, project=None):
        """grid_provider: função sem argumentos que retorna a TopodataGrid (pode lançar
        GridError)."""
        super().__init__(parent)
        self.setObjectName("TopodataDownloaderDialog")
        self.setWindowTitle(tr("TOPODATA — download by area"))
        self.setSizeGripEnabled(True)
        self.resize(720, 760)
        self.grid_provider = grid_provider
        self.project = project
        self.settings = QgsSettings()

        self.state = WAITING
        self.tiles = []
        self.selection = None                 # QgsGeometry em EPSG:4326
        self.plan = C.Plan([], [])
        self.sizes, self.size_errors = {}, {}
        self.probe_task = None
        self.pending_probe = set()
        self.task = None
        self.results = []
        self.run_items = []
        self.run_folder = ""
        self.loaded = set()
        self.cancel_requested = False
        self._shutting_down = False
        self._bytes_done = 0
        self._current_bytes = 0

        self.probe_timer = QTimer(self)
        self.probe_timer.setSingleShot(True)
        self.probe_timer.setInterval(400)
        self.probe_timer.timeout.connect(self._start_probe)

        self._build()
        self._restore_settings()
        self._set_state(WAITING)

    # ================================================================== interface
    def _build(self):
        outer = QVBoxLayout(self)

        # faixa de situação + detalhes técnicos
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setAccessibleName(tr("Status"))
        self.status.setTextInteractionFlags(TEXT_SELECTABLE | TEXT_KEYBOARD)
        self.status_detail = _label(selectable=True)
        self.details_button = QToolButton()
        self.details_button.setText(tr("Technical details"))
        self.details_button.setCheckable(True)
        self.details_button.setAccessibleName(tr("Show technical details"))
        self.copy_button = QPushButton(tr("Copy details"))
        self.copy_button.clicked.connect(self._copy_details)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName(tr("Technical details"))
        self.details.setMaximumHeight(140)
        self.details.setVisible(False)
        self.details_button.toggled.connect(self.details.setVisible)
        top = QHBoxLayout()
        top.addWidget(self.status, 1)
        top.addWidget(self.details_button)
        top.addWidget(self.copy_button)
        outer.addLayout(top)
        outer.addWidget(self.status_detail)
        outer.addWidget(self.details)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_config_page())
        self.pages.addWidget(self._build_run_page())
        outer.addWidget(self.pages, 1)

    def _build_config_page(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        scroll.setWidget(inner)
        box.addWidget(scroll, 1)

        # --- área
        area = QGroupBox(tr("Selected area (geographic coordinates, EPSG:4326)"))
        form = QFormLayout(area)
        self.west, self.south = _label(selectable=True), _label(selectable=True)
        self.east, self.north = _label(selectable=True), _label(selectable=True)
        for text, lab in ((tr("West (minimum longitude):"), self.west),
                          (tr("South (minimum latitude):"), self.south),
                          (tr("East (maximum longitude):"), self.east),
                          (tr("North (maximum latitude):"), self.north)):
            form.addRow(text, lab)
        self.tile_count = _label(selectable=True)
        form.addRow(tr("Tiles found:"), self.tile_count)
        self.tile_list = _label(selectable=True)
        form.addRow("", self.tile_list)
        self.area_hint = _label(tr(
            "Tile = TOPODATA sheet of 1° latitude × 1.5° longitude (1:250,000 index). All "
            "sheets that intersect the rectangle are included, even those only touched by its "
            "edge."))
        form.addRow(self.area_hint)
        self.reselect_button = QPushButton(tr("Select again on the map"))
        self.reselect_button.setToolTip(tr("Returns to the map to draw another rectangle. "
                                           "Folder, products and options are kept."))
        self.reselect_button.clicked.connect(self.reselectRequested.emit)
        form.addRow(self.reselect_button)
        lay.addWidget(area)

        # --- pasta
        dest = QGroupBox(tr("Destination folder"))
        dlay = QVBoxLayout(dest)
        self.folder = QgsFileWidget()
        self.folder.setStorageMode(DIRECTORY_MODE)
        self.folder.setDialogTitle(tr("Choose the destination folder for the TOPODATA files"))
        self.folder.setAccessibleName(tr("Destination folder"))
        self.folder.setToolTip(tr("Files are saved with their original INPE name "
                                  "(e.g. 07S36_ZN.tif)."))
        self.folder.fileChanged.connect(self._refresh)
        self.folder_msg = _label()
        dlay.addWidget(self.folder)
        dlay.addWidget(self.folder_msg)
        lay.addWidget(dest)

        # --- produtos
        prod = QGroupBox(tr("Products"))
        play = QVBoxLayout(prod)
        self.products = QListWidget()
        self.products.setAccessibleName(tr("TOPODATA products"))
        self.products.setAccessibleDescription(tr("Check the products to download with the "
                                                  "space bar."))
        self.products.setSelectionMode(SINGLE_SELECTION)
        for p in C.PRODUCTS:
            it = QListWidgetItem("{}  ({})".format(tr(p.label), p.code))
            it.setData(USER_ROLE, p.code)
            it.setToolTip(tr(p.description))
            it.setFlags(ITEM_ENABLED | ITEM_SELECTABLE | ITEM_CHECKABLE)
            it.setCheckState(UNCHECKED)
            self.products.addItem(it)
        self.products.setMinimumHeight(200)
        self.products.itemChanged.connect(self._refresh)
        play.addWidget(self.products)
        row = QHBoxLayout()
        self.select_all = QPushButton(tr("Select all"))
        self.select_all.clicked.connect(lambda: self._check_all(True))
        self.clear_all = QPushButton(tr("Clear selection"))
        self.clear_all.clicked.connect(lambda: self._check_all(False))
        row.addWidget(self.select_all)
        row.addWidget(self.clear_all)
        row.addStretch(1)
        play.addLayout(row)
        self.product_msg = _label()
        play.addWidget(self.product_msg)
        lay.addWidget(prod)

        # --- opções
        opt = QGroupBox(tr("Options"))
        olay = QVBoxLayout(opt)
        self.load_check = QCheckBox(tr("Load the images into QGIS when finished"))
        self.load_check.setToolTip(tr("Each file becomes a separate raster layer, in the "
                                      "TOPODATA group. No mosaicking, clipping or reprojection "
                                      "is done."))
        self.overwrite_check = QCheckBox(tr("Download again files that already exist in the "
                                            "folder"))
        self.overwrite_check.setToolTip(tr(
            "Unchecked: an existing file with the same size reported by the server is reused. "
            "Checked: it is downloaded again; the current file is only replaced when the new "
            "one is complete."))
        self.overwrite_check.toggled.connect(self._refresh)
        olay.addWidget(self.load_check)
        olay.addWidget(self.overwrite_check)
        lay.addWidget(opt)

        # --- resumo
        summ = QGroupBox(tr("Summary before downloading"))
        slay = QVBoxLayout(summ)
        self.summary_table = QTableWidget(0, 3)
        self.summary_table.setHorizontalHeaderLabels([tr("Product"), tr("Files"), tr("Size")])
        self.summary_table.setAccessibleName(tr("Summary by product"))
        self.summary_table.setEditTriggers(NO_EDIT)
        self.summary_table.setSelectionBehavior(SELECT_ROWS)
        self.summary_table.verticalHeader().setVisible(False)
        header = self.summary_table.horizontalHeader()
        header.setSectionResizeMode(0, STRETCH)
        header.setSectionResizeMode(1, RESIZE_TO_CONTENTS)
        header.setSectionResizeMode(2, RESIZE_TO_CONTENTS)
        self.summary_table.setMinimumHeight(140)
        slay.addWidget(self.summary_table)
        self.summary_text = _label(selectable=True)
        slay.addWidget(self.summary_text)
        self.size_method = _label(selectable=True)
        slay.addWidget(self.size_method)
        self.retry_sizes = QPushButton(tr("Check sizes again"))
        self.retry_sizes.clicked.connect(self._retry_sizes)
        self.retry_sizes.setVisible(False)
        slay.addWidget(self.retry_sizes)
        self.large_msg = _label()
        slay.addWidget(self.large_msg)
        slay.addWidget(_label(tr("The duration depends on your connection, the INPE server and "
                                 "the volume of data. The original files are downloaded "
                                 "without mosaicking, clipping or reprojection.")))
        lay.addWidget(summ)
        lay.addStretch(1)

        buttons = QHBoxLayout()
        self.download_button = QPushButton(tr("Download"))
        self.download_button.setAutoDefault(False)
        self.download_button.setDefault(False)
        self.download_button.clicked.connect(self.start_download)
        close = QPushButton(tr("Close"))
        close.setAutoDefault(False)
        close.clicked.connect(self.close)
        buttons.addStretch(1)
        buttons.addWidget(self.download_button)
        buttons.addWidget(close)
        box.addLayout(buttons)
        return page

    def _build_run_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        self.overall = QProgressBar()
        self.overall.setAccessibleName(tr("Overall progress"))
        self.overall_label = _label(selectable=True)
        self.file_label = _label(selectable=True)
        self.file_bar = QProgressBar()
        self.file_bar.setAccessibleName(tr("Current file progress"))
        lay.addWidget(QLabel(tr("Overall progress:")))
        lay.addWidget(self.overall)
        lay.addWidget(self.overall_label)
        lay.addWidget(QLabel(tr("Current file:")))
        lay.addWidget(self.file_label)
        lay.addWidget(self.file_bar)

        self.run_table = QTableWidget(0, 4)
        self.run_table.setHorizontalHeaderLabels([tr("File"), tr("Product"), tr("Status"),
                                                  tr("Message")])
        self.run_table.setAccessibleName(tr("Status of each file"))
        self.run_table.setEditTriggers(NO_EDIT)
        self.run_table.setSelectionBehavior(SELECT_ROWS)
        self.run_table.verticalHeader().setVisible(False)
        header = self.run_table.horizontalHeader()
        for col in range(3):
            header.setSectionResizeMode(col, RESIZE_TO_CONTENTS)
        header.setSectionResizeMode(3, STRETCH)
        lay.addWidget(self.run_table, 1)
        self.final_label = _label(selectable=True)
        lay.addWidget(self.final_label)

        row = QHBoxLayout()
        self.cancel_button = QPushButton(tr("Cancel download"))
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.clicked.connect(self.cancel_download)
        self.open_button = QPushButton(tr("Open destination folder"))
        self.open_button.setAutoDefault(False)
        self.open_button.clicked.connect(self.open_folder)
        self.load_button = QPushButton(tr("Load into QGIS"))
        self.load_button.setAutoDefault(False)
        self.load_button.clicked.connect(self.load_results)
        self.back_button = QPushButton(tr("Back to setup"))
        self.back_button.setAutoDefault(False)
        self.back_button.clicked.connect(self.back_to_config)
        for b in (self.cancel_button, self.open_button, self.load_button, self.back_button):
            row.addWidget(b)
        row.addStretch(1)
        close = QPushButton(tr("Close"))
        close.setAutoDefault(False)
        close.clicked.connect(self.close)
        row.addWidget(close)
        lay.addLayout(row)
        return page

    # ================================================================ preferências
    def _restore_settings(self):
        self.folder.setFilePath(self.settings.value(SETTINGS + "folder", "") or "")
        saved = self.settings.value(SETTINGS + "products", []) or []
        if isinstance(saved, str):
            saved = [saved]
        self._set_checked(set(saved))
        self.load_check.setChecked(self.settings.value(SETTINGS + "load", True, type=bool))

    def _save_settings(self):
        self.settings.setValue(SETTINGS + "folder", self.folder_path())
        self.settings.setValue(SETTINGS + "products", self.checked_codes())
        self.settings.setValue(SETTINGS + "load", self.load_check.isChecked())

    # ===================================================================== estado
    def _set_state(self, state, detail="", technical=""):
        self.state = state
        mark = STATE_MARK.get(state, "")
        self.status.setText(tr("Status: {}{}").format(mark + " " if mark else "",
                                                      tr(STATE_TEXT[state])))
        font = self.status.font()
        font.setBold(True)
        self.status.setFont(font)
        self.status_detail.setText(detail)
        self.status_detail.setVisible(bool(detail))
        self.details.setPlainText(technical)
        has_tech = bool(technical)
        self.details_button.setVisible(has_tech)
        self.copy_button.setVisible(has_tech)
        if not has_tech:
            self.details_button.setChecked(False)
        busy = state in BUSY
        self.cancel_button.setEnabled(state == DOWNLOADING)
        self.back_button.setEnabled(not busy)
        self.reselect_button.setEnabled(not busy)
        ok_paths = self._ok_paths()
        self.open_button.setEnabled(bool(self.run_folder) and os.path.isdir(self.run_folder))
        self.load_button.setEnabled(not busy and any(p not in self.loaded for p in ok_paths))
        self.download_button.setEnabled(state == READY)

    def is_busy(self):
        return self.state in BUSY

    # ===================================================================== seleção
    def set_selection(self, rect, crs, context=None):
        """Recebe o retângulo desenhado (SRC do mapa). Retorna False se ocupado."""
        if self.is_busy():
            return False
        self.pages.setCurrentIndex(0)
        self._set_state(QUERYING)
        try:
            geom = selection_to_wgs84(rect, crs, context)
        except SelectionError as err:
            self._clear_area()
            self._set_state(ERROR, str(err) + " " + tr("Use “Select again on the map”."))
            return True
        try:
            grid = self.grid_provider()
            tiles = grid.query(geom)
        except GridError as err:
            self._clear_area()
            self._set_state(ERROR, err.message + " " + tr("Reinstall the plugin or check the "
                                                          "grid file."), err.detail)
            return True
        self.selection = geom
        self.tiles = tiles
        box = geom.boundingBox()
        self.west.setText(C.format_degrees(box.xMinimum()))
        self.south.setText(C.format_degrees(box.yMinimum()))
        self.east.setText(C.format_degrees(box.xMaximum()))
        self.north.setText(C.format_degrees(box.yMaximum()))
        self._refresh()
        return True

    def _clear_area(self):
        self.selection, self.tiles = None, []
        for lab in (self.west, self.south, self.east, self.north):
            lab.setText("—")
        self.tile_count.setText("—")
        self.tile_list.setText("")
        self.plan = C.Plan([], [])
        self._fill_summary()

    # ================================================================= produtos
    def _items(self):
        return [self.products.item(i) for i in range(self.products.count())]

    def checked_codes(self):
        return [it.data(USER_ROLE) for it in self._items() if it.checkState() == CHECKED]

    def _set_checked(self, codes):
        self.products.blockSignals(True)
        for it in self._items():
            it.setCheckState(CHECKED if it.data(USER_ROLE) in codes else UNCHECKED)
        self.products.blockSignals(False)
        self._refresh()

    def _check_all(self, on):
        self._set_checked({p.code for p in C.PRODUCTS} if on else set())

    def folder_path(self):
        return (self.folder.filePath() or "").strip()

    # ================================================================ resumo
    def _refresh(self, *args):
        """Recalcula plano, validações e resumo depois de qualquer mudança."""
        if self.is_busy() or self.pages.currentIndex() != 0:
            return
        codes = self.checked_codes()
        self.plan = C.Plan(self.tiles, codes)

        if self.selection is not None:
            n = len(self.plan.tiles) if codes else len(self.tiles)
            self.tile_count.setText(str(n))
            scenes = ", ".join(t.scene for t in self.tiles)
            per_tile = set(self.plan.by_tile.values())
            if codes and len(per_tile) == 1:
                scenes += " — " + tr("{} file(s) per tile").format(per_tile.pop())
            elif codes:
                scenes = "; ".join("{}: {}".format(s, k) for s, k in self.plan.by_tile.items())
            self.tile_list.setText(scenes)

        ok_folder, folder_msg = C.describe_destination(self.folder_path())
        self.folder_msg.setText(("✖ " if not ok_folder else "") + folder_msg)
        self.folder_msg.setVisible(bool(folder_msg))

        missing = []
        if self.selection is None:
            missing.append(tr("draw the area on the map"))
        elif not self.tiles:
            missing.append(tr("select an area that covers TOPODATA tiles"))
        if not codes:
            missing.append(tr("check at least one product"))
            self.product_msg.setText("• " + tr("No product checked."))
        else:
            self.product_msg.setText(tr("{} of {} products checked.").format(len(codes),
                                                                             len(C.PRODUCTS)))
        if not ok_folder:
            missing.append(tr("choose a valid destination folder"))

        self._fill_summary()
        self.download_button.setText(tr("Download {} file(s)").format(len(self.plan))
                                     if len(self.plan) else tr("Download"))

        if self.selection is None and not self.tiles:
            self._set_state(WAITING, tr("Draw a rectangle on the map (click and drag) to "
                                        "choose the area."))
        elif not self.tiles:
            self._set_state(NO_TILES, tr("The area does not cover any tile of the TOPODATA "
                                         "grid (coverage: Brazilian territory). Use “Select "
                                         "again on the map”."))
        elif missing:
            self._set_state(INCOMPLETE, tr("To continue: {}.").format("; ".join(missing)))
        else:
            rejected = ""
            if self.plan.rejected:
                rejected = tr("Tiles skipped because of a non-standard URL: {}.").format(
                    ", ".join(s for s, _ in self.plan.rejected))
            self._set_state(READY, rejected,
                            "\n".join(m for _, m in self.plan.rejected))
        self._schedule_probe()

    def _fill_summary(self):
        plan = self.plan
        summary = C.SizeSummary(plan, self.sizes)
        t = self.summary_table
        t.setRowCount(0)
        for code, count in plan.by_product.items():
            r = t.rowCount()
            t.insertRow(r)
            t.setItem(r, 0, _item("{} ({})".format(tr(C.PRODUCT_BY_CODE[code].label), code)))
            t.setItem(r, 1, _item(str(count), True))
            t.setItem(r, 2, _item(self._size_text(summary.product_total(code), code), True))
        if plan.by_product:
            r = t.rowCount()
            t.insertRow(r)
            total = _item(tr("Total"))
            font = total.font()
            font.setBold(True)
            total.setFont(font)
            t.setItem(r, 0, total)
            t.setItem(r, 1, _item(str(len(plan)), True))
            t.setItem(r, 2, _item(self._size_text(summary.total), True))

        lines = [tr("Tiles considered: {}").format(len(plan.tiles) if plan.codes else 0),
                 tr("Files planned: {} (no duplicates)").format(len(plan))]
        folder = self.folder_path()
        existing = C.existing_files(plan, folder)
        partial = C.partial_files(plan, folder)
        if existing:
            if self.overwrite_check.isChecked():
                lines.append(tr("{} file(s) already exist in the folder and will be downloaded "
                                "again (replaced only when the new one is complete).").format(
                                    len(existing)))
            else:
                lines.append(tr("{} file(s) already exist in the folder: they will be checked by "
                                "size and reused if complete.").format(len(existing)))
        if partial:
            lines.append(tr("{} partial download(s) (.part) will be resumed if the server "
                            "confirms that the file has not changed.").format(len(partial)))
        self.summary_text.setText("\n".join(lines))
        self.size_method.setText(self._size_method_text(summary))
        self.retry_sizes.setVisible(any(u in self.size_errors for u in plan.urls))
        self.large_msg.setText(
            "⚠ " + tr("Large download: many files or several gigabytes. It may take a long "
                      "time and use a lot of disk space. You can continue anyway.")
            if C.is_large(plan, summary) else "")
        self.large_msg.setVisible(bool(self.large_msg.text()))

    def _size_text(self, value, code=None):
        if value is not None:
            return C.format_bytes(value)
        urls = [i.url for i in self.plan.items if code is None or i.code == code]
        if any(u in self.pending_probe for u in urls):
            return tr("checking…")
        return tr("not available")

    def _size_method_text(self, summary):
        if not len(self.plan):
            return ""
        origin = tr("Size source: reported by the INPE server for each file (Content-Length "
                    "header of a HEAD request, without downloading the data).")
        if summary.complete:
            return origin + " " + tr("Exact total of the current files on the server.")
        pending = sum(1 for u in self.plan.urls if u in self.pending_probe)
        failed = sum(1 for u in self.plan.urls if u in self.size_errors)
        parts = [origin]
        if summary.known_count:
            parts.append(tr("Known for {} of {} files: at least {}.").format(
                summary.known_count, summary.count, C.format_bytes(summary.known_total)))
        if pending:
            parts.append(tr("Checking {} file(s)…").format(pending))
        if failed:
            parts.append(tr("Size not available for {} file(s): the server query failed. "
                            "The download can be done anyway.").format(failed))
        if not pending and not failed and not summary.complete:
            parts.append(tr("Total size not available."))
        return " ".join(parts)

    # ============================================================ tamanhos (HEAD)
    def _schedule_probe(self):
        missing = [u for u in self.plan.urls
                   if u not in self.sizes and u not in self.size_errors]
        if missing:
            self.pending_probe.update(missing)
            self.probe_timer.start()

    def _start_probe(self):
        missing = [u for u in self.plan.urls
                   if u not in self.sizes and u not in self.size_errors]
        if not missing or self.is_busy():
            return
        if self.probe_task is not None:
            self.probe_task.cancel()
        task = SizeProbeTask(missing)
        task.sizeReady.connect(self._size_ready)
        task.taskCompleted.connect(lambda t=task: self._probe_done(t))
        task.taskTerminated.connect(lambda t=task: self._probe_done(t))
        self.probe_task = task
        self.pending_probe = set(missing)
        self._fill_summary()
        QgsApplication.taskManager().addTask(task)

    def _size_ready(self, url, size, error):
        self.pending_probe.discard(url)
        if error:
            self.size_errors[url] = error
        elif size is None:
            self.size_errors[url] = tr("the server did not report the size")
        else:
            self.sizes[url] = size
        if not self.is_busy() and self.pages.currentIndex() == 0:
            self._fill_summary()

    def _probe_done(self, task):
        if task is self.probe_task:
            self.probe_task = None
            self.pending_probe = {u for u in self.pending_probe
                                  if u not in self.sizes and u not in self.size_errors}
            if self.pending_probe and not self.is_busy():
                self.pending_probe.clear()
            if not self.is_busy() and self.pages.currentIndex() == 0:
                self._fill_summary()

    def _retry_sizes(self):
        for u in self.plan.urls:
            self.size_errors.pop(u, None)
        self._schedule_probe()
        self._fill_summary()

    # ================================================================== download
    def start_download(self):
        if self.state != READY or not len(self.plan):
            return
        folder = self.folder_path()
        ok, msg = C.check_destination(folder)
        if not ok:
            self.folder_msg.setText("✖ " + msg)
            self.folder_msg.setVisible(True)
            self.folder.setFocus()
            self._set_state(INCOMPLETE, tr("Destination folder: {}").format(msg))
            return
        summary = C.SizeSummary(self.plan, self.sizes)
        if C.is_large(self.plan, summary):
            text = tr("{} files will be downloaded ({}). This may take a long time. "
                      "Do you want to continue?").format(
                        len(self.plan), C.format_bytes(summary.total)
                        if summary.total is not None else tr("total size not available"))
            if QMessageBox.question(self, tr("Large download"), text, MB_YES | MB_NO,
                                    MB_NO) != MB_YES:
                return
        self._save_settings()
        if self.probe_task is not None:
            self.probe_task.cancel()
        self.pending_probe.clear()
        self.run_items = list(self.plan.items)
        self.run_folder = folder
        self.results = [None] * len(self.run_items)
        self.loaded = set()
        self.cancel_requested = False
        self._bytes_done = 0
        self._current_bytes = 0
        self._prepare_run_page()
        self.pages.setCurrentIndex(1)
        task = DownloadTask(self.run_items, folder, self.sizes,
                            overwrite=self.overwrite_check.isChecked())
        self._connect_task(task)
        self.task = task
        self._set_state(DOWNLOADING, tr("You can keep using QGIS. The task also appears in "
                                        "the task manager (status bar)."))
        QgsApplication.taskManager().addTask(task)

    def _connect_task(self, task):
        task.fileStarted.connect(self._file_started)
        task.fileProgress.connect(self._file_progress)
        task.fileFinished.connect(self._file_finished)
        task.allFinished.connect(self._run_finished)

    def _by_bytes(self):
        return all(isinstance(self.sizes.get(i.url), int) and self.sizes[i.url] > 0
                   for i in self.run_items)

    def _prepare_run_page(self):
        t = self.run_table
        t.setRowCount(0)
        for item in self.run_items:
            r = t.rowCount()
            t.insertRow(r)
            t.setItem(r, 0, _item(item.filename))
            t.setItem(r, 1, _item(tr(C.PRODUCT_BY_CODE[item.code].label)))
            t.setItem(r, 2, _item(tr("Pending")))
            t.setItem(r, 3, _item(""))
        self.final_label.setText("")
        self.overall.setRange(0, 1000 if self._by_bytes() else max(1, len(self.run_items)))
        self.overall.setValue(0)
        self.overall.setFormat("%p%" if self._by_bytes() else tr("%v of %m files"))
        self._update_overall()
        self.file_label.setText("—")
        self.file_bar.setRange(0, 1000)
        self.file_bar.setValue(0)

    def _done_count(self):
        return sum(1 for r in self.results if r is not None)

    def _update_overall(self):
        n = len(self.run_items)
        done = self._done_count()
        if self._by_bytes():
            total = sum(self.sizes[i.url] for i in self.run_items)
            value = self._bytes_done + self._current_bytes
            self.overall.setValue(int(1000 * value / total) if total else 0)
            self.overall_label.setText(tr("{} of {} files completed — {} of {}").format(
                done, n, C.format_bytes(value), C.format_bytes(total)))
        else:
            self.overall.setValue(done)
            self.overall_label.setText(
                tr("{} of {} files processed. Progress by files: the total size is not "
                   "available.").format(done, n))

    def _file_started(self, i):
        item = self.run_items[i]
        self._current_bytes = 0
        self.run_table.item(i, 2).setText(tr("Downloading…"))
        self.run_table.scrollToItem(self.run_table.item(i, 0))
        self.file_label.setText(tr("{} — {} ({} of {})").format(
            item.filename, tr(C.PRODUCT_BY_CODE[item.code].label), i + 1, len(self.run_items)))
        self.file_bar.setValue(0)
        self.file_bar.setVisible(True)

    def _file_progress(self, i, received, total):
        item = self.run_items[i]
        self._current_bytes = received or 0
        base = tr("{} — {} ({} of {})").format(
            item.filename, tr(C.PRODUCT_BY_CODE[item.code].label), i + 1, len(self.run_items))
        if total:
            self.file_bar.setVisible(True)
            self.file_bar.setValue(int(1000 * received / total))
            self.file_bar.setFormat(tr("{} of {}").format(C.format_bytes(received),
                                                          C.format_bytes(total)))
            self.file_label.setText(base)
        else:
            self.file_bar.setVisible(False)
            self.file_label.setText(base + " — " + tr(
                "{} received; file percentage not available (the server did not report the "
                "size).").format(C.format_bytes(received)))
        self._update_overall()

    def _file_finished(self, i, result):
        self.results[i] = result
        self._current_bytes = 0
        if self._by_bytes():
            self._bytes_done += self.sizes[self.run_items[i].url]
        self.run_table.item(i, 2).setText(tr(D.STATUS_LABELS[result.status]))
        msg = self.run_table.item(i, 3)
        msg.setText(result.message)
        msg.setToolTip(result.detail or result.message)
        self._update_overall()

    def cancel_download(self):
        if self.task is not None and self.state == DOWNLOADING:
            self.cancel_requested = True
            self.task.cancel()
            self._set_state(CANCELING, tr("Files already completed are not changed; the file "
                                          "in progress is kept as partial (.part) to resume."))

    def _ok_paths(self):
        return [r.path for r in self.results if r is not None and r.ok]

    def _run_finished(self, ok):
        task, self.task = self.task, None
        error = task.error if task is not None else ""
        counts = {s: 0 for s in D.STATUS_LABELS}
        for r in self.results:
            if r is not None:
                counts[r.status] += 1
        n = len(self.run_items)
        available = counts[D.DONE] + counts[D.EXISTING]
        lines = [tr("{} of {} files available in the folder ({} downloaded, {} already "
                    "existed).").format(available, n, counts[D.DONE], counts[D.EXISTING])]
        if counts[D.FAILED]:
            lines.append(tr("{} failed — see the Message column and the technical "
                            "details.").format(counts[D.FAILED]))
        if counts[D.CANCELED]:
            lines.append(tr("{} canceled or not started.").format(counts[D.CANCELED]))
        parts = [r for r in self.results if r is not None and not r.ok
                 and os.path.exists(r.path + C.PART_SUFFIX)]
        if parts:
            lines.append(tr("{} partial file(s) (.part) kept: download again to "
                            "resume.").format(len(parts)))
        lines.append(tr("Folder: {}").format(self.run_folder))

        if not ok:
            state = PARTIAL if available else ERROR
            detail = tr("The download task was interrupted by an internal error.")
        elif available == n:
            state, detail = DONE, ""
        elif self.cancel_requested:
            state, detail = CANCELED, ""
        else:
            state, detail = PARTIAL, ""
        technical = self.report()
        if error:
            technical = error + "\n\n" + technical
        self.final_label.setText("\n".join(lines))
        self.file_label.setText("—")
        self.file_bar.setVisible(False)
        self._set_state(state, detail or lines[0], technical
                        if state != DONE or error else "")
        if self.load_check.isChecked() and available:
            self.load_results()

    def load_results(self):
        paths = [p for p in self._ok_paths() if p not in self.loaded]
        if not paths:
            return
        added, skipped, failed = add_rasters(paths, self.project)
        self.loaded.update(added)
        self.loaded.update(skipped)
        rows = {r.path: i for i, r in enumerate(self.results) if r is not None}
        for path, reason in failed:
            i = rows.get(path)
            if i is not None:
                self.run_table.item(i, 2).setText(tr(D.STATUS_LABELS[self.results[i].status]) +
                                                  " — " + tr("not loaded"))
                self.run_table.item(i, 3).setText(reason)
        text = tr("Layers loaded into QGIS: {}.").format(len(added))
        if skipped:
            text += " " + tr("Already in the project (not duplicated): {}.").format(len(skipped))
        if failed:
            text += " " + tr("Not loaded: {} (reason in the table).").format(len(failed))
        self.final_label.setText((self.final_label.text() + "\n" + text).strip())
        self.load_button.setEnabled(any(p not in self.loaded for p in self._ok_paths()))
        return added, skipped, failed

    def open_folder(self):
        if self.run_folder and os.path.isdir(self.run_folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.run_folder))

    def back_to_config(self):
        if self.is_busy():
            return
        self.pages.setCurrentIndex(0)
        self._refresh()

    def report(self):
        """Relatório técnico (texto) de todos os arquivos da execução."""
        out = []
        for item, r in zip(self.run_items, self.results):
            status = tr(D.STATUS_LABELS[r.status]) if r else tr("Pending")
            out.append("{} [{}] {}".format(item.filename, status, item.url))
            if r is not None:
                out.append("    " + r.message)
                if r.detail:
                    out.append("    " + tr("detail:") + " " + r.detail)
        return "\n".join(out)

    def _copy_details(self):
        QApplication.clipboard().setText(self.details.toPlainText())

    # =============================================================== fechamento
    def _confirm_stop(self):
        """Antes de fechar (botão, Esc ou X): durante o download, pergunta e cancela.
        Retorna False se o usuário quiser continuar com a janela aberta."""
        if self.state != DOWNLOADING or self._shutting_down:
            return True
        answer = QMessageBox.question(
            self, tr("Download in progress"),
            tr("A download is in progress. Do you want to cancel it and close the window?\n\n"
               "Files already completed are kept; the file in progress is kept as partial "
               "(.part) to resume later."), MB_YES | MB_NO, MB_NO)
        if answer != MB_YES:
            return False
        self.cancel_download()
        return True

    def closeEvent(self, event):
        if not self._confirm_stop():
            event.ignore()
            return
        if not self.is_busy():
            self._save_settings()
        super().closeEvent(event)

    def reject(self):
        # Esc chama reject() sem passar por closeEvent
        if not self._confirm_stop():
            return
        super().reject()

    def shutdown(self):
        """Descarrega o plugin: cancela tarefas e desconecta sinais."""
        self._shutting_down = True
        self.probe_timer.stop()
        for task in (self.task, self.probe_task):
            if task is None:
                continue
            for sig in ("fileStarted", "fileProgress", "fileFinished", "allFinished",
                        "sizeReady"):
                if hasattr(task, sig):
                    signal = getattr(task, sig)
                    try:
                        signal.disconnect()
                    except TypeError:           # nenhum receptor conectado
                        continue
            task.cancel()
        self.task = self.probe_task = None
