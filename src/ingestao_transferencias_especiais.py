"""
Ingestão de Transferências Especiais ("pix parlamentar") via API SIAFI.

Transferências Especiais são emendas parlamentares individuais que vão direto
para o caixa do município — sem SICONV, sem convênio, sem objeto formal.
O parlamentar indica, o dinheiro entra na conta. Por isso nunca aparecem no
TransfereGov e não são capturadas por nenhum dos outros scripts de ingestão.

Fonte: /despesas/documentos-por-favorecido (Portal da Transparência)
       empenhos com ação "0EC2" ou "TRANSFERENCIA ESPECIAL" na observação.

Uso:
    python src/ingestao_transferencias_especiais.py
"""

import os
import re
import sys
import time

import requests
import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(__file__))
from config import CIDADES, get_conn

CGU_API_KEY = os.environ.get("CGU_API_KEY", "")
if not CGU_API_KEY:
    raise RuntimeError("CGU_API_KEY não configurada. Adicione ao .env.")

BASE = "https://api.portaldatransparencia.gov.br/api-de-dados"
HEADERS = {
    "chave-api-dados": CGU_API_KEY,
    "Accept": "application/json",
    "User-Agent": "GedGov/1.0",
}

ANOS = list(range(2020, 2027))   # TE foi criada em 2020

_RE_TE = re.compile(r'TRANSFERENCIA\s+ESPECIAL', re.IGNORECASE)
_RE_EMENDA = re.compile(r'EMENDA\s+(\d{12})', re.IGNORECASE)
_RE_CNPJ = re.compile(r'\D')


def _cnpj_limpo(cnpj: str) -> str:
    return _RE_CNPJ.sub("", cnpj)


def _nome_parlamentar(autor_campo: str) -> str:
    """'2366 - VANDERLEI MACRIS' → 'VANDERLEI MACRIS'."""
    if " - " in autor_campo:
        return autor_campo.split(" - ", 1)[1].strip()
    return autor_campo.strip()


def _get_cnpjs(conn, ibge: str) -> list[str]:
    """Todos os CNPJs vinculados a essa cidade no banco (prefeitura + fundos)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT payload->'convenente'->>'cnpjFormatado'
        FROM raw_transferegov
        WHERE codigo_ibge = %s
          AND payload->'convenente'->>'cnpjFormatado' IS NOT NULL
          AND payload->'convenente'->>'cnpjFormatado' != ''
        ORDER BY 1;
    """, (ibge,))
    rows = cur.fetchall()
    cur.close()
    return [_cnpj_limpo(r[0]) for r in rows if r[0]]


def _buscar_empenhos(cnpj: str, ano: int) -> list[dict]:
    resultados: list[dict] = []
    pagina = 1
    while True:
        try:
            r = requests.get(
                f"{BASE}/despesas/documentos-por-favorecido",
                params={"codigoPessoa": cnpj, "fase": 1, "ano": ano, "pagina": pagina},
                headers=HEADERS,
                timeout=30,
            )
        except requests.RequestException as e:
            print(f"    Erro de rede: {e}")
            break

        if r.status_code != 200:
            break

        lote = r.json()
        if not lote:
            break

        resultados.extend(lote)
        if len(lote) < 10:
            break

        pagina += 1
        time.sleep(0.25)

    return resultados


def _extrair_tes(empenhos: list[dict], ano: int) -> list[dict]:
    """
    Filtra empenhos de Transferência Especial e monta os payloads
    prontos para gravar no banco.
    """
    tes = []

    for doc in empenhos:
        obs = (doc.get("observacao") or "").strip()
        acao = (doc.get("acao") or "")

        # Identifica TE pela ação ou pela observação
        eh_te = "0EC2" in acao or _RE_TE.search(obs)
        if not eh_te:
            continue

        autor_raw = doc.get("autor", "").strip()
        if not autor_raw or autor_raw == "0000":
            continue

        # Valor monetário: "617.470,00" → float
        valor_str = (doc.get("valor") or "0").replace(".", "").replace(",", ".")
        try:
            valor = float(valor_str)
        except ValueError:
            valor = 0.0

        if valor <= 0:
            continue

        # Extrai código da emenda da observação (12 dígitos)
        m_em = _RE_EMENDA.search(obs)
        cod_emenda = m_em.group(1) if m_em else ""

        # Ano da emenda vem do código ("202323660008" → 2023) ou do ano do empenho
        ano_emenda = int(cod_emenda[:4]) if len(cod_emenda) == 12 else ano

        tes.append({
            "parlamentar": _nome_parlamentar(autor_raw),
            "parlamentar_codigo": autor_raw.split(" - ")[0].strip(),
            "valor": valor,
            "ano": ano_emenda,
            "documento": doc.get("documentoResumido") or doc.get("documento", ""),
            "data": doc.get("data", ""),
            "observacao": obs,
            "cod_emenda": cod_emenda,
            "funcao": doc.get("funcao", ""),
            "subfuncao": doc.get("subfuncao", ""),
        })

    return tes


def _salvar_banco(ibge: str, tes: list[dict], conn) -> int:
    """
    Upsert: insere TE nova ou ignora se o documento já existe
    (unique index em codigo_ibge + documento).
    """
    if not tes:
        return 0

    cur = conn.cursor()
    inseridos = 0

    for te in tes:
        cur.execute(
            """
            INSERT INTO raw_transferencias_especiais (codigo_ibge, payload)
            VALUES (%s, %s)
            ON CONFLICT (codigo_ibge, (payload->>'documento')) DO NOTHING;
            """,
            (ibge, psycopg2.extras.Json(te)),
        )
        if cur.rowcount > 0:
            print(f"    + {te['ano']} | {te['parlamentar']:30} | R$ {te['valor']:>12,.2f}")
            inseridos += cur.rowcount

    conn.commit()
    cur.close()
    return inseridos


def main() -> None:
    conn = get_conn()
    total_geral = 0

    for ibge, nome_cidade in CIDADES.items():
        print(f"\n{'='*60}")
        print(f"  {nome_cidade}  (IBGE {ibge})")
        print(f"{'='*60}")

        cnpjs = _get_cnpjs(conn, ibge)
        if not cnpjs:
            print("  Sem CNPJs no banco — pulando.")
            continue

        print(f"  CNPJs: {', '.join(cnpjs[:3])}{'...' if len(cnpjs)>3 else ''}")

        tes_cidade: list[dict] = []

        for cnpj in cnpjs:
            for ano in ANOS:
                empenhos = _buscar_empenhos(cnpj, ano)
                novos = _extrair_tes(empenhos, ano)
                if novos:
                    print(f"  CNPJ {cnpj} | {ano}: {len(novos)} TEs encontradas")
                tes_cidade.extend(novos)
                time.sleep(0.1)

        # Remove duplicatas pelo documento antes de salvar
        vistos: set[str] = set()
        tes_unicas = []
        for te in tes_cidade:
            if te["documento"] not in vistos:
                vistos.add(te["documento"])
                tes_unicas.append(te)

        print(f"\n  Total de TEs únicas: {len(tes_unicas)}")
        n = _salvar_banco(ibge, tes_unicas, conn)
        print(f"  Registros inseridos no banco: {n}")
        total_geral += n

    conn.close()
    print(f"\n{'='*60}")
    print(f"  CONCLUÍDO — total inserido: {total_geral}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
