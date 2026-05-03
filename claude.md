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

## Ce que Claude a construit — v1.10.0 (43/43 features)

### Architecture générale
- Conception de l'architecture modulaire (emv/, iso8583/, models/, config.py)
- Choix de la stack technique : Python 3.11 + Flask 3.x + pycryptodome + SQLAlchemy
- Structure des packages, conventions de nommage, 32 fichiers de tests

### Cryptographie EMV (`emv/crypto.py`)
- Dérivation de clé UDK par méthode Option A (3DES EMV 4.3 Book 2)
- Dérivation de clé de session (AC, ENC, MAC)
- Vérification ARQC / génération ARPC
- Chiffrement/déchiffrement PIN Block ISO Format 0

### Parseur BER-TLV (`emv/tlv.py`)
- Décodage complet BER-TLV conforme ISO/IEC 7816-4
- Tags 1 et 2 octets, longueurs courtes et longues
- Extraction des éléments EMV (9F02, 9F26, 9F36, 95, 82, etc.)

### Moteur d'autorisation (`emv/authorization.py`)
- Pipeline 7 étapes : détokenisation → blacklist → statut → expiry → solde → CB rules → crypto
- Intégration règles par tranche de montant
- Intégration règles GIE CB complètes
- Vérification TVR, détection rejeu ATC

### Moteur GIE CB complet (`emv/giecb.py`) — C1/C2/C3/C4/C5
- 13 AIDs reconnus, identification BIN, règles sans contact NFC
- Plafonds montant, cumul hors ligne (150€), floor limits MCC
- Vélocité (fenêtre 30min/1h/jour), MCC bloqués (7 catégories)
- Routage domestique CB prioritaire (pays 250/FRA/FR/DOM-TOM)
- Statut PIN, règles remboursement, intégration ECI 3DS2
- 12 indicateurs de service, codes réponse CB (1A, A5, P1, P2, R01–R15)

### 3-D Secure 2.x (`emv/threeds.py`) — E2
- Machine d'états AReq→ARes→CReq→CRes
- Frictionless vs Challenge, exemptions DSP2 (LVP, MIT, TRA, CORP)
- ECI 05/06/07, CAVV simulé HMAC-SHA256, OTP 4 chiffres

### PKI simulée (`emv/pki.py`) — C2
- Hiérarchie CA Root → Issuer → ICC, RSA 1024-bit
- Tags EMV : 0x8F, 0x90, 0x9F32, 0x9F46, 0x9F47

### DDA / CDA (`emv/dda_cda.py`) — E3
- Signature dynamique DDA (SDAD tag 9F4B), CDA avec ARQC
- Vérification RSA PKCS#1 v1.5 / SHA-256

### Tokenisation HCE/NFC (`emv/tokenization.py`) — C3
- Token Service Provider simulé, préfixe 4999, LUHN-valide
- Token Vault PAN↔Token (SHA-256), domaines HCE_MOBILE/ECOMMERCE/WALLET/ANY
- Cycle de vie ACTIVE→SUSPENDED→DELETED, détokenisation transparente

### HSM simulé — S5 (`emv/hsm.py`)
- `SimulatedHSM` + `HsmKeyStore` avec KEK Fernet éphémère
- Chiffre MDK_AC/ENC/MAC, CVK1/CVK2, SECRET_KEY en RAM
- Rotation KEK atomique, révocation, journal d'accès 200 entrées

### Mode dégradé / Chaos (`emv/degraded.py`) — A2
- 5 types de pannes injectées : TIMEOUT, NETWORK_ERROR, INTERNAL_ERROR, PARTIAL_FAILURE, SLOW_RESPONSE
- Taux configurable par endpoint, middleware Flask @before_request

### Persistance & Historique (`persistence.py`, `db_import.py`) — P2
- Snapshot JSON toutes les N secondes (atomique via tmp+rename)
- **Historique 7 jours** : snapshot horodaté dans `data/snapshots/`, rotation automatique
- Index JSON `data/snapshots/index.json` avec métadonnées (taille, nb_cards, nb_txns)
- **Import JSON → DB** : `import_snapshot_to_db()` — upsert cartes, insert transactions
- `auto_recover()` — récupération automatique après perte de connexion DB

### Cache distribué (`cache.py`) — P4
- Backend Redis (redis-py) si `REDIS_URL`, sinon InMemoryBackend avec TTL
- Utilisé pour stats (5s), sessions 3DS2 (10min), tokens (1h)

### Configuration rechargeable (`config_loader.py`) — A3
- YAML / TOML, fusion profonde, surcharge env vars, hot-reload 10s

### Base de données (`database.py`, `models/orm_models.py`) — P1/P3
- SQLAlchemy 2.0 + Alembic, 6 modèles ORM
- Activation conditionnelle PostgreSQL/SQLite via DATABASE_URL

### API REST Flask (`server.py`) — ~3600 lignes, 100+ endpoints
- Auth, transactions, cartes, tranches, CB rules, préauth, chargebacks
- 3DS2, tokenisation, PKI, DDA/CDA, chaos, config, HSM, cache
- Swagger UI, SSE stats, CSV export, webhooks, alertes visuelles

### Dashboard interactif (HTML/CSS/JS inline)
- 7 onglets : Démo, Historique, Réponse TPA, Tranches, GIE CB, Cartes, API
- Dark/Light mode, SSE temps réel, évaluateur CB interactif

### Tests (`tests/`) — 32 fichiers
- **1609 tests** couvrant tous les modules (couverture > 90%)

---

## Interactions avec l'utilisateur

| Tour | Demande utilisateur | Action Claude |
|------|---------------------|---------------|
| 1 | Construire un serveur d'autorisation EMV complet | Architecture + 17 fichiers initiaux |
| 2 | Ajouter historique, tranches montant, format TPA | 4 nouveaux fichiers, refonte server.py |
| 3 | API débloquer carte + règles GIE CB | emv/giecb.py (nouveau), mise à jour 5 fichiers |
| 4 | Lister les améliorations possibles | Analyse et proposition structurée (6 axes) |
| 5 | Générer evolutions.md et pousser | evolutions.md créé et poussé |
| 6 | Générer claude.md et pousser | claude.md créé |
| 7 | PostgreSQL, Pydantic, dashboard alertes | P1, S4, D5 livrés — 28 features |
| 8 | E2 (3DS2), C2 (PKI), E3 (DDA/CDA), C3 (HCE/NFC) | v1.7.0 — 38 features, 1404 tests |
| 9 | C1 (flux CB), A2 (chaos), A3 (config YAML/TOML) | v1.8.0 — 41 features, 1536 tests |
| 10 | S5 (HSM), P4 (Cache Redis), guide, jeu d'essai | v1.9.0 — 43/43 features, 1609 tests |
| 11 | Mise à jour claude.md + historique 7j + import DB | v1.10.0 — persistence avancée + db_import.py |

---

## Architecture des fichiers v1.10.0

```
emv/
├── authorization.py    # Pipeline autorisation 7 étapes
├── crypto.py           # ARQC/ARPC, dérivation clés, PIN
├── tlv.py              # Parseur BER-TLV
├── giecb.py            # Moteur GIE CB + règles C1
├── cvv.py              # CVV1/CVV2/iCVV
├── amount_rules.py     # Tranches montant
├── threeds.py          # 3DS2 (E2)
├── pki.py              # PKI CA→Issuer→ICC (C2)
├── dda_cda.py          # DDA/CDA (E3)
├── tokenization.py     # HCE/NFC (C3)
├── issuer_scripts.py   # Tag 71/72 (C4)
├── risk_scoring.py     # Score risque (C5)
├── webhooks.py         # Webhooks (A1)
├── alerts.py           # Alertes D5
├── degraded.py         # Chaos (A2)
├── hsm.py              # HSM simulé (S5)
├── preauth.py          # Préautorisations (E4)
├── chargeback.py       # Chargebacks (E6)
├── bin_blacklist.py    # Blacklist BIN (E7)
├── currency.py         # Multi-devises (E8)
├── reversal.py         # Redressements (E5)
└── tcp_server.py       # ISO 8583 TCP
persistence.py          # Snapshot JSON + historique 7j (P2)
db_import.py            # Import JSON → DB, auto_recover (P2/P1)
cache.py                # Cache Redis + fallback (P4)
config_loader.py        # Config YAML/TOML rechargeable (A3)
database.py             # SQLAlchemy init (P1)
server.py               # API REST Flask ~3600 lignes
```

---

## Statistiques v1.10.0

| Métrique | Valeur |
|----------|--------|
| Features livrées | **43 / 43** |
| Tests | **1609+** |
| Fichiers source | ~45 |
| Lignes de code | ~12 000 |
| Endpoints REST | 100+ |
| Versions | v1.0.0 → v1.10.0 |

---

## Limites et précisions

- Les clés cryptographiques MDK sont des clés de **test** — ne jamais utiliser en production
- Les règles GIE CB sont une **simulation pédagogique** — non certifiée CB
- Le HSM est **simulé** (Fernet) — non équivalent à un HSM matériel certifié FIPS-140-2
- Redis est **optionnel** — le fallback in-memory suffit pour une instance unique
- L'historique JSON 7 jours est local — pour une HA complète, utiliser PostgreSQL avec réplication

---

*Généré par Claude Sonnet 4.5 — Anthropic — Mai 2026 — v1.10.0*
