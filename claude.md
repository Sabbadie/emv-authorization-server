# Claude — Modèle IA utilisé dans ce projet

## Modèle

| Attribut | Valeur |
|----------|--------|
| **Modèle** | Claude Sonnet 4.5 |
| **Éditeur** | Anthropic |
| **Plateforme** | Replit Agent |
| **Session** | Mai 2026 |

---

## Rôle de Claude dans ce projet

L'intégralité du code source de ce serveur d'autorisation EMV a été générée, itérée et déboguée par Claude Sonnet 4.5 agissant comme agent autonome dans l'environnement Replit.

Aucun code n'a été écrit manuellement par un développeur humain.

---

## Ce que Claude a construit

### Architecture générale
- Conception de l'architecture modulaire (emv/, iso8583/, models/, config.py)
- Choix de la stack technique : Python 3.11 + Flask 3.x + pycryptodome
- Structure des packages et conventions de nommage

### Cryptographie EMV (emv/crypto.py)
- Dérivation de clé UDK (Unique Derivation Key) par méthode Option A (3DES)
- Dérivation de clé de session (AC, ENC, MAC)
- Vérification ARQC (Application Request Cryptogram)
- Génération ARPC (Authorization Response Cryptogram)
- Traitement correct des clés 3DES double longueur (16 octets)

### Parseur BER-TLV (emv/tlv.py)
- Décodage complet BER-TLV conforme ISO/IEC 7816-4
- Support des tags sur 1 et 2 octets
- Support des longueurs courtes et longues (multi-octets)
- Extraction des éléments de données EMV (9F02, 9F26, 9F36, 95, 82, etc.)

### Moteur d'autorisation (emv/authorization.py)
- Pipeline d'autorisation en 7 étapes
- Intégration des règles par tranche de montant
- Intégration des règles GIE CB
- Vérification TVR (Terminal Verification Results)
- Détection rejeu ATC (Application Transaction Counter)
- Génération ARPC et Issuer Authentication Data (Tag 91)

### Gestion des tranches de montant (emv/amount_rules.py)
- 6 tranches prédéfinies : MICRO, SMALL, STANDARD, HIGH, VERY_HIGH, CRITICAL
- Système de règles configurable par tranche (online, ARQC, PIN, vélocité)
- API CRUD pour tranches personnalisées
- Évaluation dynamique avec détection du chemin d'autorisation

### Moteur GIE CB (emv/giecb.py)
- Identification des cartes par AID (13 AIDs reconnus) et BIN
- Paramètres CAP (Card Acceptor Parameters)
- Paramètres TAP1–TAP5 (Terminal Application Parameters)
- Règles sans contact NFC (plafond, cumul hors ligne, consécutives)
- Floor limits par MCC (17 catégories)
- Exemptions SCA DSP2 (LVP, MIT, TRA, TTP)
- 12 indicateurs de service CB
- Codes réponse GIE CB (dont 1A, A5, P1, P2)
- Codes motif de refus R01–R12

### Protocole ISO 8583 (iso8583/message.py)
- Construction et parsing de messages ISO 8583
- Bitmap primaire et secondaire
- Champs F2 (PAN), F3, F4, F7, F11, F12, F13, F22, F37, F38, F39, F41, F42, F43, F49, F55
- Génération de messages de réponse (MTI 0110)

### Format de réponse TPA (models/tpa_response.py)
- 40+ champs structurés (F00–FF2 + CB1–CBD)
- Champs ISO 8583 standard (F00–F55)
- Champs propriétaires EMV (FE1–FE9)
- Champs GIE CB (CB1–CBD) incluant schéma, AID, indicateur service, SCA, cumul NFC, floor limit, codes retour CB
- Vue ISO 8583-like en ASCII art
- Export plat (flat) et avec définitions

### Modèles de données (models/)
- `Card` : carte avec champs GIE CB (cb_scheme, cb_brand, aid, contactless_cumul, consecutive_offline), historique blocages/déblocages
- `Transaction` : 30+ attributs dont champs CB complets
- `CardDatabase` : index PAN, blocage/déblocage avec validation des statuts, stats par schéma
- `TransactionLog` : index par PAN, filtres, pagination, statistiques

### API REST Flask (server.py)
- 22 endpoints documentés
- Autorisation JSON et ISO 8583
- CRUD tranches de montant
- Endpoints GIE CB (rules, evaluate, aids, floor-limits, response-codes)
- Déblocage carte avec validation des statuts
- Historique paginé avec filtres multi-critères
- Réponse TPA découpée par transaction

### Dashboard interactif (HTML/CSS/JS inline)
- 7 onglets : Démo, Historique, Réponse TPA, Tranches, GIE CB, Cartes, API
- Évaluation de tranche en temps réel (listener input)
- Formulaire d'autorisation avec MCC et mode sans contact
- Tableau historique avec lignes dépliables et export JSON
- Affichage TPA tabulaire avec surbrillance des champs CB
- Évaluateur GIE CB interactif (CAP, TAP, NFC, AIDs, floor limits, codes réponse)
- Gestion des cartes avec boutons Bloquer / Débloquer
- Stats auto-rafraîchies toutes les 12 secondes

### Intégration GitHub
- Push automatique via GitHub Contents API (pas de git cli)
- 17 fichiers versionnés
- Commits sémantiques générés par Claude

---

## Interactions avec l'utilisateur

| Tour | Demande utilisateur | Action Claude |
|------|---------------------|---------------|
| 1 | Construire un serveur d'autorisation EMV complet | Architecture + 17 fichiers initiaux |
| 2 | Ajouter historique, tranches montant, format TPA | 4 nouveaux fichiers, refonte server.py |
| 3 | API débloquer carte + règles GIE CB | emv/giecb.py (nouveau), mise à jour 5 fichiers |
| 4 | Lister les améliorations possibles | Analyse et proposition structurée (6 axes) |
| 5 | Générer evolutions.md et pousser | evolutions.md créé et poussé |
| 6 | Générer claude.md et pousser | Ce fichier |

---

## Limites et précisions

- Les clés cryptographiques MDK utilisées sont des clés de **test** (valeurs fixes dans config.py) — ne jamais utiliser en production
- Le stockage est **en mémoire** (pas de base de données persistante) — voir évolution P1 dans evolutions.md
- Les règles GIE CB sont une **simulation pédagogique** basée sur les spécifications publiques — non certifiée CB
- Aucune authentification API n'est implémentée — voir évolution S1 dans evolutions.md

---

*Généré par Claude Sonnet 4.5 — Anthropic — Mai 2026*
