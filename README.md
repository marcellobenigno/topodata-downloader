# TOPODATA Downloader (plugin QGIS)

📖 **Documentação:** https://marcellobenigno.github.io/topodata-downloader/pt-br/ · **Documentation (English):** https://marcellobenigno.github.io/topodata-downloader/en/

Baixa, a partir de um **retângulo desenhado no mapa**, os produtos TOPODATA (INPE) das
quadrículas que **intersectam** a área. Mostra antes quantos arquivos serão baixados (por
produto e por quadrícula) e quanto ocupam, baixa em segundo plano com progresso e
cancelamento, e opcionalmente carrega cada arquivo como camada raster separada.

O plugin **baixa os GeoTIFF originais do INPE**. Ele não cria mosaicos, não recorta, não
reprojeta e não processa os dados.

Interface em português do Brasil. Fonte dos dados: <https://data.inpe.br/dados/topodata/>.

## Instalação

1. Gere o ZIP: `python scripts/make_zip.py` (cria `dist/topodata_downloader-0.1.0.zip`).
2. No QGIS: *Complementos → Gerenciar e instalar complementos → Instalar a partir de ZIP*.
   Escolha o ZIP e confirme. Como o plugin é experimental, marque *Mostrar também
   complementos experimentais* nas configurações do gerenciador, se ele não aparecer.

Alternativa para desenvolvimento: copie a pasta `topodata_downloader/` para a pasta de
complementos do perfil do QGIS e reinicie o QGIS (ou use o *Plugin Reloader*):

| Sistema | Pasta de complementos (perfil `default`) |
|---|---|
| Windows | `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins` |
| macOS | `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins` |
| Linux | `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins` |

Não há dependências externas: o plugin usa só a biblioteca padrão do Python e o PyQGIS.

## Uso

1. Clique no botão **Baixar dados TOPODATA por área** (barra de complementos, ou menu
   *Raster → TOPODATA Downloader*).
2. **Clique e arraste** no mapa para desenhar o retângulo. `Esc` cancela; um clique sem
   arrasto é recusado com um aviso.
3. Abre-se o diálogo:
   - **Área selecionada**: oeste, sul, leste e norte em graus decimais (EPSG:4326), número de
     quadrículas e seus nomes (ex.: `07S36_, 07S375`). *Refazer seleção no mapa* volta ao mapa
     mantendo pasta, produtos e opções.
   - **Pasta de destino**: digite ou use o botão do seletor nativo. A validação aparece logo
     abaixo do campo (vazia, caminho relativo, é um arquivo, sem permissão, será criada).
   - **Produtos**: marque com o mouse ou com a barra de espaço; *Selecionar todos* e
     *Limpar seleção*. Passe o mouse sobre um produto para ver a descrição.
   - **Opções**: *Carregar as imagens no QGIS ao concluir* e *Baixar novamente arquivos que já
     existem na pasta*.
   - **Resumo**: arquivos por produto, total, quadrículas, tamanho por produto e total, origem
     da estimativa e aviso de download grande (não bloqueia).
4. **Baixar N arquivo(s)** abre a página de execução (download grande pede confirmação). O
   QGIS continua utilizável; a tarefa também aparece no gerenciador de tarefas do QGIS.
5. Ao final: resumo (baixados, já existentes, falhas, cancelados), tabela com a situação e a
   mensagem de cada arquivo, *Detalhes técnicos* (copiáveis), *Abrir pasta de destino*,
   *Carregar no QGIS* e *Voltar à configuração*.

Estados mostrados no topo do diálogo: aguardando seleção, consultando a grade, nenhuma
quadrícula, falta configurar, pronto para baixar, baixando, cancelando, cancelado, concluído
com sucesso e concluído parcialmente. "Concluído com sucesso" só aparece se **todos** os
arquivos estiverem disponíveis.

## Dados locais e mapeamento produto → arquivo

**Grade** (`topodata_downloader/data/grade_topodata.geojson`, cópia de
`download-topodata/grade_topodata.geojson`):

- GeoJSON, 556 polígonos, SRC `urn:ogc:def:crs:OGC:1.3:CRS84` (lon/lat WGS 84, equivalente a
  EPSG:4326 na ordem lon/lat).
- Campos: `scene` (nome da folha, ex. `07S36_`, `07S405`, `01N495`) e `url` (sempre o produto
  Altitude, ex. `https://data.inpe.br/bdc/data/topodata/v001/07S/36_/07S36_ZN.tif`).
- Folhas de 1° de latitude × 1,5° de longitude (articulação 1:250.000), com **meia margem de
  pixel** (~0,000139°) além do limite nominal; folhas vizinhas se sobrepõem levemente.
  Exceções existentes nos dados: `23S465` e `24S48_` têm 1,25° de altura; `01S45_`, `05S36_`,
  `09S36_` e `11S375` não têm margem; `09S375` tem margem menor. O plugin usa as geometrias
  como estão.

**URLs dos produtos**: a página do INPE (ver `download-topodata/inspecao_html.md`) monta a URL
de cada produto trocando só o código final da URL da grade (`…/07S36_ZN.tif` →
`…/07S36_SN.tif`). O plugin faz o mesmo e preserva o nome original do arquivo. Se a URL de
uma folha não terminar em `<scene>ZN.tif`, a folha é ignorada e informada (nada é
adivinhado). Verificação: as 556 URLs da grade seguem o padrão (teste automatizado), e
requisições HEAD ao servidor confirmaram os 16 produtos em folhas de tipos diferentes
(`07S36_`, `23S465`, `09S375`, `01N495`, `33S54_`).

| Rótulo | Código | Descrição (resumo de `descricao_dos_dados.md`) |
|---|---|---|
| Altitude | ZN | MDE refinado, altitude ortométrica (m, EGM96) |
| Declividade | SN | declividade numérica (%) |
| Decliv. (A) | SA | 4 classes (Marques 1971; Lepsch et al. 1991) |
| Decliv. (B) | SB | 7 classes A–G (Lepsch et al. 1991) |
| Decliv. (C) | SC | 6 classes (EMBRAPA 1999) |
| Curv. vertical | VN | numérica (°/m) |
| Curv. vertical — 3 classes | V3 | côncava, retilínea, convexa |
| Curv. vertical — 5 classes | V5 | 5 intervalos |
| Curv. horizontal | HN | numérica (°/m) |
| Curv. horizontal — 3 classes | H3 | convergente, planar, divergente |
| Curv. horizontal — 5 classes | H5 | 5 intervalos |
| Orientação | ON | azimute 0–360° |
| Orientação — octantes | OC | 8 direções |
| Forma de terreno | FT | 9 classes (curv. vertical × horizontal) |
| Relevo sombreado | RS | hillshade (código só no seletor do INPE; existe no servidor) |
| Divisores e talvegues | DD | delineamento de microbacias (ADD) |

Os arquivos são GeoTIFF otimizados para nuvem (COG), EPSG:4326, pixel de 0,00027777°
(~30 m). Exemplo: `07S36_ZN.tif` tem 80.775.987 bytes; produtos classificados (ex. `SA`) têm
~2 MB; produtos numéricos e o relevo sombreado, 60–120 MB por folha.

## Critério de interseção

- A seleção é feita no SRC do mapa. O retângulo vira polígono, recebe 32 vértices extras por
  lado e é transformado para EPSG:4326 com o contexto de transformação do projeto. Em SRC
  projetados (UTM, Web Mercator, Policônica) a consulta usa a forma real da seleção em
  coordenadas geográficas, não só a caixa envolvente transformada.
- A grade é lida uma vez por sessão e indexada (`QgsSpatialIndex`). O índice pré-seleciona
  candidatas pela caixa envolvente; cada candidata é confirmada com `intersects` sobre a
  geometria real (motor GEOS preparado).
- **Regra de borda**: `intersects` do modelo OGC — folhas **apenas tocadas** pela borda ou por
  um vértice do retângulo **entram**. Por causa da meia margem das folhas, um retângulo que
  começa exatamente num meridiano/paralelo de articulação (ex.: −36°) inclui as duas folhas
  vizinhas daquele limite.
- A extensão exibida (oeste, sul, leste, norte) é a caixa envolvente da seleção já em
  EPSG:4326.

## Contagem de arquivos e estimativa de tamanho

- **Contagem**: para cada produto marcado × cada folha encontrada, uma URL; URLs repetidas
  são contadas uma vez. O resumo mostra arquivos por produto, por folha e total.
- **Tamanho**: não existe índice local de tamanhos (o servidor também não lista diretórios:
  HTTP 403). O plugin consulta em segundo plano, com `HEAD`, o `Content-Length` de cada
  arquivo que seria baixado (6 consultas em paralelo, resultado guardado durante a sessão).
  Esse valor é o tamanho exato do arquivo atual do servidor. Enquanto consulta, mostra
  "consultando…"; se alguma consulta falhar, o total aparece como **"não disponível"** e o
  resumo informa quantos arquivos são conhecidos ("pelo menos X"). Nunca há estimativa
  inventada.

## Download seguro

- Rede sempre fora da thread da interface (`QgsTask`); um arquivo por vez.
- Grava em `<arquivo>.part`. Só renomeia para o nome final (`os.replace`, atômico) depois de
  conferir o tamanho recebido contra o `Content-Length` e o cabeçalho TIFF. Conteúdo que não é
  TIFF (ex.: página de erro) é descartado.
- **Retomada**: o validador do servidor (ETag forte; o servidor do INPE envia) e o total vão
  para `<arquivo>.part.json`. Na retomada são enviados `Range` + `If-Range`; os bytes só são
  anexados se a resposta for `206` com `Content-Range` começando exatamente no fim do parcial
  e com o mesmo total. Se o arquivo mudou no servidor (resposta `200`), se não há validador,
  ou se a faixa não confere, o parcial é descartado e o download recomeça do zero.
- **Repetições**: falhas temporárias (conexão, tempo esgotado, HTTP 408/425/429/5xx) são
  repetidas até 4 tentativas, com esperas de 2, 5 e 10 s (canceláveis). Erros definitivos
  (404, 403) não são repetidos. Um corte de conexão no meio do arquivo é retomado na
  tentativa seguinte.
- **Cancelamento** cooperativo: verificado a cada bloco de 256 kB e durante as esperas. O
  arquivo em andamento fica como `.part` (retomável); arquivos já concluídos não são tocados;
  os não iniciados aparecem como "Cancelado".
- **Arquivos já existentes**: com *Baixar novamente* desmarcado, um arquivo existente é
  reutilizado só se tiver o mesmo tamanho informado pelo servidor e cabeçalho TIFF válido; se
  for diferente, é baixado de novo e substituído só quando o novo estiver completo (se o novo
  download falhar, o arquivo antigo fica intacto). Marcado, sempre baixa de novo, com a mesma
  substituição segura.
- Proxy: usa o proxy HTTP de *Configurações → Opções → Rede* do QGIS (tipos HttpProxy e
  HttpCachingProxy); senão, o proxy do sistema/variáveis de ambiente. A senha do proxy nunca
  vai para o log.
- Log: *Exibir → Painéis → Mensagens de log*, aba "TOPODATA Downloader" (um registro por
  arquivo).

## Carregamento no QGIS

Cada arquivo disponível (baixado ou reutilizado) vira uma camada raster separada no grupo
`TOPODATA`, com o caminho final do arquivo e o nome `07S36_ZN — Altitude`. Arquivos que já
estão no projeto (mesmo caminho) não são adicionados de novo. Arquivos que o GDAL não abre
são listados na tabela com o motivo. Nada é alterado nos rasters.

Os produtos classificados do INPE (SA, SB, SC, V3, V5, H3, H5, OC, FT, DD) trazem uma tabela
de cores em cinza quase preto (valor v → cinza v−1) e aparecem pretos no QGIS. Ao carregar,
o plugin aplica um estilo de camada com uma cor por classe (`styles.py`); o arquivo não é
alterado. Classes conferidas nos dados: SA 1–4, SB 1–7, SC 1–6, V3/H3 1–3, V5/H5 1–5,
OC 1–8, FT 1–9, DD 1–16 + 17–18 (linhas).

## Documentação (site)

Branch `gh-pages` (GitHub Pages), no mesmo formato do site do `osmnx-routing-isochrones`: `pt-br/`, `en/` e `index.html`, que escolhe o idioma. No `main`, `docs/` não é versionada; para editar o site, use o branch como worktree: `git worktree add docs gh-pages`.
As figuras são feitas pelo próprio plugin num QGIS headless, com dados reais do INPE (precisa
de internet; perfil do QGIS temporário):

```bash
QT_QPA_PLATFORM=offscreen <python do QGIS> scripts/build_docs_figures.py
```

## Estrutura

```
topodata_downloader/        o plugin (esta pasta vai no ZIP)
  catalog.py                Python puro: produtos, URLs, plano, contagem, tamanho, pasta
  downloader.py             Python puro: HEAD, download com .part, retomada, repetição, cancelamento
  grid.py                   grade, índice espacial, interseção, transformação para EPSG:4326
  map_tool.py               ferramenta de retângulo no mapa
  tasks.py                  QgsTask de consulta de tamanhos e de download; proxy do QGIS
  loader.py                 carregamento das camadas raster
  styles.py                 cores por classe dos produtos classificados
  dialog.py                 diálogo (configuração / execução)
  plugin.py                 botão, menu e ligação entre ferramenta e diálogo
  compat.py                 enums compatíveis com Qt5 (QGIS 3) e Qt6 (QGIS 4)
  data/grade_topodata.geojson
tests/                      test_core.py (sem QGIS), test_qgis.py e test_plugin.py (QGIS headless)
scripts/make_zip.py, build_docs_figures.py
docs/                       worktree do branch gh-pages (site de documentação)
```

Padrões seguidos do `osmnx-routing-isochrones` (mesmo autor): núcleo em Python puro testável
sem QGIS, `compat.py` com `_first` para Qt5/Qt6, `qgisMinimumVersion=3.28`, testes headless
com `os._exit` no fim, `make_zip.py`, sem `try/except/pass`. Do `OSMDownloader` (GPL, Luiz
Andrade) veio a ideia do fluxo "desenhar retângulo → diálogo com a extensão"; o código foi
escrito do zero (o original grava direto no arquivo final e não valida o download).

## Testes

Nenhum teste acessa o servidor do INPE: o download é testado contra um servidor HTTP local
(`tests/fake_server.py`) que imita o nginx do INPE (HEAD, ETag, Range/If-Range) e simula
falhas. Os testes com QGIS usam um **perfil temporário isolado** (não leem nem gravam as
configurações reais, como proxy ou preferências).

```bash
# sem QGIS (Python ≥ 3.8 + pytest)
python -m pytest -v tests/test_core.py

# todos, num QGIS headless (Python do QGIS + pytest)
QT_QPA_PLATFORM=offscreen <python do QGIS> -m pytest -v tests
```

No macOS o Python do QGIS.app precisa de `PYTHONHOME` e `PYTHONPATH` apontando para
`QGIS.app/Contents/Resources` e `…/Resources/python3.11` (+ `lib-dynload`, `site-packages`),
executando `QGIS.app/Contents/MacOS/python3.12`; o pytest pode ser instalado numa pasta à
parte (`pip install --target <pasta> pytest`) adicionada ao `PYTHONPATH`.

### Resultado (26/10/2026, QGIS 3.44.8, Qt 5.15.18, Python 3.12.11, macOS)

`68 passed` (37 em `test_core.py`, 26 em `test_qgis.py`, 5 em `test_plugin.py`); `flake8
--max-line-length 110` sem avisos; `compileall` com Python 3.8 sem erros.

| Requisito | Teste |
|---|---|
| 1. Retângulo cruzando várias folhas | `test_rectangle_crossing_several_tiles`, `test_bbox_alone_is_not_enough`, `test_bbox_candidate_rejected_by_real_geometry` |
| 2. Sem interseção | `test_rectangle_without_tiles`, `test_dialog_validation_states` |
| 3. Apenas tocando o limite | `test_touching_edge_and_corner_are_included`, `test_real_grid_margin_overlap_at_sheet_boundary` |
| 4. Transformação para EPSG:4326 | `test_selection_in_other_crs_is_transformed_to_wgs84` (3857, 31985, 5880), `test_selection_opens_dialog_in_wgs84_and_restores_tool` |
| 5. Contagem por produto/folha/total, duplicatas | `test_plan_counts_per_product_tile_and_total`, `test_plan_has_no_duplicates`, `test_every_grid_feature_has_a_resolvable_url`, `test_dialog_counts_and_sizes` |
| 6. Tamanho com e sem metadados | `test_size_summary_*`, `test_dialog_counts_and_sizes`, `test_dialog_size_not_available` |
| 7. Destino inválido / sem permissão | `test_destination_*`, `test_dialog_validation_states` |
| 8. Validação antes de renomear | `test_download_ok_validates_before_rename`, `test_download_not_a_tiff_is_discarded` |
| 9. Falha de rede, repetição limitada, cancelamento | `test_temporary_failure_is_retried_then_succeeds`, `test_retries_are_limited`, `test_http_404_is_not_retried`, `test_unreachable_server_message`, `test_cancel_*`, `test_dialog_cancel` |
| 10. Parcial preexistente, retomada/reinício seguro | `test_connection_drop_resumes_with_validated_range`, `test_existing_partial_is_resumed_on_restart`, `test_partial_of_changed_file_restarts_from_zero`, `test_partial_without_validator_is_discarded`, `test_inconsistent_content_range_is_not_concatenated`, `test_server_without_range_support_restarts_safely` |
| 11. Completos não corrompidos por cancelamento | `test_cancel_does_not_touch_completed_files`, `test_dialog_cancel`, `test_existing_file_is_kept_when_replacement_fails` |
| 12. Carregamento sem mosaico/recorte | `test_dialog_download_load_and_responsive_ui` (4 camadas separadas, extensão e tamanho originais, sem duplicar), `test_loader_reports_unreadable_and_missing`, `test_classified_products_get_class_colors` (estilo sem alterar o arquivo) |
| 13. Interface responsiva | `test_dialog_download_load_and_responsive_ui` (timer de 20 ms na thread da interface sem intervalos > 0,5 s durante o download) |
| 14. Falha parcial sem falso sucesso | `test_dialog_partial_failure_summary` |

### Verificação manual feita contra o servidor real (fora da suíte automática)

Com `downloader.py`: HEAD de `07S36_SA.tif` e `07S36_ZN.tif` (1.968.681 e 80.775.987 bytes,
este igual ao arquivo de amostra local); download de `07S36_SA.tif` cancelado em ~720 kB
(ficaram só `.part` e `.part.json` com o ETag), retomado com `Range`/`If-Range` (resposta
206) e concluído; o arquivo final é **idêntico byte a byte** ao baixado com `curl` e abre no
GDAL (5400 × 3600, Byte, paleta). Uma terceira execução reutilizou o arquivo verificado.

### Validação manual pendente (não executada)

Faça no QGIS de verdade, com tela:

1. Instalar pelo ZIP; o botão aparece na barra e em *Raster → TOPODATA Downloader*.
2. Com o projeto em EPSG:31984/31985 (SIRGAS 2000 / UTM), desenhar um retângulo sobre
   João Pessoa: o diálogo mostra `07S36_` (e vizinhas, se a área cruzar −36° ou −7°).
3. Marcar *Decliv. (A)*, escolher uma pasta, conferir a contagem e o tamanho (~2 MB por folha)
   e baixar; acompanhar o progresso; ver as camadas no grupo TOPODATA.
4. Marcar *Altitude* + *Relevo sombreado* em várias folhas, iniciar e **cancelar**: o resumo
   mostra cancelados e `.part` mantidos; baixar de novo retoma.
5. Desligar a rede no meio de um arquivo: repetições, mensagem de falha e "Concluído
   parcialmente".
6. Fechar o diálogo durante o download (pergunta de confirmação); *Abrir pasta de destino*.
7. Navegar só pelo teclado (Tab, espaço nos produtos, Enter não inicia o download) e
   conferir foco e contraste nos temas claro e escuro do QGIS.
8. Repetir no QGIS 4 (Qt6) e no Windows.

## Limitações conhecidas

- Testado apenas no QGIS 3.44.8 (Qt5) no macOS. A compatibilidade com Qt6/QGIS 4 segue o
  padrão do `osmnx-routing-isochrones`, mas não foi executada.
- A estimativa de tamanho depende de consultas HEAD ao INPE; sem internet, aparece "não
  disponível" (o download também não seria possível).
- O proxy usa apenas as configurações HttpProxy/HttpCachingProxy do QGIS ou o proxy do
  sistema; configurações de autenticação do QGIS (`authcfg`), exclusões de proxy e
  certificados personalizados do QGIS não são aplicados (o `urllib` usa os certificados do
  Python/sistema).
- O cancelamento espera o bloco de dados em andamento; com a conexão travada, pode levar até
  o tempo limite de leitura (60 s).
- Os arquivos são salvos todos na pasta escolhida, com os nomes originais (sem subpastas).

## Publicação de versões

1. Atualize `version=` em `topodata_downloader/metadata.txt` e acrescente `## X.Y.Z - data`
   ao `CHANGELOG.md`.
2. Faça o commit e envie a tag com o mesmo número:
   `git tag -a X.Y.Z -m "TOPODATA Downloader X.Y.Z" && git push origin X.Y.Z`.

O workflow `.github/workflows/release.yml` confere a versão, roda os testes sem QGIS, gera o
ZIP, cria a release no GitHub (notas do CHANGELOG, ZIP anexado) e publica no
plugins.qgis.org com o secret `QGIS_TOKEN` (token do plugin; sem ele, essa etapa é pulada).

## Licença

[GPL-2.0-or-later](LICENSE). Dados: TOPODATA, Instituto Nacional de Pesquisas Espaciais
(INPE).
