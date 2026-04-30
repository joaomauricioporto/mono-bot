from fastapi import FastAPI, Form
from fastapi.responses import PlainTextResponse
import anthropic
import json
import os
from datetime import datetime
import httpx
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

# ============================================================
# BANCO DE DADOS — Supabase
# ============================================================
def salvar_gasto(descricao, valor, categoria, forma_pagamento, telefone):
    data = {
        "data": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "descricao": descricao,
        "valor": valor,
        "categoria": categoria,
        "forma_pagamento": forma_pagamento,
        "telefone": telefone
    }
    r = httpx.post(f"{SUPABASE_URL}/rest/v1/gastos", headers=HEADERS, json=data)
    r.raise_for_status()
    resultado = r.json()
    gasto_id = resultado[0]["id"] if resultado else "?"
    logger.info(f"Gasto salvo: id={gasto_id} descricao={descricao} valor={valor}")
    return gasto_id

def buscar_gastos(telefone, periodo="mes"):
    hoje = datetime.now()
    if periodo == "hoje":
        filtro = hoje.strftime("%Y-%m-%d")
        params = {"telefone": f"eq.{telefone}", "data": f"like.{filtro}%", "order": "id.desc"}
    elif periodo == "semana":
        from datetime import timedelta
        inicio = (hoje - timedelta(days=7)).strftime("%Y-%m-%d")
        params = {"telefone": f"eq.{telefone}", "data": f"gte.{inicio}", "order": "id.desc"}
    else:
        filtro = hoje.strftime("%Y-%m")
        params = {"telefone": f"eq.{telefone}", "data": f"like.{filtro}%", "order": "id.desc"}

    r = httpx.get(f"{SUPABASE_URL}/rest/v1/gastos", headers=HEADERS, params=params)
    r.raise_for_status()
    return r.json()

def remover_ultimo_gasto(telefone):
    r = httpx.get(
        f"{SUPABASE_URL}/rest/v1/gastos",
        headers=HEADERS,
        params={"telefone": f"eq.{telefone}", "order": "id.desc", "limit": "1"}
    )
    r.raise_for_status()
    gastos = r.json()
    if not gastos:
        return None
    gasto = gastos[0]
    httpx.delete(
        f"{SUPABASE_URL}/rest/v1/gastos",
        headers=HEADERS,
        params={"id": f"eq.{gasto['id']}"}
    )
    return gasto

def remover_gasto_por_descricao(telefone, descricao):
    r = httpx.get(
        f"{SUPABASE_URL}/rest/v1/gastos",
        headers=HEADERS,
        params={"telefone": f"eq.{telefone}", "descricao": f"ilike.%{descricao}%", "order": "id.desc", "limit": "1"}
    )
    r.raise_for_status()
    gastos = r.json()
    if not gastos:
        return None
    gasto = gastos[0]
    httpx.delete(
        f"{SUPABASE_URL}/rest/v1/gastos",
        headers=HEADERS,
        params={"id": f"eq.{gasto['id']}"}
    )
    return gasto

def listar_ultimos_gastos(telefone, limite=5):
    r = httpx.get(
        f"{SUPABASE_URL}/rest/v1/gastos",
        headers=HEADERS,
        params={"telefone": f"eq.{telefone}", "order": "id.desc", "limit": str(limite)}
    )
    r.raise_for_status()
    return r.json()

# ============================================================
# IA
# ============================================================
SYSTEM_PROMPT = """Você é um assistente financeiro pessoal via WhatsApp chamado Mono 🐒.
Responda APENAS com JSON válido, sem markdown, sem explicações.

1. REGISTRAR GASTO (ex: "uber 27", "mercado 150 débito", "almoço 35 pix"):
{"tipo": "gasto", "descricao": "descrição", "valor": 27.0, "categoria": "Transporte", "forma_pagamento": "não informado"}
Categorias: Alimentação, Transporte, Lazer, Saúde, Moradia, Educação, Vestuário, Outros

2. RELATÓRIO (ex: "resumo", "quanto gastei hoje", "resumo da semana"):
{"tipo": "relatorio", "periodo": "mes"}
Períodos: hoje, semana, mes

3. REMOVER ÚLTIMO (ex: "remover último", "apagar último", "desfazer"):
{"tipo": "remover_ultimo"}

4. REMOVER ESPECÍFICO (ex: "remover uber", "apagar mercado"):
{"tipo": "remover_item", "descricao": "uber"}

5. HISTÓRICO (ex: "últimos gastos", "o que registrei"):
{"tipo": "historico"}

6. OUTROS (ex: "oi", "ajuda"):
{"tipo": "ajuda"}"""

def interpretar_mensagem(mensagem):
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": mensagem}]
    )
    texto = response.content[0].text.strip()
    if texto.startswith("```"):
        texto = texto.split("```")[1]
        if texto.startswith("json"):
            texto = texto[4:]
    return json.loads(texto.strip())

# ============================================================
# RELATÓRIO
# ============================================================
def gerar_relatorio(telefone, periodo):
    gastos = buscar_gastos(telefone, periodo)
    if not gastos:
        nomes = {"hoje": "hoje", "semana": "nos últimos 7 dias", "mes": "este mês"}
        return f"📭 Nenhum gasto registrado {nomes.get(periodo, 'neste período')}."

    total = sum(g["valor"] for g in gastos)
    por_categoria = {}
    for g in gastos:
        por_categoria[g["categoria"]] = por_categoria.get(g["categoria"], 0) + g["valor"]

    nomes_periodo = {"hoje": "Hoje", "semana": "Últimos 7 dias", "mes": "Este mês"}
    linhas = [f"📊 *Relatório — {nomes_periodo.get(periodo, 'Período')}*\n"]
    for cat, val in sorted(por_categoria.items(), key=lambda x: -x[1]):
        linhas.append(f"  {cat}: R$ {val:.2f}")
    linhas.append(f"\n💰 *Total: R$ {total:.2f}*")
    return "\n".join(linhas)

def gerar_historico(telefone):
    gastos = listar_ultimos_gastos(telefone)
    if not gastos:
        return "📭 Nenhum gasto registrado ainda."
    linhas = ["🧾 *Últimos gastos:*\n"]
    for g in gastos:
        linhas.append(f"• {g['descricao'].capitalize()} — R$ {g['valor']:.2f} ({g['categoria']})")
    return "\n".join(linhas)

# ============================================================
# AJUDA
# ============================================================
MENSAGEM_AJUDA = """🐒 *Olá! Sou o Mono, seu assistente financeiro!*

*📝 Registrar gastos:*
• "mercado 150"
• "uber 27 pix"
• "almoço 35 cartão"

*📊 Ver relatórios:*
• "resumo" ou "resumo da semana"
• "quanto gastei hoje"

*🧾 Ver histórico:*
• "últimos gastos"

*🗑️ Remover gastos:*
• "remover último"
• "remover uber"
• "apagar mercado"

*💡 Escreva de forma natural, eu entendo! 😊*"""

# ============================================================
# WEBHOOK
# ============================================================
@app.post("/webhook", response_class=PlainTextResponse)
async def webhook(
    Body: str = Form(...),
    From: str = Form(...)
):
    mensagem = Body.strip()
    telefone = From
    logger.info(f"Mensagem recebida de {telefone}: {mensagem}")

    try:
        resultado = interpretar_mensagem(mensagem)
        logger.info(f"Interpretado: {resultado}")

        if resultado["tipo"] == "gasto":
            gasto_id = salvar_gasto(
                descricao=resultado["descricao"],
                valor=resultado["valor"],
                categoria=resultado["categoria"],
                forma_pagamento=resultado.get("forma_pagamento", "não informado"),
                telefone=telefone
            )
            resposta = (
                f"✅ *Gasto registrado!* (#{gasto_id})\n\n"
                f"📌 {resultado['descricao'].capitalize()}\n"
                f"💵 R$ {resultado['valor']:.2f}\n"
                f"🏷️ {resultado['categoria']}\n"
                f"💳 {resultado.get('forma_pagamento', 'não informado').capitalize()}"
            )

        elif resultado["tipo"] == "relatorio":
            resposta = gerar_relatorio(telefone, resultado.get("periodo", "mes"))

        elif resultado["tipo"] == "remover_ultimo":
            gasto = remover_ultimo_gasto(telefone)
            if gasto:
                resposta = f"🗑️ *Gasto removido!*\n\n📌 {gasto['descricao'].capitalize()} — R$ {gasto['valor']:.2f}"
            else:
                resposta = "📭 Nenhum gasto encontrado para remover."

        elif resultado["tipo"] == "remover_item":
            gasto = remover_gasto_por_descricao(telefone, resultado.get("descricao", ""))
            if gasto:
                resposta = f"🗑️ *Gasto removido!*\n\n📌 {gasto['descricao'].capitalize()} — R$ {gasto['valor']:.2f}"
            else:
                resposta = "❌ Não encontrei nenhum gasto com esse nome."

        elif resultado["tipo"] == "historico":
            resposta = gerar_historico(telefone)

        else:
            resposta = MENSAGEM_AJUDA

    except Exception as e:
        logger.error(f"Erro ao processar mensagem: {e}")
        resposta = "⚠️ Não entendi sua mensagem. Tente:\n• 'mercado 50'\n• 'resumo'\n• 'remover último'"

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{resposta}</Message>
</Response>"""
    return PlainTextResponse(content=twiml, media_type="application/xml")

@app.get("/")
def health():
    return {"status": "Mono bot rodando! 🐒"}
