from fastapi import FastAPI, Form, BackgroundTasks
from fastapi.responses import PlainTextResponse
import anthropic
import json
import os
from datetime import datetime, timedelta
import httpx
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
SUPABASE_API = f"{SUPABASE_URL}/rest/v1"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

# ============================================================
# HELPERS
# ============================================================
def get(url, params=None):
    r = httpx.get(url, headers=HEADERS, params=params)
    r.raise_for_status()
    return r.json()

def post(url, data):
    r = httpx.post(url, headers=HEADERS, json=data)
    r.raise_for_status()
    return r.json()

def delete(url, params):
    httpx.delete(url, headers=HEADERS, params=params)

def filtro_mes(hoje, offset=0):
    """Retorna o prefixo YYYY-MM para o mês atual ou anterior."""
    mes = hoje.month - offset
    ano = hoje.year
    while mes <= 0:
        mes += 12
        ano -= 1
    return f"{ano}-{mes:02d}"

def buscar_gastos_periodo(telefone, periodo="mes"):
    hoje = datetime.now()
    url = f"{SUPABASE_API}/gastos"
    if periodo == "hoje":
        params = {"telefone": f"eq.{telefone}", "data": f"like.{hoje.strftime('%Y-%m-%d')}%25", "order": "id.desc"}
    elif periodo == "semana":
        inicio = (hoje - timedelta(days=7)).strftime("%Y-%m-%d")
        params = {"telefone": f"eq.{telefone}", "data": f"gte.{inicio}", "order": "id.desc"}
    else:
        params = {"telefone": f"eq.{telefone}", "data": f"like.{filtro_mes(hoje)}%25", "order": "id.desc"}
    return get(url, params)

def buscar_gastos_mes_offset(telefone, offset=0):
    """Busca gastos de um mês específico. offset=0 = mês atual, offset=1 = mês passado."""
    hoje = datetime.now()
    prefixo = filtro_mes(hoje, offset)
    url = f"{SUPABASE_API}/gastos"
    params = {"telefone": f"eq.{telefone}", "data": f"like.{prefixo}%25", "order": "id.desc"}
    return get(url, params)

# ============================================================
# GASTOS
# ============================================================
def salvar_gasto(descricao, valor, categoria, forma_pagamento, telefone):
    data = {
        "data": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "descricao": descricao, "valor": valor,
        "categoria": categoria, "forma_pagamento": forma_pagamento,
        "telefone": telefone
    }
    resultado = post(f"{SUPABASE_API}/gastos", data)
    return resultado[0]["id"] if resultado else "?"

def remover_ultimo_gasto(telefone):
    url = f"{SUPABASE_API}/gastos"
    gastos = get(url, {"telefone": f"eq.{telefone}", "order": "id.desc", "limit": "1"})
    if not gastos: return None
    gasto = gastos[0]
    delete(url, {"id": f"eq.{gasto['id']}"})
    return gasto

def remover_gasto_por_descricao(telefone, descricao):
    url = f"{SUPABASE_API}/gastos"
    gastos = get(url, {"telefone": f"eq.{telefone}", "order": "id.desc", "limit": "50"})
    filtrados = [g for g in gastos if descricao.lower() in g.get("descricao", "").lower()]
    if not filtrados: return None
    gasto = filtrados[0]
    delete(url, {"id": f"eq.{gasto['id']}"})
    return gasto

def remover_gasto_por_categoria(telefone, categoria, valor=None):
    url = f"{SUPABASE_API}/gastos"
    gastos = get(url, {"telefone": f"eq.{telefone}", "order": "id.desc", "limit": "50"})
    filtrados = [g for g in gastos if categoria.lower() in g.get("categoria", "").lower()]
    if not filtrados: return None
    if valor:
        por_valor = [g for g in filtrados if abs(g["valor"] - valor) < 0.01]
        if not por_valor: return None
        gasto = por_valor[0]
    else:
        gasto = filtrados[0]
    delete(url, {"id": f"eq.{gasto['id']}"})
    return gasto

def listar_ultimos_gastos(telefone, limite=5):
    return get(f"{SUPABASE_API}/gastos", {"telefone": f"eq.{telefone}", "order": "id.desc", "limit": str(limite)})

# ============================================================
# RECEITAS
# ============================================================
def salvar_receita(descricao, valor, categoria, telefone):
    data = {
        "data": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "descricao": descricao, "valor": valor,
        "categoria": categoria, "telefone": telefone
    }
    resultado = post(f"{SUPABASE_API}/receitas", data)
    return resultado[0]["id"] if resultado else "?"

def buscar_receitas_periodo(telefone, periodo="mes"):
    hoje = datetime.now()
    url = f"{SUPABASE_API}/receitas"
    if periodo == "hoje":
        params = {"telefone": f"eq.{telefone}", "data": f"like.{hoje.strftime('%Y-%m-%d')}%25", "order": "id.desc"}
    elif periodo == "semana":
        inicio = (hoje - timedelta(days=7)).strftime("%Y-%m-%d")
        params = {"telefone": f"eq.{telefone}", "data": f"gte.{inicio}", "order": "id.desc"}
    else:
        params = {"telefone": f"eq.{telefone}", "data": f"like.{filtro_mes(datetime.now())}%25", "order": "id.desc"}
    return get(url, params)

# ============================================================
# METAS
# ============================================================
def salvar_meta(telefone, categoria, limite):
    url = f"{SUPABASE_API}/metas"
    # Verifica se já existe meta para essa categoria
    existentes = get(url, {"telefone": f"eq.{telefone}", "order": "id.desc", "limit": "50"})
    for m in existentes:
        if categoria.lower() in m.get("categoria", "").lower():
            # Atualiza
            httpx.patch(url, headers=HEADERS, params={"id": f"eq.{m['id']}"}, json={"limite": limite})
            return "atualizada"
    data = {"telefone": telefone, "categoria": categoria, "limite": limite}
    post(url, data)
    return "criada"

def buscar_metas(telefone):
    return get(f"{SUPABASE_API}/metas", {"telefone": f"eq.{telefone}", "order": "categoria.asc"})

# ============================================================
# LEMBRETES
# ============================================================
def salvar_lembrete(telefone, descricao, valor, dia_vencimento):
    data = {"telefone": telefone, "descricao": descricao, "valor": valor, "dia_vencimento": dia_vencimento}
    resultado = post(f"{SUPABASE_API}/lembretes", data)
    return resultado[0]["id"] if resultado else "?"

def buscar_lembretes(telefone):
    return get(f"{SUPABASE_API}/lembretes", {"telefone": f"eq.{telefone}", "order": "dia_vencimento.asc"})

def remover_lembrete(telefone, descricao):
    url = f"{SUPABASE_API}/lembretes"
    lembretes = get(url, {"telefone": f"eq.{telefone}", "order": "id.desc", "limit": "50"})
    filtrados = [l for l in lembretes if descricao.lower() in l.get("descricao", "").lower()]
    if not filtrados: return None
    lembrete = filtrados[0]
    delete(url, {"id": f"eq.{lembrete['id']}"})
    return lembrete

# ============================================================
# IA
# ============================================================
SYSTEM_PROMPT = """Você é um assistente financeiro pessoal via WhatsApp chamado Paylo.IA 🐒.
Responda APENAS com JSON válido, sem markdown, sem explicações.

1. REGISTRAR GASTO (ex: "uber 27", "mercado 150 débito", "almoço 35 pix"):
{"tipo": "gasto", "descricao": "descrição", "valor": 27.0, "categoria": "Transporte", "forma_pagamento": "não informado"}
Categorias: Alimentação, Transporte, Lazer, Saúde, Moradia, Educação, Vestuário, Outros

2. REGISTRAR RECEITA (ex: "recebi salário 3000", "freelance 500", "entrada 1200"):
{"tipo": "receita", "descricao": "salário", "valor": 3000.0, "categoria": "Salário"}
Categorias receita: Salário, Freelance, Investimento, Presente, Outros

3. RELATÓRIO GASTOS (ex: "resumo", "quanto gastei hoje", "resumo da semana"):
{"tipo": "relatorio", "periodo": "mes"}
Períodos: hoje, semana, mes

4. RELATÓRIO POR FORMA DE PAGAMENTO (ex: "quanto gastei no cartão", "total no pix"):
{"tipo": "relatorio_pagamento", "forma": "cartão", "periodo": "mes"}

5. SALDO DISPONÍVEL (ex: "saldo", "quanto tenho", "quanto sobrou"):
{"tipo": "saldo", "periodo": "mes"}

6. COMPARATIVO MESES (ex: "comparar meses", "esse mês vs mês passado", "comparativo"):
{"tipo": "comparativo"}

7. DEFINIR META (ex: "meta alimentação 500", "limite lazer 300", "definir meta transporte 200"):
{"tipo": "definir_meta", "categoria": "Alimentação", "limite": 500.0}

8. VER METAS (ex: "minhas metas", "ver limites", "metas"):
{"tipo": "ver_metas"}

9. ADICIONAR LEMBRETE (ex: "lembrete aluguel 1200 dia 5", "conta luz 80 vence dia 10"):
{"tipo": "adicionar_lembrete", "descricao": "aluguel", "valor": 1200.0, "dia_vencimento": 5}

10. VER LEMBRETES (ex: "meus lembretes", "contas fixas", "ver lembretes"):
{"tipo": "ver_lembretes"}

11. REMOVER LEMBRETE (ex: "remover lembrete aluguel", "apagar conta luz"):
{"tipo": "remover_lembrete", "descricao": "aluguel"}

12. REMOVER ÚLTIMO (ex: "remover último", "desfazer"):
{"tipo": "remover_ultimo"}

13. REMOVER ESPECÍFICO (ex: "remover uber", "apagar mercado"):
{"tipo": "remover_item", "descricao": "uber"}

14. REMOVER POR CATEGORIA (ex: "remover lazer", "extorno 100 transporte"):
{"tipo": "remover_categoria", "categoria": "Lazer", "valor": null}

15. HISTÓRICO (ex: "últimos gastos", "o que registrei"):
{"tipo": "historico"}

16. OUTROS (ex: "oi", "ajuda"):
{"tipo": "ajuda"}"""

def interpretar_mensagem(mensagem):
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
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
# RELATÓRIOS
# ============================================================
def gerar_relatorio(telefone, periodo):
    gastos = buscar_gastos_periodo(telefone, periodo)
    if not gastos:
        nomes = {"hoje": "hoje", "semana": "nos últimos 7 dias", "mes": "este mês"}
        return f"📭 Nenhum gasto registrado {nomes.get(periodo, 'neste período')}."
    total = sum(g["valor"] for g in gastos)
    por_cat = {}
    for g in gastos:
        por_cat[g["categoria"]] = por_cat.get(g["categoria"], 0) + g["valor"]
    nomes_p = {"hoje": "Hoje", "semana": "Últimos 7 dias", "mes": "Este mês"}
    linhas = [f"📊 *Relatório — {nomes_p.get(periodo, 'Período')}*\n"]
    for cat, val in sorted(por_cat.items(), key=lambda x: -x[1]):
        linhas.append(f"  {cat}: R$ {val:.2f}")
    linhas.append(f"\n💰 *Total: R$ {total:.2f}*")

    # Verifica metas
    metas = buscar_metas(telefone)
    alertas = []
    for meta in metas:
        cat = meta["categoria"]
        limite = meta["limite"]
        gasto_cat = por_cat.get(cat, 0)
        pct = (gasto_cat / limite) * 100 if limite > 0 else 0
        if pct >= 100:
            alertas.append(f"🚨 *{cat}*: limite de R$ {limite:.2f} ultrapassado!")
        elif pct >= 80:
            alertas.append(f"⚠️ *{cat}*: {pct:.0f}% do limite (R$ {gasto_cat:.2f}/R$ {limite:.2f})")
    if alertas:
        linhas.append("\n" + "\n".join(alertas))
    return "\n".join(linhas)

def gerar_relatorio_pagamento(telefone, forma, periodo):
    todos = buscar_gastos_periodo(telefone, periodo)
    gastos = [g for g in todos if forma.lower() in g.get("forma_pagamento", "").lower()]
    nomes = {"hoje": "hoje", "semana": "nos últimos 7 dias", "mes": "este mês"}
    if not gastos:
        return f"📭 Nenhum gasto no {forma} {nomes.get(periodo, 'neste período')}."
    total = sum(g["valor"] for g in gastos)
    por_cat = {}
    for g in gastos:
        por_cat[g["categoria"]] = por_cat.get(g["categoria"], 0) + g["valor"]
    nomes2 = {"hoje": "Hoje", "semana": "Últimos 7 dias", "mes": "Este mês"}
    linhas = [f"💳 *{forma.capitalize()} — {nomes2.get(periodo, 'Período')}*\n"]
    for cat, val in sorted(por_cat.items(), key=lambda x: -x[1]):
        linhas.append(f"  {cat}: R$ {val:.2f}")
    linhas.append(f"\n💰 *Total no {forma}: R$ {total:.2f}*")
    return "\n".join(linhas)

def gerar_saldo(telefone, periodo):
    gastos = buscar_gastos_periodo(telefone, periodo)
    receitas = buscar_receitas_periodo(telefone, periodo)
    total_gastos = sum(g["valor"] for g in gastos)
    total_receitas = sum(r["valor"] for r in receitas)
    saldo = total_receitas - total_gastos
    nomes = {"hoje": "Hoje", "semana": "Últimos 7 dias", "mes": "Este mês"}
    emoji = "✅" if saldo >= 0 else "🔴"
    linhas = [
        f"💼 *Saldo — {nomes.get(periodo, 'Período')}*\n",
        f"  📈 Receitas: R$ {total_receitas:.2f}",
        f"  📉 Gastos: R$ {total_gastos:.2f}",
        f"\n{emoji} *Saldo: R$ {saldo:.2f}*"
    ]
    if not receitas:
        linhas.append("\n💡 Dica: registre suas receitas com 'recebi salário 3000'")
    return "\n".join(linhas)

def gerar_comparativo(telefone):
    hoje = datetime.now()
    gastos_atual = buscar_gastos_mes_offset(telefone, 0)
    gastos_passado = buscar_gastos_mes_offset(telefone, 1)

    total_atual = sum(g["valor"] for g in gastos_atual)
    total_passado = sum(g["valor"] for g in gastos_passado)

    mes_atual = hoje.strftime("%B/%Y")
    mes_passado = (hoje.replace(day=1) - timedelta(days=1)).strftime("%B/%Y")

    # Categorias dos dois meses
    cats_atual = {}
    for g in gastos_atual:
        cats_atual[g["categoria"]] = cats_atual.get(g["categoria"], 0) + g["valor"]
    cats_passado = {}
    for g in gastos_passado:
        cats_passado[g["categoria"]] = cats_passado.get(g["categoria"], 0) + g["valor"]

    todas_cats = set(list(cats_atual.keys()) + list(cats_passado.keys()))

    diff = total_atual - total_passado
    emoji = "📈" if diff > 0 else "📉"

    linhas = [f"📅 *Comparativo de Meses*\n"]
    linhas.append(f"  {mes_passado}: R$ {total_passado:.2f}")
    linhas.append(f"  {mes_atual}: R$ {total_atual:.2f}")
    linhas.append(f"\n{emoji} Diferença: R$ {abs(diff):.2f} {'a mais' if diff > 0 else 'a menos'} que o mês passado\n")

    if todas_cats:
        linhas.append("*Por categoria:*")
        for cat in sorted(todas_cats):
            v_atual = cats_atual.get(cat, 0)
            v_passado = cats_passado.get(cat, 0)
            d = v_atual - v_passado
            sinal = "▲" if d > 0 else "▼" if d < 0 else "="
            linhas.append(f"  {cat}: R$ {v_atual:.2f} {sinal}")
    return "\n".join(linhas)

def gerar_ver_metas(telefone):
    metas = buscar_metas(telefone)
    if not metas:
        return "📭 Nenhuma meta definida.\n\n💡 Defina uma com: 'meta alimentação 500'"
    gastos = buscar_gastos_mes_offset(telefone, 0)
    por_cat = {}
    for g in gastos:
        por_cat[g["categoria"]] = por_cat.get(g["categoria"], 0) + g["valor"]

    linhas = ["🎯 *Suas metas este mês:*\n"]
    for meta in metas:
        cat = meta["categoria"]
        limite = meta["limite"]
        gasto = por_cat.get(cat, 0)
        pct = (gasto / limite) * 100 if limite > 0 else 0
        barra = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
        emoji = "🚨" if pct >= 100 else "⚠️" if pct >= 80 else "✅"
        linhas.append(f"{emoji} *{cat}*")
        linhas.append(f"  [{barra}] {pct:.0f}%")
        linhas.append(f"  R$ {gasto:.2f} / R$ {limite:.2f}\n")
    return "\n".join(linhas)

def gerar_ver_lembretes(telefone):
    lembretes = buscar_lembretes(telefone)
    if not lembretes:
        return "📭 Nenhum lembrete cadastrado.\n\n💡 Adicione com: 'lembrete aluguel 1200 dia 5'"
    hoje = datetime.now().day
    linhas = ["🔔 *Contas fixas:*\n"]
    for l in lembretes:
        dia = l["dia_vencimento"]
        valor = l["valor"]
        desc = l["descricao"].capitalize()
        dias_restantes = dia - hoje
        if dias_restantes < 0:
            dias_restantes += 30
        if dias_restantes == 0:
            emoji = "🚨"
            aviso = "vence HOJE!"
        elif dias_restantes <= 3:
            emoji = "⚠️"
            aviso = f"vence em {dias_restantes} dia(s)"
        else:
            emoji = "📅"
            aviso = f"dia {dia}"
        linhas.append(f"{emoji} *{desc}* — R$ {valor:.2f} ({aviso})")
    return "\n".join(linhas)

def gerar_historico(telefone):
    gastos = listar_ultimos_gastos(telefone)
    if not gastos:
        return "📭 Nenhum gasto registrado ainda."
    linhas = ["🧾 *Últimos gastos:*\n"]
    for g in gastos:
        forma = g.get("forma_pagamento", "não informado")
        linhas.append(f"• {g['descricao'].capitalize()} — R$ {g['valor']:.2f} ({g['categoria']} · {forma})")
    return "\n".join(linhas)

# ============================================================
# AJUDA
# ============================================================
MENSAGEM_AJUDA = """🐒 *Paylo.IA — Seu assistente financeiro!*

*📝 Gastos:*
• "mercado 150" / "uber 27 pix"

*📈 Receitas:*
• "recebi salário 3000"
• "freelance 500"

*📊 Relatórios:*
• "resumo" / "resumo da semana"
• "quanto gastei no cartão"
• "saldo" / "quanto sobrou"
• "comparar meses"

*🎯 Metas:*
• "meta alimentação 500"
• "metas" / "ver limites"

*🔔 Lembretes:*
• "lembrete aluguel 1200 dia 5"
• "lembretes" / "contas fixas"

*🗑️ Remover:*
• "remover último"
• "remover uber" / "remover lazer"

*💡 Escreva naturalmente, eu entendo! 😊*"""

# ============================================================
# WEBHOOK
# ============================================================
@app.post("/webhook", response_class=PlainTextResponse)
async def webhook(Body: str = Form(...), From: str = Form(...)):
    mensagem = Body.strip()
    telefone = From
    logger.info(f"Mensagem de {telefone}: {mensagem}")

    try:
        resultado = interpretar_mensagem(mensagem)
        logger.info(f"Interpretado: {resultado}")
        tipo = resultado["tipo"]

        if tipo == "gasto":
            gasto_id = salvar_gasto(
                resultado["descricao"], resultado["valor"],
                resultado["categoria"], resultado.get("forma_pagamento", "não informado"), telefone
            )
            # Verifica meta da categoria
            metas = buscar_metas(telefone)
            gastos_mes = buscar_gastos_mes_offset(telefone, 0)
            por_cat = {}
            for g in gastos_mes:
                por_cat[g["categoria"]] = por_cat.get(g["categoria"], 0) + g["valor"]
            alerta = ""
            for meta in metas:
                if meta["categoria"].lower() == resultado["categoria"].lower():
                    gasto_cat = por_cat.get(resultado["categoria"], 0)
                    pct = (gasto_cat / meta["limite"]) * 100
                    if pct >= 100:
                        alerta = f"\n\n🚨 *Atenção!* Você ultrapassou o limite de R$ {meta['limite']:.2f} em {resultado['categoria']}!"
                    elif pct >= 80:
                        alerta = f"\n\n⚠️ Você usou {pct:.0f}% do limite de {resultado['categoria']} (R$ {gasto_cat:.2f}/R$ {meta['limite']:.2f})"
            resposta = (
                f"✅ *Gasto registrado!* (#{gasto_id})\n\n"
                f"📌 {resultado['descricao'].capitalize()}\n"
                f"💵 R$ {resultado['valor']:.2f}\n"
                f"🏷️ {resultado['categoria']}\n"
                f"💳 {resultado.get('forma_pagamento', 'não informado').capitalize()}"
                + alerta
            )

        elif tipo == "receita":
            rec_id = salvar_receita(resultado["descricao"], resultado["valor"], resultado.get("categoria", "Outros"), telefone)
            resposta = (
                f"✅ *Receita registrada!* (#{rec_id})\n\n"
                f"📌 {resultado['descricao'].capitalize()}\n"
                f"💵 R$ {resultado['valor']:.2f}\n"
                f"🏷️ {resultado.get('categoria', 'Outros')}"
            )

        elif tipo == "relatorio":
            resposta = gerar_relatorio(telefone, resultado.get("periodo", "mes"))

        elif tipo == "relatorio_pagamento":
            resposta = gerar_relatorio_pagamento(telefone, resultado.get("forma", "cartão"), resultado.get("periodo", "mes"))

        elif tipo == "saldo":
            resposta = gerar_saldo(telefone, resultado.get("periodo", "mes"))

        elif tipo == "comparativo":
            resposta = gerar_comparativo(telefone)

        elif tipo == "definir_meta":
            status = salvar_meta(telefone, resultado["categoria"], resultado["limite"])
            resposta = f"🎯 *Meta {status}!*\n\n{resultado['categoria']}: R$ {resultado['limite']:.2f}/mês"

        elif tipo == "ver_metas":
            resposta = gerar_ver_metas(telefone)

        elif tipo == "adicionar_lembrete":
            lembrete_id = salvar_lembrete(telefone, resultado["descricao"], resultado["valor"], resultado["dia_vencimento"])
            resposta = f"🔔 *Lembrete adicionado!* (#{lembrete_id})\n\n📌 {resultado['descricao'].capitalize()}\n💵 R$ {resultado['valor']:.2f}\n📅 Todo dia {resultado['dia_vencimento']}"

        elif tipo == "ver_lembretes":
            resposta = gerar_ver_lembretes(telefone)

        elif tipo == "remover_lembrete":
            lembrete = remover_lembrete(telefone, resultado.get("descricao", ""))
            resposta = f"🗑️ *Lembrete removido!*\n\n📌 {lembrete['descricao'].capitalize()}" if lembrete else "❌ Lembrete não encontrado."

        elif tipo == "remover_ultimo":
            gasto = remover_ultimo_gasto(telefone)
            resposta = f"🗑️ *Gasto removido!*\n\n📌 {gasto['descricao'].capitalize()} — R$ {gasto['valor']:.2f}" if gasto else "📭 Nenhum gasto para remover."

        elif tipo == "remover_item":
            gasto = remover_gasto_por_descricao(telefone, resultado.get("descricao", ""))
            resposta = f"🗑️ *Gasto removido!*\n\n📌 {gasto['descricao'].capitalize()} — R$ {gasto['valor']:.2f}" if gasto else "❌ Gasto não encontrado."

        elif tipo == "remover_categoria":
            gasto = remover_gasto_por_categoria(telefone, resultado.get("categoria", ""), resultado.get("valor"))
            resposta = f"🗑️ *Gasto removido!*\n\n📌 {gasto['descricao'].capitalize()} — R$ {gasto['valor']:.2f} ({gasto['categoria']})" if gasto else f"❌ Nenhum gasto em {resultado.get('categoria', '')}."

        elif tipo == "historico":
            resposta = gerar_historico(telefone)

        else:
            resposta = MENSAGEM_AJUDA

    except Exception as e:
        logger.error(f"Erro: {e}")
        resposta = "⚠️ Não entendi sua mensagem.\n\nMande 'ajuda' para ver os comandos disponíveis."

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{resposta}</Message>
</Response>"""
    return PlainTextResponse(content=twiml, media_type="application/xml")

@app.get("/")
def health():
    return {"status": "Paylo.IA rodando! 🐒", "supabase_api": SUPABASE_API}
