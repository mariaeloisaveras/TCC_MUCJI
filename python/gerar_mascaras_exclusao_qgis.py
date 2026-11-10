"""Gera máscaras de exclusão a partir de GeoTIFFs com seis bandas.

Execute no editor do console Python do QGIS.
Selecione as imagens e, em seguida, a pasta de saída nas janelas abertas.
Máscara: 0 = manter; 1 = excluir. A imagem original não é alterada.
"""
from pathlib import Path

import numpy as np
from osgeo import gdal
from qgis.PyQt.QtWidgets import QFileDialog
from qgis.utils import iface

gdal.UseExceptions()
NUMERO_BANDAS = 6


def identificar_pixels_invalidos(imagem):
    """Marca pixels não finitos ou iguais ao NoData declarado em cada banda."""
    invalidos = np.zeros((imagem.RasterYSize, imagem.RasterXSize), dtype=bool)
    for numero in range(1, NUMERO_BANDAS + 1):
        banda = imagem.GetRasterBand(numero)
        valores = banda.ReadAsArray()
        nodata = banda.GetNoDataValue()
        invalidos |= ~np.isfinite(valores)
        if nodata is not None:
            invalidos |= valores == nodata
    return invalidos


def salvar_mascara(caminho, imagem, mascara):
    """Grava uma banda Byte na mesma grade da imagem de entrada."""
    resultado = gdal.GetDriverByName('GTiff').Create(
        str(caminho), imagem.RasterXSize, imagem.RasterYSize, 1,
        gdal.GDT_Byte, options=['COMPRESS=LZW']
    )
    try:
        resultado.SetProjection(imagem.GetProjection())
        resultado.SetGeoTransform(imagem.GetGeoTransform())
        resultado.GetRasterBand(1).WriteArray(mascara)
        # Não definir NoData: tanto 0 quanto 1 são valores válidos da máscara.
    finally:
        resultado = None


def verificar_mascara(caminho, imagem, mascara):
    """Confere os valores, o sistema de referência e o alinhamento da saída."""
    conferencia = gdal.Open(str(caminho), gdal.GA_ReadOnly)
    try:
        if not np.array_equal(conferencia.ReadAsArray(), mascara):
            raise RuntimeError('Os valores gravados diferem da máscara calculada.')
        if (conferencia.GetGeoTransform() != imagem.GetGeoTransform()
                or conferencia.GetProjection() != imagem.GetProjection()):
            raise RuntimeError('A grade de saída difere da imagem de entrada.')
    finally:
        conferencia = None


def criar_mascara(caminho_entrada, pasta_saida):
    """Cria uma máscara por imagem, preservando arquivos já existentes."""
    entrada = Path(caminho_entrada)
    saida = Path(pasta_saida) / f'{entrada.stem}_mascara_exclusao.tif'
    if saida.exists():
        raise FileExistsError(f'O arquivo existente foi preservado: {saida.name}')
    imagem = gdal.Open(str(entrada), gdal.GA_ReadOnly)
    try:
        if imagem.RasterCount != NUMERO_BANDAS:
            raise ValueError(f'A imagem deve conter {NUMERO_BANDAS} bandas.')
        mascara = identificar_pixels_invalidos(imagem).astype(np.uint8)
        salvar_mascara(saida, imagem, mascara)
        verificar_mascara(saida, imagem, mascara)
    finally:
        imagem = None
    return saida


def executar():
    """Solicita as imagens e uma pasta comum de saída; processa cada arquivo."""
    imagens, _ = QFileDialog.getOpenFileNames(
        iface.mainWindow(), 'Selecione as imagens Landsat com seis bandas',
        '', 'GeoTIFF (*.tif *.tiff)'
    )
    if not imagens:
        return
    pasta_saida = QFileDialog.getExistingDirectory(
        iface.mainWindow(), 'Selecione a pasta para salvar as máscaras'
    )
    if not pasta_saida:
        return
    for caminho in imagens:
        try:
            saida = criar_mascara(caminho, pasta_saida)
            print(f'Máscara criada e verificada: {saida}')
        except Exception as erro:
            print(f'Erro em {Path(caminho).name}: {erro}')


executar()
