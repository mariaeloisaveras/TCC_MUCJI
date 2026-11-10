# Cobertura da terra no Mosaico Juréia-Itatins

Códigos de preparação das imagens Landsat e geração das máscaras de exclusão utilizados no desenvolvimento do TCC de Maria Eloisa Véras (UFABC). Os scripts GEE são adaptações do exemplo fornecido pela Profa. Dra. Ângela Terumi Fushita.

## Organização

- `gee/landsat_1991.js`: imagem de referência de 01/06/1991, Landsat 5.
- `gee/landsat_2000.js`: mediana anual, Landsat 7.
- `gee/landsat_2010.js`: mediana de duas cenas, Landsat 5.
- `gee/landsat_2020.js`: mediana anual das cenas Landsat 8 selecionadas.
- `python/gerar_mascaras_exclusao_qgis.py`: seleção de GeoTIFFs e geração das máscaras no QGIS.

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

## Dados necessários

Este repositório contém os códigos. Imagens raster, amostras e limites vetoriais não estão incluídos. Para executar o processamento, é necessário acesso ao Google Earth Engine e à delimitação da área de estudo indicada nos scripts.

## Documentação das fontes

- [Landsat 5 Collection 2 Level-2](https://developers.google.com/earth-engine/datasets/catalog/LANDSAT_LT05_C02_T1_L2)
- [Landsat 7 Collection 2 Level-2](https://developers.google.com/earth-engine/datasets/catalog/LANDSAT_LE07_C02_T1_L2)
- [Landsat 8 Collection 2 Level-2](https://developers.google.com/earth-engine/datasets/catalog/LANDSAT_LC08_C02_T1_L2)
