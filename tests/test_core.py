"""
Testes sem QGIS: catálogo (URLs, contagem, estimativa), validação da pasta e cliente de
download contra um servidor HTTP local (nenhum acesso à rede real).

    python -m pytest -v tests/test_core.py
"""
import json
import os
import stat
import sys
import threading

import pytest

from fake_server import Resource, tiff_bytes, write
from topodata_downloader import catalog as C
from topodata_downloader import downloader as D
from topodata_downloader import translation

GRID = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "topodata_downloader", "data", "grade_topodata.geojson")
BASE = "https://data.inpe.br/bdc/data/topodata/v001"


def tile(scene):
    return C.Tile(scene, "{}/{}/{}/{}ZN.tif".format(BASE, scene[:3], scene[3:], scene))


def fast(**kw):
    kw.setdefault("backoff", (0,))
    kw.setdefault("timeout", 5)
    kw.setdefault("chunk_size", 32 * 1024)
    return D.Downloader(**kw)


# ----------------------------------------------------------------- catálogo
def test_products_match_inpe_selector():
    """16 produtos, mesmos códigos e ordem do seletor da página do INPE."""
    assert [p.code for p in C.PRODUCTS] == [
        "ZN", "SN", "SA", "SB", "SC", "VN", "V3", "V5", "HN", "H3", "H5", "ON", "OC", "FT",
        "RS", "DD"]
    assert [p.label for p in C.PRODUCTS][:3] == ["Elevation", "Slope", "Slope (A)"]
    assert C.PRODUCT_BY_CODE["DD"].label == "Ridges and drainage lines"


def test_product_url_follows_inpe_examples():
    # exemplos de inspecao_html.md
    assert C.product_url(tile("06S42_").url, "06S42_", "SN") == \
        BASE + "/06S/42_/06S42_SN.tif"
    assert C.product_url(tile("07S405").url, "07S405", "DD") == \
        BASE + "/07S/405/07S405DD.tif"
    assert C.product_url(tile("07S36_").url, "07S36_", "ZN") == \
        BASE + "/07S/36_/07S36_ZN.tif"


def test_product_url_rejects_unknown_pattern():
    with pytest.raises(C.CatalogError):
        C.product_url(BASE + "/07S/36_/outro_nome.tif", "07S36_", "SN")
    with pytest.raises(C.CatalogError):
        C.product_url(tile("07S36_").url, "07S36_", "XX")


def test_every_grid_feature_has_a_resolvable_url():
    with open(GRID, encoding="utf-8") as f:
        feats = json.load(f)["features"]
    assert len(feats) == 556
    tiles = [C.Tile(ft["properties"]["scene"], ft["properties"]["url"]) for ft in feats]
    plan = C.Plan(tiles, [p.code for p in C.PRODUCTS])
    assert plan.rejected == []
    assert len(plan) == 556 * 16


def test_plan_counts_per_product_tile_and_total():
    tiles = [tile("07S36_"), tile("07S375"), tile("08S36_")]
    plan = C.Plan(tiles, ["SN", "ZN"])
    assert len(plan) == 6
    assert list(plan.by_product.items()) == [("ZN", 3), ("SN", 3)]   # ordem do catálogo
    assert dict(plan.by_tile) == {"07S36_": 2, "07S375": 2, "08S36_": 2}
    assert plan.items[0].filename == "07S36_ZN.tif"


def test_plan_has_no_duplicates():
    tiles = [tile("07S36_"), tile("07S36_"), tile("07S375")]
    plan = C.Plan(tiles, ["ZN", "ZN", "SA"])
    assert len(plan) == 4
    assert len(set(plan.urls)) == 4
    assert plan.tiles == ["07S36_", "07S375"]


def test_plan_reports_tiles_with_unknown_url():
    bad = C.Tile("07S375", BASE + "/07S/405/07S405ZN.tif")      # URL de outra folha
    plan = C.Plan([tile("07S36_"), bad], ["ZN"])
    assert len(plan) == 1
    assert plan.rejected and plan.rejected[0][0] == "07S375"


def test_plan_empty():
    assert len(C.Plan([], ["ZN"])) == 0
    assert len(C.Plan([tile("07S36_")], [])) == 0


def test_size_summary_complete():
    plan = C.Plan([tile("07S36_"), tile("07S375")], ["ZN", "SA"])
    sizes = {u: 1000 for u in plan.urls}
    s = C.SizeSummary(plan, sizes)
    assert s.complete and s.total == 4000
    assert s.product_total("ZN") == 2000


def test_size_summary_without_metadata_is_not_invented():
    plan = C.Plan([tile("07S36_"), tile("07S375")], ["ZN", "SA"])
    s = C.SizeSummary(plan, {})
    assert s.total is None and s.product_total("ZN") is None
    assert C.format_bytes(s.total) == "not available"
    partial = C.SizeSummary(plan, {plan.urls[0]: 500})
    assert partial.total is None and partial.known_total == 500 and partial.known_count == 1
    assert partial.product_total("ZN") is None


def test_format_bytes_and_degrees():
    assert C.format_bytes(0) == "0 bytes"
    assert C.format_bytes(80775987) == "80.8 MB"
    assert C.format_bytes(2_500_000_000) == "2.5 GB"
    assert C.format_degrees(-35.123456) == "-35.12346°"


def test_decimal_comma_follows_the_translation():
    translation.set_language("pt_BR")
    try:
        assert C.format_bytes(80775987) == "80,8 MB"
        assert C.format_degrees(-35.123456) == "-35,12346°"
    finally:
        translation.set_language("")
    assert C.format_bytes(80775987) == "80.8 MB"


def test_large_download_warning():
    many = C.Plan([tile("07S36_"), tile("07S375"), tile("08S36_")],
                  [p.code for p in C.PRODUCTS])
    assert C.is_large(many)
    small = C.Plan([tile("07S36_")], ["ZN"])
    assert not C.is_large(small)
    assert C.is_large(small, C.SizeSummary(small, {small.urls[0]: 6 * 10 ** 9}))


# -------------------------------------------------------------- destino
def test_destination_empty_relative_or_file(tmp_path):
    assert C.check_destination("")[0] is False
    assert C.check_destination("   ")[0] is False
    assert C.check_destination("relativa/pasta")[0] is False
    f = tmp_path / "arquivo.txt"
    f.write_text("x")
    ok, msg = C.check_destination(str(f))
    assert not ok and "file" in msg


def test_destination_is_created(tmp_path):
    target = tmp_path / "nova" / "sub"
    assert C.check_destination(str(target)) == (True, "")
    assert target.is_dir()
    assert os.listdir(str(target)) == []                    # arquivo de teste removido


@pytest.mark.skipif(sys.platform.startswith("win") or os.geteuid() == 0,
                    reason="permissões POSIX; root ignora")
def test_destination_without_write_permission(tmp_path):
    ro = tmp_path / "somente_leitura"
    ro.mkdir()
    ro.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        ok, msg = C.check_destination(str(ro))
        assert not ok and "permission" in msg
        ok, msg = C.check_destination(str(ro / "filha"))
        assert not ok
    finally:
        ro.chmod(stat.S_IRWXU)


# ------------------------------------------------------------- download
def test_download_ok_validates_before_rename(server, tmp_path):
    data = tiff_bytes(200_000)
    url = server.add("/v001/07S/36_/07S36_ZN.tif", Resource(data))
    dest = str(tmp_path / "07S36_ZN.tif")
    seen = []

    def progress(received, total):
        # durante a transferência o nome final ainda não existe
        seen.append((received, total, os.path.exists(dest), os.path.exists(dest + ".part")))

    r = fast().download(url, dest, on_progress=progress)
    assert r.status == D.DONE and r.ok and r.size == len(data)
    with open(dest, "rb") as f:
        assert f.read() == data
    assert not os.path.exists(dest + ".part") and not os.path.exists(dest + ".part.json")
    assert all(not final for (_, _, final, _) in seen)
    assert any(part for (_, _, _, part) in seen)
    assert seen[-1][0] == seen[-1][1] == len(data)


def test_download_not_a_tiff_is_discarded(server, tmp_path):
    url = server.add("/x/html.tif", Resource(b"<html>manutencao</html>"))
    dest = str(tmp_path / "html.tif")
    r = fast().download(url, dest)
    assert r.status == D.FAILED and "GeoTIFF" in r.message
    assert not os.path.exists(dest) and not os.path.exists(dest + ".part")


def test_http_404_is_not_retried(server, tmp_path):
    url = server.add("/x/a.tif", Resource(b"", status=404))
    r = fast(max_attempts=4).download(url, str(tmp_path / "a.tif"))
    assert r.status == D.FAILED and "404" in r.message and r.attempts == 1
    assert len(server.gets("/x/a.tif")) == 1


def test_temporary_failure_is_retried_then_succeeds(server, tmp_path):
    data = tiff_bytes(50_000)
    url = server.add("/x/b.tif", Resource(data, fail_first=2, fail_status=503))
    waits = []
    r = fast(max_attempts=4, backoff=(0.01, 0.02), sleep=lambda s: waits.append(s)).download(
        url, str(tmp_path / "b.tif"))
    assert r.status == D.DONE and r.attempts == 3
    assert waits                                               # houve espera entre tentativas


def test_retries_are_limited(server, tmp_path):
    url = server.add("/x/c.tif", Resource(tiff_bytes(10_000), fail_first=99, fail_status=500))
    dest = str(tmp_path / "c.tif")
    r = fast(max_attempts=3).download(url, dest)
    assert r.status == D.FAILED and r.attempts == 3 and "3 attempts" in r.message
    assert len(server.gets("/x/c.tif")) == 3
    assert not os.path.exists(dest)


def test_connection_drop_resumes_with_validated_range(server, tmp_path):
    data = tiff_bytes(300_000)
    url = server.add("/x/d.tif", Resource(data, drop_first=1, drop_after=120_000))
    dest = str(tmp_path / "d.tif")
    r = fast(max_attempts=3).download(url, dest)
    assert r.status == D.DONE and r.resumed and r.attempts == 2
    gets = server.gets("/x/d.tif")
    assert "Range" not in gets[0]
    assert gets[1]["Range"] == "bytes=120000-" and gets[1]["If-Range"] == '"v1"'
    with open(dest, "rb") as f:
        assert f.read() == data


def test_existing_partial_is_resumed_on_restart(server, tmp_path):
    data = tiff_bytes(100_000)
    url = server.add("/x/e.tif", Resource(data, etag='"abc"'))
    dest = str(tmp_path / "e.tif")
    write(dest + ".part", data[:40_000])
    with open(dest + ".part.json", "w") as f:
        json.dump({"url": url, "validator": '"abc"', "total": len(data)}, f)
    r = fast().download(url, dest)
    assert r.status == D.DONE and r.resumed
    assert server.gets("/x/e.tif")[0]["Range"] == "bytes=40000-"
    with open(dest, "rb") as f:
        assert f.read() == data


def test_partial_of_changed_file_restarts_from_zero(server, tmp_path):
    """ETag mudou no servidor: If-Range falha, o servidor manda 200 completo e o parcial
    antigo não é concatenado."""
    data = tiff_bytes(100_000, seed=7)
    url = server.add("/x/f.tif", Resource(data, etag='"novo"'))
    dest = str(tmp_path / "f.tif")
    write(dest + ".part", tiff_bytes(100_000, seed=1)[:30_000])
    with open(dest + ".part.json", "w") as f:
        json.dump({"url": url, "validator": '"antigo"', "total": len(data)}, f)
    r = fast().download(url, dest)
    assert r.status == D.DONE and not r.resumed
    with open(dest, "rb") as f:
        assert f.read() == data


def test_partial_without_validator_is_discarded(server, tmp_path):
    data = tiff_bytes(60_000)
    url = server.add("/x/g.tif", Resource(data))
    dest = str(tmp_path / "g.tif")
    write(dest + ".part", b"lixo de uma execucao antiga")
    r = fast().download(url, dest)
    assert r.status == D.DONE and not r.resumed
    assert "Range" not in server.gets("/x/g.tif")[0]
    with open(dest, "rb") as f:
        assert f.read() == data


def test_inconsistent_content_range_is_not_concatenated(server, tmp_path):
    data = tiff_bytes(100_000)
    url = server.add("/x/h.tif", Resource(data, bad_range=True))
    dest = str(tmp_path / "h.tif")
    write(dest + ".part", data[:50_000])
    with open(dest + ".part.json", "w") as f:
        json.dump({"url": url, "validator": '"v1"', "total": len(data)}, f)
    r = fast(max_attempts=3).download(url, dest)
    assert r.status == D.DONE and not r.resumed
    gets = server.gets("/x/h.tif")
    assert gets[0]["Range"] == "bytes=50000-" and "Range" not in gets[1]
    with open(dest, "rb") as f:
        assert f.read() == data


def test_server_without_range_support_restarts_safely(server, tmp_path):
    data = tiff_bytes(100_000)
    url = server.add("/x/i.tif", Resource(data, ranges=False))
    dest = str(tmp_path / "i.tif")
    write(dest + ".part", data[:50_000])
    with open(dest + ".part.json", "w") as f:
        json.dump({"url": url, "validator": '"v1"', "total": len(data)}, f)
    r = fast().download(url, dest)
    assert r.status == D.DONE and not r.resumed
    with open(dest, "rb") as f:
        assert f.read() == data


def test_cancel_keeps_partial_and_no_final_file(server, tmp_path):
    data = tiff_bytes(400_000)
    url = server.add("/x/j.tif", Resource(data, delay=0.01))
    dest = str(tmp_path / "j.tif")
    flag = threading.Event()

    def progress(received, total):
        if received > 100_000:
            flag.set()

    r = fast(is_canceled=flag.is_set).download(url, dest, on_progress=progress)
    assert r.status == D.CANCELED and not r.ok
    assert not os.path.exists(dest)
    assert os.path.exists(dest + ".part") and os.path.exists(dest + ".part.json")
    # retomada posterior completa o arquivo
    r2 = fast().download(url, dest)
    assert r2.status == D.DONE and r2.resumed
    with open(dest, "rb") as f:
        assert f.read() == data


def test_cancel_during_retry_wait(server, tmp_path):
    url = server.add("/x/k.tif", Resource(tiff_bytes(10_000), fail_first=99))
    calls = []

    def canceled():
        return len(calls) > 0

    r = fast(max_attempts=4, backoff=(30,), is_canceled=canceled,
             sleep=lambda s: calls.append(s)).download(url, str(tmp_path / "k.tif"))
    assert r.status == D.CANCELED
    assert len(server.gets("/x/k.tif")) == 1


def test_existing_valid_file_is_reused_without_download(server, tmp_path):
    data = tiff_bytes(30_000)
    url = server.add("/x/l.tif", Resource(data))
    dest = str(tmp_path / "l.tif")
    write(dest, data)
    r = fast().download(url, dest)
    assert r.status == D.EXISTING and r.ok
    assert server.gets("/x/l.tif") == []                       # só HEAD


def test_existing_file_with_wrong_size_is_replaced(server, tmp_path):
    data = tiff_bytes(30_000)
    url = server.add("/x/m.tif", Resource(data))
    dest = str(tmp_path / "m.tif")
    write(dest, data[:1000])
    r = fast().download(url, dest)
    assert r.status == D.DONE and "Replaced" in r.message
    with open(dest, "rb") as f:
        assert f.read() == data


def test_existing_file_is_kept_when_replacement_fails(server, tmp_path):
    url = server.add("/x/n.tif", Resource(tiff_bytes(30_000), fail_first=99))
    dest = str(tmp_path / "n.tif")
    old = tiff_bytes(1000, seed=3)
    write(dest, old)
    r = fast(max_attempts=2).download(url, dest)
    assert r.status == D.FAILED and "was not changed" in r.message
    with open(dest, "rb") as f:
        assert f.read() == old


def test_overwrite_forces_new_download(server, tmp_path):
    data = tiff_bytes(30_000)
    url = server.add("/x/o.tif", Resource(data))
    dest = str(tmp_path / "o.tif")
    write(dest, data)
    r = fast().download(url, dest, overwrite=True)
    assert r.status == D.DONE
    assert len(server.gets("/x/o.tif")) == 1


def test_cancel_does_not_touch_completed_files(server, tmp_path):
    """Cancelar o 2º arquivo não altera o 1º, já concluído."""
    a, b = tiff_bytes(50_000, 1), tiff_bytes(400_000, 2)
    url_a = server.add("/x/p.tif", Resource(a))
    url_b = server.add("/x/q.tif", Resource(b, delay=0.01))
    flag = threading.Event()
    dl = fast(is_canceled=flag.is_set)
    ra = dl.download(url_a, str(tmp_path / "p.tif"))
    rb = dl.download(url_b, str(tmp_path / "q.tif"),
                     on_progress=lambda r, t: r > 50_000 and flag.set())
    assert ra.status == D.DONE and rb.status == D.CANCELED
    with open(str(tmp_path / "p.tif"), "rb") as f:
        assert f.read() == a
    assert not os.path.exists(str(tmp_path / "q.tif"))


def test_missing_content_length_is_accepted_but_flagged(server, tmp_path):
    data = tiff_bytes(20_000)
    url = server.add("/x/r.tif", Resource(data, content_length=False))
    r = fast().download(url, str(tmp_path / "r.tif"))
    assert r.status == D.DONE and "not verified" in r.message


def test_probe_sizes(server):
    a = server.add("/s/a.tif", Resource(tiff_bytes(1234)))
    b = server.add("/s/b.tif", Resource(tiff_bytes(99)))
    missing = server.base + "/s/nao_existe.tif"
    got = []
    sizes, errors = D.probe_sizes([a, b, missing], workers=3,
                                  on_result=lambda u, s, e: got.append(u))
    assert sizes == {a: 1234, b: 99}
    assert list(errors) == [missing] and "404" in errors[missing]
    assert sorted(got) == sorted([a, b, missing])


def test_unreachable_server_message(tmp_path):
    r = fast(max_attempts=1).download("http://127.0.0.1:9/x.tif", str(tmp_path / "x.tif"))
    assert r.status == D.FAILED and "connect" in r.message and r.detail


def test_parse_content_range():
    assert D.parse_content_range("bytes 10-19/100") == (10, 19, 100)
    assert D.parse_content_range("bytes */100") is None
    assert D.parse_content_range(None) is None
