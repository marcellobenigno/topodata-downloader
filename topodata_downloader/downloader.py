# -*- coding: utf-8 -*-
"""
Cliente de download robusto (Python puro, sem QGIS).

Regras de segurança dos arquivos:

* O conteúdo é gravado em ``<arquivo>.part``; só depois de conferir o tamanho declarado pelo
  servidor (``Content-Length``) e o cabeçalho TIFF o parcial é renomeado (``os.replace``,
  atômico) para o nome final. Um cancelamento ou falha nunca deixa um arquivo final
  incompleto, e um arquivo final já existente só é substituído por outro completo.
* Retomada: o validador do servidor (``ETag`` forte ou ``Last-Modified``) e o tamanho total
  ficam em ``<arquivo>.part.json``. Na retomada são enviados ``Range`` + ``If-Range``; o
  trecho só é anexado se a resposta for ``206`` com ``Content-Range`` começando exatamente no
  fim do parcial e com o mesmo total. Qualquer outra resposta descarta o parcial e recomeça.
* Falhas temporárias (conexão, tempo esgotado, HTTP 408/429/5xx) são repetidas um número
  limitado de vezes, com espera crescente; erros definitivos (ex.: HTTP 404) não.
* O cancelamento é cooperativo: verificado entre blocos e durante as esperas.
"""
import http.client
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from .catalog import META_SUFFIX, PART_SUFFIX
from .translation import N_, tr

USER_AGENT = "QGIS-TOPODATA-Downloader/0.1"
TIFF_MAGICS = (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")      # TIFF e BigTIFF
RETRYABLE_HTTP = (408, 425, 429, 500, 502, 503, 504)

DONE, EXISTING, FAILED, CANCELED = "concluido", "existente", "falhou", "cancelado"
STATUS_LABELS = {                                   # traduzidos com tr() onde são exibidos
    DONE: N_("Downloaded"),
    EXISTING: N_("Already existed (verified)"),
    FAILED: N_("Failed"),
    CANCELED: N_("Canceled"),
}


class Canceled(Exception):
    """O usuário cancelou."""


class DownloadError(Exception):
    """Falha com mensagem amigável (``message``) e detalhe técnico (``detail``)."""

    def __init__(self, message, detail="", retryable=False, discard_partial=False):
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.retryable = retryable
        self.discard_partial = discard_partial


class Result:
    def __init__(self, url, path, status, size=None, message="", detail="", attempts=0,
                 resumed=False):
        self.url = url
        self.path = path
        self.status = status
        self.size = size
        self.message = message
        self.detail = detail
        self.attempts = attempts
        self.resumed = resumed

    @property
    def ok(self):
        return self.status in (DONE, EXISTING)

    def __repr__(self):
        return "Result({!r}, {!r}, {!r})".format(os.path.basename(self.path), self.status,
                                                 self.message)


def build_opener(proxies=None):
    """Opener do urllib. ``proxies`` = {'http': url, 'https': url}; None usa o padrão do
    sistema (variáveis de ambiente)."""
    handlers = []
    if proxies:
        handlers.append(urllib.request.ProxyHandler(proxies))
    return urllib.request.build_opener(*handlers)


def classify(err):
    """Converte exceções de rede em DownloadError com mensagem amigável (traduzida)."""
    if isinstance(err, DownloadError):
        return err
    detail = "{}: {}".format(type(err).__name__, err)
    if isinstance(err, urllib.error.HTTPError):
        if err.code == 404:
            return DownloadError(tr("File not found on the server (HTTP 404)."), detail)
        if err.code in (401, 403):
            return DownloadError(tr("The server refused access to the file (HTTP {}).").format(
                err.code), detail)
        return DownloadError(tr("The server responded with HTTP error {} ({}).").format(
            err.code, err.reason), detail, retryable=err.code in RETRYABLE_HTTP)
    if isinstance(err, urllib.error.URLError):
        reason = err.reason
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return DownloadError(tr("Timed out while connecting to the server."), detail,
                                 retryable=True)
        return DownloadError(tr("Could not connect to the INPE server. Check the internet "
                                "connection or the QGIS proxy."), detail,
                             retryable=True)
    if isinstance(err, (socket.timeout, TimeoutError)):
        return DownloadError(tr("Timed out: the server stopped sending data."),
                             detail, retryable=True)
    if isinstance(err, (ConnectionError, http.client.HTTPException)):
        return DownloadError(tr("The connection to the server was interrupted."), detail,
                             retryable=True)
    return DownloadError(tr("Error communicating with the server."), detail, retryable=True)


def parse_content_range(value):
    """'bytes 100-199/1000' -> (100, 199, 1000); None se ausente ou fora do formato."""
    m = re.match(r"^\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$", value or "")
    return tuple(int(g) for g in m.groups()) if m else None


def looks_like_tiff(path):
    try:
        with open(path, "rb") as f:
            return f.read(4) in TIFF_MAGICS
    except OSError:
        return False


def _int_or_none(value):
    value = (value or "").strip()
    return int(value) if value.isdigit() else None


def _remove(*paths):
    for p in paths:
        if os.path.exists(p):
            os.remove(p)


def _read_meta(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_meta(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def _strong(validator):
    """If-Range exige validador forte: ETag sem 'W/' ou data Last-Modified."""
    return bool(validator) and not validator.startswith("W/")


def head(url, opener=None, timeout=30, user_agent=USER_AGENT):
    """Tamanho (Content-Length) do arquivo no servidor, ou None se não informado."""
    opener = opener or build_opener()
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": user_agent})
    try:
        with opener.open(req, timeout=timeout) as resp:
            return _int_or_none(resp.headers.get("Content-Length"))
    except (urllib.error.URLError, OSError, http.client.HTTPException) as err:
        raise classify(err)


def probe_sizes(urls, opener=None, timeout=30, workers=6, attempts=2, is_canceled=None,
                on_result=None):
    """Consulta o tamanho de vários arquivos (HEAD) em paralelo.

    Retorna (sizes, errors): {url: bytes ou None} e {url: mensagem}. ``on_result(url, size,
    error)`` é chamado a cada resposta (na thread que chamou probe_sizes)."""
    is_canceled = is_canceled or (lambda: False)
    opener = opener or build_opener()

    def one(url):
        last = None
        for _ in range(attempts):
            if is_canceled():
                return url, None, "cancelado"
            try:
                return url, head(url, opener, timeout), None
            except DownloadError as err:
                last = err
                if not err.retryable:
                    break
        return url, None, last.message

    sizes, errors = {}, {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(one, u) for u in urls]
        for fut in as_completed(futures):
            url, size, error = fut.result()
            if error:
                errors[url] = error
            else:
                sizes[url] = size
            if on_result:
                on_result(url, size, error)
    return sizes, errors


class Downloader:
    """Baixa um arquivo por vez com retomada validada, repetições limitadas e cancelamento.

    is_canceled  função sem argumentos que retorna True quando o usuário cancelou
    backoff      esperas (s) antes da 2ª, 3ª... tentativa
    sleep        função de espera (substituível nos testes)
    """

    def __init__(self, opener=None, timeout=60, max_attempts=4, backoff=(2, 5, 10),
                 chunk_size=256 * 1024, is_canceled=None, sleep=None, user_agent=USER_AGENT):
        self.opener = opener or build_opener()
        self.timeout = timeout
        self.max_attempts = max(1, int(max_attempts))
        self.backoff = tuple(backoff) or (0,)
        self.chunk_size = chunk_size
        self.is_canceled = is_canceled or (lambda: False)
        self.sleep = sleep or time.sleep
        self.user_agent = user_agent

    # ------------------------------------------------------------------ API
    def download(self, url, path, overwrite=False, expected_size=None, on_progress=None):
        """Baixa ``url`` para ``path``. Nunca lança exceção de rede: retorna um Result."""
        part, meta = path + PART_SUFFIX, path + META_SUFFIX
        note = ""
        if os.path.isfile(path) and not overwrite:
            size = expected_size
            if size is None:
                try:
                    size = head(url, self.opener, self.timeout, self.user_agent)
                except DownloadError as err:
                    note = tr("Could not check the existing file ({}).").format(err.message)
            if size is not None and os.path.getsize(path) == size and looks_like_tiff(path):
                _remove(part, meta)                 # parcial antigo do mesmo arquivo
                return Result(url, path, EXISTING, size,
                              tr("Existing file with the same size as on the server; reused."))
            if size is not None:
                note = tr("The existing file was incomplete or different from the server "
                          "({} bytes on disk, {} on the server).").format(os.path.getsize(path),
                                                                          size)

        attempts, resumed, last = 0, False, None
        while attempts < self.max_attempts:
            if self.is_canceled():
                return self._canceled_result(url, path, attempts, resumed)
            attempts += 1
            try:
                size, resumed_now, verified = self._transfer(url, part, meta, on_progress)
            except Canceled:
                return self._canceled_result(url, path, attempts, resumed)
            except DownloadError as err:
                last = err
                if err.discard_partial:
                    _remove(part, meta)
                if not err.retryable or attempts >= self.max_attempts:
                    break
                if not self._wait(self.backoff[min(attempts - 1, len(self.backoff) - 1)]):
                    return self._canceled_result(url, path, attempts, resumed)
                continue
            resumed = resumed or resumed_now
            try:
                os.replace(part, path)
            except OSError as err:
                last = DownloadError(tr("Could not rename the downloaded file to its final name."),
                                     "{}: {}".format(type(err).__name__, err))
                break
            _remove(meta)
            msg = tr("Downloaded, resuming a previous partial file.") if resumed else tr("Downloaded.")
            if not verified:
                msg += " " + tr("The server did not report the size; integrity not verified.")
            if note:
                msg += " " + note + " " + tr("Replaced.")
            return Result(url, path, DONE, size, msg, attempts=attempts, resumed=resumed)

        message = last.message if last else tr("Unknown failure.")
        if attempts > 1:
            message += " " + tr("({} attempts.)").format(attempts)
        if os.path.exists(part):
            message += " " + tr("The partial file was kept to resume later.")
        if note:
            message += " " + note + " " + tr("The existing file was not changed.")
        return Result(url, path, FAILED, None, message, last.detail if last else "",
                      attempts=attempts, resumed=resumed)

    # ------------------------------------------------------------- internos
    def _canceled_result(self, url, path, attempts, resumed):
        msg = tr("Canceled by the user.")
        if os.path.exists(path + PART_SUFFIX):
            msg += " " + tr("The partial file (.part) was kept to resume later.")
        return Result(url, path, CANCELED, None, msg, attempts=attempts, resumed=resumed)

    def _wait(self, seconds):
        """Espera cancelável. Retorna False se o usuário cancelou durante a espera."""
        end = time.monotonic() + seconds
        while True:
            if self.is_canceled():
                return False
            left = end - time.monotonic()
            if left <= 0:
                return True
            self.sleep(min(0.1, left))

    def _resume_offset(self, url, part, meta):
        """Bytes do parcial que podem ser retomados com segurança (0 = recomeçar)."""
        if not os.path.isfile(part):
            _remove(meta)
            return 0, None
        state = _read_meta(meta)
        have = os.path.getsize(part)
        if (state and state.get("url") == url and _strong(state.get("validator"))
                and isinstance(state.get("total"), int) and 0 < have < state["total"]):
            return have, state
        _remove(part, meta)
        return 0, None

    def _transfer(self, url, part, meta, on_progress):
        """Uma tentativa. Retorna (bytes, retomado?, tamanho verificado?)."""
        offset, state = self._resume_offset(url, part, meta)
        headers = {"User-Agent": self.user_agent}
        if offset:
            headers["Range"] = "bytes={}-".format(offset)
            headers["If-Range"] = state["validator"]
        req = urllib.request.Request(url, headers=headers)
        try:
            resp = self.opener.open(req, timeout=self.timeout)
        except urllib.error.HTTPError as err:
            if err.code == 416:
                raise DownloadError(tr("The server refused to resume the partial file; the "
                                       "download will restart."), "HTTP 416", retryable=True,
                                    discard_partial=True)
            raise classify(err)
        except (urllib.error.URLError, OSError, http.client.HTTPException) as err:
            raise classify(err)

        try:
            status = resp.getcode()
            validator = resp.headers.get("ETag") or resp.headers.get("Last-Modified")
            resumed = False
            if offset and status == 206:
                rng = parse_content_range(resp.headers.get("Content-Range"))
                if (rng is None or rng[0] != offset or rng[2] != state["total"]
                        or (validator and validator != state["validator"])):
                    raise DownloadError(
                        tr("The server's response to the resume does not match the partial "
                           "file; the download will restart from the beginning."),
                        "Content-Range={!r}, expected start {} and total {}".format(
                            resp.headers.get("Content-Range"), offset, state["total"]),
                        retryable=True, discard_partial=True)
                total, mode, resumed = state["total"], "ab", True
            elif status == 200:
                # sem Range, ou o arquivo mudou no servidor (If-Range falhou): do início
                offset, mode = 0, "wb"
                total = _int_or_none(resp.headers.get("Content-Length"))
                if total and _strong(validator):
                    _write_meta(meta, {"url": url, "validator": validator, "total": total})
                else:
                    _remove(meta)
            else:
                raise DownloadError(tr("Unexpected server response (HTTP {}).").format(status),
                                    retryable=False, discard_partial=True)

            received = offset
            if on_progress:
                on_progress(received, total)
            try:
                f = open(part, mode)
            except OSError as err:
                raise DownloadError(tr("Could not write to the destination folder."),
                                    "{}: {}".format(type(err).__name__, err))
            with f:
                while True:
                    if self.is_canceled():
                        raise Canceled()
                    try:
                        chunk = resp.read(self.chunk_size)
                    except (OSError, http.client.HTTPException) as err:
                        raise classify(err)
                    if not chunk:
                        break
                    try:
                        f.write(chunk)
                    except OSError as err:
                        raise DownloadError(tr("Error writing to disk (space or permission)."),
                                            "{}: {}".format(type(err).__name__, err))
                    received += len(chunk)
                    if total is not None and received > total:
                        raise DownloadError(tr("The server sent more data than announced."),
                                            retryable=True, discard_partial=True)
                    if on_progress:
                        on_progress(received, total)
                f.flush()
                os.fsync(f.fileno())
        finally:
            resp.close()

        if total is not None and received != total:
            raise DownloadError(tr("Incomplete transfer: {} of {} bytes received.").format(
                received, total), retryable=True)
        if not looks_like_tiff(part):
            raise DownloadError(tr("The content received is not a GeoTIFF; the file was "
                                   "discarded."), discard_partial=True)
        return received, resumed, total is not None
