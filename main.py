from fastapi import FastAPI, Form
from fastapi.responses import PlainTextResponse
import anthropic
import json
import os
from datetime import datetime
import sqlite3

app = FastAPI()

# ============================================================
# CONFIGURAÇÕES — preencha com suas chaves
# ============================================================
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "sua-chave-aqui")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ============================================================
# BANCO DE DADOS
# ============================================================
def init_db():
    conn = sqlite3.connect("gastos.db")
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

def salvar_gasto(descricao, valor, categoria, forma_pagamento, telefone):
    conn = sqlite3.connect("gastos.db")
    c = conn.cursor()
    c.execute("""
        INSERT INTO gastos (data, descricao, valor, categoria, forma_pagamento, telefone)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (datetime.now().strftime("%Y-%m-%d %H:%M"), descricao, valor, categoria, forma_pagamento, telefone))
    conn.commit()
    conn.close()

def buscar_gastos(telefone, periodo="mes"):
    conn = sqlite3.connect("gastos.db")
    c = conn.cursor()
    hoje = datetime.now()

    if periodo == "hoje":
        filtro = hoje.strftime("%Y-%m-%d")
        c.execute("SELECT * FROM gastos WHERE telefone=? AND data LIKE ?", (telefone, f"{filtro}%"))
    elif periodo == "semana":
        from datetime import timedelta
        inicio = (hoje - timedelta(days=7)).strftime("%Y-%m-%d")
        c.execute("SELECT * FROM gastos WHERE telefone=? AND data >= ?", (telefone, inicio))
    else:  # mes
        filtro = hoje.strftime("%Y-%m")
        c.execute("SELECT * FROM gastos WHERE telefone=? AND data LIKE ?", (telefone, f"{filtro}%"))

    rows = c.fetchall()
    conn.close()
    return rows

# ============================================================
# IA — INTERPRETAÇÃO DA MENSAGEM
# ============================================================
SYSTEM_PROMPT = """Você é um assistente financeiro pessoal via WhatsApp chamado Mono 🐒.
Seu trabalho é interpretar mensagens e extrair informações de gastos OU gerar relatórios.

Quando o usuário mandar uma mensagem de gasto (ex: "uber 27", "mercado 150 débito", "almoço 35 pix"):
Responda APENAS com JSON válido no formato:
{
  "tipo": "gasto",
  "descricao": "descrição do gasto",
  "valor": 27.0,
  "categoria": "Transporte",
  "forma_pagamento": "não informado"
}

Categorias possíveis: Alimentação, Transporte, Lazer, Saúde, Moradia, Educação, Vestuário, Outros

Quando o usuário pedir relatório (ex: "resumo", "relatório", "quanto gastei", "resumo do mês"):
Responda APENAS com JSON:
{
  "tipo": "relatorio",
  "periodo": "mes"
}
Períodos possíveis: hoje, semana, mes

Quando a mensagem não for gasto nem relatório (ex: "oi", "ajuda", "comandos"):
Responda APENAS com JSON:
{
  "tipo": "ajuda"
}

IMPORTANTE: Responda SOMENTE o JSON, sem texto adicional, sem markdown."""

def interpretar_mensagem(mensagem):
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": mensagem}]
    )
    texto = response.content[0].text.strip()
    return json.loads(texto)

# ============================================================
# GERAÇÃO DE RELATÓRIO
# ============================================================
def gerar_relatorio(telefone, periodo):
    gastos = buscar_gastos(telefone, periodo)

    if not gastos:
        nomes = {"hoje": "hoje", "semana": "nos últimos 7 dias", "mes": "este mês"}
        return f"📭 Nenhum gasto registrado {nomes.get(periodo, 'neste período')}."

    total = sum(g[3] for g in gastos)
    por_categoria = {}
    for g in gastos:
        cat = g[4]
        por_categoria[cat] = por_categoria.get(cat, 0) + g[3]

    nomes_periodo = {"hoje": "Hoje", "semana": "Últimos 7 dias", "mes": "Este mês"}
    titulo = nomes_periodo.get(periodo, "Período")

    linhas = [f"📊 *Relatório — {titulo}*\n"]
    for cat, val in sorted(por_categoria.items(), key=lambda x: -x[1]):
        linhas.append(f"  {cat}: R$ {val:.2f}")
    linhas.append(f"\n💰 *Total: R$ {total:.2f}*")

    return "\n".join(linhas)

# ============================================================
# MENSAGEM DE AJUDA
# ============================================================
MENSAGEM_AJUDA = """🐒 *Olá! Sou o Mono, seu assistente financeiro!*

Veja o que posso fazer:

*📝 Registrar gastos:*
• "mercado 150"
• "uber 27 pix"
• "almoço 35 cartão"

*📊 Ver relatórios:*
• "resumo" ou "relatório"
• "quanto gastei hoje"
• "resumo da semana"

*💡 Dica:* Pode escrever de forma natural, eu entendo! 😊"""

# ============================================================
# WEBHOOK — recebe mensagens do WhatsApp via Twilio
# ============================================================
@app.post("/webhook", response_class=PlainTextResponse)
async def webhook(
    Body: str = Form(...),
    From: str = Form(...)
):
    mensagem = Body.strip()
    telefone = From

    try:
        resultado = interpretar_mensagem(mensagem)

        if resultado["tipo"] == "gasto":
            salvar_gasto(
                descricao=resultado["descricao"],
                valor=resultado["valor"],
                categoria=resultado["categoria"],
                forma_pagamento=resultado.get("forma_pagamento", "não informado"),
                telefone=telefone
            )
            resposta = (
                f"✅ *Gasto registrado!*\n\n"
                f"📌 {resultado['descricao'].capitalize()}\n"
                f"💵 R$ {resultado['valor']:.2f}\n"
                f"🏷️ {resultado['categoria']}\n"
                f"💳 {resultado.get('forma_pagamento', 'não informado').capitalize()}"
            )

        elif resultado["tipo"] == "relatorio":
            resposta = gerar_relatorio(telefone, resultado.get("periodo", "mes"))

        else:
            resposta = MENSAGEM_AJUDA

    except Exception as e:
        resposta = f"⚠️ Não entendi sua mensagem. Tente algo como:\n• 'mercado 50'\n• 'resumo do mês'"

    # Formata resposta para o Twilio (TwiML)
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{resposta}</Message>
</Response>"""
    return PlainTextResponse(content=twiml, media_type="application/xml")

@app.get("/")
def health():
    return {"status": "Mono bot rodando! 🐒"}

# ============================================================
# INICIALIZAÇÃO
# ============================================================
init_db()
