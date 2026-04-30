from fastapi import FastAPI, Form
from fastapi.responses import PlainTextResponse
import anthropic
import json
import os
from datetime import datetime
import sqlite3
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "sua-chave-aqui")
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ============================================================
# BANCO DE DADOS
# ============================================================
DB_PATH = "/tmp/gastos.db"

def get_conn():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS gastos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT,
            descricao TEXT,
            valor REAL,
            categoria TEXT,
            forma_pagamento TEXT,
            telefone TEXT
        )
    """)
    conn.commit()
    conn.close()
    logger.info("Banco de dados inicializado.")

def salvar_gasto(descricao, valor, categoria, forma_pagamento, telefone):
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute("""
            INSERT INTO gastos (data, descricao, valor, categoria, forma_pagamento, telefone)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (datetime.now().strftime("%Y-%m-%d %H:%M"), descricao, valor, categoria, forma_pagamento, telefone))
        conn.commit()
        inserted_id = c.lastrowid
        conn.close()
        logger.info(f"Gasto salvo: id={inserted_id} descricao={descricao} valor={valor}")
        return inserted_id
    except Exception as e:
        logger.error(f"Erro ao salvar gasto: {e}")
        raise

def buscar_gastos(telefone, periodo="mes"):
    conn = get_conn()
    c = conn.cursor()
    hoje = datetime.now()

    if periodo == "hoje":
        filtro = hoje.strftime("%Y-%m-%d")
        c.execute("SELECT * FROM gastos WHERE telefone=? AND data LIKE ?", (telefone, f"{filtro}%"))
    elif periodo == "semana":
        from datetime import timedelta
        inicio = (hoje - timedelta(days=7)).strftime("%Y-%m-%d")
        c.execute("SELECT * FROM gastos WHERE telefone=? AND data >= ?", (telefone, inicio))
    else:
        filtro = hoje.strftime("%Y-%m")
        c.execute("SELECT * FROM gastos WHERE telefone=? AND data LIKE ?", (telefone, f"{filtro}%"))

    rows = c.fetchall()
    conn.close()
    return rows

def remover_ultimo_gasto(telefone):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM gastos WHERE telefone=? ORDER BY id DESC LIMIT 1", (telefone,))
    gasto = c.fetchone()
    if gasto:
        c.execute("DELETE FROM gastos WHERE id=?", (gasto[0],))
        conn.commit()
    conn.close()
    return gasto

def remover_gasto_por_descricao(telefone, descricao):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM gastos WHERE telefone=? AND descricao LIKE ?
        ORDER BY id DESC LIMIT 1
    """, (telefone, f"%{descricao}%"))
    gasto = c.fetchone()
    if gasto:
        c.execute("DELETE FROM gastos WHERE id=?", (gasto[0],))
        conn.commit()
    conn.close()
    return gasto

def listar_ultimos_gastos(telefone, limite=5):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM gastos WHERE telefone=? ORDER BY id DESC LIMIT ?", (telefone, limite))
    rows = c.fetchall()
    conn.close()
    return rows

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

    total = sum(g[3] for g in gastos)
    por_categoria = {}
    for g in gastos:
        por_categoria[g[4]] = por_categoria.get(g[4], 0) + g[3]

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
        linhas.append(f"• {g[2].capitalize()} — R$ {g[3]:.2f} ({g[4]})")
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
                resposta = f"🗑️ *Gasto removido!*\n\n📌 {gasto[2].capitalize()} — R$ {gasto[3]:.2f}"
            else:
                resposta = "📭 Nenhum gasto encontrado para remover."

        elif resultado["tipo"] == "remover_item":
            gasto = remover_gasto_por_descricao(telefone, resultado.get("descricao", ""))
            if gasto:
                resposta = f"🗑️ *Gasto removido!*\n\n📌 {gasto[2].capitalize()} — R$ {gasto[3]:.2f}"
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

init_db()
