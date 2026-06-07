# 🤖 Agent boursier automatique

Surveille tes valeurs 24h/24, t'envoie un **digest chaque matin à 8h** et des **alertes**
dès qu'il se passe quelque chose (mouvement violent, volume anormal, actualité nouvelle),
avec une **interprétation par IA** (le « pourquoi »).

100% gratuit : GitHub Actions (exécution) + Yahoo Finance (cours) + Google Actualités (news) + Gemini (IA gratuite) + Gmail (envoi).

---

## 📋 Ce dont tu as besoin (tout est gratuit)

1. Un compte **GitHub** (déjà fait ✅)
2. Une clé **Google Gemini** (gratuite, sans carte bancaire)
3. Un **mot de passe d'application Gmail** (pour l'envoi des emails)

Suis les étapes dans l'ordre. Compte ~20 minutes la première fois.

---

## ÉTAPE 1 — Récupérer ta clé Gemini (gratuite)

1. Va sur **https://aistudio.google.com/apikey**
2. Connecte-toi avec ton compte Google.
3. Clique sur **« Create API key »** (Créer une clé API).
4. **Copie la clé** (une longue suite de caractères) et garde-la de côté.

> Pas de carte bancaire demandée. C'est l'offre gratuite.

---

## ÉTAPE 2 — Préparer Gmail pour l'envoi

Gmail a besoin d'un « mot de passe d'application » (différent de ton mot de passe normal).

1. Active d'abord la **validation en 2 étapes** si ce n'est pas fait :
   **https://myaccount.google.com/security** → « Validation en deux étapes ».
2. Va ensuite sur **https://myaccount.google.com/apppasswords**
3. Donne un nom (ex : « agent bourse ») et clique sur **Créer**.
4. Google affiche un mot de passe de **16 lettres** → copie-le (sans les espaces).

> Si la page « apppasswords » te dit qu'elle n'est pas disponible, c'est que la
> validation en 2 étapes n'est pas encore active. Fais l'étape 1 d'abord.

---

## ÉTAPE 3 — Déposer le projet sur GitHub

1. Va sur **https://github.com/new** (créer un nouveau dépôt).
2. **Repository name** : `agent-bourse` (ou ce que tu veux).
3. ⚠️ Choisis **Public** (les dépôts publics ont des exécutions GitHub Actions illimitées et gratuites).
4. Clique **« Create repository »**.
5. Sur la page du dépôt vide, clique sur **« uploading an existing file »**.
6. **Glisse-dépose TOUS les fichiers du dossier** (`agent.py`, `config.py`,
   `requirements.txt`, `state.json`, `.gitignore`, et le dossier `.github`).
   - Astuce : sélectionne tout le contenu du dossier et glisse-le d'un coup.
7. En bas, clique **« Commit changes »**.

> Vérifie qu'il y a bien un dossier `.github/workflows/agent.yml` en ligne.

---

## ÉTAPE 4 — Configurer les secrets (tes clés)

Tes clés ne doivent JAMAIS être écrites dans le code. On les met dans les « Secrets » de GitHub.

1. Sur ton dépôt : **Settings** (en haut) → menu de gauche **Secrets and variables** → **Actions**.
2. Clique **« New repository secret »** et crée ces 4 secrets, un par un :

| Name (exactement) | Secret value |
|---|---|
| `GEMINI_API_KEY` | ta clé Gemini de l'étape 1 |
| `GMAIL_ADDRESS` | ton adresse Gmail (ex : `moi@gmail.com`) |
| `GMAIL_APP_PASSWORD` | le mot de passe 16 lettres de l'étape 2 |
| `RECIPIENT_EMAIL` | l'adresse où recevoir les alertes (peut être la même) |

> Respecte exactement les noms (majuscules, underscores).

---

## ÉTAPE 5 — Activer et tester

1. Va dans l'onglet **« Actions »** de ton dépôt.
2. Si GitHub demande d'activer les workflows, clique pour **autoriser**.
3. Clique sur **« Agent boursier »** dans la liste de gauche.
4. Clique **« Run workflow »** (bouton à droite) → **Run workflow** → ça lance un test immédiat.
5. Attends ~1 minute, rafraîchis. Un point vert ✅ = ça a marché.
6. Clique sur l'exécution pour voir les logs (utile en cas de souci).

À partir de là, l'agent tourne **tout seul toutes les 5 minutes**, sans rien faire.

---

## ✅ C'est fini !

- **Chaque matin à 8h** (heure de Paris) → email digest avec l'état de tes 9 valeurs.
- **Pendant la journée** → alertes dès qu'un mouvement, un volume ou une news le justifie.

---

## 🔧 Personnaliser

Tout se règle dans **`config.py`** (modifie le fichier sur GitHub avec le crayon ✏️) :
- Ajouter/retirer une valeur → liste `WATCHLIST`.
- Changer les seuils d'alerte → `seuil` par valeur, ou `SEUIL_DEFAUT`.
- Sensibilité volume → `MULTIPLE_VOLUME`.
- Anti-spam → `COOLDOWN_MINUTES`.
- Heure du digest → `HEURE_DIGEST`.
- Couper l'IA → `UTILISER_IA = False`.

---

## ❓ Problèmes fréquents

- **Pas d'email reçu** : vérifie tes spams ; revérifie `GMAIL_APP_PASSWORD` (16 lettres, sans espaces) et que la validation 2 étapes est active.
- **Exécution rouge ❌** : ouvre les logs dans Actions, le message d'erreur indique quoi corriger (souvent un secret mal nommé).
- **« Cours indisponible »** : Yahoo bloque parfois temporairement les serveurs GitHub. Ça se rétablit en général tout seul ; si ça persiste, dis-le moi, on changera de source de cours.
- **GitHub peut retarder** les exécutions planifiées en période de forte charge (c'est normal sur l'offre gratuite). En pratique tu seras alerté à quelques minutes près.

---

⚠️ **Avertissement** : cet agent fournit de l'information d'aide à la décision, **pas un conseil
d'investissement**. Les cours sont différés (~15 min). Les décisions t'appartiennent.
