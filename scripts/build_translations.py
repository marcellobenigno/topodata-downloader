"""
Builds topodata_downloader/i18n/topodata_downloader_<lang>.ts/.qm from
translations/<lang>.json  ({"English source text": "translation", ...}).

Checks before writing:
  * every tr("...") and N_("...") literal in the plugin has a translation (stale entries are reported)
  * each translation keeps the same {placeholders} as the source text
Requires 'lrelease' (Qt Linguist tools) on PATH or in the LRELEASE environment variable.

To add a language: copy translations/pt_BR.json to translations/<lang>.json, translate the
values, run this script (or `make translations`).
"""
import ast
import glob
import json
import os
import string
import subprocess
import sys
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "topodata_downloader")
PREFIX = "topodata_downloader"
CONTEXT = "TopodataDownloader"


def source_texts():
    texts = set()
    for path in glob.glob(os.path.join(PLUGIN, "*.py")):
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and node.args:
                f = node.func
                name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
                a = node.args[0]
                if name in ("tr", "N_") and isinstance(a, ast.Constant) and isinstance(a.value, str):
                    texts.add(a.value)
    return texts


def fields(text):
    return sorted(f for _, f, _, _ in string.Formatter().parse(text) if f is not None)


def main():
    lrelease = os.environ.get("LRELEASE", "lrelease")
    src = source_texts()
    ok = True
    for jpath in sorted(glob.glob(os.path.join(ROOT, "translations", "*.json"))):
        lang = os.path.splitext(os.path.basename(jpath))[0]
        table = json.load(open(jpath, encoding="utf-8"))
        missing, stale = src - table.keys(), table.keys() - src
        bad = [k for k, v in table.items() if k in src and fields(k) != fields(v)]
        for title, items in (("missing", missing), ("stale", stale),
                             ("placeholder mismatch", bad)):
            for t in sorted(items):
                print(f"[{lang}] {title}: {t[:90]!r}")
        if missing or bad:
            ok = False
            continue
        os.makedirs(os.path.join(PLUGIN, "i18n"), exist_ok=True)
        ts = os.path.join(PLUGIN, "i18n", f"{PREFIX}_{lang}.ts")
        with open(ts, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE TS>\n'
                    f'<TS version="2.1" language="{lang}" sourcelanguage="en">\n'
                    f'<context>\n    <name>{CONTEXT}</name>\n')
            for s in sorted(src):
                f.write(f"    <message>\n        <source>{escape(s)}</source>\n"
                        f"        <translation>{escape(table[s])}</translation>\n"
                        "    </message>\n")
            f.write("</context>\n</TS>\n")
        try:
            out = subprocess.run([lrelease, ts], capture_output=True, text=True)
        except FileNotFoundError:
            print("lrelease not found: install Qt Linguist tools or set LRELEASE=<path>")
            sys.exit(1)
        print(out.stdout.strip() or out.stderr.strip())
        ok = ok and out.returncode == 0
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
