"""
Ingestão de emendas parlamentares — Portal da Transparência (CSV bulk).

Baixa os ZIPs anuais, cruza dimConvenio.codigo com Número Convênio
e salva autor + tipo_emenda no payload de raw_transferegov.

Uso:
    python src/ingestao_emendas_parlamentares.py
"""

import csv
import io
import os
import time
import zipfile

import psycopg2
import psycopg2.extras
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass

ANOS = list(range(2020, 2026))
ZIP_URL = "https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/{ano}.zip"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/zip, application/octet-stream, */*",
}


def baixar_zip(ano: int) -> bytes | None:
    url = ZIP_URL.format(ano=ano)
    print(f"  Baixando {url}...")
    try:
        r = requests.get(url, headers=HEADERS, timeout=120)
        if r.status_code == 200 and len(r.content) > 10_000:
            return r.content
        print(f"  [{r.status_code}] ignorado.")
    except Exception as e:
        print(f"  Erro: {e}")
    return None


def parsear_zip(conteudo: bytes) -> tuple[dict, dict]:
    """
    Retorna:
        emendas:    {codigo_emenda: {autor, tipo}}
        convenios:  {siconv_numero: codigo_emenda}
    """
    emendas: dict = {}
    convenios: dict = {}

    with zipfile.ZipFile(io.BytesIO(conteudo)) as zf:
        # Autores das emendas
        with zf.open("EmendasParlamentares.csv") as f:
            reader = csv.DictReader(io.StringIO(f.read().decode("latin-1")), delimiter=";")
            for row in reader:
                cod = row.get("Código da Emenda", "").strip()
                autor = row.get("Nome do Autor da Emenda", "").strip()
                tipo = row.get("Tipo de Emenda", "").strip()
                if cod and cod not in ("Sem informação", "S/I") and autor not in ("Sem informação", ""):
                    emendas[cod] = {"autor": autor, "tipo": tipo}

        # Vínculo emenda → convênio SICONV
        with zf.open("EmendasParlamentares_Convenios.csv") as f:
            reader = csv.DictReader(io.StringIO(f.read().decode("latin-1")), delimiter=";")
            for row in reader:
                siconv = row.get("Número Convênio", "").strip()
                cod = row.get("Código da Emenda", "").strip()
                if siconv and cod and cod not in ("Sem informação", "S/I"):
                    convenios[siconv] = cod

    return emendas, convenios


def enriquecer_banco(mapa: dict, conn) -> int:
    """
    mapa: {siconv_codigo: {autor, tipo_emenda}}
    Atualiza o payload JSONB em uma única query via unnest.
    """
    if not mapa:
        return 0

    valores = [(siconv, info["autor"], info["tipo"]) for siconv, info in mapa.items()]

    cur = conn.cursor()
    psycopg2.extras.execute_values(
        cur,
        """
        UPDATE raw_transferegov t
           SET payload = jsonb_set(
                   jsonb_set(payload, '{parlamentar_nome}', to_jsonb(m.autor::text)),
                   '{parlamentar_tipo}', to_jsonb(m.tipo::text)
               )
          FROM (VALUES %s) AS m(siconv, autor, tipo)
         WHERE t.payload->'dimConvenio'->>'codigo' = m.siconv
        """,
        valores,
        page_size=5000
    )
    atualizados = cur.rowcount
    conn.commit()
    cur.close()
    return atualizados


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERRO: DATABASE_URL não configurada.")
        return

    conn = psycopg2.connect(database_url)

    mapa_global: dict = {}

    for ano in ANOS:
        print(f"\n=== {ano} ===")
        conteudo = baixar_zip(ano)
        if not conteudo:
            continue

        emendas, convenios = parsear_zip(conteudo)
        print(f"  Emendas com autor: {len(emendas)} | Vínculos emenda→convênio: {len(convenios)}")

        novos = 0
        for siconv, cod_emenda in convenios.items():
            if cod_emenda in emendas:
                info = emendas[cod_emenda]
                # Ano mais recente vence (sobrescreve)
                mapa_global[siconv] = info
                novos += 1

        print(f"  Mapeados neste ano: {novos}")
        time.sleep(1)

    print(f"\nTotal de convênios mapeados (todos os anos): {len(mapa_global)}")
    print("Enriquecendo banco...")
    total = enriquecer_banco(mapa_global, conn)
    print(f"Registros atualizados no banco: {total}")
    conn.close()
    print("\nConcluído.")


if __name__ == "__main__":
    main()
