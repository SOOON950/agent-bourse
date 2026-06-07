"""
Agent boursier automatique (version analyse complete).

Ce que fait l'agent a chaque execution (toutes les 5 min via GitHub) :
  1. Recupere 1 an de cours + volumes (Yahoo Finance, gratuit).
  2. Calcule les indicateurs techniques : RSI, MACD, moyennes mobiles
     20/50/200, support/resistance, volatilite, variations semaine/mois.
  3. Calcule un SCORE DE CONVICTION (-10 a +10) a partir de la technique.
  4. Recupere le contexte MACRO (taux 10 ans US, EUR/USD, Nasdaq-100, VIX).
  5. Recupere les ACTUALITES (Google Actualites RSS, gratuit).
  6. Classe les evenements en 3 niveaux :
       ROUGE  (immediat)  : mouvement violent, volume anormal.
       ORANGE (regroupe)  : signal technique, news nouvelle, "silence".
       Digest (8h)        : recap complet de toutes les valeurs.
  7. Fait interpreter l'evenement par l'IA Gemini (le "pourquoi" + conviction).
  8. Envoie les emails (Gmail).

Tu n'as normalement PAS besoin de modifier ce fichier. Reglages -> config.py.
"""

import os
import json
import time
import smtplib
import datetime as dt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from zoneinfo import ZoneInfo

import requests
import feedparser

import config

# ---- Secrets (lus depuis les GitHub Secrets / variables d'environnement) ----
GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY", "")
GMAIL_ADDRESS      = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
RECIPIENT_EMAIL    = os.environ.get("RECIPIENT_EMAIL", "") or GMAIL_ADDRESS

PARIS = ZoneInfo("Europe/Paris")
STATE_FILE = "state.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}


# =========================================================================
#  ETAT (persiste entre les executions via un commit GitHub)
# =========================================================================
def default_state():
    return {
        "digest_last_sent": "",     # date du dernier digest envoye
        "signaux_last_sent": {},    # {"YYYY-MM-DD-HH": True} creneaux signaux deja envoyes
        "seen_news": {},            # {ticker: [liens deja vus]}
        "last_alert": {},           # {ticker: {time, price, reason}} pour le cooldown rouge
        "tech_state": {},           # {ticker: {ma_sign, rsi_zone, macd_sign, hi, lo}}
        "pending_signaux": [],      # file d'attente des alertes oranges
    }


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            s = json.load(f)
        base = default_state()
        base.update(s)
        return base
    except Exception:
        return default_state()


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# =========================================================================
#  RESEAU YAHOO (robuste contre les blocages 403 des serveurs GitHub)
# =========================================================================
_session = None


def _yahoo_session():
    global _session
    if _session is not None:
        return _session
    s = requests.Session()
    s.headers.update(UA)
    for warmup in ("https://fc.yahoo.com", "https://finance.yahoo.com"):
        try:
            s.get(warmup, timeout=15)
            break
        except Exception:
            continue
    _session = s
    return s


def fetch_series(ticker, rng="1y"):
    """Recupere l'historique journalier. Retourne (closes, volumes, meta) ou None."""
    s = _yahoo_session()
    params = {"interval": "1d", "range": rng}
    last_err = None
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        url = f"https://{host}/v8/finance/chart/{ticker}"
        for _ in range(2):
            try:
                r = s.get(url, params=params, timeout=15)
                if r.status_code in (401, 403, 429):
                    last_err = f"HTTP {r.status_code}"
                    globals()["_session"] = None
                    s = _yahoo_session()
                    time.sleep(1.5)
                    continue
                r.raise_for_status()
                res = r.json()["chart"]["result"][0]
                meta = res["meta"]
                q = res["indicators"]["quote"][0]
                closes = [c for c in q.get("close", []) if c is not None]
                volumes = [v for v in q.get("volume", []) if v is not None]
                if len(closes) < 5:
                    return None
                return closes, volumes, meta
            except Exception as e:
                last_err = e
                time.sleep(1)
    print(f"  [!] Donnees indisponibles pour {ticker}: {last_err}")
    return None


# =========================================================================
#  INDICATEURS TECHNIQUES (Python pur, aucune dependance externe)
# =========================================================================
def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema_series(values, period):
    """Retourne la serie complete d'EMA."""
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    out = [sum(values[:period]) / period]  # 1ere EMA = SMA
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    # Moyenne de Wilder
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(closes, fast=12, slow=26, signal=9):
    """Retourne (macd_line, signal_line, histogramme) pour la derniere bougie."""
    if len(closes) < slow + signal:
        return None
    ema_fast = ema_series(closes, fast)
    ema_slow = ema_series(closes, slow)
    n = min(len(ema_fast), len(ema_slow))
    macd_line = [ema_fast[-n + i] - ema_slow[-n + i] for i in range(n)]
    signal_line = ema_series(macd_line, signal)
    if not signal_line:
        return None
    m = macd_line[-1]
    sig = signal_line[-1]
    return m, sig, m - sig


def variation_pct(closes, n):
    """Variation % sur n bougies (ex : ~5 = semaine, ~21 = mois)."""
    if len(closes) <= n:
        return None
    ref = closes[-1 - n]
    if not ref:
        return None
    return (closes[-1] - ref) / ref * 100


def volatilite(closes, n=20):
    """Ecart-type des rendements quotidiens sur n bougies (en %)."""
    if len(closes) <= n:
        return None
    rets = [(closes[-i] - closes[-i - 1]) / closes[-i - 1]
            for i in range(1, n + 1) if closes[-i - 1]]
    if not rets:
        return None
    moy = sum(rets) / len(rets)
    var = sum((x - moy) ** 2 for x in rets) / len(rets)
    return (var ** 0.5) * 100


def get_data(ticker):
    """Recupere et calcule TOUT ce dont on a besoin pour une valeur."""
    res = fetch_series(ticker)
    if not res:
        return None
    closes, volumes, meta = res

price = meta.get("regularMarketPrice") or closes[-1]
prev = closes[-2] if len(closes) > 1 else closes[-1]
    volume = meta.get("regularMarketVolume") or (volumes[-1] if volumes else None)

    mois = volumes[-21:] if len(volumes) >= 21 else volumes
    avg_volume = sum(mois) / len(mois) if mois else None
    vol5 = sum(volumes[-5:]) / len(volumes[-5:]) if len(volumes) >= 5 else None

    if not prev:
        return None
    change_pct = (price - prev) / prev * 100
    if abs(change_pct) > 50:
        print(f"  [!] Variation suspecte ignoree ({change_pct:+.1f}%) - donnee Yahoo incorrecte")
        change_pct = 0
    m = macd(closes)
    window = closes[-config.FENETRE_SR:] if len(closes) >= config.FENETRE_SR else closes
    return {
        "price": price,
        "prev": prev,
        "change_pct": change_pct,
        "volume": volume,
        "avg_volume": avg_volume,
        "vol5": vol5,
        "currency": meta.get("currency", ""),
        "rsi": rsi(closes, config.RSI_PERIODE),
        "macd": m[0] if m else None,
        "macd_signal": m[1] if m else None,
        "macd_hist": m[2] if m else None,
        "ma20": sma(closes, 20),
        "ma50": sma(closes, 50),
        "ma200": sma(closes, 200),
        "support": min(window),
        "resistance": max(window),
        "vol_pct": volatilite(closes, 20),
        "var_semaine": variation_pct(closes, 5),
        "var_mois": variation_pct(closes, 21),
        "closes": closes,
    }


# =========================================================================
#  SCORE DE CONVICTION (heuristique technique, -10 a +10)
# =========================================================================
def score_technique(d):
    """Retourne (score:int, raisons:list[str]). Sert de base; l'IA peut l'affiner."""
    score = 0
    raisons = []
    p = d["price"]

    if d["ma200"]:
        if p > d["ma200"]:
            score += 3; raisons.append("au-dessus de la MM200 (tendance long terme haussiere)")
        else:
            score -= 3; raisons.append("sous la MM200 (tendance long terme baissiere)")
    if d["ma50"]:
        if p > d["ma50"]:
            score += 2; raisons.append("au-dessus de la MM50")
        else:
            score -= 2; raisons.append("sous la MM50")
    if d["ma20"] and d["ma50"]:
        if d["ma20"] > d["ma50"]:
            score += 1; raisons.append("MM20 > MM50 (court terme oriente a la hausse)")
        else:
            score -= 1; raisons.append("MM20 < MM50 (court terme oriente a la baisse)")
    if d["macd"] is not None:
        if d["macd"] > 0:
            score += 2; raisons.append("ligne MACD positive (momentum haussier)")
        else:
            score -= 2; raisons.append("ligne MACD negative (momentum baissier)")
    if d["rsi"] is not None:
        if d["rsi"] >= config.RSI_SURACHAT:
            score -= 1; raisons.append(f"RSI {d['rsi']:.0f} (surachat, prudence)")
        elif d["rsi"] <= config.RSI_SURVENTE:
            score += 1; raisons.append(f"RSI {d['rsi']:.0f} (survente, rebond possible)")
        elif d["rsi"] >= 50:
            score += 1; raisons.append(f"RSI {d['rsi']:.0f} (momentum positif)")
        else:
            score -= 1; raisons.append(f"RSI {d['rsi']:.0f} (momentum faible)")
    if d["var_semaine"] is not None:
        if d["var_semaine"] > 3:
            score += 1
        elif d["var_semaine"] < -3:
            score -= 1

    score = max(-10, min(10, score))
    return score, raisons


def libelle_score(s):
    if s >= 7:   return "fortement haussier"
    if s >= 3:   return "haussier modere"
    if s >= -2:  return "neutre"
    if s >= -6:  return "baissier modere"
    return "fortement baissier"


# =========================================================================
#  CONTEXTE MACRO
# =========================================================================
MACRO_TICKERS = [
    ("^TNX",     "Taux 10 ans US"),
    ("EURUSD=X", "EUR/USD"),
    ("^NDX",     "Nasdaq-100"),
    ("^VIX",     "VIX (volatilite)"),
]


def get_macro():
    if not config.AFFICHER_MACRO:
        return {}
    out = {}
    for tk, label in MACRO_TICKERS:
        res = fetch_series(tk, rng="5d")
        if not res:
            continue
        closes, _, meta = res
        price = meta.get("regularMarketPrice") or closes[-1]
        prev = meta.get("chartPreviousClose") or (closes[-2] if len(closes) > 1 else price)
        chg = (price - prev) / prev * 100 if prev else 0
        out[label] = {"value": price, "change_pct": chg}
    return out


def macro_texte(macro):
    if not macro:
        return ""
    bouts = []
    for label, v in macro.items():
        bouts.append(f"{label}: {v['value']:.2f} ({v['change_pct']:+.2f}%)")
    return " | ".join(bouts)


# =========================================================================
#  ACTUALITES (Google Actualites RSS)
# =========================================================================
def get_news(query, max_items=5):
    url = ("https://news.google.com/rss/search?q="
           + requests.utils.quote(query) + "&hl=fr&gl=FR&ceid=FR:fr")
    try:
        feed = feedparser.parse(url, request_headers=UA)
        return [{"title": e.get("title", ""), "link": e.get("link", ""),
                 "published": e.get("published", "")} for e in feed.entries[:max_items]]
    except Exception as e:
        print(f"  [!] Actualites indisponibles pour '{query}': {e}")
        return []


# =========================================================================
#  IA (Google Gemini)
# =========================================================================
def _gemini(prompt):
    if not config.UTILISER_IA or not GEMINI_API_KEY:
        return None
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{config.MODELE_IA}:generateContent?key={GEMINI_API_KEY}")
    try:
        r = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]},
                          timeout=30)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"  [!] IA indisponible: {e}")
        return None


def _parse_json(txt):
    """Extrait le 1er objet JSON d'une reponse IA (qui peut contenir du texte autour)."""
    if not txt:
        return None
    a, b = txt.find("{"), txt.rfind("}")
    if a == -1 or b == -1:
        return None
    try:
        return json.loads(txt[a:b + 1])
    except Exception:
        return None


def analyse_ia_alerte(v, d, articles, score, contexte, macro):
    """Interprete une alerte. Retourne un dict {pourquoi, score, justif, a_surveiller} ou None."""
    titres = "\n".join(f"- {a['title']}" for a in articles) or "(aucune actualite recente)"
    bloc = (
        f"Valeur : {v['name']} ({v['secteur']})\n"
        f"Cours : {d['price']:.2f} {d['currency']} ({d['change_pct']:+.2f}% jour, "
        f"{(d['var_semaine'] or 0):+.1f}% semaine)\n"
        f"Volume jour : {d['volume']} | moyenne 1 mois : {d['avg_volume']:.0f}\n"
        f"RSI : {d['rsi']:.0f} | MACD hist : {d['macd_hist']:+.3f}\n"
        f"Position : prix vs MM50 {'>' if d['ma50'] and d['price']>d['ma50'] else '<'} | "
        f"vs MM200 {'>' if d['ma200'] and d['price']>d['ma200'] else '<'}\n"
        f"Support {d['support']:.2f} / Resistance {d['resistance']:.2f}\n"
        f"Score technique calcule : {score:+d}/10\n"
        f"Contexte macro : {macro_texte(macro) or 'n/d'}\n"
        f"Declencheur de l'alerte : {contexte}\n\n"
        f"Actualites recentes liees a la valeur :\n{titres}\n"
    )
    instructions = (
        "Tu es un analyste financier factuel specialise small caps FR et ETF a levier. "
        "Analyse l'evenement ci-dessus en croisant macro, technique, micro et sentiment. "
        "Ne donne PAS de conseil d'achat/vente. Reponds UNIQUEMENT par un objet JSON valide, "
        "sans texte autour, avec exactement ces cles :\n"
        '{"pourquoi": "1-2 phrases sur la cause la plus probable, reliee a une actualite si pertinent", '
        '"score": un entier de -10 a 10 (ta conviction finale, en partant du score technique mais '
        'en ajustant selon news/sentiment), '
        '"justif": "1 phrase justifiant le score et le principal risque", '
        '"a_surveiller": "1 phrase: prochain niveau de prix, catalyseur ou risque a surveiller"}'
    )
    data = _parse_json(_gemini(bloc + "\n" + instructions))
    if data and "pourquoi" in data:
        return data
    return None


def analyse_ia_digest(lignes, macro):
    """Genere la meteo macro + le focus du jour pour le digest. Retourne (meteo, focus)."""
    resume = "\n".join(lignes)
    bloc = (
        f"Contexte macro du jour : {macro_texte(macro) or 'n/d'}\n\n"
        f"Etat des valeurs suivies (variation jour, RSI, score de conviction) :\n{resume}\n"
    )
    instructions = (
        "Tu es un analyste financier factuel. A partir des donnees ci-dessus, "
        "redige un point d'avant-marche. Pas de conseil d'achat/vente. "
        "Reponds UNIQUEMENT par un objet JSON valide avec ces cles :\n"
        '{"meteo": "2-3 phrases sur le climat de marche du jour (taux, EUR/USD, Nasdaq, VIX) '
        'et son impact probable sur ces small caps tech", '
        '"focus": "1-2 phrases sur les valeurs a surveiller en priorite aujourd hui et pourquoi"}'
    )
    data = _parse_json(_gemini(bloc + "\n" + instructions))
    if data:
        return data.get("meteo", ""), data.get("focus", "")
    return "", ""


# =========================================================================
#  EMAIL (Gmail SMTP)
# =========================================================================
def send_email(subject, html_body):
    if not (GMAIL_ADDRESS and GMAIL_APP_PASSWORD):
        print("  [!] Email non configure, alerte affichee seulement :")
        print("     ", subject)
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            s.sendmail(GMAIL_ADDRESS, [RECIPIENT_EMAIL], msg.as_string())
        print(f"  -> Email envoye : {subject}")
    except Exception as e:
        print(f"  [!] Echec envoi email : {e}")


def html_wrap(inner):
    return f"""<div style="font-family:Arial,Helvetica,sans-serif;max-width:640px;color:#222;line-height:1.5">
{inner}
<hr style="border:none;border-top:1px solid #eee;margin:18px 0">
<p style="font-size:11px;color:#999">Agent boursier automatique. Information d'aide a la decision,
PAS un conseil d'investissement. Cours Yahoo Finance (differe ~15 min), actualites Google,
analyse Gemini. Les decisions vous appartiennent.</p>
</div>"""


def badge_score(s):
    if s >= 3:   c = "#1e8449"
    elif s >= -2: c = "#7f8c8d"
    else:        c = "#c0392b"
    return (f'<span style="background:{c};color:#fff;padding:2px 8px;border-radius:10px;'
            f'font-size:13px;font-weight:bold">{s:+d}/10 · {libelle_score(s)}</span>')


def bloc_donnees(d):
    pos50 = "au-dessus" if (d["ma50"] and d["price"] > d["ma50"]) else "en-dessous"
    pos200 = "au-dessus" if (d["ma200"] and d["price"] > d["ma200"]) else "en-dessous"
    vol_txt = f"{d['volume']:,}".replace(",", " ") if d["volume"] else "n/d"
    avg_txt = f"{d['avg_volume']:,.0f}".replace(",", " ") if d["avg_volume"] else "n/d"
    rsi_txt = f"{d['rsi']:.0f}" if d["rsi"] is not None else "n/d"
    return f"""<table style="font-size:13px;border-collapse:collapse;margin:8px 0">
<tr><td style="padding:2px 10px 2px 0;color:#666">Cours</td><td><b>{d['price']:.2f} {d['currency']}</b>
({d['change_pct']:+.2f}% jour · {(d['var_semaine'] or 0):+.1f}% sem · {(d['var_mois'] or 0):+.1f}% mois)</td></tr>
<tr><td style="padding:2px 10px 2px 0;color:#666">Volume</td><td>{vol_txt} (moy. {avg_txt})</td></tr>
<tr><td style="padding:2px 10px 2px 0;color:#666">RSI</td><td>{rsi_txt} · MACD {('+' if (d['macd'] or 0)>=0 else '')}{(d['macd'] or 0):.2f} (hist {('+' if (d['macd_hist'] or 0)>=0 else '')}{(d['macd_hist'] or 0):.2f})</td></tr>
<tr><td style="padding:2px 10px 2px 0;color:#666">Tendance</td><td>{pos50} MM50, {pos200} MM200</td></tr>
<tr><td style="padding:2px 10px 2px 0;color:#666">Support/Resist.</td><td>{d['support']:.2f} / {d['resistance']:.2f}</td></tr>
</table>"""


# =========================================================================
#  DETECTION DES EVENEMENTS (3 niveaux)
# =========================================================================
def rsi_zone(r):
    if r is None:
        return "n/d"
    if r >= config.RSI_SURACHAT:
        return "surachat"
    if r <= config.RSI_SURVENTE:
        return "survente"
    return "neutre"


def evaluer(v, d, state):
    """Retourne (rouges, oranges) : listes de libelles d'evenements declenches."""
    ticker = v["ticker"]
    seuil = v.get("seuil", config.SEUIL_DEFAUT)
    rouges, oranges = [], []

    # ----- ROUGE : mouvement violent / volume anormal -----
    if abs(d["change_pct"]) >= seuil:
        rouges.append(f"variation de {d['change_pct']:+.2f}% (seuil {seuil}%)")
    if d["avg_volume"] and d["volume"] and d["volume"] >= config.MULTIPLE_VOLUME * d["avg_volume"]:
        rouges.append(f"volume anormal (x{d['volume'] / d['avg_volume']:.1f} la moyenne)")

    # ----- ORANGE : signaux techniques (sur TRANSITION uniquement) -----
    ts = state["tech_state"].get(ticker, {})
    new_ts = dict(ts)

    # Croisement MM50/MM200 (golden / death cross)
    if d["ma50"] and d["ma200"]:
        sign = 1 if d["ma50"] > d["ma200"] else -1
        if ts.get("ma_sign") is not None and ts["ma_sign"] != sign:
            oranges.append("golden cross (MM50 repasse au-dessus MM200)" if sign > 0
                           else "death cross (MM50 repasse sous MM200)")
        new_ts["ma_sign"] = sign

    # Entree en zone RSI extreme
    zone = rsi_zone(d["rsi"])
    if ts.get("rsi_zone") and ts["rsi_zone"] != zone and zone in ("surachat", "survente"):
        oranges.append(f"RSI entre en zone de {zone} ({d['rsi']:.0f})")
    new_ts["rsi_zone"] = zone

    # Croisement MACD (signe de l'histogramme)
    if d["macd_hist"] is not None:
        msign = 1 if d["macd_hist"] >= 0 else -1
        if ts.get("macd_sign") is not None and ts["macd_sign"] != msign:
            oranges.append("MACD repasse positif" if msign > 0 else "MACD repasse negatif")
        new_ts["macd_sign"] = msign

    # Cassure de plus haut / plus bas (hors mouvement deja signale en rouge)
    if ts.get("hi") and d["price"] > ts["hi"] * 1.001 and not rouges:
        oranges.append("cassure d'un plus-haut recent")
    if ts.get("lo") and d["price"] < ts["lo"] * 0.999 and not rouges:
        oranges.append("cassure d'un plus-bas recent")
    new_ts["hi"] = d["resistance"]
    new_ts["lo"] = d["support"]

    # Silence : volume recent anormalement bas + cours calme
    if (d["vol5"] and d["avg_volume"] and d["vol5"] < config.SILENCE_VOLUME_RATIO * d["avg_volume"]
            and abs(d["change_pct"]) < 1):
        oranges.append("activite anormalement calme (volume effondre)")

    state["tech_state"][ticker] = new_ts
    return rouges, oranges


def cooldown_actif(state, ticker, price):
    info = state["last_alert"].get(ticker)
    if not info:
        return False
    try:
        last_time = dt.datetime.fromisoformat(info["time"])
    except Exception:
        return False
    minutes = (dt.datetime.now(PARIS) - last_time).total_seconds() / 60
    if minutes >= config.COOLDOWN_MINUTES:
        return False
    bouge = abs(price - info["price"]) / info["price"] * 100
    return bouge < config.REALERTE_MOUVEMENT


# =========================================================================
#  TRAITEMENT D'UNE VALEUR
# =========================================================================
def traiter_valeur(v, state, macro):
    ticker, name = v["ticker"], v["name"]
    print(f"- {name} ({ticker})")

    d = get_data(ticker)
    if not d:
        return
    score, raisons_tech = score_technique(d)

    # Actualites (memorisation au 1er passage pour ne pas spammer l'historique)
    premiere_fois = ticker not in state["seen_news"]
    seen = state["seen_news"].setdefault(ticker, [])
    articles = get_news(v["query"])
    nouvelles = [] if premiere_fois else [a for a in articles if a["link"] not in seen]
    for a in articles:
        if a["link"] not in seen:
            seen.append(a["link"])
    state["seen_news"][ticker] = seen[-40:]

    rouges, oranges = evaluer(v, d, state)
    if nouvelles:
        oranges.append(f"{len(nouvelles)} actualite(s) nouvelle(s)")

    # ---- ALERTE ROUGE : email immediat ----
    if rouges:
        if cooldown_actif(state, ticker, d["price"]):
            print("  (cooldown actif, alerte rouge ignoree)")
        else:
            contexte = " + ".join(rouges)
            print(f"  !! ROUGE : {contexte}")
            ia = analyse_ia_alerte(v, d, nouvelles or articles, score, contexte, macro)
            conviction = ia["score"] if ia and isinstance(ia.get("score"), int) else score
            fleche = "🟢" if d["change_pct"] >= 0 else "🔴"
            subject = f"{fleche} {name} {d['change_pct']:+.1f}% — {rouges[0]}"

            liste_news = "".join(
                f'<li><a href="{a["link"]}">{a["title"]}</a></li>'
                for a in (nouvelles or articles)[:4]) or "<li>Aucune actualite recente.</li>"
            bloc_ia = ""
            if ia:
                bloc_ia = (f'<div style="background:#f4f7fb;padding:10px 12px;border-radius:6px;margin:8px 0">'
                           f'<b>Pourquoi :</b> {ia.get("pourquoi","")}<br>'
                           f'<b>A surveiller :</b> {ia.get("a_surveiller","")}<br>'
                           f'<span style="color:#666;font-size:12px">{ia.get("justif","")}</span></div>')

            inner = (f'<h2 style="margin:0 0 4px">{fleche} {name}</h2>'
                     f'<p style="margin:0 0 8px">{badge_score(conviction)}</p>'
                     f'<p style="margin:0 0 4px"><b>Declencheur :</b> {contexte}</p>'
                     f'{bloc_donnees(d)}{bloc_ia}'
                     f'<p style="margin:10px 0 4px"><b>Actualites :</b></p>'
                     f'<ul style="margin:0;padding-left:18px">{liste_news}</ul>')
            send_email(subject, html_wrap(inner))
            state["last_alert"][ticker] = {
                "time": dt.datetime.now(PARIS).isoformat(),
                "price": d["price"], "reason": contexte,
            }

    # ---- ALERTE ORANGE : mise en file pour l'email regroupe ----
    if oranges:
        print(f"  ~ ORANGE : {', '.join(oranges)}")
        liens = [{"title": a["title"], "link": a["link"]} for a in (nouvelles or articles)[:2]]
        state["pending_signaux"].append({
            "name": name, "ticker": ticker, "score": score,
            "change_pct": round(d["change_pct"], 2),
            "rsi": round(d["rsi"], 0) if d["rsi"] is not None else None,
            "events": oranges, "news": liens,
        })


# =========================================================================
#  EMAIL "SIGNAUX" (niveau orange regroupe, 1-2x / jour)
# =========================================================================
def envoyer_signaux(state):
    now = dt.datetime.now(PARIS)
    if now.hour not in config.HEURES_SIGNAUX:
        return
    slot = now.strftime("%Y-%m-%d-") + str(now.hour)
    if state["signaux_last_sent"].get(slot):
        return
    pending = state.get("pending_signaux", [])
    if not pending:
        state["signaux_last_sent"][slot] = True
        return

    print(f"=> Envoi de l'email signaux ({len(pending)} valeur(s))")
    # Regroupe par valeur (derniere occurrence = la plus fraiche)
    par_valeur = {}
    for s in pending:
        par_valeur[s["ticker"]] = s

    cartes = []
    for s in par_valeur.values():
        evts = "".join(f"<li>{e}</li>" for e in s["events"])
        news = "".join(f'<li><a href="{n["link"]}">{n["title"]}</a></li>' for n in s["news"])
        news_bloc = f'<p style="margin:6px 0 2px;color:#666;font-size:12px">Actualites :</p><ul style="margin:0;padding-left:18px;font-size:12px">{news}</ul>' if news else ""
        rsi_txt = f" · RSI {s['rsi']:.0f}" if s["rsi"] is not None else ""
        cartes.append(
            f'<div style="border:1px solid #eee;border-radius:8px;padding:10px 12px;margin:0 0 10px">'
            f'<div style="display:flex;justify-content:space-between">'
            f'<b>{s["name"]}</b> {badge_score(s["score"])}</div>'
            f'<p style="margin:4px 0;color:#666;font-size:13px">{s["change_pct"]:+.2f}% jour{rsi_txt}</p>'
            f'<ul style="margin:4px 0;padding-left:18px;font-size:13px">{evts}</ul>{news_bloc}</div>')

    inner = (f'<h2 style="margin:0 0 4px">🟠 Signaux importants — {now.strftime("%d/%m %H:%M")}</h2>'
             f'<p style="color:#666;margin:0 0 12px">Signaux techniques et actualites a regarder.</p>'
             + "".join(cartes))
    send_email(f"🟠 {len(par_valeur)} signal(aux) boursier(s) — {now.strftime('%d/%m %Hh')}",
               html_wrap(inner))
    state["signaux_last_sent"][slot] = True
    state["pending_signaux"] = []


# =========================================================================
#  DIGEST MATINAL (8h)
# =========================================================================
def envoyer_digest(state, macro):
    now = dt.datetime.now(PARIS)
    today = now.date().isoformat()
    if state.get("digest_last_sent") == today:
        return
    if now.hour < config.HEURE_DIGEST:
        return
    if not config.DIGEST_WEEKEND and now.weekday() >= 5:
        state["digest_last_sent"] = today
        return

    print("=> Construction du digest matinal")
    lignes_html, lignes_ia, movers = [], [], []
    for v in config.WATCHLIST:
        d = get_data(v["ticker"])
        if not d:
            lignes_html.append(f'<tr><td style="padding:5px 8px">{v["name"]}</td>'
                               f'<td colspan="4" style="padding:5px 8px;color:#999">indisponible</td></tr>')
            continue
        sc, _ = score_technique(d)
        movers.append((abs(d["change_pct"]), v["name"], d["change_pct"]))
        rsi_txt = f"{d['rsi']:.0f}" if d["rsi"] is not None else "—"
        coul = "#c0392b" if d["change_pct"] < 0 else "#1e8449"
        lignes_html.append(
            f'<tr style="border-bottom:1px solid #f0f0f0">'
            f'<td style="padding:5px 8px">{v["name"]}</td>'
            f'<td style="padding:5px 8px;text-align:right">{d["price"]:.2f}</td>'
            f'<td style="padding:5px 8px;text-align:right;color:{coul}">{d["change_pct"]:+.2f}%</td>'
            f'<td style="padding:5px 8px;text-align:right">{rsi_txt}</td>'
            f'<td style="padding:5px 8px;text-align:right;font-weight:bold">{sc:+d}</td></tr>')
        lignes_ia.append(f"{v['name']}: {d['change_pct']:+.1f}% jour, RSI {rsi_txt}, score {sc:+d}")

    meteo, focus = analyse_ia_digest(lignes_ia, macro)
    bloc_macro = (f'<p style="background:#f7f9fc;padding:8px 12px;border-radius:6px;font-size:13px;color:#444">'
                  f'<b>Macro :</b> {macro_texte(macro)}</p>') if macro else ""
    bloc_meteo = (f'<div style="background:#f4f7fb;padding:10px 12px;border-radius:6px;margin:8px 0">'
                  f'<b>Meteo du jour :</b> {meteo}<br><b>A surveiller :</b> {focus}</div>') if meteo else ""

    movers.sort(reverse=True)
    top = movers[:3]
    top_txt = ", ".join(f"{n} ({c:+.1f}%)" for _, n, c in top) if top else "—"

    inner = (f'<h2 style="margin:0 0 10px">☕ Digest boursier — {now.strftime("%d/%m/%Y")}</h2>'
             f'<p style="color:#666;margin:0 0 10px">Avant ouverture Euronext (9h).</p>'
             f'{bloc_macro}{bloc_meteo}'
             f'<p style="margin:10px 0 4px"><b>Mouvements marquants :</b> {top_txt}</p>'
             f'<table style="border-collapse:collapse;width:100%;font-size:13px;margin-top:8px">'
             f'<tr style="border-bottom:2px solid #ddd;text-align:right">'
             f'<th style="text-align:left;padding:5px 8px">Valeur</th>'
             f'<th style="padding:5px 8px">Cours</th><th style="padding:5px 8px">Jour</th>'
             f'<th style="padding:5px 8px">RSI</th><th style="padding:5px 8px">Score</th></tr>'
             f'{"".join(lignes_html)}</table>')
    send_email(f"☕ Digest boursier du {now.strftime('%d/%m')}", html_wrap(inner))
    state["digest_last_sent"] = today


# =========================================================================
#  MAIN
# =========================================================================
def main():
    print(f"=== Agent boursier — {dt.datetime.now(PARIS):%Y-%m-%d %H:%M} (Paris) ===")
    state = load_state()
    macro = get_macro()
    if macro:
        print("Macro :", macro_texte(macro))

    envoyer_digest(state, macro)

    for v in config.WATCHLIST:
        try:
            traiter_valeur(v, state, macro)
        except Exception as e:
            print(f"  [!] Erreur sur {v['name']}: {e}")

    envoyer_signaux(state)
    save_state(state)
    print("=== Termine ===")


if __name__ == "__main__":
    main()
