"""
Servidor HTTP local que imita o servidor do INPE (nginx): HEAD com Content-Length e ETag,
Range/If-Range com 206 + Content-Range. Cada caminho tem um comportamento configurável para
simular falhas. Nenhum teste acessa a rede real.
"""
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def tiff_bytes(size, seed=0):
    """Conteúdo com cabeçalho TIFF válido e bytes determinísticos."""
    body = bytes((i * 31 + seed) % 251 for i in range(size - 4))
    return b"II*\x00" + body


class Resource:
    def __init__(self, data, etag='"v1"', ranges=True, fail_first=0, fail_status=500,
                 drop_first=0, drop_after=None, status=200, delay=0.0, bad_range=False,
                 content_length=True):
        self.data = data
        self.etag = etag
        self.ranges = ranges            # aceita Range
        self.fail_first = fail_first    # n primeiras requisições GET respondem fail_status
        self.fail_status = fail_status
        self.drop_first = drop_first    # n primeiras GET enviam só drop_after bytes e fecham
        self.drop_after = drop_after if drop_after is not None else len(data) // 2
        self.status = status            # ex.: 404
        self.delay = delay              # pausa entre blocos (download lento)
        self.bad_range = bad_range      # 206 com Content-Range que não confere
        self.content_length = content_length
        self.gets = 0


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        return None

    def _res(self):
        self.server.log.append((self.command, self.path, dict(self.headers)))
        return self.server.resources.get(self.path)

    def do_HEAD(self):
        res = self._res()
        if res is None or res.status != 200:
            self.send_response(404 if res is None else res.status)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/tiff")
        if res.content_length:
            self.send_header("Content-Length", str(len(res.data)))
        self.send_header("ETag", res.etag)
        if res.ranges:
            self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

    def do_GET(self):
        res = self._res()
        if res is None or res.status != 200:
            body = b"<html>not found</html>"
            self.send_response(404 if res is None else res.status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        res.gets += 1
        if res.gets <= res.fail_first:
            self.send_response(res.fail_status)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        data, start, status = res.data, 0, 200
        rng = self.headers.get("Range")
        if_range = self.headers.get("If-Range")
        if rng and res.ranges and (if_range is None or if_range == res.etag):
            start = int(rng.split("=")[1].split("-")[0])
            if start >= len(data):
                self.send_response(416)
                self.send_header("Content-Range", "bytes */{}".format(len(data)))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = 206
        body = data[start:]
        self.send_response(status)
        self.send_header("Content-Type", "image/tiff")
        self.send_header("ETag", res.etag)
        if res.content_length:
            self.send_header("Content-Length", str(len(body)))
        if status == 206:
            first = start + 7 if res.bad_range else start
            self.send_header("Content-Range", "bytes {}-{}/{}".format(
                first, len(data) - 1, len(data)))
        if not res.content_length:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if res.gets <= res.drop_first:
            limit = max(0, res.drop_after - start)
            self.wfile.write(body[:limit])
            self.wfile.flush()
            self.close_connection = True
            return
        step = 16 * 1024
        for i in range(0, len(body), step):
            self.wfile.write(body[i:i + step])
            if res.delay:
                self.wfile.flush()
                time.sleep(res.delay)


class FakeServer:
    def __init__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.resources = {}
        self.httpd.log = []
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base(self):
        return "http://127.0.0.1:{}".format(self.httpd.server_address[1])

    @property
    def log(self):
        return self.httpd.log

    def add(self, path, resource):
        self.httpd.resources[path] = resource
        return self.base + path

    def gets(self, path):
        return [h for (m, p, h) in self.httpd.log if m == "GET" and p == path]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
