# -*- coding: utf-8 -*-
"""
Catálogo TOPODATA: produtos, URLs e plano de download. Python puro (sem QGIS), testável fora
do QGIS.

Fonte do mapeamento (verificado nos dados locais e no servidor do INPE):

* A grade ``grade_topodata.geojson`` tem uma feição por folha, com os campos ``scene``
  (ex.: ``07S36_``) e ``url``, que aponta sempre para o produto Altitude (``ZN``):
  ``https://data.inpe.br/bdc/data/topodata/v001/07S/36_/07S36_ZN.tif``.
* A página do INPE (seletor "Selecione o produto para baixar") monta a URL dos demais
  produtos trocando apenas o código final: ``.../07S36_SN.tif``, ``.../07S405SA.tif``...

Por isso a URL de cada produto é derivada da URL da grade, substituindo ``ZN.tif`` pelo
código do produto. Uma folha cuja URL não siga esse padrão não é adivinhada: fica fora do
plano e é informada ao usuário.
"""
import os
from collections import OrderedDict, namedtuple

from .translation import N_, number, tr

Product = namedtuple("Product", "code label description")

# Ordem e códigos = seletor da página do INPE. Rótulos e descrições em inglês, traduzidos com
# tr() onde são exibidos.
PRODUCTS = (
    Product("ZN", N_("Elevation"),
            N_("Numerical altimetry: refined digital elevation model, orthometric heights in "
               "metres (EGM96). Primary data from which the other variables are derived.")),
    Product("SN", N_("Slope"),
            N_("Numerical slope, in percent.")),
    Product("SA", N_("Slope (A)"),
            N_("Slope in 4 classes (Marques, 1971; Lepsch et al., 1991).")),
    Product("SB", N_("Slope (B)"),
            N_("Slope in 7 classes, A to G (Lepsch et al., 1991).")),
    Product("SC", N_("Slope (C)"),
            N_("Slope in 6 classes (EMBRAPA, 1999): flat to escarpment.")),
    Product("VN", N_("Vertical curvature"),
            N_("Numerical vertical curvature (°/m): convexity (+) or concavity (−) in "
               "profile.")),
    Product("V3", N_("Vertical curvature — 3 classes"),
            N_("Vertical curvature in 3 classes: concave, rectilinear and convex.")),
    Product("V5", N_("Vertical curvature — 5 classes"),
            N_("Vertical curvature in 5 intervals.")),
    Product("HN", N_("Horizontal curvature"),
            N_("Numerical horizontal curvature (°/m): convergence (−) or divergence (+) of "
               "the flow.")),
    Product("H3", N_("Horizontal curvature — 3 classes"),
            N_("Horizontal curvature in 3 classes: convergent, planar and divergent.")),
    Product("H5", N_("Horizontal curvature — 5 classes"),
            N_("Horizontal curvature in 5 intervals.")),
    Product("ON", N_("Aspect"),
            N_("Numerical slope aspect: azimuth of the steepest slope (0° to 360°).")),
    Product("OC", N_("Aspect — octants"),
            N_("Slope aspect in 8 directions: N, NE, E, SE, S, SW, W and NW.")),
    Product("FT", N_("Landform"),
            N_("Landform: 9 classes combining vertical and horizontal curvature.")),
    Product("RS", N_("Shaded relief"),
            N_("Shaded relief (hillshade).")),
    Product("DD", N_("Ridges and drainage lines"),
            N_("Micro-basin delineation (ADD process): drainage lines and ridges over the "
               "aspect in 16 semi-octants.")),
)
PRODUCT_BY_CODE = OrderedDict((p.code, p) for p in PRODUCTS)

GRID_PRODUCT = "ZN"                       # produto para o qual a grade traz a URL
GRID_SUFFIX = GRID_PRODUCT + ".tif"
PART_SUFFIX = ".part"                     # download em andamento
META_SUFFIX = ".part.json"                # validador (ETag) do parcial, para retomada segura

# Acima destes valores o diálogo avisa que o download pode ser grande ou demorado.
LARGE_FILE_COUNT = 40
LARGE_TOTAL_BYTES = 5 * 1000 ** 3

Tile = namedtuple("Tile", "scene url")
FileItem = namedtuple("FileItem", "scene code url filename")


class CatalogError(ValueError):
    """URL da grade fora do padrão conhecido."""


def product_url(grid_url, scene, code):
    """URL do produto ``code`` para a folha ``scene``, a partir da URL ``ZN`` da grade."""
    if code not in PRODUCT_BY_CODE:
        raise CatalogError(tr("Unknown product: {}").format(code))
    name = grid_url.rsplit("/", 1)[-1]
    if not grid_url.startswith(("https://", "http://")) or name != scene + GRID_SUFFIX:
        raise CatalogError(tr("The URL of tile {} does not follow the pattern '<tile>{}': {}").format(
            scene, GRID_SUFFIX, grid_url))
    return grid_url[:-len(GRID_SUFFIX)] + code + ".tif"


class Plan:
    """Arquivos a baixar para as folhas e produtos escolhidos, sem duplicatas.

    items       [FileItem] na ordem dos produtos e, dentro de cada produto, das folhas
    by_product  {code: n de arquivos}  (só produtos escolhidos, na ordem de PRODUCTS)
    by_tile     {scene: n de arquivos}
    tiles       [scene] folhas consideradas (com URL válida)
    rejected    [(scene, motivo)] folhas fora do padrão de URL
    """

    def __init__(self, tiles, codes):
        codes = [c for c in PRODUCT_BY_CODE if c in set(codes)]
        self.codes = codes
        self.rejected = []
        seen = OrderedDict()
        valid_tiles = OrderedDict()
        for tile in tiles:
            if tile.scene in valid_tiles:
                continue
            try:
                urls = [(code, product_url(tile.url, tile.scene, code))
                        for code in PRODUCT_BY_CODE]
            except CatalogError as err:
                self.rejected.append((tile.scene, str(err)))
                continue
            valid_tiles[tile.scene] = dict(urls)
        self.tiles = list(valid_tiles)
        for code in codes:
            for scene, urls in valid_tiles.items():
                url = urls[code]
                if url not in seen:
                    seen[url] = FileItem(scene, code, url, url.rsplit("/", 1)[-1])
        self.items = list(seen.values())
        self.by_product = OrderedDict((c, 0) for c in codes)
        self.by_tile = OrderedDict((s, 0) for s in self.tiles)
        for item in self.items:
            self.by_product[item.code] += 1
            self.by_tile[item.scene] += 1

    def __len__(self):
        return len(self.items)

    @property
    def urls(self):
        return [i.url for i in self.items]


class SizeSummary:
    """Estimativa de tamanho a partir de tamanhos conhecidos {url: bytes}.

    O total só é dado como exato quando o tamanho de todos os arquivos é conhecido; caso
    contrário ``total`` é None e ``known_total`` é um limite inferior.
    """

    def __init__(self, plan, sizes):
        self.by_product = OrderedDict()
        self.known_count = 0
        self.known_total = 0
        for code in plan.codes:
            self.by_product[code] = [0, 0]           # [bytes conhecidos, n conhecidos]
        for item in plan.items:
            size = sizes.get(item.url)
            if size is None:
                continue
            self.known_count += 1
            self.known_total += size
            self.by_product[item.code][0] += size
            self.by_product[item.code][1] += 1
        self.count = len(plan)
        self.product_counts = dict(plan.by_product)

    @property
    def complete(self):
        return self.count > 0 and self.known_count == self.count

    @property
    def total(self):
        return self.known_total if self.complete else None

    def product_total(self, code):
        known, n = self.by_product.get(code, (0, 0))
        return known if n == self.product_counts.get(code, 0) and n else None


def format_bytes(n):
    """Tamanho legível, unidades decimais (1 MB = 1.000.000 bytes); vírgula decimal conforme
    o idioma da interface."""
    if n is None:
        return tr("not available")
    units = ("bytes", "kB", "MB", "GB", "TB")
    value, unit = float(n), units[0]
    for unit in units:
        if value < 1000 or unit == units[-1]:
            break
        value /= 1000.0
    if unit == "bytes":
        return "{} bytes".format(int(n))
    return number("{:.1f} {}".format(value, unit))


def format_degrees(value):
    """Grau decimal, 5 casas (~1 m); vírgula decimal conforme o idioma da interface."""
    return number("{:.5f}°".format(value))


def is_large(plan, summary=None):
    """O download merece um aviso de volume (não impede nada)."""
    if len(plan) >= LARGE_FILE_COUNT:
        return True
    return bool(summary and summary.known_total >= LARGE_TOTAL_BYTES)


def describe_destination(path):
    """Validação imediata, sem criar nada (usada enquanto o usuário digita).

    Retorna (ok, mensagem); a mensagem também informa quando a pasta será criada."""
    path = (path or "").strip()
    if not path:
        return False, tr("Choose the folder where the files will be saved.")
    if not os.path.isabs(path):
        return False, tr("Enter the full path of the folder (e.g. starting with the drive or /).")
    if os.path.isdir(path):
        if not os.access(path, os.W_OK):
            return False, tr("No permission to write to this folder. Choose another one.")
        return True, ""
    if os.path.exists(path):
        return False, tr("The path points to a file, not to a folder.")
    parent = path
    while parent and not os.path.exists(parent):
        up = os.path.dirname(parent)
        if up == parent:
            break
        parent = up
    if not os.path.isdir(parent) or not os.access(parent, os.W_OK):
        return False, tr("The folder does not exist and cannot be created in '{}'.").format(parent)
    return True, tr("The folder does not exist and will be created when the download starts.")


def check_destination(path):
    """Valida a pasta de destino. Retorna (ok, mensagem). Cria a pasta se não existir.

    A gravação é testada de fato (arquivo temporário), porque permissões e pastas
    sincronizadas nem sempre refletem o resultado de os.access.
    """
    path = (path or "").strip()
    if not path:
        return False, tr("Choose the folder where the files will be saved.")
    if not os.path.isabs(path):
        return False, tr("Enter the full path of the folder (e.g. starting with the drive or /).")
    if os.path.exists(path) and not os.path.isdir(path):
        return False, tr("The path points to a file, not to a folder.")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as err:
        return False, tr("Could not create the folder: {}").format(err.strerror or err)
    probe = os.path.join(path, ".topodata_teste_escrita.tmp")
    try:
        with open(probe, "wb") as f:
            f.write(b"ok")
        os.remove(probe)
    except OSError as err:
        return False, tr("No permission to write to this folder: {}").format(err.strerror or err)
    return True, ""


def existing_files(plan, folder):
    """Arquivos do plano que já existem na pasta de destino."""
    if not folder or not os.path.isdir(folder):
        return []
    return [i for i in plan.items if os.path.isfile(os.path.join(folder, i.filename))]


def partial_files(plan, folder):
    """Arquivos do plano com download parcial (.part) na pasta de destino."""
    if not folder or not os.path.isdir(folder):
        return []
    return [i for i in plan.items
            if os.path.isfile(os.path.join(folder, i.filename + PART_SUFFIX))]
