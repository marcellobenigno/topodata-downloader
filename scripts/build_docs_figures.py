"""
Gera as figuras do site de documentação (docs/assets/img) com o próprio plugin, num QGIS
headless e com dados TOPODATA reais:

* mapas renderizados pelo QGIS a partir das visões gerais (overviews) dos COG do INPE, lidas
  remotamente com /vsicurl/ (só alguns MB, sem baixar os arquivos inteiros);
* capturas do diálogo após uma consulta real (tamanhos via HEAD) e um download real de
  produtos pequenos (Decliv. (A), Orientação — octantes, Forma de terreno).

    QT_QPA_PLATFORM=offscreen <python do QGIS> scripts/build_docs_figures.py

Precisa de internet (servidor do INPE). Usa um perfil do QGIS temporário: não lê nem grava
as configurações reais (proxy, preferências do plugin). Imagens em 2x para ficarem nítidas.
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QGIS_CUSTOM_CONFIG_PATH"] = tempfile.mkdtemp(prefix="topodata_docs_")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "docs", "assets", "img")

from qgis.PyQt.QtCore import QCoreApplication, QRectF, QSettings, QSize, Qt  # noqa: E402

QCoreApplication.setOrganizationName("TopodataDownloaderDocs")
QCoreApplication.setApplicationName("docs")
QSettings.setDefaultFormat(QSettings.IniFormat)
for _fmt in (QSettings.IniFormat, QSettings.NativeFormat):
    for _scope in (QSettings.UserScope, QSettings.SystemScope):
        QSettings.setPath(_fmt, _scope, os.environ["QGIS_CUSTOM_CONFIG_PATH"])

from qgis.core import (QgsApplication, QgsColorRampShader, QgsContrastEnhancement,  # noqa: E402
                       QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature,
                       QgsFillSymbol, QgsGeometry, QgsMapRendererParallelJob, QgsMapSettings,
                       QgsPalLayerSettings, QgsProject, QgsRasterLayer, QgsRasterShader,
                       QgsRectangle, QgsSingleBandGrayRenderer,
                       QgsSingleBandPseudoColorRenderer, QgsSingleSymbolRenderer,
                       QgsTextBufferSettings, QgsTextFormat, QgsVectorLayer,
                       QgsVectorLayerSimpleLabeling, Qgis)
from qgis.PyQt.QtGui import QColor, QFont, QImage, QPainter, QPainterPath  # noqa: E402

APP = QgsApplication([], True)
APP.initQgis()

from topodata_downloader import catalog as C  # noqa: E402
from topodata_downloader.grid import DEFAULT_GRID, TopodataGrid  # noqa: E402
from topodata_downloader.styles import apply_class_style  # noqa: E402

WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")
POLYCONIC = QgsCoordinateReferenceSystem("EPSG:5880")       # SIRGAS 2000 / Brazil Polyconic
WORLD = os.path.join(QgsApplication.pkgDataPath(), "resources", "data", "world_map.gpkg")
OCEAN = QColor("#cfe2ea")
ORANGE = "#e8590c"
GRID = TopodataGrid(DEFAULT_GRID)
ZOOM = 2
# Paraíba: do litoral (João Pessoa) ao planalto da Borborema (Campina Grande)
HERO_EXTENT = QgsRectangle(-37.05, -7.95, -34.65, -6.15)
SELECTION = QgsRectangle(-36.40, -7.50, -35.60, -6.60)        # cruza 4 folhas
DOWNLOAD_SELECTION = QgsRectangle(-36.30, -7.55, -35.70, -7.15)  # 07S375 + 07S36_
PRODUCTS_EXTENT = QgsRectangle(-36.00, -7.48, -35.40, -7.08)
HYPSO = [(0, "#2f7d5b"), (60, "#5a9f62"), (150, "#9cc47a"), (300, "#e3dc94"),
         (450, "#e6b56b"), (600, "#c98146"), (800, "#9b5b3a"), (1000, "#f2ece2")]


# ------------------------------------------------------------------ camadas
def remote(scene, code):
    url = C.product_url([t.url for t in GRID.tiles.values() if t.scene == scene][0], scene,
                        code)
    layer = QgsRasterLayer("/vsicurl/" + url, "{}{}".format(scene, code), "gdal")
    if not layer.isValid():
        raise RuntimeError("não abriu " + url)
    return layer


def stats(layer, extent=None):
    return layer.dataProvider().bandStatistics(
        1, Qgis.RasterBandStatistic.All, extent or layer.extent(), 250000)


def pseudocolor(layer, stops):
    fn = QgsColorRampShader(stops[0][0], stops[-1][0])
    fn.setColorRampType(QgsColorRampShader.Interpolated)
    fn.setColorRampItemList([QgsColorRampShader.ColorRampItem(v, QColor(c), str(v))
                             for v, c in stops])
    fn.setClip(False)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(fn)
    r = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
    r.setClassificationMin(stops[0][0])
    r.setClassificationMax(stops[-1][0])
    layer.setRenderer(r)
    return layer


def gray(layer, extent=None, multiply=False, opacity=1.0):
    s = stats(layer, extent)
    r = QgsSingleBandGrayRenderer(layer.dataProvider(), 1)
    ce = QgsContrastEnhancement(layer.dataProvider().dataType(1))
    ce.setContrastEnhancementAlgorithm(QgsContrastEnhancement.StretchToMinimumMaximum)
    ce.setMinimumValue(s.mean - 2.5 * s.stdDev)
    ce.setMaximumValue(s.mean + 2.5 * s.stdDev)
    r.setContrastEnhancement(ce)
    layer.setRenderer(r)
    if multiply:
        layer.setBlendMode(QPainter.CompositionMode_Multiply)
    layer.setOpacity(opacity)
    return layer


def diverging(layer, extent, low, mid, high):
    s = stats(layer, extent)
    m = 2 * s.stdDev
    return pseudocolor(layer, [(-m, low), (0, mid), (m, high)])


def vector(source, name, style, subset=None):
    layer = QgsVectorLayer(source, name, "ogr")
    if subset:
        layer.setSubsetString(subset)
    layer.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(style)))
    return layer


def grid_layer(style, scenes=None, labels=False, size=9):
    subset = None
    if scenes is not None:
        subset = '"scene" IN ({})'.format(", ".join("'{}'".format(s) for s in scenes))
    layer = vector(DEFAULT_GRID, "grade", style, subset)
    if labels:
        label(layer, "scene", size)
    return layer


def label(layer, field, size=9, color="#1f2328", buffer="#ffffff"):
    pal = QgsPalLayerSettings()
    pal.fieldName = field
    pal.placement = Qgis.LabelPlacement.OverPoint
    fmt = QgsTextFormat()
    font = QFont()
    font.setBold(True)
    fmt.setFont(font)
    fmt.setSize(size)
    fmt.setColor(QColor(color))
    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(1.2)
    buf.setColor(QColor(buffer))
    fmt.setBuffer(buf)
    pal.setFormat(fmt)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(pal))
    layer.setLabelsEnabled(True)


def rect_layer(rect, style):
    layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "selecao", "memory")
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromRect(rect))
    layer.dataProvider().addFeatures([f])
    layer.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(style)))
    return layer


SELECTION_STYLE = {"color": "255,140,0,45", "outline_color": ORANGE, "outline_width": "0.9",
                   "outline_style": "dash"}


def states(style=None):
    return vector(WORLD + "|layername=states_provinces", "estados", style or {
        "color": "#f3eee4", "outline_color": "#b9ad99", "outline_width": "0.2"},
        "\"iso_a2\" = 'BR'")


def countries():
    return vector(WORLD + "|layername=countries", "países", {
        "color": "#e6e3dc", "outline_color": "#c7c1b5", "outline_width": "0.2"})


# ------------------------------------------------------------------ desenho
def render(layers, extent, size, crs=WGS84, bg=OCEAN, chip=None):
    """layers: de cima para baixo; extent em EPSG:4326."""
    ms = QgsMapSettings()
    ms.setLayers(layers)
    ms.setDestinationCrs(crs)
    ext = extent
    if crs != WGS84:
        ext = QgsCoordinateTransform(WGS84, crs, QgsProject.instance()).transformBoundingBox(
            extent)
    ms.setExtent(ext)
    ms.setOutputSize(QSize(size[0] * ZOOM, size[1] * ZOOM))
    ms.setOutputDpi(110 * ZOOM)
    ms.setBackgroundColor(bg)
    ms.setFlag(Qgis.MapSettingsFlag.Antialiasing, True)
    job = QgsMapRendererParallelJob(ms)
    job.start()
    job.waitForFinished()
    img = job.renderedImage()
    if chip:
        _chip(img, chip)
    return img


def _font(px, bold=False):
    f = QFont()
    f.setPixelSize(px * ZOOM)
    f.setBold(bold)
    return f


def _chip(img, text, x=16, y=16, fill=QColor(255, 255, 255, 230), ink="#2b2f36"):
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setFont(_font(15, True))
    w = p.fontMetrics().horizontalAdvance(text) + 28 * ZOOM
    rect = QRectF(x * ZOOM, y * ZOOM, w, 32 * ZOOM)
    path = QPainterPath()
    path.addRoundedRect(rect, 16 * ZOOM, 16 * ZOOM)
    p.fillPath(path, fill)
    p.setPen(QColor(ink))
    p.drawText(rect, int(Qt.AlignCenter), text)
    p.end()


def save(img, name):
    """Mapas e capturas com relevo em JPEG (bem menores); o resto em PNG."""
    path = os.path.join(OUT, name)
    if name.endswith(".jpg"):
        img.save(path, "JPG", 86)
    else:
        img.save(path)
    print("gerado", os.path.relpath(path, ROOT), img.width(), "x", img.height())


def side_by_side(images, gap=12, bg="#ffffff"):
    w = sum(i.width() for i in images) + gap * ZOOM * (len(images) - 1)
    h = max(i.height() for i in images)
    out = QImage(w, h, QImage.Format_ARGB32)
    out.fill(QColor(bg))
    p = QPainter(out)
    x = 0
    for img in images:
        p.drawImage(x, 0, img)
        x += img.width() + gap * ZOOM
    p.end()
    return out


def tiles_in(rect):
    return [t.scene for t in GRID.query(QgsGeometry.fromRect(rect))]


# ------------------------------------------------------------------ figuras
def relief_layers(rect, opacity=0.6):
    layers = []
    for scene in tiles_in(rect):
        layers.append(gray(remote(scene, "RS"), multiply=True, opacity=opacity))
    for scene in tiles_in(rect):
        layers.append(pseudocolor(remote(scene, "ZN"), HYPSO))
    return layers


def hero():
    relief = relief_layers(HERO_EXTENT)
    sel = tiles_in(SELECTION)
    layers = ([rect_layer(SELECTION, SELECTION_STYLE),
               grid_layer({"color": "255,140,0,0", "outline_color": ORANGE,
                           "outline_width": "0.7"}, sel, labels=True, size=10),
               grid_layer({"color": "0,0,0,0", "outline_color": "#ffffff",
                           "outline_width": "0.35", "outline_style": "dot"})]
              + relief + [states({"color": "#eae6dc", "outline_color": "#b9ad99",
                                  "outline_width": "0.2"})])
    save(render(layers, HERO_EXTENT, (600, 450), chip="Paraíba · altitude + relevo sombreado"),
         "hero.jpg")


def brasil():
    full = QgsRectangle(-75.5, -34.5, -33.5, 6.5)
    sel = tiles_in(SELECTION)
    left = render([rect_layer(QgsRectangle(-38.2, -8.6, -34.3, -5.4),
                              {"color": "0,0,0,0", "outline_color": ORANGE,
                               "outline_width": "0.8"}),
                   grid_layer({"color": "255,140,0,200", "outline_color": ORANGE,
                               "outline_width": "0.2"}, sel),
                   grid_layer({"color": "26,150,65,40", "outline_color": "#3d7a55",
                               "outline_width": "0.12"}),
                   states(), countries()], full, (520, 560), POLYCONIC,
                  chip="Grade: 556 folhas de 1° × 1,5°")
    zoom_ext = QgsRectangle(-38.2, -8.6, -34.3, -5.4)
    right = render([rect_layer(SELECTION, SELECTION_STYLE),
                    grid_layer({"color": "255,140,0,110", "outline_color": ORANGE,
                                "outline_width": "0.5"}, sel),
                    grid_layer({"color": "0,0,0,0", "outline_color": "#3d7a55",
                                "outline_width": "0.3"}, labels=True, size=9),
                    states(), countries()], zoom_ext, (520, 560), POLYCONIC,
                   chip="{} folhas intersectam a seleção".format(len(sel)))
    save(side_by_side([left, right]), "brasil_grade.png")


def produtos():
    """Os 16 produtos da folha 07S36_ (recorte entre Itabaiana e Campina Grande)."""
    ext = PRODUCTS_EXTENT
    cell = (300, 200)
    imgs = []
    for p in C.PRODUCTS:
        layer = remote("07S36_", p.code)
        extra = []
        if p.code == "ZN":
            pseudocolor(layer, HYPSO)
            extra = [gray(remote("07S36_", "RS"), ext, multiply=True, opacity=0.55)]
        elif p.code == "SN":
            pseudocolor(layer, [(0, "#fff7d6"), (8, "#fdd36a"), (20, "#f08a3c"),
                                (45, "#c2362b"), (75, "#5b1a3a")])
        elif p.code == "VN":
            diverging(layer, ext, "#2166ac", "#f7f7f7", "#b35806")
        elif p.code == "HN":
            diverging(layer, ext, "#1b7837", "#f7f7f7", "#762a83")
        elif p.code == "ON":
            pseudocolor(layer, [(0, "#d7301f"), (90, "#fdd835"), (180, "#2e9e5b"),
                                (270, "#3a6fb0"), (360, "#d7301f")])
        elif p.code == "RS":
            gray(layer, ext)
        else:
            apply_class_style(layer, p.code)       # o mesmo estilo que o plugin aplica
        img = render(extra + [layer], ext, cell, bg=QColor("#ffffff"))
        imgs.append((p, img))
    cols, gap, bar = 4, 10 * ZOOM, 34 * ZOOM
    cw, ch = imgs[0][1].width(), imgs[0][1].height()
    rows = (len(imgs) + cols - 1) // cols
    out = QImage(cols * cw + (cols - 1) * gap, rows * (ch + bar) + (rows - 1) * gap,
                 QImage.Format_ARGB32)
    out.fill(QColor("#ffffff"))
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    for i, (prod, img) in enumerate(imgs):
        x, y = (i % cols) * (cw + gap), (i // cols) * (ch + bar + gap)
        p.drawImage(x, y, img)
        p.fillRect(x, y + ch, cw, bar, QColor("#1f2328"))
        p.setPen(QColor("#ffffff"))
        p.setFont(_font(13, True))
        p.drawText(QRectF(x + 10 * ZOOM, y + ch, cw - 60 * ZOOM, bar),
                   int(Qt.AlignVCenter | Qt.AlignLeft), prod.label)
        p.setPen(QColor("#ffb347"))
        p.setFont(_font(12, True))
        p.drawText(QRectF(x, y + ch, cw - 10 * ZOOM, bar),
                   int(Qt.AlignVCenter | Qt.AlignRight), prod.code)
    p.end()
    save(out, "produtos.jpg")


# ------------------------------------------------------------- capturas
def _grab(widget):
    img = QImage(widget.width() * ZOOM, widget.height() * ZOOM, QImage.Format_ARGB32)
    img.fill(QColor("#ececee"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.scale(ZOOM, ZOOM)
    widget.render(p)
    p.end()
    return img


def _window(map_img, dialog_img, title):
    """Janela do QGIS com o mapa e o diálogo flutuante à direita, com sombra."""
    bar = 34 * ZOOM
    w = map_img.width()
    h = bar + map_img.height()
    out = QImage(w, h, QImage.Format_ARGB32)
    out.fill(QColor("#f3f3f4"))
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.fillRect(0, 0, w, bar, QColor("#dedee2"))
    for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        p.setBrush(QColor(c))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF((14 + 20 * i) * ZOOM, 11 * ZOOM, 12 * ZOOM, 12 * ZOOM))
    p.setFont(_font(13))
    p.setPen(QColor("#4a4f57"))
    p.drawText(QRectF(0, 0, w, bar), int(Qt.AlignCenter), "QGIS — TOPODATA Downloader")
    p.drawImage(0, bar, map_img)
    # diálogo: barra de título + conteúdo, com sombra
    tb = 28 * ZOOM
    dx = w - dialog_img.width() - 24 * ZOOM
    dy = bar + 22 * ZOOM
    for k in range(12, 0, -1):
        p.setBrush(QColor(0, 0, 0, 7))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(dx - k * ZOOM, dy - k * ZOOM + 6 * ZOOM,
                                 dialog_img.width() + 2 * k * ZOOM,
                                 dialog_img.height() + tb + 2 * k * ZOOM), 10 * ZOOM, 10 * ZOOM)
    p.fillRect(QRectF(dx, dy, dialog_img.width(), tb), QColor("#e4e4e7"))
    p.setFont(_font(12, True))
    p.setPen(QColor("#2b2f36"))
    p.drawText(QRectF(dx, dy, dialog_img.width(), tb), int(Qt.AlignCenter), title)
    p.drawImage(int(dx), int(dy + tb), dialog_img)
    p.end()
    return out


FREE = 560                                   # px livres à esquerda do diálogo


def _map_beside(shot, sel, top_layers, pad=1.8):
    """Mapa do tamanho da janela, com ``sel`` centralizada na área livre à esquerda."""
    w, h = shot.width() // ZOOM + FREE, shot.height() // ZOOM + 70
    dpp = max(sel.width() * pad / FREE, sel.height() * pad / (h * 0.75))
    cx, cy = sel.center().x(), sel.center().y()
    x0 = cx - dpp * FREE / 2
    ext = QgsRectangle(x0, cy - dpp * h / 2, x0 + dpp * w, cy + dpp * h / 2)
    return render(top_layers + relief_layers(ext, 0.55) + [states()], ext, (w, h))


def _wait(cond, timeout=600):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        QgsApplication.processEvents()
        time.sleep(0.05)
    QgsApplication.processEvents()
    if not cond():
        raise RuntimeError("tempo esgotado")


def dialogs(folder):
    from topodata_downloader import dialog as G
    project = QgsProject.instance()
    dlg = G.DownloadDialog(lambda: GRID, None, project)
    dlg.folder.setFilePath(folder)
    dlg.load_check.setChecked(True)

    # 1. configuração: 4 folhas, 3 produtos, tamanhos reais via HEAD
    dlg._set_checked({"ZN", "SA", "OC"})
    dlg.set_selection(SELECTION, WGS84)
    _wait(lambda: dlg.probe_task is None and not dlg.pending_probe
          and len([u for u in dlg.plan.urls if u in dlg.sizes]) == len(dlg.plan))
    from qgis.PyQt.QtWidgets import QScrollArea
    dlg.show()
    QgsApplication.processEvents()
    inner = dlg.findChild(QScrollArea).widget()
    dlg.resize(700, inner.sizeHint().height() + 80)        # tudo visível, sem rolagem
    QgsApplication.processEvents()
    _tidy(dlg)
    shot = _grab(dlg)
    base = _map_beside(shot, SELECTION, [
        rect_layer(SELECTION, SELECTION_STYLE),
        grid_layer({"color": "0,0,0,0", "outline_color": "#ffffff", "outline_width": "0.35"},
                   labels=True, size=8)])
    save(_window(base, shot, dlg.windowTitle()), "dialogo_configuracao.jpg")

    # 2. execução: download real de produtos pequenos para 2 folhas
    dlg._set_checked({"SA", "OC", "FT"})
    dlg.set_selection(DOWNLOAD_SELECTION, WGS84)
    _wait(lambda: dlg.probe_task is None and not dlg.pending_probe)
    dlg.start_download()
    _wait(lambda: dlg.task is None)
    print("execução:", dlg.status.text(), [r.status for r in dlg.results])
    dlg.resize(700, 720)
    QgsApplication.processEvents()
    _tidy(dlg, folder)
    shot = _grab(dlg)
    layers = [lyr for lyr in project.mapLayers().values()
              if isinstance(lyr, QgsRasterLayer) and lyr.name().split(" ")[0].endswith("SA")]
    base = _map_beside(shot, DOWNLOAD_SELECTION, [
        rect_layer(DOWNLOAD_SELECTION, SELECTION_STYLE),
        grid_layer({"color": "0,0,0,0", "outline_color": "#1f2328", "outline_width": "0.35"},
                   labels=True, size=8)] + layers, pad=2.6)
    save(_window(base, shot, dlg.windowTitle()), "dialogo_execucao.jpg")
    camadas(project)
    dlg.shutdown()


TIDY = "/Users/voce/TOPODATA/paraiba"


def _tidy(dlg, folder=None):
    """Caminho curto e genérico no lugar da pasta temporária (só na imagem)."""
    edit = dlg.folder.lineEdit()
    edit.blockSignals(True)
    edit.setText(TIDY)
    edit.blockSignals(False)
    if folder:
        dlg.final_label.setText(dlg.final_label.text().replace(folder, TIDY))


def camadas(project):
    """Camadas carregadas separadas (sem mosaico) + o painel de camadas real do QGIS."""
    from qgis.core import QgsLayerTreeModel
    from qgis.gui import QgsLayerTreeView
    for node in project.layerTreeRoot().findLayers():
        node.setExpanded(False)                  # só as camadas, sem a legenda das classes
    view = QgsLayerTreeView()
    model = QgsLayerTreeModel(project.layerTreeRoot())
    view.setModel(model)
    view.resize(330, 250)
    tree = _grab(view)
    rasters = [lyr for lyr in project.mapLayers().values() if isinstance(lyr, QgsRasterLayer)]
    order = {"OC": 0, "FT": 1, "SA": 2}
    imgs = []
    for code in ("SA", "OC", "FT"):
        layers = [lyr for lyr in rasters if lyr.name().split(" ")[0].endswith(code)]
        ext = QgsRectangle(-37.62, -8.08, -34.38, -6.92)
        img = render([grid_layer({"color": "0,0,0,0", "outline_color": "#1f2328",
                                  "outline_width": "0.4"},
                                 [t for t in tiles_in(DOWNLOAD_SELECTION)], labels=True,
                                 size=8)] + layers + [states()], ext, (420, 170),
                     chip=C.PRODUCT_BY_CODE[code].label)
        imgs.append((order[code], img))
    imgs = [img for _, img in sorted(imgs, key=lambda t: t[0])]
    h = sum(i.height() for i in imgs) + 8 * ZOOM * (len(imgs) - 1)
    stack = QImage(imgs[0].width(), h, QImage.Format_ARGB32)
    stack.fill(QColor("#ffffff"))
    p = QPainter(stack)
    y = 0
    for img in imgs:
        p.drawImage(0, y, img)
        y += img.height() + 8 * ZOOM
    p.end()
    panel = QImage(tree.width(), stack.height(), QImage.Format_ARGB32)
    panel.fill(QColor("#ffffff"))
    p = QPainter(panel)
    p.fillRect(0, 0, panel.width(), 30 * ZOOM, QColor("#e4e4e7"))
    p.setFont(_font(13, True))
    p.setPen(QColor("#2b2f36"))
    p.drawText(QRectF(12 * ZOOM, 0, panel.width(), 30 * ZOOM),
               int(Qt.AlignVCenter | Qt.AlignLeft), "Camadas")
    p.drawImage(0, 30 * ZOOM, tree)
    p.end()
    save(side_by_side([panel, stack], gap=8), "camadas.jpg")


def main():
    os.makedirs(OUT, exist_ok=True)
    hero()
    brasil()
    produtos()
    folder = tempfile.mkdtemp(prefix="topodata_docs_download_")
    dialogs(folder)


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)
