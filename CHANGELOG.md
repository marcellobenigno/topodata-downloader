# CHANGELOG

O formato segue [Keep a Changelog](https://keepachangelog.com/) e o projeto usa
[Versionamento Semântico](https://semver.org/).

## Não lançado

- Produtos classificados recebem cores por classe ao carregar (a tabela de cores dos arquivos
  do INPE é cinza quase preta); os arquivos não são alterados.
- Botão "Fechar" da página de execução sempre em português (antes seguia o idioma do Qt).
- Site de documentação em `docs/` com figuras geradas pelo plugin a partir de dados reais.

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
