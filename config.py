"""
Configuration de l'agent boursier.
C'est le SEUL fichier que tu auras besoin de modifier si tu veux
ajouter/retirer des valeurs ou changer les seuils d'alerte.
"""

# =========================================================================
#  VALEURS A SURVEILLER
# =========================================================================
# - ticker  : symbole Yahoo Finance (ne pas changer sauf si tu sais)
# - name    : nom affiche dans les emails
# - query   : mots-cles pour chercher les actualites (Google Actualites)
# - seuil   : variation (%) du jour qui declenche une alerte pour CETTE valeur
WATCHLIST = [
    {"ticker": "ALKAL.PA", "name": "Kalray",              "query": "Kalray action bourse",          "seuil": 8},
    {"ticker": "AL2SI.PA", "name": "2CRSI",               "query": "2CRSI action bourse",            "seuil": 8},
    {"ticker": "ALRIB.PA", "name": "Riber",               "query": "Riber action bourse",            "seuil": 6},
    {"ticker": "ALHAF.PA", "name": "Haffner Energy",      "query": "Haffner Energy action bourse",   "seuil": 6},
    {"ticker": "ALMDT.PA", "name": "Median Technologies", "query": "Median Technologies bourse",     "seuil": 6},
    {"ticker": "VU.PA",    "name": "Vusion Group",        "query": "Vusion Group SES imagotag bourse","seuil": 5},
    {"ticker": "ALSTI.PA", "name": "STIF",                "query": "STIF action bourse",             "seuil": 6},
    {"ticker": "SIVE.ST",  "name": "Sivers Semiconductors","query": "Sivers Semiconductors stock",   "seuil": 6},
    {"ticker": "LQQ.PA",   "name": "LQQ (Nasdaq x2)",     "query": "ETF LQQ Nasdaq levier",          "seuil": 3},
]

# Seuil par defaut si non precise au-dessus
SEUIL_DEFAUT = 5

# =========================================================================
#  REGLES D'ALERTE
# =========================================================================
# Volume anormal : on alerte si le volume du jour depasse ce multiple
# de la moyenne du dernier mois.
MULTIPLE_VOLUME = 3.0

# Temps minimum (en minutes) entre deux alertes pour une MEME valeur,
# pour ne pas inonder ta boite mail. Une nouvelle alerte passe quand meme
# si le cours bouge encore de +X% (voir ci-dessous).
COOLDOWN_MINUTES = 60

# Mouvement supplementaire (%) qui force une nouvelle alerte malgre le cooldown
REALERTE_MOUVEMENT = 4.0

# =========================================================================
#  DIGEST MATINAL
# =========================================================================
# Heure (heure de Paris) d'envoi du recap quotidien, avant l'ouverture (9h).
HEURE_DIGEST = 8

# Envoyer le digest aussi le week-end ? (les marches sont fermes)
DIGEST_WEEKEND = False

# =========================================================================
#  MOTEUR IA (Google Gemini - gratuit)
# =========================================================================
# Modele gratuit. "gemini-2.5-flash" = bon equilibre. "gemini-2.5-flash-lite" = + de quota.
MODELE_IA = "gemini-2.5-flash"

# Mettre False pour desactiver totalement l'IA (alertes brutes sans interpretation)
UTILISER_IA = True
