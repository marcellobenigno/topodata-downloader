# -*- coding: utf-8 -*-
"""
Tarefas em segundo plano (QgsTask): consulta de tamanhos e download. A rede nunca é usada
na thread da interface; os sinais emitidos em ``run`` chegam ao diálogo pela fila de eventos
do Qt. O cancelamento é cooperativo (``isCanceled`` é consultado entre blocos de dados).
"""
import os
import time
import traceback

from qgis.PyQt.QtCore import pyqtSignal
from qgis.core import QgsMessageLog, QgsSettings, QgsTask

from . import downloader as D
from .compat import MSG_INFO, MSG_WARNING, TASK_CAN_CANCEL

LOG_TAG = "TOPODATA Downloader"
PROGRESS_INTERVAL = 0.15                       # s entre avisos de progresso de um arquivo


def qgis_proxies():
    """Proxy HTTP de Configurações > Opções > Rede, no formato do urllib (None = padrão do
    sistema). A senha nunca é registrada em log."""
    from urllib.parse import quote
    s = QgsSettings()
    if not s.value("proxy/proxyEnabled", False, type=bool):
        return None
    if s.value("proxy/proxyType", "") not in ("HttpProxy", "HttpCachingProxy"):
        return None
    host = s.value("proxy/proxyHost", "")
    port = s.value("proxy/proxyPort", "")
    if not host:
        return None
    user, pwd = s.value("proxy/proxyUser", ""), s.value("proxy/proxyPassword", "")
    auth = "{}:{}@".format(quote(user, safe=""), quote(pwd, safe="")) if user else ""
    url = "http://{}{}:{}".format(auth, host, port) if port else "http://{}{}".format(auth, host)
    return {"http": url, "https": url}


def make_opener():
    return D.build_opener(qgis_proxies())


class SizeProbeTask(QgsTask):
    """Consulta (HEAD) o tamanho de cada URL."""
    sizeReady = pyqtSignal(str, object, str)       # url, bytes ou None, erro ("" = ok)

    def __init__(self, urls, opener=None, workers=6):
        super().__init__("TOPODATA: consultando tamanhos dos arquivos", TASK_CAN_CANCEL)
        self.urls = list(urls)
        self.opener = opener
        self.workers = workers
        self.error = ""

    def run(self):
        total, count = max(1, len(self.urls)), [0]

        def on_result(url, size, error):
            count[0] += 1
            self.setProgress(100.0 * count[0] / total)
            if error != "cancelado":
                self.sizeReady.emit(url, size, error or "")

        try:
            D.probe_sizes(self.urls, self.opener or make_opener(), workers=self.workers,
                          is_canceled=self.isCanceled, on_result=on_result)
        except Exception:                       # nunca deixar a tarefa morrer em silêncio
            self.error = traceback.format_exc()
            QgsMessageLog.logMessage(self.error, LOG_TAG, MSG_WARNING)
            return False
        return not self.isCanceled()


class DownloadTask(QgsTask):
    """Baixa os itens do plano, um arquivo por vez."""
    fileStarted = pyqtSignal(int)                   # índice
    fileProgress = pyqtSignal(int, object, object)  # índice, recebidos, total (ou None)
    fileFinished = pyqtSignal(int, object)          # índice, downloader.Result
    allFinished = pyqtSignal(bool)                  # True = terminou sem exceção

    def __init__(self, items, folder, sizes=None, overwrite=False, opener=None,
                 downloader_options=None):
        super().__init__("TOPODATA: baixando {} arquivo(s)".format(len(items)), TASK_CAN_CANCEL)
        self.items = list(items)
        self.folder = folder
        self.sizes = dict(sizes or {})
        self.overwrite = overwrite
        self.opener = opener
        self.options = dict(downloader_options or {})
        self.results = [None] * len(self.items)
        self.error = ""

    def _weights(self):
        """Peso de cada arquivo no progresso geral: bytes, se todos os tamanhos forem
        conhecidos; senão cada arquivo vale o mesmo."""
        sizes = [self.sizes.get(i.url) for i in self.items]
        if sizes and all(isinstance(s, int) and s > 0 for s in sizes):
            return sizes
        return [1] * len(self.items)

    def run(self):
        try:
            return self._run()
        except Exception:                       # nunca deixar a tarefa morrer em silêncio
            self.error = traceback.format_exc()
            QgsMessageLog.logMessage(self.error, LOG_TAG, MSG_WARNING)
            return False

    def _run(self):
        weights = self._weights()
        grand = float(sum(weights)) or 1.0
        done_weight = 0.0
        dl = D.Downloader(self.opener or make_opener(), is_canceled=self.isCanceled,
                          **self.options)
        for i, item in enumerate(self.items):
            if self.isCanceled():
                break
            self.fileStarted.emit(i)
            last = [0.0]

            def progress(received, total, i=i, base=done_weight):
                now = time.monotonic()
                if now - last[0] < PROGRESS_INTERVAL and received != total:
                    return
                last[0] = now
                if total:
                    self.setProgress(100.0 * (base + weights[i] * received / total) / grand)
                self.fileProgress.emit(i, received, total)

            path = os.path.join(self.folder, item.filename)
            result = dl.download(item.url, path, overwrite=self.overwrite,
                                 expected_size=self.sizes.get(item.url), on_progress=progress)
            self.results[i] = result
            done_weight += weights[i]
            self.setProgress(100.0 * done_weight / grand)
            self.fileFinished.emit(i, result)
            QgsMessageLog.logMessage("{}: {}".format(item.filename, result.message), LOG_TAG,
                                     MSG_INFO if result.ok else MSG_WARNING)
        for i, item in enumerate(self.items):
            if self.results[i] is None:
                self.results[i] = D.Result(item.url, os.path.join(self.folder, item.filename),
                                           D.CANCELED, message="Não iniciado: download "
                                           "cancelado antes deste arquivo.")
                self.fileFinished.emit(i, self.results[i])
        return True

    def finished(self, ok):
        self.allFinished.emit(bool(ok))
