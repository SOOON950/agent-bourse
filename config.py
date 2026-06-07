"""
Configuration de l'agent boursier.
C'est le SEUL fichier que tu auras besoin de modifier au quotidien
(ajouter une valeur, changer un seuil, etc.).
"""

# =========================================================================
#  VALEURS A SURVEILLER
# =========================================================================
# - ticker  : symbole Yahoo Finance (ne pas changer sauf si tu sais)
# - name    : nom affiche dans les emails
# - secteur : la these/secteur (sert de contexte a l'analyse IA)
# - query   : mots-cles pour chercher les actualites (Google Actualites)
# - seuil   : variation (%) du jour qui declenche une alerte ROUGE pour CETTE valeur
WATCHLIST = [
    {"ticker": "ALKAL.PA", "name": "Kalray",               "secteur": "Processeurs DPU / infrastructure IA",   "query": "Kalray action bourse",            "seuil": 8},
    {"ticker": "AL2SI.PA", "name": "2CRSI",                "secteur": "Serveurs HPC / infrastructure IA",       "query": "2CRSI action bourse",             "seuil": 8},
    {"ticker": "ALRIB.PA", "name": "Riber",                "secteur": "Equipements epitaxie / semi-conducteurs","query": "Riber action bourse",             "seuil": 6},
    {"ticker": "ALHAF.PA", "name": "Haffner Energy",       "secteur": "Hydrogene / decarbonation",              "query": "Haffner Energy action bourse",    "seuil": 6},
    {"ticker": "ALMDT.PA", "name": "Median Technologies",  "secteur": "MedTech / imagerie oncologie (IA)",      "query": "Median Technologies bourse",      "seuil": 6},
    {"ticker": "VU.PA",    "name": "Vusion Group",         "secteur": "Etiquettes electroniques / retail tech", "query": "Vusion Group SES imagotag bourse","seuil": 5},
    {"ticker": "ALSTI.PA", "name": "STIF",                 "secteur": "Securite industrielle / anti-explosion", "query": "STIF action bourse",              "seuil": 6},
    {"ticker": "SIVE.ST",  "name": "Sivers Semiconductors","secteur": "Semi-conducteurs RF / photonique 5G",    "query": "Sivers Semiconductors stock",     "seuil": 6},
    {"ticker": "LQQ.PA",   "name": "LQQ (Nasdaq x2)",      "secteur": "ETF a levier x2 sur Nasdaq-100",         "query": "ETF LQQ Nasdaq levier",           "seuil": 3},
]

# Seuil par defaut si non precise au-dessus
SEUIL_DEFAUT = 5

# =========================================================================
#  REGLES D'ALERTE
# =========================================================================
# Volume anormal : alerte si le volume du jour depasse ce multiple
# de la moyenne du dernier mois.
MULTIPLE_VOLUME = 3.0

# Volume "silence" : alerte calme si le volume recent tombe sous ce multiple
# de la moyenne (valeur anormalement peu echangee).
SILENCE_VOLUME_RATIO = 0.4

# Temps minimum (en minutes) entre deux alertes ROUGES pour une MEME valeur,
# pour ne pas inonder ta boite mail. Une nouvelle alerte passe quand meme
# si le cours bouge encore de +X% (voir ci-dessous).
COOLDOWN_MINUTES = 60

# Mouvement supplementaire (%) qui force une nouvelle alerte malgre le cooldown
REALERTE_MOUVEMENT = 4.0

# =========================================================================
#  HORAIRES DES EMAILS (heure de Paris)
# =========================================================================
# Digest du matin, AVANT l'ouverture Euronext (9h).
HEURE_DIGEST = 8

# Emails "signaux importants" (niveau orange) regroupes : 1 a 2 fois / jour.
# Mets [] pour desactiver. Ex : [13, 18] = un point a midi, un a la cloture.
HEURES_SIGNAUX = [13, 18]

# Envoyer le digest aussi le week-end ? (marches fermes)
DIGEST_WEEKEND = False

# =========================================================================
#  INDICATEURS TECHNIQUES
# =========================================================================
RSI_PERIODE = 14          # periode du RSI (standard = 14)
RSI_SURACHAT = 70         # au-dessus = surachat
RSI_SURVENTE = 30         # en-dessous = survente
FENETRE_SR = 20           # nb de jours pour support/resistance (plus bas/haut recents)

# Afficher le contexte macro (taux 10 ans US, EUR/USD, Nasdaq-100, VIX)
AFFICHER_MACRO = True

# =========================================================================
#  MOTEUR IA (Google Gemini - gratuit)
# =========================================================================
# "gemini-2.5-flash" = bon equilibre. "gemini-2.5-flash-lite" = plus de quota.
MODELE_IA = "gemini-2.5-flash"

# Mettre False pour desactiver l'IA (alertes + score technique, sans interpretation)
UTILISER_IA = True
