"""Calcula áreas e mudanças de cobertura a partir de mapas classificados.

Execute: python3 python/quantificar_cobertura_mudancas.py
Requer Python 3.10+, NumPy, GDAL/OGR e Tkinter, com interface gráfica.

Configure ANOS e CLASSES abaixo. Selecione os rasters, o vetor de áreas
e a pasta de saída nas janelas. Zero é reservado para pixels excluídos.
Os rasters devem ter uma banda, a mesma grade sem rotação e CRS em metros.
A resolução pode variar entre projetos, mas deve ser igual entre os mapas.

As tabelas usam a área válida comum a todos os mapas. As áreas do vetor
são atribuídas pelo centro do pixel e não podem se sobrepor nesses centros.
As áreas calculadas não recebem ajuste estatístico de acurácia.
Cada execução cria uma pasta própria, sem substituir resultados anteriores.
"""

import csv
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()

# Ajuste os anos e os códigos/nomes conforme suas classificações.
ANOS = (1991, 2000, 2010, 2020)
CLASSES = {1: 'Água', 2: 'Vegetação', 3: 'Área não vegetada'}


def carregar_mapas(caminhos):
    """Confere as grades, os códigos e as máscaras de validade."""
    mapas = {}
    validade = {}
    referencia = None
    for ano in sorted(caminhos):
        imagem = gdal.Open(str(caminhos[ano]), gdal.GA_ReadOnly)
        try:
            if imagem.RasterCount != 1:
                raise ValueError(f'{ano}: selecione o mapa classificado de uma banda.')
            crs = osr.SpatialReference()
            crs.ImportFromWkt(imagem.GetProjection())
            grade = imagem.GetGeoTransform()
            if not np.all(np.isfinite(grade)):
                raise ValueError(f'{ano}: a transformação da grade contém valores não finitos.')
            if not crs.IsProjected() or abs(crs.GetLinearUnits() - 1) > 1e-8:
                raise ValueError(f'{ano}: o raster deve usar um CRS projetado em metros.')
            if grade[1] <= 0 or grade[5] >= 0 or not np.allclose(
                    (grade[2], grade[4]), (0, 0), rtol=0, atol=1e-8):
                raise ValueError(f'{ano}: esperada grade sem rotação, orientada para o norte.')
            dados_grade = {
                'largura': imagem.RasterXSize,
                'altura': imagem.RasterYSize,
                'transformacao': grade,
                'projecao': imagem.GetProjection(),
            }
            if referencia is None:
                referencia = dados_grade
            else:
                crs_ref = osr.SpatialReference()
                crs_ref.ImportFromWkt(referencia['projecao'])
                mesma_grade = (
                    imagem.RasterXSize == referencia['largura']
                    and imagem.RasterYSize == referencia['altura']
                    and np.allclose(grade, referencia['transformacao'], rtol=0, atol=1e-8)
                    and bool(crs.IsSame(crs_ref))
                )
                if not mesma_grade:
                    raise ValueError(
                        f'{ano}: a grade difere da referência. '
                        'Alinhe os rasters antes de executar.'
                    )
            banda = imagem.GetRasterBand(1)
            valores = banda.ReadAsArray()
            validos = np.isfinite(valores) & (banda.GetMaskBand().ReadAsArray() != 0)
            nodata = banda.GetNoDataValue()
            if nodata is not None:
                validos &= valores != nodata
            # Zero é reservado à exclusão.
            validos &= valores != 0
            inesperados = validos & ~np.isin(valores, tuple(CLASSES))
            if np.any(inesperados):
                codigos = np.unique(valores[inesperados])
                raise ValueError(f'{ano}: códigos ausentes em CLASSES: {codigos}.')
            mapas[ano] = np.where(validos, valores, 0).astype(np.int64)
            validade[ano] = validos
            print(f'{ano}: {np.count_nonzero(validos):,} pixels válidos.')
        finally:
            imagem = None
    return mapas, validade, referencia


def listar_camadas(caminho):
    fonte = ogr.Open(str(caminho))
    try:
        return [fonte.GetLayerByIndex(i).GetName() for i in range(fonte.GetLayerCount())]
    finally:
        fonte = None


def listar_campos(caminho, camada):
    fonte = ogr.Open(str(caminho))
    try:
        return [campo.GetName() for campo in fonte.GetLayerByName(camada).schema]
    finally:
        fonte = None


def rasterizar_areas(caminho, camada, campo, referencia):
    """Transforma as geometrias em memória e atribui um código a cada área."""
    fonte = ogr.Open(str(caminho))
    try:
        layer = fonte.GetLayerByName(camada)
        if layer is None or campo not in [item.GetName() for item in layer.schema]:
            raise ValueError('Confira a camada e o campo de identificação das áreas.')
        origem = layer.GetSpatialRef()
        if origem is None:
            raise ValueError('O vetor das áreas não tem sistema de referência definido.')
        origem = origem.Clone()
        destino = osr.SpatialReference()
        destino.ImportFromWkt(referencia['projecao'])
        origem.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        destino.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        transformar = osr.CoordinateTransformation(origem, destino)
        geometrias = {}
        for feicao in layer:
            nome = feicao.GetField(campo)
            geometria = feicao.GetGeometryRef()
            if (nome is None or not str(nome).strip()
                    or geometria is None or geometria.IsEmpty()):
                raise ValueError('Há uma feição sem identificação ou sem geometria.')
            if ogr.GT_Flatten(geometria.GetGeometryType()) not in (
                    ogr.wkbPolygon, ogr.wkbMultiPolygon):
                raise ValueError(f'{nome}: a geometria deve ser polígono ou multipolígono.')
            if not geometria.IsValid():
                raise ValueError(f'Geometria inválida em {nome}. Use Corrigir geometrias no QGIS.')
            copia = geometria.Clone()
            copia.Transform(transformar)
            geometrias.setdefault(str(nome).strip(), []).append(copia)
        if not geometrias:
            raise ValueError('O vetor não contém áreas.')
        altura, largura = referencia['altura'], referencia['largura']
        zonas = np.zeros((altura, largura), np.int32)
        nomes = {}
        for codigo, nome in enumerate(sorted(geometrias), start=1):
            memoria = ogr.GetDriverByName('Memory').CreateDataSource('')
            poligonos = memoria.CreateLayer('area', destino, ogr.wkbUnknown)
            for geometria in geometrias[nome]:
                feicao = ogr.Feature(poligonos.GetLayerDefn())
                feicao.SetGeometry(geometria)
                poligonos.CreateFeature(feicao)
            raster = gdal.GetDriverByName('MEM').Create('', largura, altura, 1, gdal.GDT_Byte)
            raster.SetGeoTransform(referencia['transformacao'])
            raster.SetProjection(referencia['projecao'])
            raster.GetRasterBand(1).Fill(0)
            gdal.RasterizeLayer(
                raster, [1], poligonos, burn_values=[1], options=['ALL_TOUCHED=FALSE']
            )
            dentro = raster.ReadAsArray() == 1
            if np.any(dentro & (zonas > 0)):
                raise ValueError(
                    f'As áreas se sobrepõem em centros de pixels, incluindo {nome}. '
                    'Confira o vetor.'
                )
            zonas[dentro] = codigo
            nomes[codigo] = nome
            raster = None
            poligonos = None
            memoria = None
        return zonas, nomes
    finally:
        fonte = None


def percentual(parte, total):
    return 100 * parte / total if total else ''


def gravar_csv(caminho, campos, linhas):
    """Grava em arquivo temporário e substitui a tabela após concluir."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8-sig', newline='',
                                         dir=caminho.parent, delete=False) as arquivo:
            temporario = Path(arquivo.name)
            tabela = csv.DictWriter(arquivo, fieldnames=campos, delimiter=';')
            tabela.writeheader()
            for linha in linhas:
                tabela.writerow({k: f'{v:.6f}'.replace('.', ',') if isinstance(v, float) else v
                                 for k, v in linha.items()})
        os.replace(temporario, caminho)
    finally:
        if temporario is not None:
            temporario.unlink(missing_ok=True)


def analisar(caminhos, vetor, camada, campo, pasta_saida):
    """Cria uma nova pasta de execução e calcula áreas e transições."""
    anos = tuple(sorted(caminhos))
    if len(anos) < 2:
        raise ValueError('Selecione pelo menos dois anos.')
    if not CLASSES or any(type(c) is not int or c <= 0 for c in CLASSES):
        raise ValueError('CLASSES deve conter códigos inteiros positivos; zero é exclusão.')
    if max(CLASSES) > np.iinfo(np.int64).max:
        raise ValueError('Os códigos de CLASSES devem caber em um inteiro de 64 bits.')
    classes = tuple(CLASSES)
    intervalos = list(zip(anos[:-1], anos[1:]))
    if (anos[0], anos[-1]) not in intervalos:
        intervalos.append((anos[0], anos[-1]))
    mapas, validade, grade = carregar_mapas(caminhos)
    zonas, nomes = rasterizar_areas(vetor, camada, campo, grade)
    comum = np.logical_and.reduce([validade[ano] for ano in anos]) & (zonas > 0)
    if not np.any(comum):
        raise ValueError('Não há pixels válidos em todos os mapas dentro das áreas.')
    pixel_ha = abs(grade['transformacao'][1] * grade['transformacao'][5]) / 10000
    recortes = [('TOTAL', comum, zonas > 0)]
    recortes.extend((nome, comum & (zonas == codigo), zonas == codigo)
                    for codigo, nome in nomes.items())
    tabelas = {ano: [] for ano in anos}
    linhas_gerais = []
    for indice_recorte, (nome, mascara, dentro_area) in enumerate(recortes):
        total = int(np.count_nonzero(mascara))
        contagens_ano = {
            ano: np.array([np.count_nonzero(mapas[ano][mascara] == c) for c in classes])
            for ano in anos
        }
        matrizes = {}
        for inicio, fim in intervalos:
            # Índices compactos permitem códigos de classe não consecutivos.
            ordem = np.argsort(classes)
            ordenadas = np.array(classes)[ordem]
            origem = ordem[np.searchsorted(ordenadas, mapas[inicio][mascara])]
            destino = ordem[np.searchsorted(ordenadas, mapas[fim][mascara])]
            matriz = np.bincount(origem * len(classes) + destino,
                                 minlength=len(classes) ** 2).reshape(len(classes), len(classes))
            if not (np.array_equal(matriz.sum(axis=1), contagens_ano[inicio])
                    and np.array_equal(matriz.sum(axis=0), contagens_ano[fim])):
                raise RuntimeError('As transições não correspondem às áreas anuais.')
            matrizes[inicio, fim] = matriz
        for posicao, ano in enumerate(anos):
            anterior = anos[posicao - 1] if posicao else None
            for indice, (classe, descricao) in enumerate(CLASSES.items()):
                quantidade = int(contagens_ano[ano][indice])
                linha = {
                    'ano': ano, 'recorte': nome,
                    'tipo_recorte': 'total' if indice_recorte == 0 else 'area',
                    'classe_codigo': classe, 'classe_nome': descricao,
                    'pixels': quantidade, 'area_ha': quantidade * pixel_ha,
                    'percentual_area_comum': percentual(quantidade, total),
                    'area_comum_recorte_ha': total * pixel_ha,
                    'area_recorte_grade_ha': int(np.count_nonzero(dentro_area)) * pixel_ha,
                    'area_valida_ano_ha': (
                        int(np.count_nonzero(validade[ano] & dentro_area)) * pixel_ha
                    ),
                    'ano_inicial_comparacao': anterior if anterior else '',
                }
                # A linha identifica a mesma classe no ano inicial e no ano final.
                # As colunas destino descrevem a linha dessa classe na matriz.
                comparacoes = [
                    ('', anterior),
                    (f'_desde_{anos[0]}', anos[0] if ano == anos[-1] else None),
                ]
                for sufixo, inicio in comparacoes:
                    valores = dict.fromkeys(
                        ['area_classe_inicial_ha', 'permanencia_ha', 'ganho_ha',
                         'perda_ha', 'saldo_ha']
                        + [f'destino_classe_{c}_ha' for c in classes], ''
                    )
                    if inicio is not None:
                        matriz = matrizes[inicio, ano]
                        permanencia = int(matriz[indice, indice])
                        perda = int(matriz[indice].sum()) - permanencia
                        ganho = int(matriz[:, indice].sum()) - permanencia
                        valores.update({
                            'area_classe_inicial_ha': int(matriz[indice].sum()) * pixel_ha,
                            'permanencia_ha': permanencia * pixel_ha, 'ganho_ha': ganho * pixel_ha,
                            'perda_ha': perda * pixel_ha, 'saldo_ha': (ganho - perda) * pixel_ha,
                            **{f'destino_classe_{c}_ha': int(matriz[indice, j]) * pixel_ha
                               for j, c in enumerate(classes)},
                        })
                    linha.update({chave + sufixo: valor for chave, valor in valores.items()})
                tabelas[ano].append(linha)
            if indice_recorte == 0:
                geral = {'ano': ano}
                for indice, classe in enumerate(classes):
                    identificador = f'classe_{classe}'
                    quantidade = int(contagens_ano[ano][indice])
                    geral[f'{identificador}_ha'] = quantidade * pixel_ha
                    geral[f'{identificador}_percentual'] = percentual(quantidade, total)
                geral['area_comum_total_ha'] = total * pixel_ha
                linhas_gerais.append(geral)
    registro = {
        'executado_em': datetime.now().astimezone().isoformat(),
        'rasters': {str(a): str(Path(caminhos[a]).resolve()) for a in anos},
        'vetor_areas': str(Path(vetor).resolve()), 'camada_areas': camada, 'campo_area': campo,
        'classes': CLASSES, 'grade': grade, 'area_pixel_ha': pixel_ha,
        'area_comum_total_ha': int(np.count_nonzero(comum)) * pixel_ha,
        'criterio_limite_area': 'centro do pixel',
        'area_calculada': 'área plana na grade projetada; sem ajuste de acurácia',
        'intervalos': intervalos,
        'colunas_destino': (
            'Área da classe indicada na linha, no ano inicial, '
            'segundo seu destino no ano final.'
        ),
        'comparacao_acumulada': {'inicio': anos[0], 'fim': anos[-1]},
    }
    pasta_saida = Path(pasta_saida)
    pasta_saida.mkdir(parents=True, exist_ok=True)
    execucao = Path(tempfile.mkdtemp(
        prefix=datetime.now().strftime('analise_%Y%m%d_%H%M%S_'), dir=pasta_saida))
    saidas = {ano: execucao / str(ano) for ano in anos}
    temporarias = {}
    try:
        for ano in anos:
            saidas[ano].parent.mkdir(parents=True, exist_ok=True)
            temporarias[ano] = Path(tempfile.mkdtemp(
                prefix='.analise_nova_', dir=saidas[ano].parent
            ))
            gravar_csv(
                temporarias[ano] / f'resultado_{ano}.csv',
                list(tabelas[ano][0]), tabelas[ano]
            )
            (temporarias[ano] / f'parametros_analise_{ano}.json').write_text(
                json.dumps(registro, ensure_ascii=False, indent=2), encoding='utf-8')
        gravar_csv(temporarias[anos[-1]] / f'comparacao_geral_{anos[0]}_{anos[-1]}.csv',
                   list(linhas_gerais[0]), linhas_gerais)
        for ano in anos:
            temporarias[ano].rename(saidas[ano])
    except Exception:
        shutil.rmtree(execucao)
        raise
    finally:
        for pasta in temporarias.values():
            if pasta.exists():
                shutil.rmtree(pasta)
    for ano in anos:
        print(f'Saída {ano}: {saidas[ano]}')
    print(f'Área comum analisada: {registro["area_comum_total_ha"]:.2f} ha.')
    return registro


def executar():
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog

    janela = tk.Tk()
    janela.withdraw()
    try:
        caminhos = {}
        for ano in ANOS:
            arquivo = filedialog.askopenfilename(
                title=f'Selecione a classificação mascarada de {ano}',
                filetypes=[('GeoTIFF', '*.tif *.tiff')]
            )
            if not arquivo:
                return
            caminhos[ano] = Path(arquivo)
        vetor = filedialog.askopenfilename(
            title='Selecione o vetor de áreas de análise',
            filetypes=[('Vetor', '*.gpkg *.shp')]
        )
        if not vetor:
            return
        camadas = listar_camadas(vetor)
        if not camadas:
            raise ValueError('O vetor não contém camadas.')
        camada = camadas[0]
        if len(camadas) > 1:
            camada = simpledialog.askstring(
                'Camada das áreas', 'Digite o nome da camada:\n' + '\n'.join(camadas)
            )
            if camada is None:
                return
            if camada not in camadas:
                raise ValueError('Nome de camada não encontrado no arquivo.')
        campos = listar_campos(vetor, camada)
        if not campos:
            raise ValueError('A camada não contém campos de identificação.')
        campo = simpledialog.askstring(
            'Identificação das áreas',
            'Campo com o nome ou código de cada área:\n' + ', '.join(campos),
            initialvalue=campos[0]
        )
        if campo is None:
            return
        pasta_saida = filedialog.askdirectory(title='Selecione a pasta de saída')
        if not pasta_saida:
            return
        print('Iniciando análise das classificações...')
        analisar(caminhos, vetor, camada, campo, pasta_saida)
        messagebox.showinfo(
            'Concluído', f'Tabelas salvas em uma nova pasta dentro de:\n{pasta_saida}'
        )
    except Exception as erro:
        print(f'ERRO: {erro}')
        messagebox.showerror('Falha na análise', str(erro))
    finally:
        janela.destroy()


if __name__ == '__main__':
    executar()
