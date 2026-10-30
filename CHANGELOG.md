# CHANGELOG

O formato segue [Keep a Changelog](https://keepachangelog.com/) e o projeto usa
[Versionamento Semântico](https://semver.org/).

## 0.2.0 - 2026-10-30

- Interface em inglês (English user interface), como no `osmnx-routing-isochrones`, com
  tradução para o português do Brasil escolhida conforme o idioma do QGIS
  (`translations/pt_BR.json` → `topodata_downloader/i18n/*.qm`).
- Nomes das camadas, mensagens, tarefas e nomes dos produtos também traduzidos; números com
  vírgula decimal na tradução em português e com ponto em inglês.
- `scripts/build_translations.py` confere se todos os textos estão traduzidos e compila os
  `.qm`; `make_zip.py` e o workflow de release compilam as traduções.

## 0.1.2 - 2026-10-30

- Documentação revisada e publicada em português e em inglês
  (https://marcellobenigno.github.io/topodata-downloader/), com seleção de idioma.
- O site passa a ficar no branch `gh-pages`; `docs/` deixa de ser versionada no `main`.
- README com link para a documentação em inglês; nova descrição do autor no site.
- Sem mudanças no código do plugin.

## 0.1.1 - 2026-10-28

- Descrição e texto "about" dos metadados em inglês (exigência do plugins.qgis.org),
  mantendo o texto em português.

## 0.1.0 - 2026-10-26

- Versão inicial de desenvolvimento.
- Seleção retangular no mapa, conversão para EPSG:4326 (seleção adensada) e consulta
  `intersects` na grade local com índice espacial.
- Diálogo em pt-BR: extensão, quadrículas, pasta com validação, 16 produtos, contagem por
  produto e por quadrícula, tamanho exato via HEAD (ou "não disponível").
- Download em segundo plano com `.part`, validação de tamanho e TIFF antes de renomear,
  retomada com `Range`/`If-Range` validados, repetições limitadas, cancelamento, reutilização
  verificada de arquivos existentes.
- Carregamento opcional como camadas raster separadas, sem duplicatas.
- Produtos classificados recebem cores por classe ao carregar (a tabela de cores dos arquivos
  do INPE é cinza quase preta); os arquivos não são alterados.
- Interface toda em português, sem botões padrão do Qt que seguiriam o idioma do sistema.
- Site de documentação em `docs/` com figuras geradas pelo plugin a partir de dados reais.
