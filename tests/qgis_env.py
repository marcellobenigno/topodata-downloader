"""
QGIS headless (offscreen) com perfil isolado, compartilhado pelos testes que usam QGIS.

Os testes não leem nem gravam as configurações reais do usuário: um proxy configurado no
QGIS mudaria o resultado, e as preferências do plugin seriam gravadas no perfil real.
"""
import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QGIS_CUSTOM_CONFIG_PATH"] = tempfile.mkdtemp(prefix="topodata_qgis_")

from qgis.PyQt.QtCore import QCoreApplication, QSettings  # noqa: E402

QCoreApplication.setOrganizationName("TopodataDownloaderTests")
QCoreApplication.setApplicationName("tests")
QSettings.setDefaultFormat(QSettings.IniFormat)
for _fmt in (QSettings.IniFormat, QSettings.NativeFormat):
    for _scope in (QSettings.UserScope, QSettings.SystemScope):
        QSettings.setPath(_fmt, _scope, os.environ["QGIS_CUSTOM_CONFIG_PATH"])

from qgis.core import QgsApplication  # noqa: E402

APP = QgsApplication([], True)
APP.initQgis()
