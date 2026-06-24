"""
Ingestão de emendas parlamentares via API SIAFI (Portal da Transparência).

Por que este script existe:
  O bulk CSV do Portal só cobre "Emenda Individual - Transferências com
  Finalidade Definida". Emendas de Comissão, de Bancada e casos onde o
  link proposta→convênio não estava no CSV ficam sem parlamentar_nome.

  Este script usa o endpoint /despesas/documentos-por-favorecido (SIAFI),
  que devolve TODOS os empenhos para um CNPJ, com o campo `autor` já
  resolvido como nome do parlamentar.  Cruzamos o número de proposta/convênio
  presente na observação do empenho com dimConvenio.numero no nosso banco.

Não cobre (→ Frente 2):
  Transferências Especiais (ação "0EC2"/"TRANSFERENCIA ESPECIAL"): são
  repasses diretos ao município, sem SICONV — tratados em script separado.

Uso:
    python src/ingestao_emendas_siafi.py
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

ANOS = list(range(2015, 2027))

# Extrai padrões de número de proposta/convênio: "XXXXXX/YYYY"
_RE_NUM = re.compile(r'\b(\d{3,6}/\d{4})\b')
# Detecta Transferência Especial — pular (Frente 2)
_RE_TE = re.compile(r'TRANSFERENCIA\s+ESPECIAL', re.IGNORECASE)
# Remove tudo que não é dígito de um CNPJ formatado
_RE_CNPJ = re.compile(r'\D')


def _cnpj_limpo(cnpj: str) -> str:
    return _RE_CNPJ.sub("", cnpj)


def _normalizar_numero(raw: str) -> str:
    """'014153/2024' → '14153/2024'  (remove zeros à esquerda do número)."""
    partes = raw.split("/")
    if len(partes) == 2:
        try:
            return f"{int(partes[0])}/{partes[1]}"
        except ValueError:
            pass
    return raw


def _inferir_tipo(autor: str) -> str:
    upper = autor.upper()
    if "COM." in upper or upper.startswith("6") or upper.startswith("5"):
        return "Emenda de Comissão"
    if "BANCADA" in upper:
        return "Emenda de Bancada"
    if "RELAT" in upper:
        return "Emenda de Relator"
    return "Emenda Individual - Transferências com Finalidade Definida"


def _nome_parlamentar(autor_campo: str) -> str:
    """'4161 - MARCOS PEREIRA' → 'MARCOS PEREIRA'."""
    if " - " in autor_campo:
        return autor_campo.split(" - ", 1)[1].strip()
    return autor_campo.strip()


def _get_cnpj_principal(conn, ibge: str) -> str | None:
    """Retorna o CNPJ (limpo, sem pontuação) com mais convênios para o IBGE."""
    cur = conn.cursor()
    cur.execute("""
        SELECT payload->'convenente'->>'cnpjFormatado', COUNT(*)
        FROM raw_transferegov
        WHERE codigo_ibge = %s
          AND payload->'convenente'->>'cnpjFormatado' IS NOT NULL
          AND payload->'convenente'->>'cnpjFormatado' != ''
        GROUP BY 1
        ORDER BY 2 DESC
        LIMIT 1;
    """, (ibge,))
    row = cur.fetchone()
    cur.close()
    return _cnpj_limpo(row[0]) if row else None


def _buscar_empenhos(cnpj: str, ano: int) -> list[dict]:
    """Página completa de empenhos (fase=1) para o CNPJ no ano."""
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
            print(f"    Erro de rede (ano={ano}, pág={pagina}): {e}")
            break

        if r.status_code != 200:
            break

        lote = r.json()
        if not lote:
            break

        resultados.extend(lote)

        # A API retorna até 10 itens por página (padrão)
        if len(lote) < 10:
            break

        pagina += 1
        time.sleep(0.25)

    return resultados


def _extrair_vinculos(empenhos: list[dict]) -> list[dict]:
    """
    Filtra empenhos parlamentares (excluindo Transferências Especiais)
    e devolve lista de {codigo, numero, nome, tipo}.

    Os números na observação do SIAFI podem ser:
      - O código SICONV (ex: "893176/2019") → match em dimConvenio.codigo
      - O número/proposta (ex: "14153/2024")  → match em dimConvenio.numero

    Guardamos os dois separados para a query SQL poder tentar ambos.
    Quando o mesmo número aparece em mais de um empenho (aditamentos etc.),
    a última ocorrência vence.
    """
    # Keyed by (codigo_ou_numero_parte, ano) para deduplicar
    vinculos: dict[tuple, dict] = {}

    for doc in empenhos:
        autor_raw = doc.get("autor", "").strip()

        # Sem parlamentar identificado
        if not autor_raw or autor_raw == "0000":
            continue

        # Pula Comissão Mista de Planos (protocolo orçamentário, não emenda direta)
        if "MISTA" in autor_raw.upper():
            continue

        obs = doc.get("observacao", "") or ""

        # Transferências Especiais → Frente 2
        if _RE_TE.search(obs):
            continue
        acao = doc.get("acao", "") or ""
        if "0EC2" in acao:
            continue

        # Cancelamentos / anulações não vinculam parlamentar
        obs_upper = obs.upper()
        if "ANULACAO" in obs_upper or "CANCELAMENTO" in obs_upper:
            continue

        nums = _RE_NUM.findall(obs)
        if not nums:
            continue

        nome = _nome_parlamentar(autor_raw)
        tipo = _inferir_tipo(autor_raw)

        for num_raw in nums:
            partes = num_raw.split("/")
            codigo_part = partes[0].lstrip("0") or "0"  # parte numérica sem zeros
            ano_part = partes[1]
            num_norm = f"{codigo_part}/{ano_part}"

            key = (codigo_part, ano_part)
            vinculos[key] = {
                "codigo_part": codigo_part,   # ex: "893176" → tenta dimConvenio.codigo
                "numero_norm": num_norm,       # ex: "893176/2019" → tenta dimConvenio.numero
                "nome": nome,
                "tipo": tipo,
            }

    return list(vinculos.values())


def _atualizar_banco(ibge: str, vinculos: list[dict], conn) -> int:
    """
    Para cada vínculo, tenta dois critérios de match em ordem:
      1. dimConvenio.codigo  = codigo_part   (ex: "893176")
      2. dimConvenio.numero  = numero_norm   (ex: "14153/2024")

    Atualiza apenas convênios ainda sem parlamentar_nome.
    """
    if not vinculos:
        return 0

    cur = conn.cursor()
    atualizados = 0

    for v in vinculos:
        cur.execute(
            """
            UPDATE raw_transferegov
               SET payload = jsonb_set(
                       jsonb_set(
                           payload,
                           '{parlamentar_nome}', to_jsonb(%s::text)
                       ),
                       '{parlamentar_tipo}', to_jsonb(%s::text)
                   )
             WHERE codigo_ibge = %s
               AND (payload->>'parlamentar_nome' IS NULL
                    OR payload->>'parlamentar_nome' = '')
               AND (
                   payload->'dimConvenio'->>'codigo' = %s
                   OR payload->'dimConvenio'->>'numero' = %s
               );
            """,
            (v["nome"], v["tipo"], ibge, v["codigo_part"], v["numero_norm"]),
        )
        if cur.rowcount > 0:
            ref = v["numero_norm"]
            print(f"    ✓ {ref:22} → {v['nome']} ({v['tipo'][:30]})")
        atualizados += cur.rowcount

    conn.commit()
    cur.close()
    return atualizados


def main() -> None:
    conn = get_conn()
    total_geral = 0

    for ibge, nome_cidade in CIDADES.items():
        print(f"\n{'='*60}")
        print(f"  {nome_cidade}  (IBGE {ibge})")
        print(f"{'='*60}")

        cnpj = _get_cnpj_principal(conn, ibge)
        if not cnpj:
            print("  Sem CNPJ no banco — pulando.")
            continue

        print(f"  CNPJ principal: {cnpj}")

        vinculos_cidade: list[dict] = []

        for ano in ANOS:
            empenhos = _buscar_empenhos(cnpj, ano)
            novos = _extrair_vinculos(empenhos)
            if novos:
                print(f"  {ano}: {len(empenhos)} empenhos → {len(novos)} vínculos parlamentares")
                vinculos_cidade.extend(novos)
            time.sleep(0.1)

        print(f"\n  Total de vínculos encontrados: {len(vinculos_cidade)}")
        n = _atualizar_banco(ibge, vinculos_cidade, conn)
        print(f"  Registros atualizados no banco: {n}")
        total_geral += n

    conn.close()
    print(f"\n{'='*60}")
    print(f"  CONCLUÍDO — total de registros atualizados: {total_geral}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
