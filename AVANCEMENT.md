# Avancement — EMV Authorization Server

> Dernière mise à jour : 06 mai 2026  
> Version courante : **1.14.0**  
> Tests : **1720+** (suite complète)

---

## Résumé de l'état du projet

| Domaine | Statut |
|---------|--------|
| Core EMV 4.3 (BER-TLV, ARQC/ARPC) | ✅ Complet |
| ISO 8583 (parse, réponse, MTI) | ✅ Complet |
| Tranches montant (6 tranches) | ✅ Complet |
| Règles GIE CB | ✅ Complet |
| Réponse TPA | ✅ Complet |
| CVV/CVV2/iCVV | ✅ Complet |
| Cartes (CRUD, blocage, déblocage) | ✅ Complet |
| Interface TCP ISO 8583 (port 8583) | ✅ Complet |
| Redressements (0400/0420) | ✅ Complet |
| Journal d'audit par transaction | ✅ Complet |
| Filtres avancés transactions | ✅ Complet |
| Recherche multi-critères | ✅ Complet |
| Historique carte | ✅ Complet |
| Mise à jour carte (PATCH) | ✅ Complet |
| Dashboard français | ✅ Complet |
| Export CSV / TXT / JSON enrichi | ✅ Complet |
| Rate Limiting | ✅ Complet |
| API Key | ✅ Complet |
| Backup JSON compressé GZIP | ✅ Complet |
| Pinning & Maintenance Snapshots | ✅ Complet |
| Persistance Hybride (DB/JSON) | ✅ Complet |
| Statistiques SQL Optimisées | ✅ Complet |
| Interface de Certification GIE CB | ✅ Complet |

---

## Historique des livrables

### v1.14.0 — Simulateur de Certification GIE CB (06/05/2026)

**Nouvelles fonctionnalités :**
- **Moteur de Certification** : Introduction de `CertificationRunner` pour l'exécution automatisée de scénarios de test complexes.
- **Bibliothèque de Scénarios** : Implémentation des cas de tests standard (Cumul sans contact A5, ARQC invalide 63, Cartes bloquées 62).
- **API de Certification** : Nouveaux endpoints `/api/v1/certification/scenarios` et `/run/<id>` pour piloter les tests.
- **Réponses Flattened** : Optimisation de `AuthorizationResult.to_dict` pour exposer les champs `cb_response_code`, `tier`, `transaction_id` et `rrn` au premier niveau.
- **Loopback Client** : Système de test interne permettant de simuler des terminaux directement via l'API.

---

### v1.13.1 — Statistiques Temporelles & SQL (06/05/2026)

**Nouvelles fonctionnalités :**
- **Statistiques Optimisées** : Refactorisation de `get_stats` pour utiliser des agrégations SQL native (`func.count`, `func.sum`). Gain de performance majeur sur les gros volumes de transactions (P1).
- **Séries Temporelles** : Implémentation de `get_time_series_stats` permettant un monitoring heure par heure des transactions.
- **Nouvel API Endpoint** : `GET /api/v1/stats/time-series` pour alimenter des graphiques de tendance.
- **Support Hybride** : Les stats temporelles sont également disponibles en mode In-Memory (P2).

---

### v1.13.0 — Persistance Hybride Robuste (06/05/2026)

**Nouvelles fonctionnalités :**
- **PersistenceManager** : Centralisation du cycle de vie de la persistance. Basculement automatique entre DB (PostgreSQL/SQLite) et In-Memory (Snapshots JSON) selon la disponibilité.
- **Auto-Recover optimisé** : Importation automatique du dernier snapshot JSON dans la base de données au démarrage si celle-ci est vide.
- **Importation par lot** : Optimisation de `db_import.py` utilisant une session unique pour des performances accrues lors des imports massifs.
- **API d'Import Manuel** : `POST /api/v1/snapshots/<filename>/import` pour forcer la synchronisation d'un snapshot vers la DB.
- **Tests d'Intégration** : Nouvelle suite de tests pour valider les scénarios de basculement et de récupération.

---

### v1.12.0 — Archivage et récupération assistée (03/05/2026)

**Nouvelles fonctionnalités :**
- Compression GZIP systématique des snapshots historiques (`.json.gz`).
- Système d'épinglage (Pinning) pour protéger les snapshots contre la rotation automatique.
- API de comparaison (Diff) : `GET /api/v1/snapshots/diff?file1=...&file2=...`.
- Endpoints de maintenance : Restauration ciblée, Épinglage manuel, Suppression forcée.
- Export global ZIP : `GET /api/v1/snapshots/export`.

**Tests :** 10 nouveaux tests (5 unitaires dans `test_persistence_v12.py` + 5 d'intégration dans `test_api_v12.py`).

---

### v1.11.0 — Exports enrichis (03/05/2026)

**Nouvelles fonctionnalités :**
- `GET /api/v1/transactions/export?format=txt` — Export ticket TPE multi-transactions
- `GET /api/v1/transactions/export?format=json_enrichi` — Export JSON avec tous les labels métier
- `GET /api/v1/transactions/<id>/receipt` — Reçu individuel (TXT ou JSON)
- Filtres enrichis sur l'export (date_from, date_to, amount_min, amount_max, terminal_id, etc.)
- Intégration de `emv/receipt.py` pour le rendu des tickets 40 colonnes

**Tests :** 4 nouveaux tests d'intégration dans `tests/test_v11_exports.py`

---

### v1.4.0 — Journal d'audit + fonctionnalités manquantes (03/05/2026)

**Nouvelles fonctionnalités :**
- `GET /api/v1/transactions/<id>/log` — journal d'audit détaillé d'une transaction
- `GET /api/v1/transactions/rrn/<rrn>` — recherche par RRN
- `POST /api/v1/transactions/search` — recherche multi-critères
- `GET /api/v1/transactions` — filtres avancés : date, montant, terminal_id, merchant_id, cb_scheme, auth_path
- `GET /api/v1/cards/<pan>/history` — historique blocages + stats transactions
- `PATCH /api/v1/cards/<pan>` — mise à jour balance/daily_limit/cardholder_name
- `GET /api/v1` — index de toutes les routes de l'API
- Journal d'événements (`events`) sur chaque Transaction
- `Transaction.log_event()` — méthode pour ajouter un événement d'audit
- `TransactionLog.get_by_rrn()` — recherche par RRN
- `TransactionLog.count()` — comptage optimisé avec filtres
- Événements dans `authorize()` : TRANSACTION_CREATED, AMOUNT_EVALUATION, GIECB_EVALUATION, CARD_LOOKUP, EMV_PARSING, ATC_CHECK, ARQC_VERIFICATION, TVR_ANALYSIS, ARPC_GENERATION, BALANCE_CHECK, AUTHORIZATION_DECISION
- Événement REVERSAL_APPLIED dans `process_reversal()`

**Tests :** 103+ nouveaux tests dans `tests/test_transaction_log.py`

---

### v1.3.1 — Redressements EMV (03/05/2026)

**Nouvelles fonctionnalités :**
- `emv/reversal.py` — logique métier complète (complet, partiel, avis)
- Endpoints REST : `POST /reverse`, `POST /reverse` (RRN), `POST /advice`
- Interface TCP : MTI 0400 → 0410, MTI 0420 → 0430
- `models/transaction.py` : statut REVERSED + champs reversed_at, reversal_amount, etc.
- `iso8583/message.py` : MTI_DESCRIPTIONS, REVERSAL_RESPONSE_CODES, to_response() amélioré
- `get_stats()` compte les transactions redressées

**Tests :** 74 tests dans `tests/test_reversal.py`

**Codes d'erreur redressement :**
| RC | Signification |
|----|---------------|
| 00 | Redressement accepté |
| 25 | Transaction originale introuvable |
| 40 | Transaction non redressable |
| 56 | Déjà redressée |
| 61 | Montant supérieur à l'original |

---

### v1.3.0 — Interface TCP ISO 8583 (mai 2026)

- `emv/tcp_server.py` — serveur TCP (port 8583, préfixe 4 octets big-endian)
- `tools/terminal_simulator.py` — simulateur terminal
- 57 tests TCP dans `tests/test_tcp_server.py`

---

### v1.2.0 — Règles GIE CB (avril 2026)

- `emv/giecb.py` — règles réseau CB (sans contact, cumul offline, SCA)
- Identification carte (VISA CB, Mastercard CB, CB natif)
- Codes réponse CB spécifiques

---

### v1.1.0 — Tranches de montant (avril 2026)

- `emv/amount_rules.py` — 6 tranches : MICRO, LOW, MEDIUM, HIGH, VERY_HIGH, BLOCKED
- Chemins d'autorisation : OFFLINE, ONLINE, ONLINE_STRICT, BLOCKED
- Endpoints CRUD des tranches

---

### v1.0.0 — Core EMV (mars 2026)

- BER-TLV parser/encodeur
- Cryptographie ARQC/ARPC (3DES, dérivation clés UDK, session)
- Autorisation EMV complète
- Dashboard Flask français
- CVV/CVV2/iCVV

---

## Carte des endpoints (v1.4.0)

### Autorisation
| Méthode | Route | Description |
|---------|-------|-------------|
| POST | `/api/v1/authorize` | Autorisation REST native |
| POST | `/api/v1/authorize/iso8583` | Autorisation format ISO 8583 |
| POST | `/api/v1/batch/simulate` | Simulation en lot |

### Transactions
| Méthode | Route | Description |
|---------|-------|-------------|
| GET | `/api/v1/transactions` | Liste + filtres avancés |
| GET | `/api/v1/transactions/<id>` | Détail d'une transaction |
| GET | `/api/v1/transactions/<id>/log` | **Journal d'audit détaillé** ✨ |
| GET | `/api/v1/transactions/<id>/tpa` | Réponse TPA décomposée |
| GET | `/api/v1/transactions/rrn/<rrn>` | **Recherche par RRN** ✨ |
| GET | `/api/v1/transactions/pan/<pan>` | Transactions d'une carte |
| POST | `/api/v1/transactions/search` | **Recherche multi-critères** ✨ |
| GET | `/api/v1/transactions/export` | Export CSV |
| POST | `/api/v1/transactions/<id>/reverse` | Redressement par ID |
| POST | `/api/v1/transactions/reverse` | Redressement par RRN |
| POST | `/api/v1/transactions/<id>/reverse/advice` | Avis de redressement (0420) |

### Cartes
| Méthode | Route | Description |
|---------|-------|-------------|
| GET | `/api/v1/cards` | Liste des cartes |
| POST | `/api/v1/cards` | Créer une carte |
| GET | `/api/v1/cards/<pan>` | Détail d'une carte |
| PATCH | `/api/v1/cards/<pan>` | **Mise à jour carte** ✨ |
| GET | `/api/v1/cards/<pan>/history` | **Historique carte** ✨ |
| POST | `/api/v1/cards/<pan>/block` | Bloquer |
| POST | `/api/v1/cards/<pan>/unblock` | Débloquer |

### Outils / Administration
| Méthode | Route | Description |
|---------|-------|-------------|
| GET | `/api/v1` | **Index de l'API** ✨ |
| GET | `/api/v1/health` | Santé du service |
| GET | `/api/v1/stats` | Statistiques globales |
| GET | `/api/v1/stats/stream` | Stats temps réel (SSE) |
| GET | `/api/v1/amount-tiers` | Tranches montant |
| POST | `/api/v1/amount-tiers` | Créer une tranche |
| GET | `/api/v1/giecb/rules` | Règles GIE CB |
| POST | `/api/v1/giecb/evaluate` | Évaluer règles CB |
| GET | `/api/v1/cvv/generate` | Générer CVV |
| POST | `/api/v1/cvv/verify` | Vérifier CVV |
| GET | `/api/v1/tpa/fields` | Champs TPA |
| POST | `/api/v1/tlv/parse` | Parser BER-TLV |

---

## Structure du journal d'audit (GET /transactions/<id>/log)

```json
{
  "transaction_id": "uuid...",
  "rrn": "26124XXXXXX",
  "summary": {
    "status": "APPROVED",
    "response_code": "00",
    "amount": 5000,
    "amount_formatted": "50.00",
    "amount_tier": "LOW",
    "auth_path": "ONLINE",
    "cb_scheme": "VISA"
  },
  "events": [
    { "stage": "TRANSACTION_CREATED", "level": "INFO", "at": "...", "message": "...", "data": {...} },
    { "stage": "AMOUNT_EVALUATION",   "level": "INFO", ... },
    { "stage": "GIECB_EVALUATION",    "level": "INFO", ... },
    { "stage": "CARD_LOOKUP",         "level": "INFO", ... },
    { "stage": "EMV_PARSING",         "level": "INFO", ... },
    { "stage": "BALANCE_CHECK",       "level": "INFO", ... },
    { "stage": "AUTHORIZATION_DECISION", "level": "INFO", ... }
  ],
  "event_count": 7,
  "reversal": null
}
```

**Étapes possibles :**
- `TRANSACTION_CREATED` — initialisation
- `AMOUNT_EVALUATION` — tranche + chemin d'autorisation
- `GIECB_EVALUATION` — réseau CB, SCA, floor limit
- `CARD_LOOKUP` — recherche carte
- `EMV_PARSING` — parsing champ 55
- `ATC_CHECK` — contrôle ATC anti-rejeu
- `ARQC_VERIFICATION` — vérification cryptogramme
- `TVR_ANALYSIS` — analyse TVR (flags de risque)
- `ARPC_GENERATION` — génération ARPC
- `BALANCE_CHECK` — contrôle solde + limite journalière
- `AUTHORIZATION_DECISION` — décision finale (INFO=approuvé, ERROR=refusé)
- `REVERSAL_APPLIED` — redressement appliqué

---

## Points d'attention / travaux futurs

| Priorité | Sujet |
|----------|-------|
| Moyen | Persistance des transactions (base de données vs mémoire) |
| Moyen | Statistiques temporelles (stats par heure/jour/semaine) |
| Bas | Authentification PIN (vérification PIN offline) |
| Bas | Gestion des clés rotatives (Key Rotation) |
| Bas | Interface de certification (simulateur réseau CB complet) |
