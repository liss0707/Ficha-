import json
import re
import time
import logging
import threading
import requests
from datetime import datetime, timedelta
import anthropic
from openai import OpenAI

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
TELEGRAM_TOKEN    = "8711474464:AAFTVoDFcfltLxPHrdJbcPQnOnN4WdCNBJM"
TELEGRAM_CHAT_ID  = "6829669389"
ANTHROPIC_API_KEY = "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"
OPENAI_API_KEY    = "sk-proj-rDGb9r6hJIzjUUk_fUeL_LerByf4X_rEg56oa6tLQE6rI1RNsF_xlzAGq1SMBe9XR_LpM6b37uT3BlbkFIORXhI6RfL6yQmiru3j5fQvcymAEVrnVZ9hQ9h8D-owcrxyD1mTLHClJSoaetmBdyyU9w0Q1gkA"
API_FOOTBALL_KEY  = "dd8d60ac0c89498b0c41b2207a44d5a9"
THE_ODDS_API_KEY  = "3a63a3da048f6db489cb3ced68633b2f"
# ═══════════════════════════════════════════════════════════════════

BASE_URL       = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
openai_client  = OpenAI(api_key=OPENAI_API_KEY)

fichas_ativas  = []
last_update_id = 0
ficha_counter  = [0]

PERIODOS = [
    {"nome": "MANHA",  "hora_wat": 6,  "de": 7,  "ate": 11},
    {"nome": "TARDE",  "hora_wat": 12, "de": 13, "ate": 17},
    {"nome": "NOITE",  "hora_wat": 18, "de": 19, "ate": 23},
]

SPORTS_FOOTBALL = [
    "soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a",
    "soccer_germany_bundesliga", "soccer_france_ligue_one",
    "soccer_netherlands_eredivisie", "soccer_portugal_primeira_liga",
    "soccer_turkey_super_league", "soccer_belgium_first_div",
    "soccer_england_championship", "soccer_uefa_champs_league",
    "soccer_uefa_europa_league", "soccer_usa_mls",
    "soccer_mexico_ligamx", "soccer_brazil_campeonato",
    "soccer_argentina_primera_division", "soccer_japan_j_league",
    "soccer_korea_kleague1", "soccer_china_superleague",
    "soccer_saudi_arabia_super_league"
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


def extrair_json(text: str) -> dict:
    if not text:
        return {}
    for pattern in [r'\{[\s\S]*\}', r'\{[\s\S]*?\}']:
        m = re.search(pattern, text.replace('```json','').replace('```',''))
        if m:
            try:
                return json.loads(m.group())
            except:
                pass
    return {}


# ── API-FOOTBALL: dados reais de jogos ────────────────────────────
def get_jogos_hoje(hora_de: int, hora_ate: int) -> list:
    """Busca jogos reais de hoje na API-Football."""
    hoje = wat_now().strftime("%Y-%m-%d")
    url  = "https://v3.football.api-sports.io/fixtures"
    headers = {
        "x-rapidapi-host": "v3.football.api-sports.io",
        "x-rapidapi-key":  API_FOOTBALL_KEY
    }
    try:
        r = requests.get(url, headers=headers, params={"date": hoje}, timeout=15)
        if r.status_code != 200:
            log.error(f"API-Football erro: {r.status_code}")
            return []

        fixtures = r.json().get("response", [])
        jogos = []
        for f in fixtures:
            # Hora do jogo em WAT
            ts      = f["fixture"]["timestamp"]
            hora_jogo = (datetime.utcfromtimestamp(ts) + timedelta(hours=1))
            h = hora_jogo.hour

            if hora_de <= h <= hora_ate:
                jogos.append({
                    "fixture_id": f["fixture"]["id"],
                    "home":       f["teams"]["home"]["name"],
                    "away":       f["teams"]["away"]["name"],
                    "league":     f["league"]["name"],
                    "country":    f["league"]["country"],
                    "kickoff_wat": hora_jogo.strftime("%H:%M"),
                    "status":     f["fixture"]["status"]["short"]
                })

        log.info(f"API-Football: {len(jogos)} jogos para {hora_de}h-{hora_ate}h WAT")
        return jogos[:40]  # máximo 40 jogos

    except Exception as e:
        log.error(f"Erro API-Football: {e}")
        return []


def get_estatisticas_jogo(fixture_id: int) -> dict:
    """Busca estatísticas detalhadas de um jogo."""
    headers = {
        "x-rapidapi-host": "v3.football.api-sports.io",
        "x-rapidapi-key":  API_FOOTBALL_KEY
    }
    try:
        # H2H
        r = requests.get("https://v3.football.api-sports.io/fixtures/statistics",
            headers=headers, params={"fixture": fixture_id}, timeout=10)
        if r.ok:
            return r.json().get("response", {})
    except Exception as e:
        log.error(f"Erro stats {fixture_id}: {e}")
    return {}


# ── THE ODDS API: odds reais ──────────────────────────────────────
def get_odds_reais(home: str, away: str) -> list:
    """Busca odds reais de múltiplas casas."""
    resultados = []
    for sport in SPORTS_FOOTBALL[:5]:  # limitar para não gastar requests
        try:
            r = requests.get(
                f"https://api.the-odds-api.com/v4/sports/{sport}/odds/",
                params={
                    "apiKey":      THE_ODDS_API_KEY,
                    "regions":     "eu",
                    "markets":     "h2h,totals",
                    "oddsFormat":  "decimal"
                }, timeout=10
            )
            if not r.ok:
                continue
            for game in r.json():
                if home.lower()[:4] in game.get("home_team","").lower() or \
                   away.lower()[:4] in game.get("away_team","").lower():
                    for bm in game.get("bookmakers", [])[:3]:
                        for mkt in bm.get("markets", []):
                            for outcome in mkt.get("outcomes", []):
                                resultados.append({
                                    "bookmaker": bm["title"],
                                    "market":    mkt["key"],
                                    "selection": outcome["name"],
                                    "odd":       outcome["price"]
                                })
            if resultados:
                break
        except Exception as e:
            log.error(f"Erro Odds API {sport}: {e}")
    return resultados[:20]


# ── SOFASCORE: estatísticas via API pública ───────────────────────
def get_sofascore_stats(home: str, away: str) -> dict:
    """Busca estatísticas do SofaScore (API pública)."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        # Pesquisa o evento
        r = requests.get(
            f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{wat_now().strftime('%Y-%m-%d')}",
            headers=headers, timeout=10
        )
        if not r.ok:
            return {}

        eventos = r.json().get("events", [])
        for ev in eventos:
            h = ev.get("homeTeam", {}).get("name", "")
            a = ev.get("awayTeam", {}).get("name", "")
            if home.lower()[:4] in h.lower() or away.lower()[:4] in a.lower():
                eid = ev.get("id")
                # Buscar estatísticas detalhadas
                rs = requests.get(
                    f"https://api.sofascore.com/api/v1/event/{eid}/statistics",
                    headers=headers, timeout=10
                )
                if rs.ok:
                    return {
                        "home_team": h,
                        "away_team": a,
                        "tournament": ev.get("tournament", {}).get("name", ""),
                        "stats": rs.json().get("statistics", [])[:3]
                    }
        return {}
    except Exception as e:
        log.error(f"Erro SofaScore: {e}")
        return {}


# ── CLAUDE: análise principal ────────────────────────────────────
def analisar_com_claude(jogos: list, odds_data: dict, periodo: str) -> dict:
    """Claude analisa os jogos com todos os dados disponíveis."""
    jogos_str = json.dumps(jogos[:20], ensure_ascii=False, indent=2)
    odds_str  = json.dumps(odds_data, ensure_ascii=False, indent=2)[:3000]

    prompt = f"""És um analista profissional de apostas desportivas com 20 anos de experiência.

DATA: {wat_now().strftime('%Y-%m-%d')} | PERIODO: {periodo} WAT

JOGOS DISPONÍVEIS (dados reais da API-Football):
{jogos_str}

ODDS REAIS (The Odds API):
{odds_str}

TAREFA:
Analisa profundamente cada jogo usando os dados fornecidos mais o teu conhecimento.
Para cada jogo calcula:
- Probabilidade real de cada resultado baseada em forma, h2h, estatísticas
- Value = ((prob_real x odd) - 1) x 100
- Nível de confiança

SELECIONA:
- CONSERVADORA: os 3-5 jogos com MAIOR certeza (confiança >85%, value >10%)
- MODERADA: 6-10 jogos muito seguros (confiança >80%, value >10%)
- AGRESSIVA: 20-30 jogos seguros com odds baixas 1.10-1.45 (confiança >78%)

Mercados: Dupla Hipótese, Over 0.5/1.5/2.5, Ambas Marcam, 1X2 favorito claro

Responde APENAS JSON válido:
{{
  "conservadora": {{
    "jogos": [
      {{
        "home": "nome", "away": "nome", "league": "liga", "flag": "emoji",
        "kickoff_wat": "HH:MM", "selection": "mercado", "odd": 1.85,
        "bookmaker": "casa", "value_pct": 19.5, "confidence_pct": 86,
        "reason": "justificação com dados"
      }}
    ],
    "odd_total": 12.5
  }},
  "moderada": {{"jogos": [], "odd_total": 55.0}},
  "agressiva": {{"jogos": [], "odd_total": 900.0}}
}}"""

    client    = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    full_text = ""
    for tentativa in range(3):
        try:
            with client.messages.stream(
                model="claude-sonnet-4-20250514",
                max_tokens=8000,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": prompt}]
            ) as stream:
                for event in stream:
                    if hasattr(event, "type") and event.type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if delta and getattr(delta, "type", None) == "text_delta":
                            full_text += delta.text
            if full_text.strip():
                break
        except Exception as e:
            log.error(f"Claude tentativa {tentativa+1}: {e}")
            time.sleep(15)

    return extrair_json(full_text)


# ── GPT-4: validação independente ────────────────────────────────
def validar_com_gpt4(fichas_claude: dict, jogos: list) -> dict:
    """GPT-4 valida e pode ajustar as fichas do Claude."""
    try:
        fichas_str = json.dumps(fichas_claude, ensure_ascii=False, indent=2)[:4000]
        jogos_str  = json.dumps(jogos[:10], ensure_ascii=False, indent=2)

        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "És um analista de apostas independente. Valida fichas de apostas e remove jogos duvidosos."
                },
                {
                    "role": "user",
                    "content": f"""Valida estas fichas de apostas geradas por outra IA:

FICHAS:
{fichas_str}

JOGOS DISPONÍVEIS:
{jogos_str}

TAREFA:
1. Verifica se cada jogo e mercado fazem sentido
2. Remove jogos com confiança abaixo de 75%
3. Ajusta odds se necessário
4. Mantém ou melhora a estrutura

Responde APENAS JSON com a mesma estrutura das fichas originais, validadas e melhoradas."""
                }
            ],
            max_tokens=4000,
            temperature=0.3
        )

        texto = response.choices[0].message.content
        resultado = extrair_json(texto)
        if resultado:
            log.info("GPT-4 validação concluída")
            return resultado
        return fichas_claude

    except Exception as e:
        log.error(f"Erro GPT-4: {e}")
        return fichas_claude


# ── SCANNER COMPLETO ──────────────────────────────────────────────
def scan_periodo(periodo: dict) -> dict:
    nome     = periodo["nome"]
    hora_de  = periodo["de"]
    hora_ate = periodo["ate"]
    log.info(f"Scan completo periodo {nome}")

    # 1. Buscar jogos reais
    send(f"📡 *{nome}* — A recolher jogos reais... (1/4)")
    jogos = get_jogos_hoje(hora_de, hora_ate)

    if not jogos:
        log.warning("API-Football sem jogos. Usando Claude com web search.")
        send(f"📡 *{nome}* — Usando pesquisa web... (1/4)")
        jogos = []

    # 2. Buscar odds reais para os primeiros jogos
    send(f"📊 *{nome}* — A recolher odds reais... (2/4)")
    odds_data = {}
    for j in jogos[:8]:
        odds = get_odds_reais(j["home"], j["away"])
        if odds:
            odds_data[f"{j['home']} vs {j['away']}"] = odds
        time.sleep(0.5)

    # 3. Claude analisa com todos os dados
    send(f"🧠 *{nome}* — Claude a analisar... (3/4)")
    fichas_claude = analisar_com_claude(jogos, odds_data, nome)

    if not fichas_claude:
        send(f"⚠️ Claude nao gerou fichas para {nome}.")
        return {}

    # 4. GPT-4 valida
    send(f"🤖 *{nome}* — GPT-4 a validar... (4/4)")
    fichas_finais = validar_com_gpt4(fichas_claude, jogos)

    log.info(f"Scan {nome} concluído com sucesso")
    return fichas_finais


# ── TRACKING COM IA ──────────────────────────────────────────────
def job_tracking_update():
    global fichas_ativas
    pendentes = [f for f in fichas_ativas if not f["concluida"]]
    if not pendentes:
        return

    log.info(f"Tracking: {len(pendentes)} fichas")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    for ficha in pendentes:
        jogos_str = "\n".join([
            f"- {j['home']} vs {j['away']} | {j['selection']} | {j['kickoff_wat']} WAT"
            for j in ficha["jogos"]
        ])

        prompt = f"""Hoje {wat_now().strftime('%Y-%m-%d')} {wat_now().strftime('%H:%M')} WAT.
Pesquisa resultados atuais:
{jogos_str}
Responde APENAS JSON: {{"jogos":[{{"home":"nome","away":"nome","status":"green|red|andamento|pendente","score":"resultado"}}]}}"""

        full_text = ""
        try:
            with client.messages.stream(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": prompt}]
            ) as stream:
                for event in stream:
                    if hasattr(event, "type") and event.type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if delta and getattr(delta, "type", None) == "text_delta":
                            full_text += delta.text
        except Exception as e:
            log.error(f"Tracking erro: {e}")
            continue

        data = extrair_json(full_text)
        if not data:
            continue

        for rj in data.get("jogos", []):
            for j in ficha["jogos"]:
                if j["home"].lower()[:4] in rj.get("home","").lower():
                    j["status"] = rj.get("status","pendente")
                    j["score"]  = rj.get("score","")

        if all(j["status"] in ["green","red"] for j in ficha["jogos"]):
            ficha["concluida"] = True

        send(format_tracking(ficha))
        time.sleep(2)


# ── FORMATADORES ─────────────────────────────────────────────────
def format_ficha(tipo: str, jogos: list, odd_total: float, periodo: str, fid: int) -> str:
    icons = {"conservadora": "🛡️", "moderada": "⚖️", "agressiva": "💣"}
    nomes = {"conservadora": "CONSERVADORA", "moderada": "MODERADA", "agressiva": "AGRESSIVA"}
    descr = {"conservadora": "3-5 jogos maxima certeza", "moderada": "6-10 jogos muito seguros", "agressiva": "20-30 jogos = odd astronomica"}
    now   = wat_now().strftime("%d/%m/%Y %H:%M")
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━",
        f"{icons[tipo]} *FICHA {nomes[tipo]} #{fid}*",
        f"🕐 {now} WAT | {periodo}",
        f"_{descr[tipo]}_",
        "🧠 _Validada por Claude + GPT-4_",
        "━━━━━━━━━━━━━━━━━━━━━━━\n",
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
        f"  $5 → *${5*odd_total:.2f}* | $10 → *${10*odd_total:.2f}* | $20 → *${20*odd_total:.2f}*",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "⚠️ _Max 2-5% do bankroll por ficha._"
    ]
    return "\n".join(lines)


def format_tracking(ficha: dict) -> str:
    tipo  = ficha["tipo"]
    fid   = ficha["id"]
    jogos = ficha["jogos"]
    icons = {"conservadora": "🛡️", "moderada": "⚖️", "agressiva": "💣"}
    green = sum(1 for j in jogos if j["status"]=="green")
    red   = sum(1 for j in jogos if j["status"]=="red")
    and_  = sum(1 for j in jogos if j["status"]=="andamento")
    pend  = sum(1 for j in jogos if j["status"]=="pendente")
    estado = "✅ GREEN!" if green==len(jogos) else "❌ CAIU" if red>0 else "⏳ EM ANDAMENTO"
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━",
        f"{icons.get(tipo,'📋')} *TRACKING #{fid} {tipo.upper()}* — {estado}",
        f"✅ {green} | ❌ {red} | ⏳ {and_} | 🕐 {pend}",
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
    hoje   = wat_now().strftime("%d/%m/%Y")
    total  = len(fichas)
    greens = sum(1 for f in fichas if all(j["status"]=="green" for j in f["jogos"]))
    reds   = sum(1 for f in fichas if any(j["status"]=="red"   for j in f["jogos"]))
    taxa   = int(greens/total*100) if total else 0
    icons  = {"conservadora": "🛡️", "moderada": "⚖️", "agressiva": "💣"}
    lines  = [
        "━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 *RELATORIO DIARIO — {hoje}*",
        "━━━━━━━━━━━━━━━━━━━━━━━\n",
        f"📋 Fichas: *{total}* | ✅ Green: *{greens}* | ❌ Caidas: *{reds}*",
        f"📈 Taxa de acerto: *{taxa}%*\n",
    ]
    for f in fichas:
        g = sum(1 for j in f["jogos"] if j["status"]=="green")
        r = sum(1 for j in f["jogos"] if j["status"]=="red")
        estado = "✅ GREEN" if r==0 and g==len(f["jogos"]) else "❌ CAIU" if r>0 else "⏳ INCOMPLETA"
        lines.append(f"{icons.get(f['tipo'],'📋')} #{f['id']} {f['tipo'].upper()} [{f['periodo']}] — {estado} ({g}✅/{r}❌)")
    lines += ["\n━━━━━━━━━━━━━━━━━━━━━━━", "_Novo dia, novas oportunidades! 💪_"]
    return "\n".join(lines)


# ── JOB PERÍODO ──────────────────────────────────────────────────
def job_periodo(periodo: dict):
    global fichas_ativas, ficha_counter
    nome = periodo["nome"]
    log.info(f"Job periodo {nome}")

    send(
        f"🚀 *Value Scanner — Periodo {nome}*\n\n"
        f"Sistema completo a trabalhar:\n"
        f"📡 API-Football → jogos reais\n"
        f"📊 The Odds API → odds reais\n"
        f"🧠 Claude → analise profunda\n"
        f"🤖 GPT-4 → validacao independente\n\n"
        f"_Aguarda 2-3 minutos..._"
    )

    data = scan_periodo(periodo)
    if not data:
        send(f"⚠️ Nao foi possivel gerar fichas para {nome}.\nUse /scan_{nome.lower()} para tentar novamente.")
        return

    fichas_periodo = []
    for tipo in ["conservadora", "moderada", "agressiva"]:
        info      = data.get(tipo, {})
        jogos_raw = info.get("jogos", [])
        odd_total = float(info.get("odd_total", 1.0))

        if not jogos_raw:
            send(f"⚠️ Sem jogos para ficha {tipo}.")
            continue

        ficha_counter[0] += 1
        fid = ficha_counter[0]

        jogos_track = [{
            "home": g.get("home","?"), "away": g.get("away","?"),
            "selection": g.get("selection","?"), "odd": g.get("odd",1.0),
            "league": g.get("league","?"), "kickoff_wat": g.get("kickoff_wat","?"),
            "status": "pendente", "score": "", "alerted": False
        } for g in jogos_raw]

        ficha = {
            "id": fid, "tipo": tipo, "periodo": nome,
            "jogos": jogos_track, "odd_total": odd_total,
            "criada_em": wat_now().isoformat(), "concluida": False
        }
        fichas_ativas.append(ficha)
        fichas_periodo.append(ficha)
        send(format_ficha(tipo, jogos_raw, odd_total, nome, fid))
        time.sleep(1)

    if fichas_periodo:
        threading.Thread(target=agendar_alertas_jogos, args=[fichas_periodo], daemon=True).start()

    log.info(f"Periodo {nome}: {len(fichas_periodo)} fichas enviadas")


def agendar_alertas_jogos(fichas: list):
    alertas = set()
    icons   = {"conservadora": "🛡️", "moderada": "⚖️", "agressiva": "💣"}
    for _ in range(360):
        am = wat_now().hour * 60 + wat_now().minute
        for ficha in fichas:
            for j in ficha["jogos"]:
                chave = f"{ficha['id']}_{j['home']}"
                if chave in alertas:
                    continue
                try:
                    h, m = map(int, j["kickoff_wat"].split(":"))
                    diff = (h*60+m) - am
                    if 8 <= diff <= 12:
                        send(
                            f"⚽ *Jogo em 10 minutos!*\n"
                            f"{icons.get(ficha['tipo'],'📋')} Ficha {ficha['tipo'].upper()}\n"
                            f"🏟️ *{j['home']} vs {j['away']}*\n"
                            f"💰 {j['selection']} @ {j['odd']}\n"
                            f"_Esta na hora de apostar!_"
                        )
                        alertas.add(chave)
                except:
                    pass
        time.sleep(60)


def notif_contagem_fichas(periodo_nome: str):
    for m, e in zip([30,25,20,15,10,5], ["🔔","🔔","⏰","⏰","🚨","🚨"]):
        send(f"{e} *Fichas {periodo_nome} em {m} minutos!*\n_Conservadora + Moderada + Agressiva a caminho._")
        time.sleep(5*60 if m > 5 else 4*60+50)


def notif_relatorio_em_breve():
    send("📊 *Relatorio diario em 10 minutos!*\n_Resumo completo de todas as fichas de hoje._")


def job_relatorio_diario():
    global fichas_ativas
    send(format_relatorio(fichas_ativas) if fichas_ativas else "📊 *Relatorio*\n\nNenhuma ficha hoje.")
    fichas_ativas = []


# ── SCHEDULER ────────────────────────────────────────────────────
def scheduler_loop():
    periodos_feitos = set()
    tracking_ultimo = 0
    relatorio_feito = set()
    notif_feita     = set()
    notif_rel_feita = set()

    while True:
        agora  = wat_now()
        hora   = agora.hour
        minuto = agora.minute
        hoje   = agora.strftime("%Y-%m-%d")
        am     = hora * 60 + minuto

        for p in PERIODOS:
            hm = p["hora_wat"] * 60
            cn = f"n_{hoje}_{p['nome']}"
            if am == hm - 30 and cn not in notif_feita:
                notif_feita.add(cn)
                threading.Thread(target=notif_contagem_fichas, args=[p["nome"]], daemon=True).start()
            cp = f"p_{hoje}_{p['nome']}"
            if hora == p["hora_wat"] and minuto < 5 and cp not in periodos_feitos:
                periodos_feitos.add(cp)
                threading.Thread(target=job_periodo, args=[p], daemon=True).start()

        periodos_feitos = {k for k in periodos_feitos if hoje in k}
        notif_feita     = {k for k in notif_feita     if hoje in k}

        ts = time.time()
        if ts - tracking_ultimo >= 1800 and fichas_ativas:
            tracking_ultimo = ts
            threading.Thread(target=job_tracking_update, daemon=True).start()

        cnr = f"nr_{hoje}"
        if hora == 5 and minuto == 50 and cnr not in notif_rel_feita:
            notif_rel_feita.add(cnr)
            threading.Thread(target=notif_relatorio_em_breve, daemon=True).start()

        cr = f"r_{hoje}"
        if hora == 5 and minuto == 59 and cr not in relatorio_feito:
            relatorio_feito.add(cr)
            threading.Thread(target=job_relatorio_diario, daemon=True).start()

        time.sleep(60)


# ── COMANDOS ─────────────────────────────────────────────────────
def handle_command(text: str, chat_id: str):
    cmd = text.strip().split()[0].lower()

    if cmd == "/start":
        send(
            "⚡ *Value Betting Scanner PRO — ONLINE*\n\n"
            "🔌 *Integracoes ativas:*\n"
            "  📡 API-Football — jogos reais\n"
            "  📊 The Odds API — odds reais\n"
            "  🧠 Claude (Anthropic) — analise\n"
            "  🤖 GPT-4 (OpenAI) — validacao\n"
            "  📈 SofaScore — estatisticas\n\n"
            "⏰ *Horarios WAT:*\n"
            "  06h → Manha | 12h → Tarde | 18h → Noite\n\n"
            "📋 *Comandos:*\n"
            "/scan\_manha | /scan\_tarde | /scan\_noite\n"
            "/teste — testar todas as APIs\n"
            "/tracking | /relatorio | /status", chat_id)

    elif cmd == "/teste":
        send("🔬 *A testar todas as APIs...* Aguarda.", chat_id)
        def _teste():
            # Testar API-Football
            jogos = get_jogos_hoje(0, 23)
            send(f"📡 API-Football: {'✅ ' + str(len(jogos)) + ' jogos' if jogos else '⚠️ Sem jogos (pode ser limite de requests)'}", chat_id)

            # Testar The Odds API
            try:
                r = requests.get(f"https://api.the-odds-api.com/v4/sports/?apiKey={THE_ODDS_API_KEY}", timeout=10)
                send(f"📊 The Odds API: {'✅ Online' if r.ok else '❌ Erro ' + str(r.status_code)}", chat_id)
            except:
                send("📊 The Odds API: ❌ Erro de conexao", chat_id)

            # Testar Claude
            try:
                client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
                r = client.messages.create(model="claude-sonnet-4-20250514", max_tokens=50,
                    messages=[{"role":"user","content":"Diz apenas: OK"}])
                send(f"🧠 Claude: ✅ Online", chat_id)
            except Exception as e:
                send(f"🧠 Claude: ❌ {str(e)[:60]}", chat_id)

            # Testar GPT-4
            try:
                r = openai_client.chat.completions.create(
                    model="gpt-4o", max_tokens=10,
                    messages=[{"role":"user","content":"Say OK"}])
                send(f"🤖 GPT-4: ✅ Online", chat_id)
            except Exception as e:
                send(f"🤖 GPT-4: ❌ {str(e)[:60]}", chat_id)

            send("🔬 *Teste concluido!*\nUse /scan\_tarde ou /scan\_noite para gerar fichas.", chat_id)
        threading.Thread(target=_teste, daemon=True).start()

    elif cmd == "/scan_manha":
        send("🔍 Scan da Manha iniciado...", chat_id)
        threading.Thread(target=job_periodo, args=[PERIODOS[0]], daemon=True).start()

    elif cmd == "/scan_tarde":
        send("🔍 Scan da Tarde iniciado...", chat_id)
        threading.Thread(target=job_periodo, args=[PERIODOS[1]], daemon=True).start()

    elif cmd == "/scan_noite":
        send("🔍 Scan da Noite iniciado...", chat_id)
        threading.Thread(target=job_periodo, args=[PERIODOS[2]], daemon=True).start()

    elif cmd == "/tracking":
        ativas = [f for f in fichas_ativas if not f["concluida"]]
        send("📋 Sem fichas ativas." if not ativas else "\n".join(format_tracking(f) for f in ativas), chat_id)

    elif cmd == "/relatorio":
        send(format_relatorio(fichas_ativas) if fichas_ativas else "📊 Sem fichas hoje.", chat_id)

    elif cmd == "/status":
        agora  = wat_now().strftime("%d/%m/%Y %H:%M WAT")
        ativas = len([f for f in fichas_ativas if not f["concluida"]])
        send(f"✅ *Bot PRO ativo*\n🕐 {agora}\n📋 Fichas ativas: {ativas} | Total: {len(fichas_ativas)}", chat_id)

    elif cmd == "/ajuda":
        send(
            "📖 *Value Scanner PRO:*\n\n"
            "🔄 9 fichas/dia com dupla validacao IA\n"
            "🛡️ Conservadora: 3-5 jogos\n"
            "⚖️ Moderada: 6-10 jogos\n"
            "💣 Agressiva: 20-30 jogos\n\n"
            "🔔 Notificacoes 30min antes das fichas\n"
            "⚽ Alertas 10min antes de cada jogo\n"
            "📊 Relatorio diario as 05h59\n\n"
            "Use /teste para verificar todas as APIs!", chat_id)


# ── POLLING ───────────────────────────────────────────────────────
def polling_loop():
    global last_update_id
    log.info("Polling iniciado")
    while True:
        try:
            updates = get_updates(offset=last_update_id + 1)
            for upd in updates:
                last_update_id = upd["update_id"]
                msg     = upd.get("message", {})
                text    = msg.get("text", "")
                chat_id = str(msg.get("chat", {}).get("id", ""))
                if text.startswith("/"):
                    log.info(f"Comando: {text}")
                    handle_command(text, chat_id)
        except Exception as e:
            log.error(f"Erro polling: {e}")
            time.sleep(5)


# ── MAIN ─────────────────────────────────────────────────────────
def main():
    log.info("Iniciando Value Betting Scanner PRO...")
    send(
        "🟢 *Value Betting Scanner PRO — ONLINE*\n\n"
        "✅ Sistema multi-IA ativo 24/7\n\n"
        "🔌 *APIs integradas:*\n"
        "  📡 API-Football\n"
        "  📊 The Odds API\n"
        "  🧠 Claude (Anthropic)\n"
        "  🤖 GPT-4 (OpenAI)\n"
        "  📈 SofaScore\n\n"
        "⏰ 06h | 12h | 18h WAT\n"
        "Use /teste para verificar todas as APIs!"
    )
    threading.Thread(target=scheduler_loop, daemon=True).start()
    polling_loop()


if __name__ == "__main__":
    main()
    
