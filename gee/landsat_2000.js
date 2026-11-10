// ============================================================
// Composição anual de reflectância de superfície
// Landsat 7 — Collection 2, Level-2
// Método de composição: mediana por banda
// Adaptado do exemplo fornecido pela Profa. Dra. Ângela Terumi Fushita.
// ============================================================

// 1. PARÂMETROS

var ano = 2000;
var inicio = ee.Date.fromYMD(ano, 1, 1);
var fim = inicio.advance(1, 'year');
var limites = ee.FeatureCollection(
  'projects/evident-plane-274108/assets/MUCJI_continental'
);
var areaEstudo = limites.geometry();
var caminho = 'LANDSAT/LE07/C02/T1_L2';
var margemMetros = 60; // Ampliação da máscara ao redor de nuvens e sombras.
var habilitarExportacao = true;
var visualizarCenasIndividuais = false;
var compararCenaNovembro = false;
var pastaSaida = 'TCC_MUCJI';
var nomeSaida = 'MUCJI_continental_L7_' + ano;
var crsSaida = 'EPSG:31983';
var gradeSaida = [30, 0, 0, 0, -30, 10000000];
var rgb = {
  bands: ['red', 'green', 'blue'],
  min: 0,
  max: 0.3,
  gamma: 1.2
};

// Lista vazia: utilizar todas as cenas disponíveis no ano e no recorte.
// Não é aplicado filtro de nebulosidade por cena neste script.
// Preencher esta lista altera o conjunto de imagens utilizado.
// Exemplo de identificador: 'LE07_219077_20001124'.
var idsSelecionados = [];

// 2. SELEÇÃO DAS IMAGENS

var colecao = ee.ImageCollection(caminho)
  .filterBounds(areaEstudo)
  .filterDate(inicio, fim)
  .sort('system:time_start');
if (idsSelecionados.length > 0) {
  colecao = colecao.filter(ee.Filter.inList('system:index', idsSelecionados));
}

// 3. PREPARAÇÃO DAS IMAGENS

function prepararL7(imagem) {
  imagem = ee.Image(imagem);
  var qa = imagem.select('QA_PIXEL');
  // Excluir preenchimento, nuvem dilatada, nuvem, sombra e neve.
  // Água não é excluída.
  var qualidade = qa.bitwiseAnd(
    (1 << 0) | (1 << 1) | (1 << 3) | (1 << 4) | (1 << 5)
  ).eq(0);
  if (margemMetros > 0) {
    var contaminacao = qa.bitwiseAnd(
      (1 << 1) | (1 << 3) | (1 << 4)
    ).neq(0);
    var ampliada = contaminacao.focalMax({
      radius: margemMetros,
      kernelType: 'circle',
      units: 'meters',
      iterations: 1
    });
    qualidade = qualidade.and(ampliada.not());
  }
  // Saturação nas seis bandas utilizadas e pixels sem leitura.
  var saturacao = imagem.select('QA_RADSAT').bitwiseAnd(
    (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) |
    (1 << 4) | (1 << 6) | (1 << 9)
  ).eq(0);
  var bandas = imagem.select(
    ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'],
    ['blue', 'green', 'red', 'nir', 'swir1', 'swir2']
  );
  var mascaraComum = bandas.mask().reduce(ee.Reducer.min());
  var reflectancia = bandas.multiply(0.0000275).add(-0.2);

  return ee.Image(
    reflectancia
      .updateMask(qualidade)
      .updateMask(saturacao)
      .updateMask(mascaraComum)
      .copyProperties(imagem, ['system:time_start'])
  );
}

// 4. FUNÇÕES DE DIAGNÓSTICO

function contar(imagens) {
  return imagens
    .select('red')
    .count()
    .unmask(0, false)
    .clip(areaEstudo)
    .rename('observacoes_validas')
    .toUint16();
}

function disponibilidade(contagem) {
  var resultado = contagem.gt(0).rename('disponivel').reduceRegion({
    reducer: ee.Reducer.mean(),
    geometry: areaEstudo,
    crs: crsSaida,
    crsTransform: gradeSaida,
    maxPixels: 1e12,
    tileScale: 4
  });

  return ee.Number(resultado.get('disponivel')).multiply(100);
}

// Exportar na mesma grade, preservando a identificação de NoData.
function exportarImagem(imagem, sufixo, valorSemDados) {
  Export.image.toDrive({
    image: imagem.unmask(valorSemDados, false),
    description: nomeSaida + sufixo,
    fileNamePrefix: nomeSaida + sufixo,
    folder: pastaSaida,
    region: areaEstudo,
    crs: crsSaida,
    crsTransform: gradeSaida,
    maxPixels: 1e12,
    fileFormat: 'GeoTIFF',
    formatOptions: {
      cloudOptimized: true,
      noData: valorSemDados
    }
  });
}

// 5. COMPOSIÇÃO ANUAL E CONTAGEM DE OBSERVAÇÕES

Map.centerObject(limites, 10);
colecao.size().evaluate(function(n, erro) {
  if (erro) {
    print('Erro na consulta:', erro);
    return;
  }

  if (!n) {
    print('Nenhuma cena encontrada. Verifique os filtros.');
    return;
  }

  var preparadas = colecao.map(prepararL7);
  var mediana = preparadas.median().clip(areaEstudo).toFloat();
  var observacoes = contar(preparadas);
  var cobertura = disponibilidade(observacoes);
  print('Número de cenas Landsat 7:', n);
  print('Área com observações (%):', cobertura);
  print('Área sem observações (%):', ee.Number(100).subtract(cobertura));
  print('Disponibilidade não representa acurácia ou ausência garantida de nuvens.');

  // 6. VISUALIZAÇÃO

  Map.addLayer(mediana, rgb, '2000 — mediana Landsat 7', true);
  Map.addLayer(observacoes.eq(0).selfMask(), {palette: ['ff00ff']},
    '2000 — lacunas da composição', false);
  Map.addLayer(observacoes, {min: 0, max: n, palette: ['ffffff', 'ffd166', '006d77']},
    '2000 — número de observações', false);

  // Comparação opcional; não interfere na composição.
  if (compararCenaNovembro) {
    // Referência visual independente: a cena de novembro tem máscara idêntica.
    var novembro = prepararL7(ee.Image(caminho + '/LE07_219077_20001124'));
    Map.addLayer(novembro.clip(areaEstudo), rgb, 'Referência — 24/11/2000', false);
    print('24/11 isolada — área com observações (%):',
      disponibilidade(contar(ee.ImageCollection.fromImages([novembro]))));
  }

  // Listar as cenas para registrar datas e selecionar as adequadas.
  var resumo = colecao.toList(n).map(function(item) {
    return ee.Image(item).toDictionary([
      'system:index', 'DATE_ACQUIRED', 'CLOUD_COVER_LAND'
    ]);
  });
  print('Cenas utilizadas:', resumo);
  if (visualizarCenasIndividuais) {
    resumo.evaluate(function(cenas, falha) {
      if (falha) { print('Erro na listagem:', falha); return; }
      cenas.forEach(function(d) {
        Map.addLayer(prepararL7(ee.Image(caminho + '/' + d['system:index']))
          .clip(areaEstudo), rgb,
          'Cena | ' + d.DATE_ACQUIRED + ' | ' + d['system:index'], false);
      });
    });
  }

  // 7. EXPORTAÇÃO
  // Reflectância: -9999 representa NoData.
  // Contagem: zero significa nenhuma observação; 65535 indica NoData.
  if (habilitarExportacao) {
    exportarImagem(mediana, '_mediana', -9999);
    exportarImagem(observacoes, '_observacoes', 65535);
    print('Tarefas de exportação disponíveis na aba Tasks.');
  }
});
