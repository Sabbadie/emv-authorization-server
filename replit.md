# EMV Authorization Server — v1.4.0

Serveur d'autorisation EMV complet conforme aux normes EMV 4.3 et ISO 8583,
développé en Python/Flask. Deux interfaces : REST HTTP (port 5000) et TCP ISO 8583
(port 8583). Voir `AVANCEMENT.md` pour l'historique détaillé.

## Architecture

```
emv-auth-server/
├── main.py                 # Point d'entrée (HTTP + TCP)
├── server.py               # API REST Flask + tableau de bord (>2000 lignes)
├── config.py               # Configuration (clés, limites, ports)
├── persistence.py          # Backup/restore JSON
├── emv/
│   ├── tlv.py              # Parser/encodeur BER-TLV (EMV 4.3)
│   ├── crypto.py           # ARQC/ARPC, dérivation UDK/session key, 3DES
│   ├── authorization.py    # Logique d'autorisation principale + journal événements
│   ├── amount_rules.py     # 6 tranches de montant (MICRO→BLOCKED)
│   ├── giecb.py            # Règles réseau GIE CB (sans contact, SCA, floor limit)
│   ├── cvv.py              # CVV/CVV2/iCVV (génération + vérification)
│   ├── reversal.py         # Redressements complet/partiel/avis (0400/0420)
│   └── tcp_server.py       # Serveur TCP ISO 8583 (port 8583)
├── iso8583/
│   └── message.py          # Messages ISO 8583 (0100/0200/0400/0420/0800)
├── models/
│   ├── card.py             # Modèle carte, CardDatabase
│   ├── transaction.py      # Modèle transaction + journal d'audit (events)
│   └── tpa_response.py     # Décomposition réponse TPA
├── tools/
│   └── terminal_simulator.py  # Client TCP (simulateur terminal)
└── tests/
    ├── test_api.py               # Tests API REST généraux
    ├── test_authorization.py     # Tests logique d'autorisation
    ├── test_transaction_log.py   # Tests journal d'audit + nouveaux endpoints
    ├── test_reversal.py          # Tests redressements (74 tests)
    ├── test_tcp_server.py        # Tests interface TCP (57+ tests)
    └── ...                       # 13 fichiers au total (900+ tests)
```

## Lancer le serveur

```bash
python main.py
```

Le serveur démarre sur le port 5000 (HTTP) et 8583 (TCP) si `TCP_ENABLED=true`.

## API REST — Endpoints principaux

### Autorisation
```
POST /api/v1/authorize
POST /api/v1/authorize/iso8583
POST /api/v1/batch/simulate
```

### Transactions
```
GET  /api/v1/transactions            # liste + filtres (status, tier, date, amount, terminal…)
GET  /api/v1/transactions/<id>       # détail + TPA
GET  /api/v1/transactions/<id>/log   # journal d'audit détaillé ★
GET  /api/v1/transactions/<id>/tpa   # réponse TPA décomposée
GET  /api/v1/transactions/rrn/<rrn>  # recherche par RRN ★
GET  /api/v1/transactions/pan/<pan>  # transactions d'une carte
POST /api/v1/transactions/search     # recherche multi-critères ★
GET  /api/v1/transactions/export     # export CSV
POST /api/v1/transactions/<id>/reverse         # redressement
POST /api/v1/transactions/reverse              # redressement par RRN
POST /api/v1/transactions/<id>/reverse/advice  # avis 0420
```

### Cartes
```
GET   /api/v1/cards
POST  /api/v1/cards
GET   /api/v1/cards/<pan>
PATCH /api/v1/cards/<pan>            # mise à jour balance/limit ★
GET   /api/v1/cards/<pan>/history    # historique blocages + stats ★
POST  /api/v1/cards/<pan>/block
POST  /api/v1/cards/<pan>/unblock
```

### Administration
```
GET  /api/v1              # index de l'API ★
GET  /api/v1/health
GET  /api/v1/stats
GET  /api/v1/stats/stream  # SSE
GET  /api/v1/amount-tiers
GET  /api/v1/giecb/rules
POST /api/v1/cvv/verify
POST /api/v1/tlv/parse
```

> ★ = ajouté en v1.4.0

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

## Journal d'audit (GET /api/v1/transactions/<id>/log)

Chaque transaction enregistre les événements de son traitement :

```
TRANSACTION_CREATED → AMOUNT_EVALUATION → GIECB_EVALUATION
  → CARD_LOOKUP → EMV_PARSING → ATC_CHECK → ARQC_VERIFICATION
  → TVR_ANALYSIS → ARPC_GENERATION → BALANCE_CHECK
  → AUTHORIZATION_DECISION [→ REVERSAL_APPLIED]
```

Chaque événement contient : `stage`, `at`, `level` (INFO/WARN/ERROR), `message`, `data`.

## Tranches de montant

| Tranche | Min | Max | Chemin |
|---------|-----|-----|--------|
| MICRO | 0 | 500 | OFFLINE |
| LOW | 501 | 3000 | OFFLINE/ONLINE |
| MEDIUM | 3001 | 15000 | ONLINE |
| HIGH | 15001 | 50000 | ONLINE_STRICT |
| VERY_HIGH | 50001 | 500000 | ONLINE_STRICT |
| BLOCKED | >500000 | — | BLOCKED |

## Variables d'environnement

| Variable | Défaut | Description |
|----------|--------|-------------|
| `TCP_ENABLED` | `true` | Active le serveur TCP |
| `TCP_PORT` | `8583` | Port TCP |
| `API_KEY` | _(vide)_ | Clé API (header `X-API-Key`) |
| `FLASK_ENV` | `production` | Environnement Flask |

## Lancer les tests

```bash
python -m pytest -v          # tous les tests
python -m pytest tests/test_transaction_log.py -v   # journal d'audit
python -m pytest tests/test_reversal.py -v           # redressements
python -m pytest tests/test_tcp_server.py -v         # interface TCP
```
