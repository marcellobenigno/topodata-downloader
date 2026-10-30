# Atalhos para Linux/macOS. No Windows, rode os mesmos comandos Python (OSGeo4W Shell).
# QGIS_PYTHON: Python do QGIS com pytest instalado (os testes test_qgis/test_plugin precisam
# das bibliotecas do QGIS). Ex. no macOS, um script que exporte PYTHONHOME/PYTHONPATH do
# QGIS.app; no Linux, normalmente python3.
PYTHON      ?= python3
QGIS_PYTHON ?= python3
PLUGIN       = topodata_downloader

.PHONY: help translations test test-qgis lint zip deploy clean

help:
	@echo "make translations  compila translations/*.json -> $(PLUGIN)/i18n/*.qm (precisa do lrelease)"
	@echo "make test       testes sem QGIS (catálogo + download contra servidor local)"
	@echo "make test-qgis  todos os testes num QGIS headless (QGIS_PYTHON=...)"
	@echo "make lint       flake8"
	@echo "make zip        gera dist/$(PLUGIN)-<versão>.zip"
	@echo "make deploy     copia o plugin para o perfil do QGIS (QGIS_PLUGINS=... para mudar)"

translations:
	$(PYTHON) scripts/build_translations.py

test:
	$(PYTHON) -m pytest -v tests/test_core.py

test-qgis:
	QT_QPA_PLATFORM=offscreen $(QGIS_PYTHON) -m pytest -v tests

lint:
	$(PYTHON) -m flake8 --max-line-length 110 $(PLUGIN) scripts tests

zip:
	$(PYTHON) scripts/make_zip.py

QGIS_PLUGINS ?= $(HOME)/.local/share/QGIS/QGIS3/profiles/default/python/plugins
deploy:
	rm -rf "$(QGIS_PLUGINS)/$(PLUGIN)"
	cp -r $(PLUGIN) "$(QGIS_PLUGINS)/"

clean:
	rm -rf dist
	find . -name __pycache__ -prune -exec rm -rf {} +
