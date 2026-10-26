"""
Gera dist/topodata_downloader-<versão>.zip, pronto para "Instalar a partir de ZIP" no QGIS.

    python scripts/make_zip.py

Funciona no Windows, macOS e Linux (não exige make).
"""
import configparser
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = "topodata_downloader"
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache"}
EXCLUDE_EXT = (".pyc", ".pyo", ".zip")


def main():
    meta = configparser.ConfigParser()
    meta.read(os.path.join(ROOT, PLUGIN, "metadata.txt"), encoding="utf-8")
    version = meta["general"]["version"]
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    out = os.path.join(ROOT, "dist", "{}-{}.zip".format(PLUGIN, version))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for folder, dirs, files in os.walk(os.path.join(ROOT, PLUGIN)):
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
            for f in sorted(files):
                if not f.endswith(EXCLUDE_EXT):
                    full = os.path.join(folder, f)
                    z.write(full, os.path.relpath(full, ROOT))
    print("gerado", out)


if __name__ == "__main__":
    main()
