// ============================================================
// Composição de reflectância de superfície — 2020
// Landsat 8 — Collection 2, Level 2
// Método: mediana por banda das cenas selecionadas.
// Adaptado do exemplo fornecido pela Profa. Dra. Ângela Terumi Fushita.
// ============================================================


// 1. PARÂMETROS

var limites = ee.FeatureCollection(
  'projects/evident-plane-274108/assets/MUCJI_continental'
);

var areaEstudo = limites.geometry();
var ano = 2020;

// Filtro inicial de nebulosidade na parte terrestre da cena.
// O filtro por cena complementa as máscaras por pixel.
var limiteNuvens = 10;

// Grade de saída: SIRGAS 2000 / UTM 23S, resolução de 30 m.
// Comparações temporais requerem a mesma grade em todos os anos.
var crsSaida = 'EPSG:31983';
var gradeSaida = [30, 0, 0, 0, -30, 10000000];

var pastaSaida = 'TCC_MUCJI';
var nomeSaida = 'MUCJI_continental_L8_' + ano;


// 2. SELEÇÃO DAS IMAGENS

// O limite final do intervalo temporal é exclusivo.
var colecao = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
  .filterBounds(areaEstudo)
  .filterDate(ano + '-01-01', (ano + 1) + '-01-01')
  .filter(ee.Filter.gte('CLOUD_COVER_LAND', 0))
  .filter(ee.Filter.lt('CLOUD_COVER_LAND', limiteNuvens))
  .sort('system:time_start');

print('Ano de referência:', ano);
print('Número de cenas selecionadas:', colecao.size());
print('Identificadores das cenas:',
  colecao.aggregate_array('LANDSAT_PRODUCT_ID'));
print('Datas das cenas:',
  colecao.aggregate_array('DATE_ACQUIRED'));


// 3. MÁSCARAS DE QUALIDADE E REFLECTÂNCIA

function prepararL8(imagem) {
  imagem = ee.Image(imagem);

  // QA_PIXEL: preenchimento, nuvem dilatada, cirrus,
  // nuvem, sombra de nuvem e neve.
  var bitsQualidade =
    (1 << 0) |
    (1 << 1) |
    (1 << 2) |
    (1 << 3) |
    (1 << 4) |
    (1 << 5);

  var mascaraQualidade = imagem.select('QA_PIXEL')
    .bitwiseAnd(bitsQualidade)
    .eq(0);

  // QA_RADSAT: saturação nas seis bandas utilizadas
  // e oclusão do terreno.
  var bitsSaturacao =
    (1 << 1) |
    (1 << 2) |
    (1 << 3) |
    (1 << 4) |
    (1 << 5) |
    (1 << 6) |
    (1 << 11);

  var mascaraSaturacao = imagem.select('QA_RADSAT')
    .bitwiseAnd(bitsSaturacao)
    .eq(0);

  var bandas = imagem.select(
    ['SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7'],
    ['blue', 'green', 'red', 'nir', 'swir1', 'swir2']
  );

  // Disponibilidade simultânea de dados nas seis bandas.
  var mascaraBandas = bandas.mask()
    .reduce(ee.Reducer.min());

  // Fator de escala e deslocamento da Collection 2.
  var reflectancia = bandas
    .multiply(0.0000275)
    .add(-0.2)
    .updateMask(mascaraQualidade)
    .updateMask(mascaraSaturacao)
    .updateMask(mascaraBandas);

  return ee.Image(
    reflectancia.copyProperties(imagem, ['system:time_start'])
  );
}


// 4. COMPOSIÇÃO, VISUALIZAÇÃO E EXPORTAÇÃO

Map.centerObject(limites, 10);

// Verificação da disponibilidade de cenas antes do processamento.
colecao.size().evaluate(function(numero, erro) {
  if (erro) {
    print('Erro na consulta das cenas:', erro);
    return;
  }

  if (!numero) {
    print('Nenhuma cena encontrada com os filtros definidos.');
    return;
  }

  var preparadas = colecao.map(prepararL8);

  var composicao = preparadas
    .median()
    .clip(areaEstudo)
    .toFloat();

  // Contagem por pixel após a aplicação das máscaras.
  // Zero indica ausência de observações aproveitáveis.
  var observacoes = preparadas
    .select('red')
    .count()
    .unmask(0, false)
    .clip(areaEstudo)
    .rename('observacoes_validas')
    .toUint16();


  // VISUALIZAÇÃO

  Map.addLayer(
    composicao,
    {
      bands: ['red', 'green', 'blue'],
      min: 0,
      max: 0.3,
      gamma: 1.2
    },
    '2020 — cores naturais'
  );

  Map.addLayer(
    composicao,
    {
      bands: ['swir1', 'nir', 'red'],
      min: 0,
      max: 0.4
    },
    '2020 — falsa cor',
    false
  );

  Map.addLayer(
    observacoes,
    {
      min: 0,
      max: numero,
      palette: ['ff00ff', 'ffd166', '2a9d8f', '225ea8']
    },
    '2020 — número de observações',
    false
  );

  Map.addLayer(
    observacoes.eq(0).selfMask(),
    {palette: ['ff00ff']},
    '2020 — sem observações',
    false
  );

  Map.addLayer(
    limites.style({
      color: 'ffff00',
      fillColor: '00000000',
      width: 1
    }),
    {},
    'Limites das unidades de conservação',
    false
  );


  // EXPORTAÇÃO

  // Reflectância nas seis bandas.
  // Valor -9999 reservado para ausência de dados.
  Export.image.toDrive({
    image: composicao.unmask(-9999, false),
    description: nomeSaida + '_mediana',
    folder: pastaSaida,
    fileNamePrefix: nomeSaida + '_mediana',
    region: areaEstudo,
    crs: crsSaida,
    crsTransform: gradeSaida,
    maxPixels: 1e12,
    fileFormat: 'GeoTIFF',
    formatOptions: {
      cloudOptimized: true,
      noData: -9999
    }
  });

  // Contagem de observações.
  // Zero preservado dentro da área de estudo.
  // Valor 65535 reservado para ausência de dados fora do recorte.
  Export.image.toDrive({
    image: observacoes.unmask(65535, false),
    description: nomeSaida + '_observacoes',
    folder: pastaSaida,
    fileNamePrefix: nomeSaida + '_observacoes',
    region: areaEstudo,
    crs: crsSaida,
    crsTransform: gradeSaida,
    maxPixels: 1e12,
    fileFormat: 'GeoTIFF',
    formatOptions: {
      cloudOptimized: true,
      noData: 65535
    }
  });

  print('Composição disponível para inspeção.');
  print('Exportações disponíveis na aba Tasks.');
});
