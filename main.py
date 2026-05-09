import os
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

TELEGRAM_TOKEN    = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID  = os.environ["TELEGRAM_CHAT_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
BASE_URL          = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

upcoming_alerts = {}
last_update_id  = 0


def send(text, chat_id=None):
    try:
        requests.post(f"{BASE_URL}/sendMessage", json={
            "chat_id": chat_id or TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        }, timeout=30)
        log.info("Mensagem enviada")
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


def scan_value_bets():
    now       = datetime.utcnow()
    from_time = now.strftime("%H:%M")
    to_time   = (now + timedelta(hours=3)).strftime("%H:%M")
    today     = now.strftime("%Y-%m-%d")
    log.info(f"Scanning {from_time} -> {to_time} UTC")

    prompt = f"""Hoje é {today}. Hora UTC: {from_time}.

Pesquisa na web jogos de futebol reais nas próximas 3 horas ({from_time}-{to_time} UTC).
Cobre TODAS as ligas: Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions League, Europa League, Liga Portugal, Eredivisie, J-League, K-League, CSL, ligas africanas, MLS e outras.

Para cada jogo:
1. Pesquisa odds reais (Bet365, Betano, 1xBet, William Hill, Betway, Pinnacle)
2. Analisa forma recente, h2h, média de golos, lesões, posição na tabela
3. Calcula value: Value pct = ((prob real x odd) - 1) x 100
4. Avalia mercados: 1X2, Over/Under, Ambas Marcam, Handicap

Seleciona TOP 5 com maior value (minimo 8 porcento).

Responde APENAS JSON valido sem texto extra:
{{
  "games": [
    {{
      "home": "Time casa",
      "away": "Time fora",
      "league": "Liga",
      "flag": "emoji bandeira",
      "kickoff_utc": "HH:MM",
      "selection": "Selecao exata",
      "best_odd": 1.85,
      "bookmaker": "Casa de apostas",
      "true_prob_pct": 65,
      "implied_prob_pct": 54,
      "value_pct": 19.5,
      "confidence_pct": 82,
      "form_home": "V V D V V",
      "form_away": "D V V D V",
      "reason": "Justificacao com dados reais"
    }}
  ]
}}"""

    client    = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    full_text = ""

    try:
        with client.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}]
        ) as stream:
            for event in stream:
                if hasattr(event, "type"):
                    if event.type == "content_block_start":
                        block = getattr(event, "content_block", None)
                        if block and getattr(block, "type", None) == "tool_use":
                            log.info("Web search...")
                    if event.type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if delta and getattr(delta, "type", None) == "text_delta":
                            full_text += delta.text

        m = re.search(r'\{[\s\S]*\}', full_text)
        if not m:
            log.error("Sem JSON")
            return []
        games = json.loads(m.group()).get("games", [])[:5]
        log.info(f"{len(games)} jogos encontrados")
        return games
    except Exception as e:
        log.error(f"Erro scan: {e}")
        return []


def format_slip(games):
    medals    = ["1", "2", "3", "4", "5"]
    now_str   = datetime.utcnow().strftime("%d/%m/%Y %H:%M") + " UTC"
    total_odd = 1.0
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "⚡ *VALUE BETTING SCANNER*",
        f"🕐 {now_str}",
        "━━━━━━━━━━━━━━━━━━━━━━━\n",
    ]
    for i, g in enumerate(games):
        val  = float(g.get("value_pct", 0))
        odd  = float(g.get("best_odd", 0))
        conf = int(g.get("confidence_pct", 0))
        total_odd *= odd
        icon = "🟢" if val >= 18 else "🟡" if val >= 11 else "🟠"
        lines.append(
            f"*{medals[i]}. {g['home']} vs {g['away']}*\n"
            f"  {g.get('flag','⚽')} {g.get('league','?')} · 🕐 {g.get('kickoff_utc','?')} UTC\n"
            f"  Forma: `{g.get('form_home','?')}` vs `{g.get('form_away','?')}`\n"
            f"  💰 *{g.get('selection','?')}*\n"
            f"  Odd: *{odd}* ({g.get('bookmaker','?')})\n"
            f"  {icon} Value: *+{val:.1f}%* | Confiança: {conf}%\n"
            f"  📝 _{g.get('reason','')}_\n"
        )
    lines += [
        "━━━━━━━━━━━━━━━━━━━━━━━",
        f"🎯 *MULTIPLA DOS 5*",
        f"  Odd total: *{total_odd:.2f}*",
        f"  $5 → *${5*total_odd:.2f}*",
        f"  $10 → *${10*total_odd:.2f}*",
        f"  $20 → *${20*total_odd:.2f}*",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "⚠️ _Nunca arrisque mais de 2-5% do bankroll._",
    ]
    return "\n".join(lines)


def format_alert(g):
    return (
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🚨 *JOGO EM 30 MINUTOS!*\n"
        f"⚽ *{g['home']} vs {g['away']}*\n"
        f"  {g.get('flag','⚽')} {g.get('league','?')}\n"
        f"  🕐 {g.get('kickoff_utc','?')} UTC\n\n"
        f"  💰 *{g.get('selection','?')}*\n"
        f"  Odd: *{g.get('best_odd','?')}* ({g.get('bookmaker','?')})\n"
        f"  🟢 Value: *+{float(g.get('value_pct',0)):.1f}%*\n\n"
        "⚡ _Esta na hora de apostar!_\n"
        "━━━━━━━━━━━━━━━━━━━━━━━"
    )


def job_scan():
    global upcoming_alerts
    log.info("Job scan iniciado")
    games = scan_value_bets()
    if not games:
        send("⚠️ *Value Scanner*\n\nSem oportunidades fortes agora.\nProximo scan em 2 horas.")
        return
    for g in games:
        key = f"{g['home']} vs {g['away']}"
        upcoming_alerts[key] = {"game": g, "kickoff_utc": g.get("kickoff_utc", "00:00"), "alerted": False}
    send(format_slip(games))


def job_kickoff_check():
    global upcoming_alerts
    now      = datetime.utcnow()
    now_mins = now.hour * 60 + now.minute
    for key, info in list(upcoming_alerts.items()):
        if info["alerted"]:
            continue
        try:
            h, m = map(int, info["kickoff_utc"].split(":"))
            diff = (h * 60 + m) - now_mins
            if 18 <= diff <= 32:
                log.info(f"Alerta: {key}")
                send(format_alert(info["game"]))
                upcoming_alerts[key]["alerted"] = True
            if diff < -30:
                del upcoming_alerts[key]
        except:
            pass


def handle_command(text, chat_id):
    cmd = text.strip().split()[0].lower()
    if cmd == "/start":
        send(
            "⚡ *Value Betting Scanner Ativo!*\n\n"
            "Estou a funcionar 24/7\n"
            "Fichas automaticas de 2 em 2 horas\n\n"
            "📋 *Comandos:*\n"
            "/scan - Forcar scan agora\n"
            "/status - Estado do bot\n"
            "/ajuda - Ajuda", chat_id)
    elif cmd == "/scan":
        send("🔍 A iniciar scan... Aguarde 30-60 segundos.", chat_id)
        threading.Thread(target=job_scan, daemon=True).start()
    elif cmd == "/status":
        now = datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")
        n   = sum(1 for v in upcoming_alerts.values() if not v["alerted"])
        send(f"✅ *Bot ativo*\n🕐 {now}\nJogos: {len(upcoming_alerts)} | Alertas: {n}", chat_id)
    elif cmd == "/ajuda":
        send(
            "📖 *Como funciona:*\n\n"
            "🔄 Scan de 2 em 2 horas - todas as ligas\n"
            "📊 IA analisa value com dados reais\n"
            "🎯 5 melhores jogos com ficha pronta\n"
            "🚨 Alerta 30 min antes de cada jogo\n\n"
            "Use /scan para analise imediata!", chat_id)


def scheduler_loop():
    last_scan  = 0
    last_check = 0
    while True:
        now = time.time()
        if now - last_scan >= 7200:
            threading.Thread(target=job_scan, daemon=True).start()
            last_scan = now
        if now - last_check >= 300:
            job_kickoff_check()
            last_check = now
        time.sleep(60)


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
                    handle_command(text, chat_id)
        except Exception as e:
            log.error(f"Erro polling: {e}")
            time.sleep(5)


def main():
    log.info("Iniciando Value Betting Scanner Bot...")
    send(
        "🟢 *Value Betting Scanner ONLINE*\n\n"
        "✅ Bot iniciado e a funcionar 24/7\n"
        "⏰ Scan automatico de 2 em 2 horas\n"
        "🚨 Alertas 30 min antes dos jogos\n"
        "🌍 Todas as ligas mundiais\n\n"
        "Primeiro scan em 15 segundos..."
    )
    def first_scan():
        time.sleep(15)
        job_scan()
    threading.Thread(target=first_scan, daemon=True).start()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    polling_loop()


if __name__ == "__main__":
    main()
