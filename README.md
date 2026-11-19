# Cobertura da terra no Mosaico Juréia-Itatins

Códigos de preparação das imagens Landsat, separação das bandas e geração das máscaras de exclusão utilizados no desenvolvimento do TCC de Maria Eloisa Véras (UFABC). Os scripts GEE são adaptações do exemplo fornecido pela Profa. Dra. Ângela Terumi Fushita.

## Organização

- `gee/landsat_1991.js`: imagem de referência de 01/06/1991, Landsat 5.
- `gee/landsat_2000.js`: mediana anual, Landsat 7.
- `gee/landsat_2010.js`: mediana de duas cenas, Landsat 5.
- `gee/landsat_2020.js`: mediana anual das cenas Landsat 8 selecionadas.
- `python/separar_bandas_qgis.py`: separação das imagens multibanda em GeoTIFFs individuais para uso no SCP.
- `python/gerar_mascaras_exclusao_qgis.py`: seleção de GeoTIFFs e geração das máscaras no QGIS.
- `python/quantificar_cobertura_mudancas.py`: cálculo de áreas por classe e transições entre anos, por área vetorial e no total.

## Seleção das imagens

| Ano | Sensor | Seleção | Produto | Ampliação adicional de nuvens/sombras |
|---|---|---|---|---|
| 1991 | Landsat 5 | `LT05_219077_19910601` | Cena única | Nenhuma |
| 2000 | Landsat 7 | Todas as cenas do ano que intersectam o recorte | Mediana por banda | Raio de 60 m |
| 2010 | Landsat 5 | `LT05_219077_20100520` e `LT05_219077_20101128` | Mediana por banda | Nenhuma |
| 2020 | Landsat 8 | `0 <= CLOUD_COVER_LAND < 10` | Mediana por banda | Nenhuma |

Em 2020, o limite de 10% é exclusivo: cenas com exatamente 10% são excluídas. A nebulosidade do metadado representa a parte terrestre da cena, não somente as unidades de conservação. Os scripts anuais pesquisam de 1º de janeiro até 1º de janeiro do ano seguinte, com término exclusivo.

## Executar no Google Earth Engine

1. Acesse o Code Editor: https://code.earthengine.google.com/.
2. Copie o conteúdo de um arquivo `gee/landsat_ANO.js` para um script novo.
3. Confira o caminho do asset `projects/evident-plane-274108/assets/MUCJI_continental`. É necessário ter acesso a esse asset ou substituí-lo por uma delimitação equivalente. A geometria não está incluída neste repositório.
4. Confira a pasta `TCC_MUCJI` de destino no Google Drive e execute **Run**.
5. Examine as imagens, a contagem de observações e as mensagens do console. Inicie as exportações na aba **Tasks**.
6. Baixe os GeoTIFFs. Preserve uma cópia dos identificadores e das datas efetivamente usados em cada execução.

Cada script funciona de forma independente. A execução cria tarefas; não baixa automaticamente os arquivos para o computador.

### Bandas e grade

As seis bandas de saída seguem a ordem: **blue, green, red, nir, swir1, swir2**. Os valores de reflectância são calculados com fator `0.0000275` e deslocamento `-0.2`. São aplicadas máscaras de QA_PIXEL, QA_RADSAT e disponibilidade simultânea nas seis bandas. Os bits utilizados são explicitados nos códigos.

A grade comum utiliza `EPSG:31983` (SIRGAS 2000 / UTM 23S), transformação `[30, 0, 0, 0, -30, 10000000]` e pixels de 30 m. A reflectância tem NoData `-9999`. Na contagem de observações, **0 é ausência de observações válidas dentro do recorte** e `65535` é NoData. Disponibilidade de observações não significa acurácia temática nem ausência garantida de nuvens.

## Separar as bandas no QGIS

1. Abra **Complementos > Console Python**, depois o editor do console.
2. Abra `python/separar_bandas_qgis.py` e execute.
3. Na primeira janela, selecione uma ou mais imagens de reflectância multibanda exportadas pelo GEE.
4. Na segunda janela, escolha a pasta de saída. Será criada uma subpasta `<nome_da_imagem>_bandas` para cada imagem.
5. Carregue os arquivos individuais no QGIS e adicione-os ao conjunto de bandas do SCP na ordem abaixo.

Requer QGIS com GDAL disponível no seu ambiente Python. O script aceita diferentes quantidades de bandas; as imagens de reflectância deste projeto contêm seis bandas.

| Sufixo do arquivo | Banda espectral neste projeto |
|---|---|
| `_banda_01.tif` | Azul (`blue`) |
| `_banda_02.tif` | Verde (`green`) |
| `_banda_03.tif` | Vermelho (`red`) |
| `_banda_04.tif` | Infravermelho próximo (`nir`) |
| `_banda_05.tif` | Infravermelho de ondas curtas 1 (`swir1`) |
| `_banda_06.tif` | Infravermelho de ondas curtas 2 (`swir2`) |

A numeração representa a posição no GeoTIFF exportado, não o número original da banda no sensor Landsat. A separação preserva os valores, o tipo de dado, o NoData declarado, as dimensões, a projeção e a transformação da grade. Não reaplica fatores de escala nem reamostra os pixels. Os arquivos usam compressão LZW, sem perdas.

As imagens originais não são alteradas. Se algum arquivo de saída já existir, a separação daquela imagem é interrompida antes das exportações. A conferência automática verifica a estrutura, a grade, o tipo de dado e o NoData das saídas.

Para gerar as máscaras de exclusão na etapa seguinte, utilize a imagem original com seis bandas, não os arquivos separados.

## Gerar as máscaras no QGIS

1. Abra **Complementos > Console Python**, depois o editor do console.
2. Abra `python/gerar_mascaras_exclusao_qgis.py` e execute.
3. Na primeira janela, selecione as imagens de reflectância com seis bandas. Não selecione os rasters de contagem ou classificação.
4. Na segunda janela, escolha a pasta onde serão salvas as máscaras.

Requer QGIS com GDAL e NumPy disponíveis no seu ambiente Python.

O código verifica cada banda. Um pixel é excluído se qualquer banda apresentar NoData declarado nos metadados, NaN ou infinito. O código não pressupõe que todo zero ou todo valor negativo seja inválido. Se `-9999` não estiver declarado como NoData, corrija o metadado antes da execução.

A máscara recebe **0 para manter** e **1 para excluir**. Nenhum desses valores é NoData na própria máscara. São preservadas a extensão, a projeção e a transformação da imagem de entrada. Arquivos existentes não são sobrescritos.

Para aplicar ao resultado no SCP, use o mapa classificado como conjunto de bandas de entrada e a máscara do ano como camada de exclusão em **Masking bands**. Indique **1** em **Mask class values**, não aplique buffer adicional e defina **0** como NoData da classificação de saída. Os códigos temáticos são 1 = água, 2 = vegetação, 3 = área não vegetada.

A máscara remove ausência de dados; não corrige confusões entre água e sombra. Em análises entre datas, considere a área válida comum e não trate NoData como mudança de cobertura.

## Quantificar cobertura e mudanças

O script de quantificação é independente do QGIS e pode ser usado em outras áreas de estudo. Requer Python 3.10+, NumPy, GDAL/OGR, Tkinter e ambiente gráfico.

1. Ajuste `ANOS` e `CLASSES` no início de `python/quantificar_cobertura_mudancas.py`. Os valores atuais são exemplos do estudo; os códigos de classe devem ser inteiros positivos. Zero é reservado para exclusão.
2. No terminal, a partir da pasta do repositório, execute:

   ```bash
   /usr/bin/python3 python/quantificar_cobertura_mudancas.py
   ```

   Em outros ambientes, use o executável Python que tenha as dependências instaladas.

3. Selecione um GeoTIFF classificado por ano, o vetor de polígonos (`.gpkg` ou `.shp`), a camada, o campo de identificação e a pasta de saída.

Os rasters devem ter uma banda, a mesma extensão, resolução e grade sem rotação, com CRS projetado em metros. O vetor é reprojetado em memória para a grade dos rasters. Feições com a mesma identificação são agrupadas; áreas diferentes não podem se sobrepor nos centros dos pixels.

Cada execução cria uma pasta `analise_<data>_<hora>_<identificador>`, preservando resultados anteriores. As subpastas por ano contêm `resultado_ANO.csv` e os parâmetros em JSON. O último ano também recebe a comparação geral. Os CSVs usam ponto e vírgula, vírgula decimal e codificação UTF-8 com BOM.

As tabelas calculam áreas em hectares, percentuais, permanência, ganhos, perdas e destinos por classe. As comparações abrangem anos consecutivos e o primeiro com o último ano. Todos os resultados usam somente os pixels válidos em todos os anos; os percentuais se referem a essa área comum. As áreas são planas, atribuídas pelo centro do pixel, sem ajuste estatístico de acurácia. Os arquivos JSON registram os caminhos locais das entradas para rastreabilidade.

## Dados necessários

Este repositório contém os códigos. Imagens raster, amostras e limites vetoriais não estão incluídos. Para executar o processamento, é necessário acesso ao Google Earth Engine e à delimitação da área de estudo indicada nos scripts.

## Documentação das fontes

- [Landsat 5 Collection 2 Level-2](https://developers.google.com/earth-engine/datasets/catalog/LANDSAT_LT05_C02_T1_L2)
- [Landsat 7 Collection 2 Level-2](https://developers.google.com/earth-engine/datasets/catalog/LANDSAT_LE07_C02_T1_L2)
- [Landsat 8 Collection 2 Level-2](https://developers.google.com/earth-engine/datasets/catalog/LANDSAT_LC08_C02_T1_L2)
