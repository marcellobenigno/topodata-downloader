# -*- coding: utf-8 -*-
"""
Estilo de exibição para os produtos classificados do TOPODATA.

Os GeoTIFF classificados do INPE (SA, SB, SC, V3, V5, H3, H5, OC, FT, DD) trazem uma tabela de
cores em tons de cinza quase pretos (valor v -> cinza v-1), então aparecem pretos no QGIS.
Aqui só se define o renderizador da camada (classes com cores distintas); o arquivo não é
alterado. Classes conferidas nos dados (folha 07S36_): SA 1–4, SB 1–7, SC 1–6, V3/H3 1–3,
V5/H5 1–5, OC 1–8, FT 1–9, DD 1–16 (semioctantes) + 17 e 18 (linhas de talvegues e
divisores). 0 = sem dado.
"""
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsPalettedRasterRenderer

SLOPE = ("#fff3c4", "#fdd36a", "#f08a3c", "#c2362b", "#67001f")
VERTICAL = ("#2166ac", "#92c5de", "#f7f7f7", "#f4a582", "#b35806")     # côncava -> convexa
HORIZONTAL = ("#3a9a5b", "#b8e3b1", "#f7f7f7", "#d4bde0", "#9a5bb0")   # converg. -> diverg.
CYCLIC = ("#d7301f", "#f28e2b", "#fdd835", "#8cc152", "#2e9e5b", "#2bb3c0", "#3a6fb0",
          "#8e5bb5")
FORMS = ("#1f78b4", "#a6cee3", "#6a3d9a", "#33a02c", "#b2df8a", "#cab2d6", "#e31a1c",
         "#fb9a99", "#ff7f00")


def _mix(a, b, t):
    a, b = QColor(a), QColor(b)
    return QColor(round(a.red() + (b.red() - a.red()) * t),
                  round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


def ramp(colors, n):
    """n cores interpoladas ao longo de ``colors``."""
    if n == 1:
        return [QColor(colors[0])]
    out = []
    for i in range(n):
        pos = i * (len(colors) - 1) / (n - 1)
        k = min(int(pos), len(colors) - 2)
        out.append(_mix(colors[k], colors[k + 1], pos - k))
    return out


def _dd():
    semi = [_mix(c, "#ffffff", 0.45) for c in ramp(CYCLIC + (CYCLIC[0],), 17)[:16]]
    return semi + [QColor("#08306b"), QColor("#a50f15")]


CLASS_COLORS = {
    "SA": ramp(SLOPE, 4),
    "SB": ramp(SLOPE, 7),
    "SC": ramp(SLOPE, 6),
    "V3": ramp(VERTICAL, 3),
    "V5": ramp(VERTICAL, 5),
    "H3": ramp(HORIZONTAL, 3),
    "H5": ramp(HORIZONTAL, 5),
    "OC": [QColor(c) for c in CYCLIC],
    "FT": [QColor(c) for c in FORMS],
    "DD": _dd(),
}


def product_code(path_or_name):
    """'…/07S36_SA.tif' -> 'SA'."""
    stem = path_or_name.replace("\\", "/").rsplit("/", 1)[-1].split(".")[0]
    return stem[-2:]


def apply_class_style(layer, code=None):
    """Aplica as cores das classes se o produto for classificado. Retorna True se aplicou."""
    code = code or product_code(layer.source())
    colors = CLASS_COLORS.get(code)
    if not colors or layer.bandCount() != 1:
        return False
    classes = [QgsPalettedRasterRenderer.Class(i + 1, c, "Classe {}".format(i + 1))
               for i, c in enumerate(colors)]
    layer.setRenderer(QgsPalettedRasterRenderer(layer.dataProvider(), 1, classes))
    layer.triggerRepaint()
    return True
