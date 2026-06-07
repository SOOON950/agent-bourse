"""
Agent boursier automatique.
- Recupere cours + volume (Yahoo Finance, gratuit)
- Recupere les actualites (Google Actualites RSS, gratuit)
- Detecte les mouvements violents / volumes anormaux / news nouvelles
- Fait interpreter l'evenement par l'IA Gemini (gratuit) -> le "pourquoi"
- Envoie une alerte email, + un digest chaque matin a 8h

Tu n'as normalement PAS besoin de modifier ce fichier.
Les reglages sont dans config.py.
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

# ---- Secrets (lus depuis les variables d'environnement / GitHub Secrets) ----
GEMINI_API_KEY   = os.environ.get("GEMINI_API_KEY", "")
GMAIL_ADDRESS    = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
RECIPIENT_EMAIL  = os.environ.get("RECIPIENT_EMAIL", "") or GMAIL_ADDRESS

PARIS = ZoneInfo("Europe/Paris")
STATE_FILE = "state.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}


# =========================================================================
#  ETAT (persiste entre les executions via un commit GitHub)
# =========================================================================
def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"digest_last_sent": "", "seen_news": {}, "last_alert": {}}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# =========================================================================
#  DONNEES DE MARCHE (Yahoo Finance)
# =========================================================================
_session = None


def _yahoo_session():
    """Session Yahoo avec cookies. Reduit fortement les blocages 403 sur les
    serveurs GitHub (Yahoo bloque souvent les requetes sans cookie de session)."""
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


def get_quote(ticker):
    """Retourne prix, variation %, volume et volume moyen, ou None si indisponible.
    Robuste : cookies de session + reessais + second serveur de secours."""
    s = _yahoo_session()
    params = {"interval": "1d", "range": "1mo"}
    last_err = None
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        url = f"https://{host}/v8/finance/chart/{ticker}"
        for attempt in range(2):
            try:
                r = s.get(url, params=params, timeout=15)
                if r.status_code in (401, 403, 429):
                    # session expiree ou rate-limit : on rafraichit et on retente
                    last_err = f"HTTP {r.status_code}"
                    globals()["_session"] = None
                    s = _yahoo_session()
                    time.sleep(1.5)
                    continue
                r.raise_for_status()
                res = r.json()["chart"]["result"][0]
                meta = res["meta"]
                price = meta.get("regularMarketPrice")
                prev = meta.get("chartPreviousClose") or meta.get("previousClose")
                volume = meta.get("regularMarketVolume")

                volumes = [v for v in res["indicators"]["quote"][0].get("volume", []) if v]
                avg_volume = sum(volumes) / len(volumes) if volumes else None

                if price is None or prev in (None, 0):
                    return None
                change_pct = (price - prev) / prev * 100
                return {
                    "price": price,
                    "prev": prev,
                    "change_pct": change_pct,
                    "volume": volume,
                    "avg_volume": avg_volume,
                    "currency": meta.get("currency", ""),
                }
            except Exception as e:
                last_err = e
                time.sleep(1)
    print(f"  [!] Cours indisponible pour {ticker}: {last_err}")
    return None


# =========================================================================
#  ACTUALITES (Google Actualites RSS)
# =========================================================================
def get_news(query, max_items=5):
    """Retourne une liste d'articles recents : [{title, link, published}]."""
    url = ("https://news.google.com/rss/search?q="
           + requests.utils.quote(query)
           + "&hl=fr&gl=FR&ceid=FR:fr")
    try:
        feed = feedparser.parse(url, request_headers=UA)
        out = []
        for entry in feed.entries[:max_items]:
            out.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
            })
        return out
    except Exception as e:
        print(f"  [!] Actualites indisponibles pour '{query}': {e}")
        return []


# =========================================================================
#  IA (Google Gemini)
# =========================================================================
def analyse_ia(name, quote, articles, contexte):
    """Demande a Gemini d'expliquer l'evenement. Retourne du texte ou ''."""
    if not config.UTILISER_IA or not GEMINI_API_KEY:
        return ""

    titres = "\n".join(f"- {a['title']}" for a in articles) or "(aucune actualite recente trouvee)"
    prompt = f"""Tu es un analyste financier. Une alerte vient de se declencher sur la valeur {name}.

Donnees :
- Cours : {quote['price']:.2f} {quote['currency']} ({quote['change_pct']:+.2f}% sur la journee)
- Volume du jour : {quote['volume']} | Volume moyen (1 mois) : {quote['avg_volume']:.0f}
- Declencheur : {contexte}

Actualites recentes liees a la valeur :
{titres}

En 4 lignes MAXIMUM et en francais :
1. Explique la cause la plus probable du mouvement (relie-le a une actualite si pertinent).
2. Donne un niveau de confiance (faible/moyen/eleve) et le principal risque.
Sois factuel et concis. Ne donne PAS de conseil d'achat ou de vente."""

    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{config.MODELE_IA}:generateContent?key={GEMINI_API_KEY}")
    try:
        r = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]},
                          timeout=30)
        r.raise_for_status()
        data = r.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"  [!] IA indisponible: {e}")
        return ""


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
    return f"""<div style="font-family:Arial,sans-serif;max-width:600px;color:#222">
{inner}
<hr style="border:none;border-top:1px solid #eee;margin:18px 0">
<p style="font-size:11px;color:#999">Agent boursier automatique. Information d'aide a la decision,
pas un conseil d'investissement. Donnees Yahoo Finance (differe ~15 min) et Google Actualites.</p>
</div>"""


# =========================================================================
#  ALERTE SUR UNE VALEUR
# =========================================================================
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
    # Cooldown encore actif SAUF si le cours a encore bien bouge
    bouge = abs(price - info["price"]) / info["price"] * 100
    return bouge < config.REALERTE_MOUVEMENT


def traiter_valeur(v, state):
    ticker, name = v["ticker"], v["name"]
    seuil = v.get("seuil", config.SEUIL_DEFAUT)
    print(f"- {name} ({ticker})")

    quote = get_quote(ticker)
    if not quote:
        return

    # Detection des declencheurs
    raisons = []
    if abs(quote["change_pct"]) >= seuil:
        raisons.append(f"variation de {quote['change_pct']:+.2f}% (seuil {seuil}%)")
    if quote["avg_volume"] and quote["volume"] and quote["volume"] >= config.MULTIPLE_VOLUME * quote["avg_volume"]:
        mult = quote["volume"] / quote["avg_volume"]
        raisons.append(f"volume anormal (x{mult:.1f} la moyenne)")

    # Actualites nouvelles (jamais vues)
    premiere_fois = ticker not in state["seen_news"]
    seen = state["seen_news"].setdefault(ticker, [])
    articles = get_news(v["query"])
    # Au tout premier passage, on memorise sans alerter (sinon rafale d'emails
    # sur des actualites deja anciennes).
    nouvelles = [] if premiere_fois else [a for a in articles if a["link"] not in seen]
    if nouvelles:
        raisons.append(f"{len(nouvelles)} actualite(s) nouvelle(s)")

    # On enregistre tous les articles vus (cap a 40)
    for a in articles:
        if a["link"] not in seen:
            seen.append(a["link"])
    state["seen_news"][ticker] = seen[-40:]

    if not raisons:
        return  # rien a signaler

    if cooldown_actif(state, ticker, quote["price"]):
        print("  (cooldown actif, alerte ignoree)")
        return

    contexte = " + ".join(raisons)
    print(f"  !! ALERTE : {contexte}")

    interpretation = analyse_ia(name, quote, nouvelles or articles, contexte)

    fleche = "🔴" if quote["change_pct"] < 0 else "🟢"
    subject = f"{fleche} {name} {quote['change_pct']:+.1f}% — {raisons[0]}"

    liste_news = "".join(
        f'<li><a href="{a["link"]}">{a["title"]}</a></li>' for a in (nouvelles or articles)[:4]
    ) or "<li>Aucune actualite recente trouvee.</li>"

    inner = f"""<h2 style="margin:0 0 4px">{fleche} {name}</h2>
<p style="margin:0 0 12px;color:#666">{quote['price']:.2f} {quote['currency']}
<b style="color:{'#c0392b' if quote['change_pct']<0 else '#1e8449'}">({quote['change_pct']:+.2f}%)</b></p>
<p style="margin:0 0 6px"><b>Declencheur :</b> {contexte}</p>
<p style="margin:0 0 6px"><b>Volume :</b> {quote['volume']:,} (moy. {quote['avg_volume']:,.0f})</p>
{f'<p style="background:#f4f7fb;padding:10px;border-radius:6px"><b>Analyse IA :</b><br>{interpretation}</p>' if interpretation else ''}
<p style="margin:12px 0 4px"><b>Actualites :</b></p>
<ul style="margin:0;padding-left:18px">{liste_news}</ul>"""

    send_email(subject, html_wrap(inner))

    state["last_alert"][ticker] = {
        "time": dt.datetime.now(PARIS).isoformat(),
        "price": quote["price"],
        "reason": contexte,
    }


# =========================================================================
#  DIGEST MATINAL
# =========================================================================
def envoyer_digest(state):
    now = dt.datetime.now(PARIS)
    today = now.date().isoformat()

    if state.get("digest_last_sent") == today:
        return
    if now.hour < config.HEURE_DIGEST:
        return
    if not config.DIGEST_WEEKEND and now.weekday() >= 5:
        state["digest_last_sent"] = today  # on marque pour ne pas reverifier
        return

    print("=> Construction du digest matinal")
    lignes = []
    for v in config.WATCHLIST:
        q = get_quote(v["ticker"])
        if not q:
            lignes.append(f'<tr><td>{v["name"]}</td><td colspan="2" style="color:#999">indisponible</td></tr>')
            continue
        couleur = "#c0392b" if q["change_pct"] < 0 else "#1e8449"
        lignes.append(
            f'<tr><td style="padding:4px 8px">{v["name"]}</td>'
            f'<td style="padding:4px 8px;text-align:right">{q["price"]:.2f} {q["currency"]}</td>'
            f'<td style="padding:4px 8px;text-align:right;color:{couleur}">{q["change_pct"]:+.2f}%</td></tr>'
        )

    inner = f"""<h2 style="margin:0 0 10px">☕ Digest boursier — {now.strftime('%d/%m/%Y')}</h2>
<p style="color:#666;margin:0 0 12px">Avant ouverture (Euronext 9h). Voici l'etat de tes valeurs.</p>
<table style="border-collapse:collapse;width:100%;font-size:14px">
<tr style="border-bottom:2px solid #ddd"><th style="text-align:left;padding:4px 8px">Valeur</th>
<th style="text-align:right;padding:4px 8px">Cours</th><th style="text-align:right;padding:4px 8px">Var.</th></tr>
{''.join(lignes)}
</table>"""

    send_email(f"☕ Digest boursier du {now.strftime('%d/%m')}", html_wrap(inner))
    state["digest_last_sent"] = today


# =========================================================================
#  MAIN
# =========================================================================
def main():
    print(f"=== Agent boursier — {dt.datetime.now(PARIS):%Y-%m-%d %H:%M} (Paris) ===")
    state = load_state()

    envoyer_digest(state)

    for v in config.WATCHLIST:
        try:
            traiter_valeur(v, state)
        except Exception as e:
            print(f"  [!] Erreur sur {v['name']}: {e}")

    save_state(state)
    print("=== Termine ===")


if __name__ == "__main__":
    main()
