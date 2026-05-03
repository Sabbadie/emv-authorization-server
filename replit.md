# EMV Authorization Server — v1.9.0

Serveur d'autorisation EMV complet conforme aux normes EMV 4.3 et ISO 8583,
développé en Python/Flask. Deux interfaces : REST HTTP (port 5000) et TCP ISO 8583
(port 8583).

## Architecture

```
emv-auth-server/
├── main.py                 # Point d'entrée (HTTP + TCP + init_db)
├── server.py               # API REST Flask + tableau de bord (~3000 lignes)
├── config.py               # Configuration (clés, limites, ports, DATABASE_URL)
├── database.py             # SQLAlchemy engine/session, init_db, db_health
├── schemas.py              # Pydantic v2 — 14 schémas de validation (S4)
├── persistence.py          # Backup/restore JSON (fallback in-memory)
├── alembic.ini             # Configuration Alembic
├── alembic/
│   ├── env.py              # Script d'environnement Alembic
│   └── versions/
│       └── 001_initial_schema.py   # Migration initiale (6 tables)
├── docker-compose.yml      # postgres:15 + serveur EMV
├── Dockerfile              # Python 3.11 + libpq5 + gcc
├── emv/
│   ├── tlv.py              # Parser/encodeur BER-TLV (EMV 4.3)
│   ├── crypto.py           # ARQC/ARPC, dérivation UDK/session key, 3DES
│   ├── authorization.py    # Logique d'autorisation principale + journal événements
│   ├── amount_rules.py     # 6 tranches de montant (MICRO→BLOCKED)
│   ├── giecb.py            # Règles réseau GIE CB (sans contact, SCA, floor limit)
│   ├── cvv.py              # CVV/CVV2/iCVV (génération + vérification)
│   ├── reversal.py         # Redressements complet/partiel/avis (0400/0420)
│   ├── preauth.py          # Préautorisation + capture différée (E4)
│   ├── chargeback.py       # Disputes/chargebacks MTI 0620/0630 (E6)
│   ├── bin_blacklist.py    # Blackliste BIN/PAN (E7)
│   ├── currency.py         # Multi-devises + conversion (E8)
│   ├── issuer_scripts.py   # Issuer Script Processing tag 71/72 (C4)
│   ├── risk_scoring.py     # Scoring risque temps réel (C5)
│   ├── webhooks.py         # Webhooks sortants asynchrones (A1)
│   ├── alerts.py           # Alertes visuelles D5 (7 types, 3 niveaux)
│   ├── threeds.py          # 3-D Secure 2.x — AReq/ARes/CReq/CRes (E2)
│   ├── pki.py              # PKI simulée CA→Issuer→ICC RSA 1024-bit (C2)
│   ├── dda_cda.py          # DDA/CDA authentification offline RSA (E3)
│   ├── tokenization.py     # Token HCE/NFC CB-PAY — Token Vault (C3)
│   ├── degraded.py         # Mode dégradé / Chaos Engineering (A2)
│   ├── hsm.py              # HSM simulé — chiffrement clés en RAM (S5)
│   └── tcp_server.py       # Serveur TCP ISO 8583 (port 8583)
├── config_loader.py        # Config YAML/TOML rechargeable à chaud (A3)
├── config.yaml             # Fichier de configuration par défaut (A3)
├── cache.py                # Cache Redis + fallback in-memory (P4)
├── iso8583/
│   └── message.py          # Messages ISO 8583
├── models/
│   ├── card.py             # Modèle carte, CardDatabase + proxy
│   ├── card_repository.py  # DBCardDatabase (SQLAlchemy)
│   ├── transaction.py      # Modèle transaction + journal d'audit
│   ├── transaction_repository.py  # DBTransactionLog (SQLAlchemy)
│   ├── orm_models.py       # 6 modèles ORM (Card, Transaction, PreAuth, Chargeback, BINBlacklist, WebhookLog)
│   └── tpa_response.py     # Décomposition réponse TPA
├── tools/
│   ├── terminal_simulator.py  # Client TCP simulateur terminal
│   └── load_test_data.py      # Script de chargement du jeu d'essai via API
├── GUIDE_UTILISATEUR.md    # Guide utilisateur complet avec exemples curl
├── test_data/
│   └── jeu_essai.json      # 7 cartes, 20 scénarios, 7 utilisateurs test
└── tests/                  # 32 fichiers, 1609 tests
    ├── test_api.py               # Tests API REST
    ├── test_authorization.py     # Tests logique d'autorisation
    ├── test_schemas.py           # Tests Pydantic S4 (57 tests)
    ├── test_alerts.py            # Tests alertes D5 (23 tests)
    ├── test_database.py          # Tests ORM + db_health P1 (13 tests)
    ├── test_threeds.py           # Tests 3DS2 E2 (44 tests)
    ├── test_tokenization.py      # Tests tokenisation HCE C3 (56 tests)
    ├── test_pki.py               # Tests PKI C2 (25 tests)
    ├── test_dda_cda.py           # Tests DDA/CDA E3 (34 tests)
    ├── test_cb_flux.py           # Tests flux CB complet C1 (45 tests)
    ├── test_degraded.py          # Tests chaos mode A2 (35 tests)
    ├── test_config_loader.py     # Tests config YAML/TOML A3 (25 tests)
    ├── test_transaction_log.py   # Tests journal d'audit
    ├── test_reversal.py          # Tests redressements (74 tests)
    ├── test_tcp_server.py        # Tests interface TCP
    └── ...                       # 15 autres fichiers
```

## Lancer le serveur

```bash
python main.py
```

Le serveur démarre sur le port 5000 (HTTP) et 8583 (TCP).

### Avec PostgreSQL (Docker)

```bash
docker-compose up
```

PostgreSQL `postgres:15` sur port 5432, serveur EMV sur port 5000.
Si `DATABASE_URL` n'est pas défini, fallback automatique en in-memory.

## API REST — Endpoints principaux

### Administration
```
GET  /api/v1              # index de l'API
GET  /api/v1/health       # statut + version + database
GET  /api/v1/stats
GET  /api/v1/stats/stream  # SSE
GET  /api/v1/alerts        # D5 — alertes visuelles temps réel
```

### Autorisation
```
POST /api/v1/authorize          # validation Pydantic S4
POST /api/v1/authorize/iso8583
POST /api/v1/batch/simulate
```

### Transactions
```
GET  /api/v1/transactions            # liste + filtres
GET  /api/v1/transactions/<id>
GET  /api/v1/transactions/<id>/log
GET  /api/v1/transactions/<id>/tpa
GET  /api/v1/transactions/rrn/<rrn>
GET  /api/v1/transactions/pan/<pan>
POST /api/v1/transactions/search
GET  /api/v1/transactions/export     # CSV
POST /api/v1/transactions/<id>/reverse
POST /api/v1/transactions/reverse
POST /api/v1/transactions/<id>/reverse/advice
```

### Cartes
```
GET   /api/v1/cards
POST  /api/v1/cards
GET   /api/v1/cards/<pan>
PATCH /api/v1/cards/<pan>
GET   /api/v1/cards/<pan>/history
POST  /api/v1/cards/<pan>/block
POST  /api/v1/cards/<pan>/unblock
```

### Fonctionnalités avancées
```
POST /api/v1/preauth
POST /api/v1/preauth/<id>/capture
POST /api/v1/preauth/<id>/cancel
GET  /api/v1/preauth/<id>
POST /api/v1/transactions/<id>/chargeback
POST /api/v1/bin-blacklist/bin
POST /api/v1/bin-blacklist/pan
GET  /api/v1/currency/convert
GET  /api/v1/docs            # Swagger UI
GET  /api/v1/openapi.json    # OpenAPI 3.0
```

## Interface TCP ISO 8583 (port 8583)

Protocole : préfixe 4 octets big-endian + corps JSON UTF-8.

| MTI | Type | Réponse |
|-----|------|---------|
| 0100 / 0200 | Demande d'autorisation | 0110 / 0210 |
| 0400 | Demande de redressement | 0410 |
| 0420 | Avis de redressement | 0430 |

## Cartes de test

| PAN | Statut | Solde |
|-----|--------|-------|
| 4111 1111 1111 1111 | ACTIVE | 500 000 cts |
| 5500 0000 0000 0004 | ACTIVE | 1 000 000 cts |
| 4000 0000 0000 0002 | ACTIVE | 250 000 cts |
| 4000 0000 0000 0010 | EXPIRÉE | — |
| 4000 0000 0000 0028 | BLOQUÉE | — |
| 4000 0000 0000 0036 | ACTIVE (solde 1 ct) | 100 cts |
| 4970 1000 0000 0154 | CB natif ACTIVE | 300 000 cts |

## Variables d'environnement

| Variable | Défaut | Description |
|----------|--------|-------------|
| `DATABASE_URL` | _(vide)_ | URL PostgreSQL (ex: `postgresql://user:pass@host/db`). Si absent → in-memory. |
| `TCP_ENABLED` | `true` | Active le serveur TCP |
| `TCP_PORT` | `8583` | Port TCP |
| `API_KEY` | _(vide)_ | Clé API (header `X-API-Key`) |
| `FLASK_ENV` | `production` | Environnement Flask |

## Nouvelles fonctionnalités v1.9.0 (roadmap complète — 43/43)

| Feature | Module | Endpoints REST |
|---------|--------|---------------|
| **S5 — HSM / Chiffrement RAM** | `emv/hsm.py` | `GET /api/v1/hsm/status` · `GET /api/v1/hsm/keys` · `GET /api/v1/hsm/access-log` · `POST /api/v1/hsm/rotate-kek` · `POST /api/v1/hsm/revoke/<key_id>` |
| **P4 — Cache Redis + fallback** | `cache.py` | `GET /api/v1/cache/stats` · `DELETE /api/v1/cache/flush` |
| **C1 — Flux CB complet** | `emv/giecb.py` | `POST /api/v1/cb/routing` · `/cb/velocity` · `/cb/mcc-check` · `/cb/pin-status` · `GET /api/v1/cb/service-indicators` |
| **A2 — Chaos Engineering** | `emv/degraded.py` | `POST /api/v1/chaos/enable` · `/chaos/disable` · `/chaos/reset` · `/chaos/endpoint` |
| **A3 — Config YAML/TOML** | `config_loader.py` | `GET /api/v1/config` · `POST /api/v1/config/reload` · `GET /api/v1/config/status` |

## Jeu d'essai utilisateurs

```bash
# Lister les scénarios
python tools/load_test_data.py --list

# Exécuter tous les scénarios (serveur doit être lancé)
python tools/load_test_data.py --url http://localhost:5000

# Un scénario spécifique
python tools/load_test_data.py --scenario SC01
```

## Lancer les tests

```bash
python -m pytest tests/ -q                    # 1609 tests, ~23 s
python -m pytest tests/test_hsm.py            # HSM S5 (43 tests)
python -m pytest tests/test_cache.py          # Cache P4 (30 tests)
python -m pytest tests/test_cb_flux.py        # Flux CB C1 (45 tests)
python -m pytest tests/test_degraded.py       # Chaos A2 (35 tests)
python -m pytest tests/test_config_loader.py  # Config A3 (25 tests)
```
