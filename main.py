import os
import time
import requests
from openai import OpenAI
from telegram import Bot

# =========================
# VARIÁVEIS
# =========================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SPORTS_API_KEY = os.getenv("SPORTS_API_KEY")

# =========================
# CLIENTES
# =========================

client = OpenAI(api_key=OPENAI_API_KEY)

bot = Bot(token=TELEGRAM_BOT_TOKEN)

# =========================
# BUSCAR JOGOS
# =========================

def buscar_jogos():

    url = "https://v3.football.api-sports.io/fixtures?next=10"

    headers = {
        "x-apisports-key": SPORTS_API_KEY
    }

    response = requests.get(url, headers=headers)

    data = response.json()

    jogos = []

    for jogo in data["response"]:

        casa = jogo["teams"]["home"]["name"]
        fora = jogo["teams"]["away"]["name"]

        jogos.append(f"{casa} vs {fora}")

    return jogos

# =========================
# ANALISAR COM IA
# =========================

def analisar_jogos(jogos):

    texto_jogos = "\n".join(jogos)

    prompt = f'''
Você é um analista profissional de apostas esportivas.

Analise os jogos abaixo e gere uma ficha extremamente conservadora.

Priorize:
- over 0.5 gols
- dupla chance
- under 4.5 gols

Jogos:
{texto_jogos}

Mostre:
- jogo
- mercado
- confiança
- justificativa
'''

    resposta = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    return resposta.choices[0].message.content

# =========================
# ENVIAR TELEGRAM
# =========================

def enviar_telegram(mensagem):

    bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=mensagem
    )

# =========================
# LOOP PRINCIPAL
# =========================

while True:

    try:

        print("Buscando jogos...")

        jogos = buscar_jogos()

        print("Analisando jogos...")

        ficha = analisar_jogos(jogos)

        print("Enviando Telegram...")

        enviar_telegram(ficha)

        print("Concluído.")

    except Exception as erro:

        print("ERRO:", erro)

    time.sleep(21600)
