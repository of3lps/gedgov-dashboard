"""Ingestão dos convênios estaduais de São Paulo (SGRI).

Fonte: Portal de Dados Abertos do Estado de SP (CKAN), dataset
"Convênios com Municípios" da Secretaria de Governo e Relações Institucionais.
Não há API/JSON (datastore inativo) — o acesso é por download de um CSV em lote
com TODOS os municípios de SP. Filtramos apenas as cidades de SP da carteira.

O município é identificado por NOME ("PREFEITURA MUNICIPAL DE ...", sem acento),
não por código IBGE — por isso derivamos o nome esperado a partir de CIDADES e
casamos de forma normalizada (sem acento, maiúsculas).
"""
import csv
import io
import json
import unicodedata

import requests

from config import CIDADES, get_conn

CSV_URL = (
    "https://dadosabertos.sp.gov.br/dataset/"
    "4c5d26af-c246-48d9-a726-613d6051493c/resource/"
    "0d03a6d3-7bb3-45a5-924b-f5233462f346/download/"
    "convenios-sgri-com-municipios.csv"
)


def _norm(texto):
    """Remove acentos, espaços extras e coloca em maiúsculas (para casar nomes)."""
    base = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return base.upper().strip()


def _municipios_sp_da_carteira():
    """Mapeia 'PREFEITURA MUNICIPAL DE <NOME>' -> codigo_ibge para as cidades de SP.

    Deriva o nome a partir do display em CIDADES (ex.: 'Itararé / SP'); assim,
    novas cidades de SP entram automaticamente, sem mapa manual.
    """
    mapa = {}
    for codigo_ibge, nome in CIDADES.items():
        if _norm(nome).endswith("/ SP") or _norm(nome).endswith("/SP"):
            municipio = nome.split("/")[0].strip()
            mapa["PREFEITURA MUNICIPAL DE " + _norm(municipio)] = codigo_ibge
    return mapa


def ingerir_convenios_sp():
    alvo = _municipios_sp_da_carteira()
    if not alvo:
        print("[Convênios SP] Nenhuma cidade de SP na carteira — ingestão ignorada.")
        return

    print(f"[Convênios SP] Baixando CSV da SGRI ({len(alvo)} cidade(s) de SP na carteira)...")
    try:
        resp = requests.get(CSV_URL, timeout=60)
        resp.raise_for_status()
    except Exception as e:
        print(f"[Convênios SP] Erro ao baixar o CSV: {e}")
        return

    # UTF-8 com BOM; delimitador ';'
    texto = resp.content.decode("utf-8-sig")
    leitor = csv.DictReader(io.StringIO(texto), delimiter=";")

    # Agrupa as linhas por código IBGE da carteira
    por_cidade = {ibge: [] for ibge in alvo.values()}
    for linha in leitor:
        ibge = alvo.get(_norm(linha.get("Demandante")))
        if ibge:
            por_cidade[ibge].append(linha)

    try:
        conexao = get_conn()
        cursor = conexao.cursor()
    except Exception as e:
        print(f"[Convênios SP] Falha ao conectar ao banco: {e}")
        return

    for ibge, registros in por_cidade.items():
        # Espelho fiel: limpa e regrava a cidade inteira (idempotente)
        cursor.execute("DELETE FROM raw_convenios_sp WHERE codigo_ibge = %s;", (ibge,))
        for registro in registros:
            cursor.execute(
                "INSERT INTO raw_convenios_sp (payload, codigo_ibge) VALUES (%s, %s);",
                (json.dumps(registro, ensure_ascii=False), ibge),
            )
        conexao.commit()
        print(f"   [Banco] {ibge}: {len(registros)} convênios estaduais carregados.")

    cursor.close()
    conexao.close()
    print("[Convênios SP] Ingestão finalizada.")


if __name__ == "__main__":
    ingerir_convenios_sp()
