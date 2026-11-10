// ============================================================
// PREPARAÇÃO DA IMAGEM LANDSAT 5 — 1991
//
// Área: unidades continentais do Mosaico Juréia-Itatins.
// Dados: Landsat Collection 2, Level-2.
// Referência: cena única de 01/06/1991.
//
// Adaptado do exemplo fornecido pela
// Profa. Dra. Ângela Terumi Fushita.
// ============================================================


// ------------------------------------------------------------
// 1. PARÂMETROS
// ------------------------------------------------------------

var limites = ee.FeatureCollection(
  'projects/evident-plane-274108/assets/MUCJI_continental'
);

var areaEstudo = limites.geometry();

var ano = 1991;
var idCena = 'LT05_219077_19910601';
var caminhoColecao = 'LANDSAT/LT05/C02/T1_L2';

// Grade comum às imagens dos quatro anos:
// SIRGAS 2000 / UTM 23S, com pixels de 30 metros.
var crsSaida = 'EPSG:31983';
var gradeSaida = [30, 0, 0, 0, -30, 10000000];

// Destino das exportações no Google Drive.
var pastaSaida = 'TCC_MUCJI';
var nomeSaida = 'MUCJI_continental_L5_' + ano;

// Valores reservados para ausência de dados.
var nodataReflectancia = -9999;
var nodataObservacoes = 65535;


// ------------------------------------------------------------
// 2. PREPARAÇÃO DAS BANDAS E MÁSCARAS
// ------------------------------------------------------------

function prepararImagem(imagem) {
  imagem = ee.Image(imagem);

  // QA_PIXEL: exclui os pixels sinalizados como:
  // bit 0 — preenchimento;
  // bit 1 — nuvem dilatada;
  // bit 3 — nuvem;
  // bit 4 — sombra de nuvem;
  // bit 5 — neve.
  // O bit 2 não é utilizado no Landsat 5.
  var bitsQualidade =
    (1 << 0) |
    (1 << 1) |
    (1 << 3) |
    (1 << 4) |
    (1 << 5);

  var mascaraQualidade = imagem.select('QA_PIXEL')
    .bitwiseAnd(bitsQualidade)
    .eq(0);

  // QA_RADSAT: exclui saturação nas bandas utilizadas
  // e pixels sem leitura do detector.
  var bitsSaturacao =
    (1 << 0) |
    (1 << 1) |
    (1 << 2) |
    (1 << 3) |
    (1 << 4) |
    (1 << 6) |
    (1 << 9);

  var mascaraSaturacao = imagem.select('QA_RADSAT')
    .bitwiseAnd(bitsSaturacao)
    .eq(0);

  // Seleciona e ordena as seis bandas espectrais.
  var bandas = imagem.select(
    ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'],
    ['blue', 'green', 'red', 'nir', 'swir1', 'swir2']
  );

  // Mantém somente pixels com dados nas seis bandas.
  var mascaraBandas = bandas.mask()
    .reduce(ee.Reducer.min());

  // Converte os valores armazenados em reflectância
  // de superfície e aplica as máscaras de qualidade.
  var reflectancia = bandas
    .multiply(0.0000275)
    .add(-0.2)
    .updateMask(mascaraQualidade)
    .updateMask(mascaraSaturacao)
    .updateMask(mascaraBandas);

  return ee.Image(
    reflectancia.copyProperties(
      imagem,
      ['system:time_start']
    )
  );
}


// ------------------------------------------------------------
// 3. FUNÇÃO DE EXPORTAÇÃO
// ------------------------------------------------------------

function exportarImagem(imagem, sufixo, nodata) {
  var nomeArquivo = nomeSaida + sufixo;

  Export.image.toDrive({
    image: imagem.unmask(nodata, false),
    description: nomeArquivo,
    folder: pastaSaida,
    fileNamePrefix: nomeArquivo,
    region: areaEstudo,
    crs: crsSaida,
    crsTransform: gradeSaida,
    maxPixels: 1e12,
    fileFormat: 'GeoTIFF',
    formatOptions: {
      cloudOptimized: true,
      noData: nodata
    }
  });
}


// ------------------------------------------------------------
// 4. SELEÇÃO E IDENTIFICAÇÃO DA CENA
// ------------------------------------------------------------

// A cena foi selecionada previamente por inspeção visual.
// Não há composição por mediana para 1991.
var colecao = ee.ImageCollection(caminhoColecao)
  .filter(ee.Filter.eq('system:index', idCena));

print('Ano de referência:', ano);
print('Número de cenas selecionadas:', colecao.size());

print(
  'Identificadores das cenas:',
  colecao.aggregate_array('LANDSAT_PRODUCT_ID')
);

print(
  'Datas das cenas:',
  colecao.aggregate_array('DATE_ACQUIRED')
);

var resumoNuvens = colecao.toList(colecao.size())
  .map(function(item) {
    var imagem = ee.Image(item);

    return ee.Dictionary({
      data: imagem.get('DATE_ACQUIRED'),
      identificador: imagem.get('system:index'),
      nuvens_cena_inteira_pct: imagem.get('CLOUD_COVER'),
      nuvens_parte_terrestre_pct:
        imagem.get('CLOUD_COVER_LAND')
    });
  });

print('Nebulosidade das cenas (%):', resumoNuvens);
print(
  'A nebulosidade dos metadados refere-se à cena, ' +
  'não apenas à área de estudo.'
);

Map.centerObject(limites, 10);


// ------------------------------------------------------------
// 5. PROCESSAMENTO E DISPONIBILIDADE DE OBSERVAÇÕES
// ------------------------------------------------------------

// Verifica se a cena está disponível antes de processá-la.
colecao.size().evaluate(function(numero, erro) {
  if (erro) {
    print('Erro na consulta da cena:', erro);
    return;
  }

  if (numero === 0) {
    print('A cena informada não foi encontrada.');
    return;
  }

  var colecaoPreparada = colecao.map(prepararImagem);

  var imagemFinal = ee.Image(colecaoPreparada.first())
    .clip(areaEstudo)
    .toFloat();

  // Como há somente uma cena:
  // 1 = observação válida;
  // 0 = ausência de observação válida.
  var observacoes = colecaoPreparada
    .select('red')
    .count()
    .unmask(0, false)
    .clip(areaEstudo)
    .rename('observacoes_validas')
    .toUint16();

  // Calcula a proporção de pixels com observação válida
  // na grade de saída.
  var disponibilidade = observacoes.gt(0)
    .reduceRegion({
      reducer: ee.Reducer.mean(),
      geometry: areaEstudo,
      crs: crsSaida,
      crsTransform: gradeSaida,
      maxPixels: 1e12,
      tileScale: 4
    });

  var percentualDisponivel = ee.Number(
    disponibilidade.get('observacoes_validas')
  ).multiply(100);

  print(
    'Área com observações (%):',
    percentualDisponivel
  );

  print(
    'Área sem observações (%):',
    ee.Number(100).subtract(percentualDisponivel)
  );

  print(
    'Disponibilidade não representa acurácia ' +
    'ou ausência garantida de nuvens.'
  );


  // ----------------------------------------------------------
  // 6. VISUALIZAÇÃO
  // ----------------------------------------------------------

  Map.addLayer(
    imagemFinal,
    {
      bands: ['red', 'green', 'blue'],
      min: 0,
      max: 0.3,
      gamma: 1.2
    },
    ano + ' — cores naturais'
  );

  Map.addLayer(
    imagemFinal,
    {
      bands: ['swir1', 'nir', 'red'],
      min: 0,
      max: 0.4
    },
    ano + ' — falsa cor',
    false
  );

  Map.addLayer(
    observacoes,
    {
      min: 0,
      max: 1,
      palette: ['ff00ff', '225ea8']
    },
    ano + ' — observações válidas',
    false
  );

  Map.addLayer(
    observacoes.eq(0).selfMask(),
    {palette: ['ff00ff']},
    ano + ' — sem observações',
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


  // ----------------------------------------------------------
  // 7. EXPORTAÇÃO DOS PRODUTOS
  // ----------------------------------------------------------

  // Reflectância: seis bandas, com NoData = -9999.
  exportarImagem(
    imagemFinal,
    '_reflectancia',
    nodataReflectancia
  );

  // Observações: preserva 0 e 1 dentro do recorte.
  // Fora dele, utiliza NoData = 65535.
  exportarImagem(
    observacoes,
    '_observacoes',
    nodataObservacoes
  );

  print('Imagem disponível para inspeção.');
  print('Exportações disponíveis na aba Tasks.');
});
