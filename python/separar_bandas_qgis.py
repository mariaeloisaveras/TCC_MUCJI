"""
Separação de imagens multibanda em arquivos GeoTIFF individuais.

Entrada:
    Uma ou mais imagens GeoTIFF multibanda.

Saída:
    Uma subpasta por imagem, contendo um arquivo para cada banda.

Execução:
    Editor do Console Python do QGIS.

As imagens originais não são alteradas.
"""

from pathlib import Path

from osgeo import gdal
from qgis.PyQt.QtWidgets import QFileDialog
from qgis.utils import iface

gdal.UseExceptions()


def separar_bandas(caminho_entrada, pasta_saida):
    """Exporta cada banda, preservando os dados e a grade original."""
    entrada = Path(caminho_entrada)
    pasta_imagem = Path(pasta_saida) / f"{entrada.stem}_bandas"

    imagem = gdal.Open(str(entrada), gdal.GA_ReadOnly)

    try:
        # Define os nomes antes de iniciar a exportação.
        arquivos = [
            pasta_imagem / f"{entrada.stem}_banda_{numero:02d}.tif"
            for numero in range(1, imagem.RasterCount + 1)
        ]

        # Evita sobrescrever bandas exportadas anteriormente.
        existentes = [arquivo for arquivo in arquivos if arquivo.exists()]

        if existentes:
            raise FileExistsError(
                f"Já existem arquivos em: {pasta_imagem}. "
                "Escolha outra pasta de saída."
            )

        pasta_imagem.mkdir(parents=True, exist_ok=True)

        for numero, arquivo in enumerate(arquivos, start=1):
            # Seleciona somente uma banda da imagem original.
            resultado = gdal.Translate(
                str(arquivo),
                imagem,
                options=gdal.TranslateOptions(
                    format="GTiff",
                    bandList=[numero],
                    creationOptions=["COMPRESS=LZW"]
                )
            )

            # Fecha o arquivo para concluir a gravação.
            resultado = None

            verificar_banda(arquivo, imagem, numero)

            print(f"Banda {numero} criada e verificada: {arquivo}")

    finally:
        imagem = None

    return pasta_imagem


def verificar_banda(caminho, imagem_original, numero):
    """Confere a estrutura, a grade, o tipo de dado e o NoData."""
    banda_exportada = gdal.Open(str(caminho), gdal.GA_ReadOnly)

    try:
        if banda_exportada.RasterCount != 1:
            raise RuntimeError("O arquivo de saída deve conter uma banda.")

        if (
            banda_exportada.RasterXSize != imagem_original.RasterXSize
            or banda_exportada.RasterYSize != imagem_original.RasterYSize
            or banda_exportada.GetGeoTransform()
            != imagem_original.GetGeoTransform()
            or banda_exportada.GetProjection()
            != imagem_original.GetProjection()
        ):
            raise RuntimeError("A grade de saída difere da imagem original.")

        origem = imagem_original.GetRasterBand(numero)
        destino = banda_exportada.GetRasterBand(1)

        if origem.DataType != destino.DataType:
            raise RuntimeError("O tipo de dado da banda foi alterado.")

        nodata_origem = origem.GetNoDataValue()
        nodata_destino = destino.GetNoDataValue()

        # repr também permite comparar NoData definido como NaN.
        if repr(nodata_origem) != repr(nodata_destino):
            raise RuntimeError("O valor NoData da banda foi alterado.")

    finally:
        banda_exportada = None


def executar():
    """Solicita as imagens e a pasta de saída."""
    imagens, _ = QFileDialog.getOpenFileNames(
        iface.mainWindow(),
        "Selecione as imagens multibanda",
        "",
        "GeoTIFF (*.tif *.tiff)"
    )

    if not imagens:
        return

    pasta_saida = QFileDialog.getExistingDirectory(
        iface.mainWindow(),
        "Selecione a pasta para salvar as bandas"
    )

    if not pasta_saida:
        return

    for caminho in imagens:
        try:
            pasta = separar_bandas(caminho, pasta_saida)
            print(f"Separação concluída: {pasta}")

        except Exception as erro:
            print(f"Erro em {Path(caminho).name}: {erro}")


executar()