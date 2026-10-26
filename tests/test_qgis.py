"""
Testes dentro de um QGIS real, sem tela (offscreen): grade e interseção, transformação de
SRC, ferramenta de seleção, diálogo (contagem, estados, download em segundo plano,
cancelamento, falhas parciais) e carregamento de rasters. A rede real nunca é usada: a grade
sintética aponta para um servidor HTTP local.

    QT_QPA_PLATFORM=offscreen <python do QGIS> -m pytest -v tests/test_qgis.py
"""
import json
import os
import time

import pytest

from qgis_env import APP  # noqa: E402,F401  (QGIS headless com perfil isolado)
from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem,  # noqa: E402
                       QgsCoordinateTransform, QgsGeometry, QgsPointXY, QgsProject,
                       QgsRasterLayer, QgsRectangle)

from qgis.PyQt.QtCore import QEvent, QPoint, Qt, QTimer  # noqa: E402
from qgis.gui import QgsMapCanvas, QgsMapMouseEvent  # noqa: E402

from fake_server import Resource  # noqa: E402
from topodata_downloader import catalog as C  # noqa: E402
from topodata_downloader import dialog as G  # noqa: E402
from topodata_downloader import downloader as D  # noqa: E402
from topodata_downloader.grid import (DEFAULT_GRID, GridError, SelectionError,  # noqa: E402
                                      TopodataGrid, selection_to_wgs84)
from topodata_downloader.loader import add_rasters  # noqa: E402
from topodata_downloader.map_tool import RectangleTool  # noqa: E402

WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")
B = 0.000138927479856                     # meia margem das folhas reais


@pytest.fixture(scope="module")
def grid():
    return TopodataGrid(DEFAULT_GRID)


def scenes(tiles):
    return [t.scene for t in tiles]


def rect_geom(w, s, e, n):
    return QgsGeometry.fromRect(QgsRectangle(w, s, e, n))


def wait_until(cond, timeout=30):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        QgsApplication.processEvents()
        time.sleep(0.01)
    QgsApplication.processEvents()
    return cond()


def geotiff_bytes(w, n, size=8, seed=1):
    """GeoTIFF real (GDAL, EPSG:4326) de size×size pixels cobrindo 1,5° × 1°."""
    from osgeo import gdal, osr
    path = "/vsimem/t{}_{}.tif".format(seed, time.time_ns())
    ds = gdal.GetDriverByName("GTiff").Create(path, size, size, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((w, 1.5 / size, 0, n, 0, -1.0 / size))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).Fill(float(seed))
    ds = None
    f = gdal.VSIFOpenL(path, "rb")
    gdal.VSIFSeekL(f, 0, 2)
    n_bytes = gdal.VSIFTellL(f)
    gdal.VSIFSeekL(f, 0, 0)
    data = gdal.VSIFReadL(1, n_bytes, f)
    gdal.VSIFCloseL(f)
    gdal.Unlink(path)
    return bytes(data)


def synthetic_grid(path, base, cells):
    """GeoJSON no formato da grade real, com URLs no servidor local.
    cells = [(scene, oeste, norte)] folhas de 1,5° × 1° sem margem."""
    feats = []
    for scene, w, n in cells:
        url = "{}/v001/{}/{}/{}ZN.tif".format(base, scene[:3], scene[3:], scene)
        ring = [[w, n], [w + 1.5, n], [w + 1.5, n - 1], [w, n - 1], [w, n]]
        feats.append({"type": "Feature", "properties": {"scene": scene, "url": url},
                      "geometry": {"type": "Polygon", "coordinates": [ring]}})
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "name": "grade_topodata",
                   "crs": {"type": "name",
                           "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
                   "features": feats}, f)
    return path


CELLS = [("07S375", -37.5, -7), ("07S36_", -36.0, -7), ("08S375", -37.5, -8),
         ("08S36_", -36.0, -8)]


# ======================================================== grade e interseção
def test_real_grid_loads_in_wgs84(grid):
    assert len(grid) == 556 and grid.invalid == []
    ext = grid.extent()
    assert ext.xMinimum() == pytest.approx(-75.0001389, abs=1e-6)
    assert ext.yMaximum() == pytest.approx(6.0001389, abs=1e-6)


def test_rectangle_crossing_several_tiles(grid):
    found = grid.query(rect_geom(-36.4, -7.5, -35.6, -6.6))
    assert scenes(found) == ["06S36_", "06S375", "07S36_", "07S375"]


def test_rectangle_inside_one_tile(grid):
    assert scenes(grid.query(rect_geom(-35.5, -7.6, -35.2, -7.3))) == ["07S36_"]


def test_rectangle_without_tiles(grid):
    assert grid.query(rect_geom(-30.0, -20.0, -29.0, -19.0)) == []        # Atlântico
    assert grid.query(QgsGeometry()) == []


def test_bbox_alone_is_not_enough(tmp_path):
    """Seleção em L: a caixa envolvente cobre 08S36_, a geometria não."""
    g = TopodataGrid(synthetic_grid(str(tmp_path / "g.geojson"), "https://x", CELLS))
    ell = QgsGeometry.fromPolygonXY([[
        QgsPointXY(-37.4, -8.5), QgsPointXY(-37.3, -8.5), QgsPointXY(-37.3, -7.3),
        QgsPointXY(-35.5, -7.3), QgsPointXY(-35.5, -7.2), QgsPointXY(-37.4, -7.2),
        QgsPointXY(-37.4, -8.5)]])
    assert ell.boundingBox().intersects(QgsRectangle(-36.0, -9.0, -34.5, -8.0))
    assert scenes(g.query(ell)) == ["07S36_", "07S375", "08S375"]


def test_bbox_candidate_rejected_by_real_geometry(tmp_path):
    """Folha triangular: a caixa envolvente da folha cobre o retângulo, a folha não."""
    path = str(tmp_path / "tri.geojson")
    ring = [[-37.5, -7.0], [-36.0, -7.0], [-37.5, -8.0], [-37.5, -7.0]]
    with open(path, "w") as f:
        json.dump({"type": "FeatureCollection", "features": [{
            "type": "Feature",
            "properties": {"scene": "07S375", "url": "https://x/07S/375/07S375ZN.tif"},
            "geometry": {"type": "Polygon", "coordinates": [ring]}}]}, f)
    g = TopodataGrid(path)
    assert g.query(rect_geom(-36.3, -7.9, -36.1, -7.7)) == []            # canto vazio
    assert scenes(g.query(rect_geom(-37.4, -7.9, -37.2, -7.7))) == ["07S375"]


def test_touching_edge_and_corner_are_included(tmp_path):
    """Regra documentada: intersects do OGC inclui folhas apenas tocadas pela borda."""
    g = TopodataGrid(synthetic_grid(str(tmp_path / "g.geojson"), "https://x", CELLS))
    # dentro de 07S36_, borda oeste exatamente em -36 (divisa com 07S375)
    assert scenes(g.query(rect_geom(-36.0, -7.5, -35.5, -7.2))) == ["07S36_", "07S375"]
    # dentro de 08S36_, com canto em (-36, -8): 07S36_ e 08S375 tocam pela borda,
    # 07S375 só pelo vértice — todas entram
    assert scenes(g.query(rect_geom(-36.0, -8.5, -35.5, -8.0))) == \
        ["07S36_", "07S375", "08S36_", "08S375"]
    # afastado 1e-9° da divisa: não toca
    assert scenes(g.query(rect_geom(-36.0 + 1e-9, -7.5, -35.5, -7.2))) == ["07S36_"]


def test_real_grid_margin_overlap_at_sheet_boundary(grid):
    """Folhas reais têm meia margem de pixel (B): 07S375 vai até -36 + B. Um retângulo que
    começa antes disso entra nas duas folhas; um que começa depois, só em 07S36_."""
    assert scenes(grid.query(rect_geom(-36.0 + B / 2, -7.5, -35.8, -7.2))) == \
        ["07S36_", "07S375"]
    assert scenes(grid.query(rect_geom(-36.0 + 3 * B, -7.5, -35.8, -7.2))) == ["07S36_"]


def test_grid_errors(tmp_path):
    with pytest.raises(GridError):
        TopodataGrid(str(tmp_path / "nao_existe.geojson"))
    bad = tmp_path / "sem_campos.geojson"
    bad.write_text(json.dumps({"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"nome": "x"},
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}]}))
    with pytest.raises(GridError) as err:
        TopodataGrid(str(bad))
    assert "campos" in err.value.message
    junk = tmp_path / "lixo.geojson"
    junk.write_text("isto não é geojson")
    with pytest.raises(GridError):
        TopodataGrid(str(junk))


# ============================================================ transformação
@pytest.mark.parametrize("epsg", ["EPSG:3857", "EPSG:31985", "EPSG:5880"])
def test_selection_in_other_crs_is_transformed_to_wgs84(grid, epsg):
    crs = QgsCoordinateReferenceSystem(epsg)
    to_map = QgsCoordinateTransform(WGS84, crs, QgsProject.instance())
    ll = to_map.transform(QgsPointXY(-36.4, -7.5))
    ur = to_map.transform(QgsPointXY(-35.6, -6.6))
    rect = QgsRectangle(ll, ur, True)
    geom = selection_to_wgs84(rect, crs)
    assert len(geom.asPolygon()[0]) > 5                     # adensado, não só 4 cantos
    # os cantos usados para desenhar estão na seleção convertida
    for x, y in ((-36.4, -7.5), (-35.6, -6.6)):
        assert geom.buffer(1e-7, 4).contains(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
    # e a volta para o SRC do mapa reproduz o retângulo desenhado
    back = QgsGeometry(geom)
    back.transform(to_map)
    tol = max(rect.width(), rect.height()) * 1e-6
    for a, b in zip((back.boundingBox().xMinimum(), back.boundingBox().yMinimum(),
                     back.boundingBox().xMaximum(), back.boundingBox().yMaximum()),
                    (rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum())):
        assert a == pytest.approx(b, abs=tol)
    assert scenes(grid.query(geom)) == ["06S36_", "06S375", "07S36_", "07S375"]


def test_selection_in_wgs84_is_unchanged():
    geom = selection_to_wgs84(QgsRectangle(-36.4, -7.5, -35.6, -6.6), WGS84)
    assert geom.boundingBox() == QgsRectangle(-36.4, -7.5, -35.6, -6.6)


def test_invalid_selection():
    with pytest.raises(SelectionError):
        selection_to_wgs84(QgsRectangle(-36, -7, -36, -6), WGS84)       # largura zero
    with pytest.raises(SelectionError):
        selection_to_wgs84(QgsRectangle(0, 0, 1, 1), QgsCoordinateReferenceSystem())


# ======================================================= ferramenta de mapa
def _mouse(canvas, kind, x, y):
    t = getattr(QEvent, "Type", QEvent)
    btn = getattr(Qt, "MouseButton", Qt)
    buttons = btn.NoButton if kind == t.MouseButtonRelease else btn.LeftButton
    return QgsMapMouseEvent(canvas, kind, QPoint(x, y), btn.LeftButton, buttons)


def test_rectangle_tool_emits_map_rectangle():
    canvas = QgsMapCanvas()
    canvas.resize(400, 400)
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    canvas.setExtent(QgsRectangle(-4_000_000, -900_000, -3_900_000, -800_000))
    canvas.refresh()
    tool = RectangleTool(canvas)
    got, bad = [], []
    tool.selected.connect(got.append)
    tool.invalid.connect(bad.append)
    t = getattr(QEvent, "Type", QEvent)
    tool.canvasPressEvent(_mouse(canvas, t.MouseButtonPress, 50, 60))
    tool.canvasMoveEvent(_mouse(canvas, t.MouseMove, 200, 220))
    tool.canvasReleaseEvent(_mouse(canvas, t.MouseButtonRelease, 300, 320))
    assert len(got) == 1 and not bad
    r = got[0]
    a = canvas.getCoordinateTransform().toMapCoordinates(50, 60)
    b = canvas.getCoordinateTransform().toMapCoordinates(300, 320)
    assert r.xMinimum() == pytest.approx(min(a.x(), b.x()))
    assert r.yMaximum() == pytest.approx(max(a.y(), b.y()))
    # clique sem arrasto
    tool.canvasPressEvent(_mouse(canvas, t.MouseButtonPress, 50, 60))
    tool.canvasReleaseEvent(_mouse(canvas, t.MouseButtonRelease, 51, 61))
    assert len(got) == 1 and len(bad) == 1


# ===================================================================== diálogo
@pytest.fixture
def setup(tmp_path, server):
    """Grade sintética (4 folhas) apontando para o servidor local, com GeoTIFFs reais."""
    path = synthetic_grid(str(tmp_path / "grade.geojson"), server.base, CELLS)
    grid = TopodataGrid(path)
    for i, (scene, w, n) in enumerate(CELLS):
        for code in ("ZN", "SA"):
            server.add("/v001/{}/{}/{}{}.tif".format(scene[:3], scene[3:], scene, code),
                       Resource(geotiff_bytes(w, n, seed=i + 1)))
    project = QgsProject()
    dest = tmp_path / "saida"
    return grid, project, str(dest)


def make_dialog(grid, project, dest, codes=("ZN", "SA"), load=False):
    dlg = G.DownloadDialog(lambda: grid, None, project)
    dlg.folder.setFilePath(dest)
    dlg._set_checked(set(codes))
    dlg.load_check.setChecked(load)
    dlg.overwrite_check.setChecked(False)
    return dlg


def select(dlg, w, s, e, n):
    dlg.set_selection(QgsRectangle(w, s, e, n), WGS84)


def test_dialog_counts_and_sizes(setup):
    grid, project, dest = setup
    dlg = make_dialog(grid, project, dest)
    assert dlg.state in (G.WAITING, G.INCOMPLETE)
    select(dlg, -36.4, -7.5, -35.6, -7.2)                      # 07S36_ + 07S375
    assert dlg.state == G.READY
    assert len(dlg.plan) == 4 and dict(dlg.plan.by_product) == {"ZN": 2, "SA": 2}
    assert dlg.tile_count.text() == "2"
    assert "2 arquivo(s) por quadrícula" in dlg.tile_list.text()
    assert dlg.download_button.text() == "Baixar 4 arquivo(s)" and dlg.download_button.isEnabled()
    t = dlg.summary_table
    assert [t.item(r, 1).text() for r in range(t.rowCount())] == ["2", "2", "4"]
    assert wait_until(lambda: dlg.probe_task is None and len(dlg.sizes) == 4)
    assert t.item(t.rowCount() - 1, 2).text() != "não disponível"
    assert "Content-Length" in dlg.size_method.text()
    assert "Total exato" in dlg.size_method.text()
    dlg.shutdown()


def test_dialog_size_not_available(setup, server):
    grid, project, dest = setup
    for path in list(server.httpd.resources):
        if path.endswith("SA.tif"):
            del server.httpd.resources[path]                  # HEAD -> 404
    dlg = make_dialog(grid, project, dest)
    select(dlg, -36.4, -7.5, -35.6, -7.2)
    assert wait_until(lambda: dlg.probe_task is None and len(dlg.size_errors) == 2)
    t = dlg.summary_table
    assert t.item(t.rowCount() - 1, 2).text() == "não disponível"     # total
    assert t.item(1, 2).text() == "não disponível"                     # SA
    assert t.item(0, 2).text() != "não disponível"                     # ZN conhecido
    assert "pelo menos" in dlg.size_method.text()
    assert dlg.retry_sizes.isVisible() or not dlg.isVisible()
    dlg.shutdown()


def test_dialog_validation_states(setup, tmp_path):
    grid, project, dest = setup
    dlg = make_dialog(grid, project, "", codes=())
    select(dlg, -36.4, -7.5, -35.6, -7.2)
    assert dlg.state == G.INCOMPLETE
    assert "produto" in dlg.status_detail.text() and "pasta" in dlg.status_detail.text()
    assert not dlg.download_button.isEnabled()
    dlg.select_all.click()
    assert len(dlg.checked_codes()) == 16
    dlg.clear_all.click()
    assert dlg.checked_codes() == []
    dlg._set_checked({"ZN"})
    f = tmp_path / "um_arquivo.txt"
    f.write_text("x")
    dlg.folder.setFilePath(str(f))
    assert dlg.state == G.INCOMPLETE and "arquivo" in dlg.folder_msg.text()
    dlg.folder.setFilePath(dest)
    assert dlg.state == G.READY
    select(dlg, -30, -20, -29, -19)                              # sem folhas
    assert dlg.state == G.NO_TILES and not dlg.download_button.isEnabled()
    dlg.set_selection(QgsRectangle(-36, -7, -36, -6), WGS84)     # sem área
    assert dlg.state == G.ERROR
    dlg.shutdown()


def test_dialog_grid_error_is_reported():
    def broken():
        raise GridError("Não foi possível abrir a grade TOPODATA.", "detalhe técnico X")
    dlg = G.DownloadDialog(broken, None, QgsProject())
    dlg.set_selection(QgsRectangle(-36.4, -7.5, -35.6, -7.2), WGS84)
    assert dlg.state == G.ERROR
    assert "detalhe técnico X" in dlg.details.toPlainText()
    dlg.shutdown()


def test_dialog_download_load_and_responsive_ui(setup, server):
    grid, project, dest = setup
    for i, (scene, w, n) in enumerate(CELLS):                 # 256 px: ~260 kB por arquivo
        for code in ("ZN", "SA"):
            server.add("/v001/{}/{}/{}{}.tif".format(scene[:3], scene[3:], scene, code),
                       Resource(geotiff_bytes(w, n, size=256, seed=i + 1), delay=0.04))
    dlg = make_dialog(grid, project, dest, load=True)
    select(dlg, -36.4, -7.5, -35.6, -7.2)
    assert wait_until(lambda: dlg.probe_task is None and len(dlg.sizes) == 4)
    ticks = []
    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start()
    dlg.start_download()
    assert dlg.state == G.DOWNLOADING and dlg.pages.currentIndex() == 1
    assert not dlg.back_button.isEnabled() and dlg.cancel_button.isEnabled()
    assert wait_until(lambda: dlg.task is None, 60)
    timer.stop()
    # a interface continuou processando eventos durante o download
    gaps = [b - a for a, b in zip(ticks, ticks[1:])]
    assert len(ticks) > 10 and max(gaps) < 0.5
    assert dlg.state == G.DONE
    assert sorted(os.listdir(dest)) == ["07S36_SA.tif", "07S36_ZN.tif", "07S375SA.tif",
                                        "07S375ZN.tif"]
    assert all(r.status == D.DONE for r in dlg.results)
    # carregados como 4 camadas separadas, sem mosaico/recorte
    layers = list(project.mapLayers().values())
    assert len(layers) == 4 and all(isinstance(lyr, QgsRasterLayer) for lyr in layers)
    assert project.layerTreeRoot().findGroup("TOPODATA") is not None
    for lyr in layers:
        assert lyr.width() == 256 and lyr.height() == 256
        assert lyr.extent().width() == pytest.approx(1.5)
    assert "Concluído com sucesso" in dlg.status.text()
    # carregar de novo não duplica
    assert dlg.load_results() is None
    added, skipped, failed = add_rasters([r.path for r in dlg.results], project)
    assert added == [] and len(skipped) == 4 and failed == []
    # segunda execução: arquivos existentes verificados e reutilizados
    dlg.back_to_config()
    assert "já existem na pasta" in dlg.summary_text.text()
    gets_before = len([x for x in server.log if x[0] == "GET"])
    dlg.start_download()
    assert wait_until(lambda: dlg.task is None, 60)
    assert all(r.status == D.EXISTING for r in dlg.results)
    assert len([x for x in server.log if x[0] == "GET"]) == gets_before
    dlg.shutdown()


def test_dialog_partial_failure_summary(setup, server):
    grid, project, dest = setup
    dlg = make_dialog(grid, project, dest)
    select(dlg, -36.4, -7.5, -35.6, -7.2)
    assert wait_until(lambda: dlg.probe_task is None)
    server.httpd.resources["/v001/07S/375/07S375SA.tif"].status = 404
    dlg.start_download()
    assert wait_until(lambda: dlg.task is None, 60)
    assert dlg.state == G.PARTIAL
    assert "Concluído parcialmente" in dlg.status.text()
    assert "sucesso" not in dlg.status.text()
    assert "3 de 4 arquivos disponíveis" in dlg.final_label.text()
    assert "1 falharam" in dlg.final_label.text()
    failed = [r for r in dlg.results if r.status == D.FAILED]
    assert len(failed) == 1 and "404" in failed[0].message
    assert "07S375SA.tif [Falhou]" in dlg.details.toPlainText()
    assert not os.path.exists(os.path.join(dest, "07S375SA.tif"))
    dlg.shutdown()


def test_dialog_cancel(setup, server):
    grid, project, dest = setup
    dlg = make_dialog(grid, project, dest)
    select(dlg, -36.4, -7.5, -35.6, -7.2)
    assert wait_until(lambda: dlg.probe_task is None)
    big = Resource(b"II*\x00" + bytes(2_000_000), delay=0.02)
    server.httpd.resources["/v001/07S/375/07S375ZN.tif"] = big     # 2º arquivo, lento
    dlg.sizes.pop(server.base + "/v001/07S/375/07S375ZN.tif", None)
    dlg.start_download()
    assert wait_until(lambda: dlg.results[0] is not None and big.gets > 0, 30)
    assert wait_until(lambda: os.path.exists(os.path.join(dest, "07S375ZN.tif.part")), 30)
    dlg.cancel_download()
    assert dlg.state == G.CANCELING and not dlg.cancel_button.isEnabled()
    assert wait_until(lambda: dlg.task is None, 30)
    assert dlg.state == G.CANCELED
    statuses = [r.status for r in dlg.results]
    assert statuses[0] == D.DONE and statuses[1] == D.CANCELED
    assert statuses[2:] == [D.CANCELED, D.CANCELED]
    assert "Concluído" not in dlg.status.text()
    with open(os.path.join(dest, "07S36_ZN.tif"), "rb") as f:
        assert f.read()[:4] == b"II*\x00"
    assert not os.path.exists(os.path.join(dest, "07S375ZN.tif"))
    assert os.path.exists(os.path.join(dest, "07S375ZN.tif.part"))
    assert "parcial" in dlg.final_label.text()
    dlg.shutdown()


# ===================================================================== carregamento
def test_loader_reports_unreadable_and_missing(tmp_path):
    project = QgsProject()
    good = tmp_path / "07S36_ZN.tif"
    good.write_bytes(geotiff_bytes(-36.0, -7.0))
    bad = tmp_path / "07S36_SA.tif"
    bad.write_bytes(b"II*\x00 corrompido")
    added, skipped, failed = add_rasters([str(good), str(bad), str(tmp_path / "x.tif")],
                                         project)
    assert added == [str(good)]
    assert [p for p, _ in failed] == [str(bad), str(tmp_path / "x.tif")]
    assert all(reason for _, reason in failed)
    (layer,) = project.mapLayers().values()
    assert layer.name() == "07S36_ZN — Altitude"
    assert layer.source() == str(good)


def test_product_catalog_matches_dialog_list(setup):
    grid, project, dest = setup
    dlg = make_dialog(grid, project, dest)
    labels = [dlg.products.item(i).text() for i in range(dlg.products.count())]
    assert labels[0] == "Altitude  (ZN)" and len(labels) == len(C.PRODUCTS)
    dlg.shutdown()


def test_escape_during_download_asks_before_canceling(setup, server, monkeypatch):
    """Esc (reject) e fechar a janela passam pela mesma confirmação."""
    grid, project, dest = setup
    dlg = make_dialog(grid, project, dest)
    select(dlg, -36.4, -7.5, -35.6, -7.2)
    assert wait_until(lambda: dlg.probe_task is None)
    for path in list(server.httpd.resources):
        server.httpd.resources[path] = Resource(b"II*\x00" + bytes(1_000_000), delay=0.02)
    dlg.sizes.clear()
    dlg.show()
    answers = [G.MB_NO, G.MB_YES]
    asked = []

    def question(*args, **kw):
        asked.append(args[1])
        return answers.pop(0)

    monkeypatch.setattr(G.QMessageBox, "question", staticmethod(question))
    dlg.start_download()
    assert dlg.state == G.DOWNLOADING
    dlg.reject()                                                # Esc, resposta "Não"
    assert dlg.isVisible() and dlg.state == G.DOWNLOADING
    dlg.reject()                                                # Esc, resposta "Sim"
    assert not dlg.isVisible() and dlg.state == G.CANCELING
    assert asked == ["Download em andamento"] * 2
    assert wait_until(lambda: dlg.task is None, 30)
    assert dlg.state == G.CANCELED
    dlg.shutdown()
