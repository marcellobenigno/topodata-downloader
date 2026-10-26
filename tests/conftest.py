"""
Caminhos de importação e encerramento do QGIS headless.

O QGIS headless costuma falhar (segfault) ao destruir QgsApplication na saída do
interpretador, depois de todos os testes passarem. Quando o QGIS foi carregado, sai logo após
o relatório do pytest com o código de saída dele.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from fake_server import FakeServer  # noqa: E402

_STATUS = {}


@pytest.fixture
def server():
    s = FakeServer()
    yield s
    s.close()


def pytest_sessionfinish(session, exitstatus):
    _STATUS["code"] = int(exitstatus)


def pytest_unconfigure(config):
    if "qgis.core" in sys.modules and "code" in _STATUS:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(_STATUS["code"])
