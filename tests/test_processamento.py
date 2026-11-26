"""Confere o processamento com rasters e polígonos de resultado conhecido."""

import csv
import importlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from osgeo import gdal, ogr, osr

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
mascaras = importlib.import_module('gerar_mascaras_exclusao_qgis')
bandas = importlib.import_module('separar_bandas_qgis')
analise = importlib.import_module('quantificar_cobertura_mudancas')


class DadosSinteticos(unittest.TestCase):
    def setUp(self):
        captura = patch('sys.stdout', new_callable=io.StringIO)
        captura.start()
        self.addCleanup(captura.stop)
        temporario = tempfile.TemporaryDirectory()
        self.addCleanup(temporario.cleanup)
        self.pasta = Path(temporario.name)
        self.crs = osr.SpatialReference()
        self.crs.ImportFromEPSG(31983)
        self.grade = (500000, 30, 0, 7400000, 0, -30)
        self.contador = 0

    def raster(self, valores, nodata=-9999, grade=None, crs=None):
        self.contador += 1
        caminho = self.pasta / f'imagem_{self.contador}.tif'
        valores = np.asarray(valores, dtype=np.float32)
        if valores.ndim == 2:
            valores = valores[np.newaxis, ...]
        numero, altura, largura = valores.shape
        imagem = gdal.GetDriverByName('GTiff').Create(
            str(caminho), largura, altura, numero, gdal.GDT_Float32
        )
        imagem.SetGeoTransform(self.grade if grade is None else grade)
        imagem.SetProjection((self.crs if crs is None else crs).ExportToWkt())
        for indice, dados in enumerate(valores, start=1):
            banda = imagem.GetRasterBand(indice)
            banda.WriteArray(dados)
            if nodata is not None:
                banda.SetNoDataValue(nodata)
        imagem = None
        return caminho

    def vetor(self, feicoes, crs=None):
        self.contador += 1
        caminho = self.pasta / f'areas_{self.contador}.gpkg'
        fonte = ogr.GetDriverByName('GPKG').CreateDataSource(str(caminho))
        camada = fonte.CreateLayer(
            'areas', self.crs if crs is None else crs, ogr.wkbUnknown
        )
        camada.CreateField(ogr.FieldDefn('nome', ogr.OFTString))
        for nome, wkt in feicoes:
            feicao = ogr.Feature(camada.GetLayerDefn())
            feicao.SetField('nome', nome)
            feicao.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
            camada.CreateFeature(feicao)
        feicao = camada = fonte = None
        return caminho

    @staticmethod
    def retangulo(xmin=500000, xmax=500120):
        return (f'POLYGON (({xmin} 7399940, {xmax} 7399940, '
                f'{xmax} 7400000, {xmin} 7400000, {xmin} 7399940))')

    @staticmethod
    def ler_csv(caminho):
        with caminho.open(encoding='utf-8-sig', newline='') as arquivo:
            return list(csv.DictReader(arquivo, delimiter=';'))


class TestarPreparacao(DadosSinteticos):
    def test_mascara_nodata_nan_infinito_preserva_zero_e_negativos(self):
        dados = np.zeros((6, 2, 4), np.float32)
        dados[0, 0, 0] = -0.2
        dados[1, 0, 2] = -9999
        dados[2, 0, 3] = np.nan
        dados[3, 1, 0] = np.inf
        dados[5, 1, 1] = -np.inf
        entrada = self.raster(dados)
        antes = entrada.read_bytes()
        saida = mascaras.criar_mascara(entrada, self.pasta)
        imagem = gdal.Open(str(saida))
        np.testing.assert_array_equal(
            imagem.ReadAsArray(), [[0, 0, 1, 1], [1, 1, 0, 0]]
        )
        self.assertIsNone(imagem.GetRasterBand(1).GetNoDataValue())
        self.assertEqual(imagem.GetRasterBand(1).DataType, gdal.GDT_Byte)
        self.assertEqual(imagem.GetGeoTransform(), self.grade)
        self.assertEqual(imagem.GetProjection(), self.crs.ExportToWkt())
        imagem = None
        self.assertEqual(entrada.read_bytes(), antes)
        with self.assertRaises(FileExistsError):
            mascaras.criar_mascara(entrada, self.pasta)

    def test_valor_sem_metadado_nodata_nao_e_excluido(self):
        entrada = self.raster(np.full((6, 1, 1), -9999), nodata=None)
        saida = mascaras.criar_mascara(entrada, self.pasta)
        imagem = gdal.Open(str(saida))
        self.assertEqual(imagem.ReadAsArray().item(), 0)
        imagem = None

    def test_mascara_rejeita_quantidade_de_bandas_incorreta(self):
        entrada = self.raster([[1, 2]])
        with self.assertRaisesRegex(ValueError, '6 bandas'):
            mascaras.criar_mascara(entrada, self.pasta)

    def test_separacao_preserva_valores_grade_tipo_e_nodata(self):
        dados = np.array([[[0, -0.2], [np.nan, -9999]], [[1, 2], [3, 4]]])
        entrada = self.raster(dados)
        antes = entrada.read_bytes()
        pasta = bandas.separar_bandas(entrada, self.pasta)
        arquivos = sorted(pasta.glob('*.tif'))
        self.assertEqual(len(arquivos), 2)
        for numero, caminho in enumerate(arquivos):
            imagem = gdal.Open(str(caminho))
            np.testing.assert_array_equal(
                imagem.ReadAsArray(), dados[numero].astype(np.float32)
            )
            self.assertEqual(imagem.RasterCount, 1)
            self.assertEqual(imagem.GetGeoTransform(), self.grade)
            self.assertEqual(imagem.GetProjection(), self.crs.ExportToWkt())
            self.assertEqual(imagem.GetRasterBand(1).DataType, gdal.GDT_Float32)
            self.assertEqual(imagem.GetRasterBand(1).GetNoDataValue(), -9999)
            imagem = None
        with self.assertRaises(FileExistsError):
            bandas.separar_bandas(entrada, self.pasta)
        self.assertEqual(entrada.read_bytes(), antes)


class TestarQuantificacao(DadosSinteticos):
    def entradas(self):
        caminhos = {
            1991: self.raster([[1, 1, 2, 2], [3, 3, 0, 1]]),
            2000: self.raster([[1, 2, 2, 3], [3, 1, 1, 1]]),
            2020: self.raster([[2, 2, 3, 3], [1, 3, 1, -9999]]),
        }
        vetor = self.vetor([
            ('Oeste', self.retangulo(xmax=500060)),
            ('Leste', self.retangulo(xmin=500060)),
        ])
        return caminhos, vetor

    def test_areas_transicoes_e_base_comum(self):
        caminhos, vetor = self.entradas()
        registro = analise.analisar(caminhos, vetor, 'areas', 'nome', self.pasta)
        self.assertAlmostEqual(registro['area_comum_total_ha'], 0.54)
        execucao, = self.pasta.glob('analise_*')
        percentuais = {
            1991: ['33,333333', '33,333333', '33,333333'],
            2000: ['33,333333', '33,333333', '33,333333'],
            2020: ['16,666667', '33,333333', '50,000000'],
        }
        for ano in caminhos:
            linhas = self.ler_csv(execucao / str(ano) / f'resultado_{ano}.csv')
            totais = [l for l in linhas if l['tipo_recorte'] == 'total']
            self.assertEqual(sum(int(l['pixels']) for l in totais), 6)
            for linha, esperado in zip(totais, percentuais[ano]):
                codigo = linha['classe_codigo']
                por_area = [l for l in linhas if l['tipo_recorte'] == 'area'
                            and l['classe_codigo'] == codigo]
                self.assertEqual(sum(int(l['pixels']) for l in por_area),
                                 int(linha['pixels']))
                self.assertEqual(linha['percentual_area_comum'], esperado)
        finais = self.ler_csv(execucao / '2020' / 'resultado_2020.csv')
        agua = next(l for l in finais if l['tipo_recorte'] == 'total'
                    and l['classe_codigo'] == '1')
        esperados = {
            'area_ha': '0,090000', 'permanencia_ha': '0,000000',
            'ganho_ha': '0,090000', 'perda_ha': '0,180000', 'saldo_ha': '-0,090000',
            'destino_classe_2_ha': '0,090000', 'destino_classe_3_ha': '0,090000',
            'perda_ha_desde_1991': '0,180000',
            'destino_classe_2_ha_desde_1991': '0,180000',
        }
        for coluna, esperado in esperados.items():
            self.assertEqual(agua[coluna], esperado, coluna)
        parametros = json.loads(
            (execucao / '2020' / 'parametros_analise_2020.json').read_text()
        )
        self.assertEqual(parametros['intervalos'], [[1991, 2000], [2000, 2020], [1991, 2020]])
        self.assertTrue((execucao / '2020' / 'comparacao_geral_1991_2020.csv').exists())

    def test_execucoes_preservam_resultados_anteriores(self):
        caminhos, vetor = self.entradas()
        analise.analisar(caminhos, vetor, 'areas', 'nome', self.pasta)
        primeira, = self.pasta.glob('analise_*')
        antes = {p.relative_to(primeira): p.read_bytes() for p in primeira.rglob('*') if p.is_file()}
        analise.analisar(caminhos, vetor, 'areas', 'nome', self.pasta)
        self.assertEqual(len(list(self.pasta.glob('analise_*'))), 2)
        for nome, conteudo in antes.items():
            self.assertEqual((primeira / nome).read_bytes(), conteudo)

    def test_classes_nao_consecutivas_e_fora_de_ordem(self):
        caminhos = {1991: self.raster([[10, 30, 20]]),
                    2020: self.raster([[30, 20, 10]])}
        vetor = self.vetor([('Área', self.retangulo())])
        with patch.object(analise, 'CLASSES', {30: 'B', 10: 'A', 20: 'C'}):
            analise.analisar(caminhos, vetor, 'areas', 'nome', self.pasta)
        execucao, = self.pasta.glob('analise_*')
        linhas = self.ler_csv(execucao / '2020' / 'resultado_2020.csv')
        linha = next(l for l in linhas if l['tipo_recorte'] == 'total'
                     and l['classe_codigo'] == '30')
        self.assertEqual(linha['destino_classe_20_ha'], '0,090000')

    def test_rejeita_grades_incompativeis(self):
        caminhos = {1991: self.raster([[1]]),
                    2020: self.raster([[1]], grade=(500001, 30, 0, 7400000, 0, -30))}
        with self.assertRaisesRegex(ValueError, 'grade difere'):
            analise.carregar_mapas(caminhos)

    def test_rejeita_crs_geografico(self):
        geografico = osr.SpatialReference()
        geografico.ImportFromEPSG(4326)
        with self.assertRaisesRegex(ValueError, 'projetado em metros'):
            analise.carregar_mapas({1991: self.raster([[1]], crs=geografico)})

    def test_rejeita_grade_com_rotacao(self):
        with self.assertRaisesRegex(ValueError, 'sem rotação'):
            analise.carregar_mapas({1991: self.raster(
                [[1]], grade=(500000, 30, 1, 7400000, 0, -30)
            )})

    def test_rejeita_grade_nao_finita(self):
        with self.assertRaisesRegex(ValueError, 'não finitos'):
            analise.carregar_mapas({1991: self.raster(
                [[1]], grade=(np.nan, 30, 0, 7400000, 0, -30)
            )})

    def test_validade_considera_nodata_zero_nan_e_mascara_gdal(self):
        caminho = self.raster([[1, 0, -9999, np.nan, 9]])
        imagem = gdal.Open(str(caminho), gdal.GA_Update)
        imagem.CreateMaskBand(gdal.GMF_PER_DATASET)
        imagem.GetRasterBand(1).GetMaskBand().WriteArray(
            np.array([[255, 255, 255, 255, 0]], dtype=np.uint8)
        )
        imagem = None
        mapas, validade, _ = analise.carregar_mapas({1991: caminho})
        np.testing.assert_array_equal(validade[1991], [[True, False, False, False, False]])
        np.testing.assert_array_equal(mapas[1991], [[1, 0, 0, 0, 0]])

    def test_rejeita_codigo_desconhecido_ou_fracionario(self):
        for codigo in (4, 1.5):
            with self.subTest(codigo=codigo):
                with self.assertRaisesRegex(ValueError, 'códigos ausentes'):
                    analise.carregar_mapas({1991: self.raster([[codigo]])})

    def test_rejeita_ausencia_de_area_comum(self):
        caminhos = {1991: self.raster([[1, 0]]), 2020: self.raster([[0, 1]])}
        vetor = self.vetor([('Área', self.retangulo())])
        with self.assertRaisesRegex(ValueError, 'Não há pixels válidos'):
            analise.analisar(caminhos, vetor, 'areas', 'nome', self.pasta)
        self.assertFalse(list(self.pasta.glob('analise_*')))

    def test_rejeita_sobreposicao_entre_areas(self):
        caminhos, _ = self.entradas()
        vetor = self.vetor([('A', self.retangulo()), ('B', self.retangulo())])
        with self.assertRaisesRegex(ValueError, 'sobrepõem'):
            analise.analisar(caminhos, vetor, 'areas', 'nome', self.pasta)

    def test_agrupa_feicoes_com_mesma_identificacao(self):
        caminhos, _ = self.entradas()
        vetor = self.vetor([('Área', self.retangulo()), ('Área', self.retangulo())])
        _, _, referencia = analise.carregar_mapas(caminhos)
        zonas, nomes = analise.rasterizar_areas(vetor, 'areas', 'nome', referencia)
        self.assertEqual(nomes, {1: 'Área'})
        np.testing.assert_array_equal(zonas, np.ones((2, 4)))

    def test_rejeita_geometria_vazia_ou_nao_poligonal(self):
        _, _, referencia = analise.carregar_mapas({1991: self.raster([[1]])})
        for wkt in ('POLYGON EMPTY', 'POINT (500015 7399985)'):
            with self.subTest(wkt=wkt):
                vetor = self.vetor([('Área', wkt)])
                with self.assertRaises(ValueError):
                    analise.rasterizar_areas(vetor, 'areas', 'nome', referencia)

    def test_reprojeta_vetor_para_a_grade(self):
        origem = self.crs.Clone()
        geografico = osr.SpatialReference()
        geografico.ImportFromEPSG(4326)
        for crs in (origem, geografico):
            crs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        geometria = ogr.CreateGeometryFromWkt(self.retangulo())
        geometria.Transform(osr.CoordinateTransformation(origem, geografico))
        vetor = self.vetor([('Área', geometria.ExportToWkt())], crs=geografico)
        _, _, referencia = analise.carregar_mapas({1991: self.raster([[1] * 4] * 2)})
        zonas, _ = analise.rasterizar_areas(vetor, 'areas', 'nome', referencia)
        np.testing.assert_array_equal(zonas, np.ones((2, 4)))

    def test_limite_considera_centro_do_pixel(self):
        vetor = self.vetor([('Faixa', self.retangulo(xmax=500010))])
        _, _, referencia = analise.carregar_mapas({1991: self.raster([[1]])})
        zonas, _ = analise.rasterizar_areas(vetor, 'areas', 'nome', referencia)
        self.assertEqual(zonas.item(), 0)


if __name__ == '__main__':
    unittest.main()
