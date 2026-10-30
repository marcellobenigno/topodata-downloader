# -*- coding: utf-8 -*-
"""
Translation helpers. The interface text is written in English in the code; the translations
(i18n/topodata_downloader_<lang>.qm) are built from translations/<lang>.json by
scripts/build_translations.py and installed by the plugin according to the QGIS locale.

Pure Python when Qt is missing, so catalog.py and downloader.py stay testable without QGIS.
"""
try:
    from qgis.PyQt.QtCore import QCoreApplication
except ImportError:                                 # tests without QGIS
    QCoreApplication = None

CONTEXT = "TopodataDownloader"
_COMMA_LANGUAGES = ("pt", "es", "fr", "de", "it")
_decimal_comma = False


def tr(text):
    if QCoreApplication is None:
        return text
    return QCoreApplication.translate(CONTEXT, text)


def N_(text):
    """Marks a constant for translation; translate it with tr() where it is shown."""
    return text


def set_language(code):
    """Language of the installed translation (e.g. 'pt_BR'); sets the decimal separator."""
    global _decimal_comma
    _decimal_comma = (code or "")[:2] in _COMMA_LANGUAGES


def number(text):
    """'80.8' -> '80,8' when the interface language uses a decimal comma."""
    return text.replace(".", ",") if _decimal_comma else text
