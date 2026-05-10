import json
import re
import time
import logging
import threading
import requests
from datetime import datetime, timedelta
import anthropic

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

TELEGRAM_TOKEN    = "8711474464:AAFTVoDFcfltLxPHrdJbcPQnOnN4WdCNBJM"
TELEGRAM_CHAT_ID  = "6829669389"
ANTHROPIC_API_KEY = "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"

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Estado global
fichas_ativas  = []
last_update_id = 0
ficha_counter  = [0]

LIGAS = """Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Eredivisie, Liga Portugal,
Super Lig Turquia, Jupiler Pro Belgium, Championship Inglaterra, Bundesliga 2, Ligue 2,
Serie B Italia, Ekstraklasa Polonia, Danish Superliga, Norwegian Eliteserien, Swedish Allsvenskan,
Swiss Super League, Austrian Bundesliga, Scottish Premiership, Greek Super League, Romanian Liga,
Champions League, Europa League, Conference League,
MLS, Liga MX, Brasileirao Serie A, Primera Division Argentina, Copa Libertadores,
J-League Japao, K-League Coreia, Chinese Super League, A-League Australia, Thai League,
Saudi Pro League, UAE Pro League, Iran Pro League, Indian Super League,
CAF Champions League, Egyptian Premier League, Botola Pro Marrocos, South African PSL"""

PERIODOS = [
    {"nome": "MANHA",  "hora_wat": 6,  "de": 7,  "ate": 11},
    {"nome": "TARDE",  "hora_wat": 12, "de": 13, "ate": 17},
    {"nome": "NOITE",  "hora_wat": 18, "de": 19, "ate": 23},
]


# ── TELEGRAM ──────────────────────────────────────────────────────
def send(text, chat_id=None):
    try:
        for i in range(0, len(text), 4000):
            requests.post(f"{BASE_URL}/sendMessage", json={
                "chat_id": chat_id or TELEGRAM_CHAT_ID,
                "text": text[i:i+4000],
                "parse_mode": "Markdown"
            }, timeout=30)
            time.sleep(0.5)
    except Exception as e:
        log.error(f"Erro send: {e}")


def get_updates(offset=0):
    try:
        r = requests.get(f"{BASE_URL}/getUpdates",
            params={"offset": offset, "timeout": 30, "allowed_updates": ["message"]},
            timeout=40)
        if r.status_code == 200:
            return r.json().get("result", [])
    except Exception as e:
        log.error(f"Erro updates: {e}")
    return []


def wat_now():
    return datetime.utcnow() + timedelta(hours=1)


# ── NOTIFICAÇÕES DE CONTAGEM DECRESCENTE ──────────────────────────
def notif_contagem_fichas(periodo_nome: str):
    """Envia notificações de 5 em 5 min durante os 30 min antes das fichas."""
    minutos = [30, 25, 20, 15, 10, 5]
    emojis  = ["🔔", "🔔", "⏰", "⏰", "🚨", "🚨"]
    for i, m in enumerate(minutos):
        send(
            f"{emojis[i]} *Fichas do periodo {periodo_nome} em {m} minutos!*\n"
            f"_Prepara-te para as 3 fichas: Conservadora, Moderada e Agressiva._"
        )
        if m > 5:
            time.sleep(5 * 60)
        else:
            time.sleep(4 * 60 + 50)


def notif_jogo_em_breve(jogo_nome: str, minutos: int, ficha_tipo: str):
    icons = {"conservadora": "🛡️", "moderada": "⚖️", "agressiva": "💣"}
    send(
        f"⚽ *Jogo em {minutos} minutos!*\n"
        f"{icons.get(ficha_tipo,'📋')} Ficha {ficha_tipo.upper()}\n"
        f"🏟️ *{jogo_nome}*\n"
        f"_Esta na hora de confirmar a tua aposta!_"
    )


def notif_relatorio_em_breve():
    send(
        "📊 *Relatorio diario em 10 minutos!*\n\n"
        "_Vou apresentar o resumo completo de todas as fichas de hoje.\n"
        "Prepara-te para ver os resultados do dia!_"
    )


# ── SCANNER IA ────────────────────────────────────────────────────
def scan_periodo(periodo: dict) -> dict:
    hoje     = wat_now().strftime("%Y-%m-%d")
    hora_de  = periodo["de"]
    hora_ate = periodo["ate"]
    nome     = periodo["nome"]
    log.info(f"Scanning periodo {nome}: {hora_de}h-{hora_ate}h WAT")

    prompt = f"""Hoje é {hoje}. Analisa jogos de futebol para o periodo das {hora_de}h as {hora_ate}h hora de Angola (WAT = UTC+1).

LIGAS A COBRIR:
{LIGAS}

ANALISE PROFUNDA OBRIGATORIA para cada jogo:
1. Odds reais atuais de pelo menos 2 casas (Bet365, Betano, 1xBet, William Hill, Betway, Pinnacle, Elephantbet, Premierbet, Kwanzabet)
2. Forma dos ultimos 5 jogos de cada equipa
3. Historico de confrontos diretos h2h
4. Media de golos marcados e sofridos (casa e fora separadamente)
5. Lesoes e suspensoes confirmadas
6. Posicao na tabela e motivacao principalmente 
7. Value: Value pct = ((probabilidade_real x odd) - 1) x 100

REGRA PRINCIPAL: TODOS os jogos em TODAS as fichas devem ser muito seguros.
- A ia deve analisar com tudo que for necessário cada jogo 
- Confianca minima: 78% para qualquer jogo em qualquer ficha
- Value minimo: 10%
- So mercados com alta probabilidade: Dupla Hipotese, Over 0.5/1.5, Ambas Marcam quando logico, favorito claro 1X2, empate anula

A DIFERENCA ENTRE AS FICHAS E APENAS O NUMERO DE JOGOS:

FICHA CONSERVADORA (3 a 5 jogos):
- Os MELHORES jogos do dia com confianca acima de 85%
- Odd total alvo: 7x a 25x
- Poucos jogos mas maxima certeza
- Ficha proibida a cair
- Ficha deve dar green obrigatoriamente 

FICHA MODERADA (6 a 10 jogos):
- Jogos muito seguros com confianca acima de 80%
- Odd total alvo: 30x a 100x
- Equilibrio entre numero de jogos e seguranca
- Ficha proibida a cair
- Ficha deve dar green obrigatoriamente 

FICHA AGRESSIVA (20 a 30 jogos):
- Jogos seguros com confianca acima de 78%
- Mercados LEVES e SEGUROS: Over 0.5, Dupla Hipotese, favoritos claros
- Odds individuais baixas (1.10 a 1.45) mas muito provaveis
- A acumulacao de jogos gera odd total alta (700x a 2000x)
- Odd total alvo: 700x a 2000x

Responde APENAS JSON valido sem texto extra:
{{
  "periodo": "{nome}",
  "janela": "{hora_de}h-{hora_ate}h WAT",
  "conservadora": {{
    "jogos": [
      {{
        "home": "Time casa",
        "away": "Time fora",
        "league": "Liga",
        "flag": "emoji",
        "kickoff_wat": "HH:MM",
        "selection": "Mercado exato",
        "odd": 1.85,
        "bookmaker": "Casa",
        "value_pct": 19.5,
        "confidence_pct": 86,
        "reason": "Justificacao profunda com dados reais"
      }}
    ],
    "odd_total": 12.5
  }},
  "moderada": {{
    "jogos": [],
    "odd_total": 55.0
  }},
  "agressiva": {{
    "jogos": [],
    "odd_total": 850.0
  }}
}}"""

    client    = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    full_text = ""

    try:
        with client.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=8000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}]
        ) as stream:
            for event in stream:
                if hasattr(event, "type"):
                    if event.type == "content_block_start":
                        block = getattr(event, "content_block", None)
                        if block and getattr(block, "type", None) == "tool_use":
                            log.info(f"  Web search {nome}...")
                    if event.type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if delta and getattr(delta, "type", None) == "text_delta":
                            full_text += delta.text

        m = re.search(r'\{[\s\S]*\}', full_text)
        if not m:
            log.error("Sem JSON")
            return {}
        return json.loads(m.group())
    except Exception as e:
        log.error(f"Erro scan {nome}: {e}")
        return {}


# ── FORMATADORES ──────────────────────────────────────────────────
def format_ficha(tipo: str, jogos: list, odd_total: float, periodo: str, fid: int) -> str:
    icons = {"conservadora": "🛡️", "moderada": "⚖️", "agressiva": "💣"}
    nomes = {"conservadora": "CONSERVADORA", "moderada": "MODERADA", "agressiva": "AGRESSIVA"}
    descr = {
        "conservadora": "3-5 jogos maxima certeza",
        "moderada":     "6-10 jogos muito seguros",
        "agressiva":    "15-30 jogos seguros = odd astronomica"
    }
    now = wat_now().strftime("%d/%m/%Y %H:%M")

    lines = [
        f"━━━━━━━━━━━━━━━━━━━━━━━",
        f"{icons[tipo]} *FICHA {nomes[tipo]} #{fid}*",
        f"🕐 {now} WAT | Periodo: {periodo}",
        f"_{descr[tipo]}_",
        f"━━━━━━━━━━━━━━━━━━━━━━━\n",
    ]

    for i, g in enumerate(jogos, 1):
        conf = int(g.get("confidence_pct", 0))
        val  = float(g.get("value_pct", 0))
        icon = "🟢" if conf >= 85 else "🟡" if conf >= 78 else "🟠"
        lines.append(
            f"*{i}. {g['home']} vs {g['away']}*\n"
            f"  {g.get('flag','⚽')} {g.get('league','?')} · 🕐 {g.get('kickoff_wat','?')} WAT\n"
            f"  💰 *{g.get('selection','?')}* @ *{g.get('odd','?')}*\n"
            f"  {icon} Confianca: {conf}% | Value: +{val:.1f}%\n"
            f"  📝 _{g.get('reason','')}_\n"
        )

    lines += [
        "━━━━━━━━━━━━━━━━━━━━━━━",
        f"🎯 *ODD TOTAL: {odd_total:.2f}x*",
        f"  $5  → *${5*odd_total:.2f}*",
        f"  $10 → *${10*odd_total:.2f}*",
        f"  $20 → *${20*odd_total:.2f}*",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "⚠️ _Max 2-5% do bankroll por ficha._"
    ]
    return "\n".join(lines)


def format_tracking(ficha: dict) -> str:
    tipo  = ficha["tipo"]
    fid   = ficha["id"]
    jogos = ficha["jogos"]
    icons = {"conservadora": "🛡️", "moderada": "⚖️", "agressiva": "💣"}

    green    = sum(1 for j in jogos if j["status"] == "green")
    red      = sum(1 for j in jogos if j["status"] == "red")
    andamento= sum(1 for j in jogos if j["status"] == "andamento")
    pendente = sum(1 for j in jogos if j["status"] == "pendente")

    if red > 0:
        estado = "❌ CAIU"
    elif green == len(jogos):
        estado = "✅ GREEN!"
    else:
        estado = "⏳ EM ANDAMENTO"

    lines = [
        f"━━━━━━━━━━━━━━━━━━━━━━━",
        f"{icons.get(tipo,'📋')} *TRACKING #{fid} {tipo.upper()}* — {estado}",
        f"✅ {green} green | ❌ {red} red | ⏳ {andamento} a decorrer | 🕐 {pendente} pendente",
        "━━━━━━━━━━━━━━━━━━━━━━━\n",
    ]

    for i, g in enumerate(jogos, 1):
        s   = g["status"]
        ico = "✅" if s=="green" else "❌" if s=="red" else "⏳" if s=="andamento" else "🕐"
        lines.append(f"{ico} *{i}. {g['home']} vs {g['away']}* — _{g['selection']}_ @ {g['odd']}")
        if g.get("score"):
            lines.append(f"   `{g['score']}`")

    return "\n".join(lines)


def format_relatorio(fichas: list) -> str:
    hoje = wat_now().strftime("%d/%m/%Y")
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 *RELATORIO DIARIO — {hoje}*",
        "━━━━━━━━━━━━━━━━━━━━━━━\n",
    ]

    total  = len(fichas)
    greens = sum(1 for f in fichas if all(j["status"]=="green" for j in f["jogos"]))
    reds   = sum(1 for f in fichas if any(j["status"]=="red" for j in f["jogos"]))
    taxa   = int(greens/total*100) if total else 0

    lines += [
        f"📋 Fichas enviadas: *{total}*",
        f"✅ Fichas green: *{greens}*",
        f"❌ Fichas caidas: *{reds}*",
        f"📈 Taxa de acerto: *{taxa}%*\n",
    ]

    icons = {"conservadora": "🛡️", "moderada": "⚖️", "agressiva": "💣"}
    for f in fichas:
        g = sum(1 for j in f["jogos"] if j["status"]=="green")
        r = sum(1 for j in f["jogos"] if j["status"]=="red")
        estado = "✅ GREEN" if r==0 and g==len(f["jogos"]) else "❌ CAIU" if r>0 else "⏳ INCOMPLETA"
        lines.append(
            f"{icons.get(f['tipo'],'📋')} Ficha #{f['id']} {f['tipo'].upper()} "
            f"[{f['periodo']}] — {estado} ({g}✅/{r}❌)"
        )

    lines += [
        "\n━━━━━━━━━━━━━━━━━━━━━━━",
        "_Novo dia, novas oportunidades! 💪_"
    ]
    return "\n".join(lines)


# ── JOBS ──────────────────────────────────────────────────────────
def job_periodo(periodo: dict):
    """Gera e envia as 3 fichas de um período. Agenda alertas de início de jogos."""
    global fichas_ativas, ficha_counter
    nome = periodo["nome"]
    log.info(f"Job periodo {nome}")

    send(
        f"📡 *Value Scanner — Periodo {nome}*\n\n"
        f"A analisar jogos das {periodo['de']}h as {periodo['ate']}h WAT...\n"
        f"Cobrindo todas as ligas mundiais.\n"
        f"_Aguarda 60-90 segundos..._"
    )

    data = scan_periodo(periodo)
    if not data:
        send(f"⚠️ Sem dados para o periodo {nome}. Tenta /scan_{nome.lower()}")
        return

    fichas_do_periodo = []
    tipos = ["conservadora", "moderada", "agressiva"]

    for tipo in tipos:
        info      = data.get(tipo, {})
        jogos_raw = info.get("jogos", [])
        odd_total = float(info.get("odd_total", 1.0))

        if not jogos_raw:
            send(f"⚠️ Sem jogos para ficha {tipo} no periodo {nome}.")
            continue

        ficha_counter[0] += 1
        fid = ficha_counter[0]

        jogos_track = [{
            "home":        g.get("home", "?"),
            "away":        g.get("away", "?"),
            "selection":   g.get("selection", "?"),
            "odd":         g.get("odd", 1.0),
            "league":      g.get("league", "?"),
            "kickoff_wat": g.get("kickoff_wat", "?"),
            "status":      "pendente",
            "score":       "",
            "alerted":     False
        } for g in jogos_raw]

        ficha = {
            "id":        fid,
            "tipo":      tipo,
            "periodo":   nome,
            "jogos":     jogos_track,
            "odd_total": odd_total,
            "criada_em": wat_now().isoformat(),
            "concluida": False
        }
        fichas_ativas.append(ficha)
        fichas_do_periodo.append(ficha)

        texto = format_ficha(tipo, jogos_raw, odd_total, nome, fid)
        send(texto)
        time.sleep(1)

    # Agendar alertas de início de jogos para estas fichas
    if fichas_do_periodo:
        threading.Thread(
            target=agendar_alertas_jogos,
            args=[fichas_do_periodo],
            daemon=True
        ).start()

    log.info(f"3 fichas enviadas — periodo {nome}")


def agendar_alertas_jogos(fichas: list):
    """Monitoriza e envia alertas 10 min antes do início de cada jogo."""
    alertas_enviados = set()

    for _ in range(360):  # monitoriza por 6 horas máximo
        agora     = wat_now()
        agora_min = agora.hour * 60 + agora.minute

        for ficha in fichas:
            for j in ficha["jogos"]:
                chave = f"{ficha['id']}_{j['home']}_{j['away']}"
                if chave in alertas_enviados:
                    continue
                try:
                    h, m    = map(int, j["kickoff_wat"].split(":"))
                    kick_min = h * 60 + m
                    diff     = kick_min - agora_min
                    if 8 <= diff <= 12:
                        notif_jogo_em_breve(
                            f"{j['home']} vs {j['away']}",
                            10,
                            ficha["tipo"]
                        )
                        alertas_enviados.add(chave)
                except:
                    pass

        time.sleep(60)


def job_tracking_update():
    """Pesquisa resultados reais e atualiza status das fichas."""
    global fichas_ativas
    pendentes = [f for f in fichas_ativas if not f["concluida"]]
    if not pendentes:
        return

    log.info(f"Tracking: {len(pendentes)} fichas")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    for ficha in pendentes:
        jogos_str = "\n".join([
            f"- {j['home']} vs {j['away']} | {j['selection']} | Kickoff: {j['kickoff_wat']} WAT"
            for j in ficha["jogos"]
        ])

        prompt = f"""Hoje {wat_now().strftime('%Y-%m-%d')} {wat_now().strftime('%H:%M')} WAT.

Pesquisa resultados atuais destes jogos:
{jogos_str}

Para cada jogo responde:
- green: selecao entrou / jogo terminou com resultado correto
- red: selecao perdeu / jogo terminou sem acertar
- andamento: jogo a decorrer agora
- pendente: ainda nao comecou

Responde APENAS JSON:
{{"jogos":[{{"home":"nome","away":"nome","status":"green|red|andamento|pendente","score":"resultado ou pendente"}}]}}"""

        try:
            full_text = ""
            with client.messages.stream(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": prompt}]
            ) as stream:
                for event in stream:
                    if hasattr(event, "type"):
                        if event.type == "content_block_delta":
                            delta = getattr(event, "delta", None)
                            if delta and getattr(delta, "type", None) == "text_delta":
                                full_text += delta.text

            m = re.search(r'\{[\s\S]*\}', full_text)
            if not m:
                continue
            result = json.loads(m.group())

            for rj in result.get("jogos", []):
                for j in ficha["jogos"]:
                    if j["home"].lower() in rj.get("home","").lower() or \
                       rj.get("home","").lower() in j["home"].lower():
                        j["status"] = rj.get("status", "pendente")
                        j["score"]  = rj.get("score", "")

            if all(j["status"] in ["green","red"] for j in ficha["jogos"]):
                ficha["concluida"] = True

            send(format_tracking(ficha))

        except Exception as e:
            log.error(f"Erro tracking #{ficha['id']}: {e}")
        time.sleep(2)


def job_relatorio_diario():
    """Envia relatório completo e reseta fichas."""
    global fichas_ativas
    log.info("Relatorio diario")
    if fichas_ativas:
        send(format_relatorio(fichas_ativas))
    else:
        send("📊 *Relatorio Diario*\n\nNenhuma ficha enviada hoje.")
    fichas_ativas = []


# ── SCHEDULER ────────────────────────────────────────────────────
def scheduler_loop():
    periodos_feitos = set()
    tracking_ultimo = 0
    relatorio_feito = set()
    notif_periodo_feita = set()
    notif_relatorio_feita = set()

    log.info("Scheduler ativo")

    while True:
        agora    = wat_now()
        hora     = agora.hour
        minuto   = agora.minute
        hoje     = agora.strftime("%Y-%m-%d")

        # ── Notificação 30 min antes de cada período ──────────────
        for p in PERIODOS:
            hora_notif = p["hora_wat"]
            minuto_ini = hora_notif * 60
            agora_min  = hora * 60 + minuto
            chave_notif = f"notif_{hoje}_{p['nome']}"

            # 30 min antes = hora_wat*60 - 30
            if agora_min == minuto_ini - 30 and chave_notif not in notif_periodo_feita:
                notif_periodo_feita.add(chave_notif)
                threading.Thread(
                    target=notif_contagem_fichas,
                    args=[p["nome"]],
                    daemon=True
                ).start()

        # ── Enviar fichas nos períodos certos ─────────────────────
        for p in PERIODOS:
            chave = f"{hoje}_{p['nome']}"
            if hora == p["hora_wat"] and minuto < 5 and chave not in periodos_feitos:
                periodos_feitos.add(chave)
                threading.Thread(target=job_periodo, args=[p], daemon=True).start()

        # ── Limpar períodos do dia anterior ───────────────────────
        periodos_feitos     = {k for k in periodos_feitos     if k.startswith(hoje)}
        notif_periodo_feita = {k for k in notif_periodo_feita if k.startswith(f"notif_{hoje}")}

        # ── Tracking a cada 30 minutos ────────────────────────────
        agora_ts = time.time()
        if agora_ts - tracking_ultimo >= 1800 and fichas_ativas:
            tracking_ultimo = agora_ts
            threading.Thread(target=job_tracking_update, daemon=True).start()

        # ── Notificação 10 min antes do relatório (05h50 WAT) ─────
        chave_notif_rel = f"notif_rel_{hoje}"
        
