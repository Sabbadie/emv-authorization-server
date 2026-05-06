# Évolutions — Serveur d'Autorisation EMV GIE CB

> Dernière mise à jour : **06 mai 2026** — Version courante : **v1.14.0**  
> Suite de tests : **1 720 tests** (toutes catégories)  
> Légende : ✅ Livré · ⚠️ Partiel · ❌ Non démarré  
> Priorité : 🔴 Haute · 🟡 Moyenne · 🟢 Basse

---

## 1. Sécurité

| # | Priorité | Évolution | Statut | Version | Notes |
|---|----------|-----------|--------|---------|-------|
| S1 | 🔴 | **Authentification API Key** | ✅ Livré | v1.3.0 | Header `X-Api-Key` activable via `EMV_API_KEY`. Sans clé → mode dev sans auth. |
| S2 | 🔴 | **Rate limiting** | ✅ Livré | v1.3.0 | `Flask-Limiter 4.1.1`. 300 req/min global, 30/min sur `/authorize`, 5/min batch. HTTP 429. |
| S3 | 🟡 | **Masquage PAN dans les logs** | ✅ Livré | v1.0.0 | PAN masqué (`************NNNN`) dans toutes les réponses REST et journaux d'audit. |
| S4 | 🟡 | **Validation stricte des entrées** | ✅ Livré | v1.6.0 | Pydantic v2 intégré (`schemas.py`). 14 schémas (AuthorizeRequest, PreauthRequest, ChargebackRequest…). Validation PAN, amount, currency, MCC, CVV, field_55 hex. HTTP 422 avec détails. 57 tests. |
| S5 | 🟡 | **Chiffrement données sensibles en RAM** | ✅ Livré | v1.9.0 | `emv/hsm.py` : `SimulatedHSM` + `HsmKeyStore`. KEK Fernet éphémère (AES-128-CBC + HMAC-SHA256) générée au démarrage, jamais persistée sur disque. Chiffre MDK_AC, MDK_ENC, MDK_MAC, CVK1, CVK2, SECRET_KEY au démarrage. Rotation KEK atomique (re-chiffre tout), révocation clé, journal d'accès (200 entrées). Init auto depuis Config. Endpoints : `GET /api/v1/hsm/status`, `GET /api/v1/hsm/keys`, `GET /api/v1/hsm/access-log`, `POST /api/v1/hsm/rotate-kek`, `POST /api/v1/hsm/revoke/<key_id>`. Compliance : FIPS-140-2 (simulation), PCI-DSS. 43 tests. |
| S6 | 🟢 | **Journal d'audit immuable** | ✅ Livré | v1.4.0 | `Transaction.log_event()` enregistre chaque étape. Endpoint `GET /api/v1/transactions/<id>/log`. |

---

## 2. Persistance des données

| # | Priorité | Évolution | Statut | Version | Notes |
|---|----------|-----------|--------|---------|-------|
| P1 | 🔴 | **Base de données SQLite / PostgreSQL** | ✅ Livré | v1.6.0 | SQLAlchemy 2.0 + Alembic. ORM complet (`CardORM`, `TransactionORM`, `PreAuthORM`, `ChargebackORM`, `BINBlacklistORM`, `WebhookLogORM`). Repositories DB (`DBCardDatabase`, `DBTransactionLog`). Activation conditionnelle via `DATABASE_URL` (fallback in-memory si absent). `docker-compose.yml` postgres:15. |
| P2 | 🟡 | **Sauvegarde JSON périodique + Historique 7 jours** | ✅ Livré | v1.3.0 → v1.12.0 | `persistence.py` : snapshot toutes les 120 s, sauvegarde SIGTERM, rechargement au démarrage. **v1.10.0** : snapshot horodaté dans `data/snapshots/`, rotation automatique (configurable `SNAPSHOT_RETENTION_DAYS`, défaut 7j), index JSON `data/snapshots/index.json`. |
| P3 | 🟡 | **Migrations de schéma** | ✅ Livré | v1.6.0 | Alembic intégré. Migration initiale `001_initial_schema.py`. `alembic upgrade head` automatique au démarrage si DATABASE_URL configurée. |
| P4 | 🟢 | **Cache Redis** | ✅ Livré | v1.9.0 | `cache.py` : `CacheManager` singleton. Backend Redis (redis-py) si `REDIS_URL` configuré, sinon `InMemoryBackend` avec TTL intégré. API identique dans les deux cas. Utilisations : stats globales (TTL 5s), sessions 3DS2 (TTL 10min), lookup token→PAN_hash (TTL 1h). Fallback automatique si Redis indisponible. Endpoints : `GET /api/v1/cache/stats`, `DELETE /api/v1/cache/flush?prefix=`. 30 tests. |
| P5 | 🔴 | **Persistance Hybride & Auto-Recover** | ✅ Livré | v1.13.0 | `persistence_manager.py` : Centralisation du cycle de vie. `auto_recover()` optimisé avec import par lot (session unique). Basculement transparent DB/Memory. Endpoint `POST /api/v1/snapshots/<file>/import`. 15 tests. |

---

## 3. Fonctionnalités EMV

| # | Priorité | Évolution | Statut | Version | Notes |
|---|----------|-----------|--------|---------|-------|
| E1 | 🔴 | **Vérification CVV/CVC** | ✅ Livré | v1.2.0 | `emv/cvv.py` : CVV1 (piste 2), CVV2 (DOS), iCVV (puce) via 3DES. |
| E2 | 🔴 | **3-D Secure 2.x (3DS2)** | ✅ Livré | v1.7.0 | `emv/threeds.py` : machine d'états AReq→ARes→CReq→CRes. Frictionless vs Challenge. Exemptions DSP2 : LVP (≤30€), TRA (≤250€ historique OK), MIT, CORP. ECI 05/06/07. CAVV simulé (HMAC-SHA256). OTP 4 chiffres, 3 tentatives max. Endpoints REST : `POST /api/v1/3ds/authenticate`, `POST /api/v1/3ds/<id>/challenge`, `GET /api/v1/3ds/<id>`, `GET /api/v1/3ds`, `GET /api/v1/3ds/stats`. 44 tests. |
| E3 | 🟡 | **DDA / CDA** | ✅ Livré | v1.7.0 | `emv/dda_cda.py` : DDA = signe données dynamiques avec ICC private key (tag 9F4B SDAD) ; CDA = DDA + ARQC inclus (tag 9F27 bit 0x40). Vérification RSA PKCS#1 v1.5 / SHA-256. Intégré dans `authorize()` step 4b (non bloquant). Tags parsés dans champ 55 : 9F4B, 9F46, 90. Endpoints : `POST /api/v1/dda/sign`, `POST /api/v1/dda/verify`, `POST /api/v1/cda/sign`, `POST /api/v1/cda/verify`. 34 tests. |
| E4 | 🟡 | **Préautorisation + capture différée** | ✅ Livré | v1.5.0 | `emv/preauth.py` : MTI 0100/0200/0400. Statuts PENDING/CAPTURED/PARTIAL/CANCELLED/EXPIRED. Capture partielle. 34 tests. |
| E5 | 🟡 | **Redressements et avis** | ✅ Livré | v1.3.1 | `emv/reversal.py` : complet, partiel, avis (0420). TCP MTI 0400→0410 et 0420→0430. 74 tests. |
| E6 | 🟡 | **Disputes / chargebacks** | ✅ Livré | v1.5.0 | `emv/chargeback.py` : MTI 0620/0630. 12 codes motif CB01–CB12. Résolution ACCEPTED/REJECTED/ARBITRATION. 37 tests. |
| E7 | 🟢 | **Blackliste BIN/PAN** | ✅ Livré | v1.5.0 | `emv/bin_blacklist.py` : BIN (préfixe) + PAN complet. Code réponse 63. Intégré en step 0 de `authorize()`. CRUD REST complet. 38 tests. |
| E8 | 🟢 | **Multi-devises avec conversion** | ✅ Livré | v1.5.0 | `emv/currency.py` : 12 devises (EUR/USD/GBP/CHF/JPY/MAD/DZD/DKK/SEK/NOK/CAD/TND). Taux croisés, formatage. 28 tests. |

---

## 4. Règles GIE CB

| # | Priorité | Évolution | Statut | Version | Notes |
|---|----------|-----------|--------|---------|-------|
| C1 | 🔴 | **Simulation flux CB complet** | ✅ Livré | v1.8.0 | `emv/giecb.py` complété : vélocité (fenêtre 30min/1h/jour), MCC bloqués (jeux/adult/crypto), routage domestique CB prioritaire (pays 250/FRA/FR/DOM-TOM), statut PIN (blocage à 0 tentative), règles remboursement (ratio 100%), intégration résultat 3DS2 ECI (05/06/07), indicateurs de service complets (01–12) par contexte. Nouveaux endpoints : `POST /api/v1/cb/routing`, `POST /api/v1/cb/velocity`, `POST /api/v1/cb/mcc-check`, `POST /api/v1/cb/pin-status`, `GET /api/v1/cb/service-indicators`. 45 tests. |
| C2 | 🟡 | **Certificats émetteurs CB** | ✅ Livré | v1.7.0 | `emv/pki.py` : PKI simulée hiérarchie CA Root → Issuer (par premier chiffre BIN) → ICC (par PAN). RSA 1024-bit via `cryptography`. Tags EMV : `0x8F` (CA PK Index), `0x90` (Issuer PK Cert), `0x9F32` (Issuer PK Exponent), `0x9F46` (ICC PK Cert), `0x9F47` (ICC PK Exponent). Clés mises en cache (lazy init). Endpoints : `GET /api/v1/pki/<pan>`, `GET /api/v1/pki/status`. 25 tests. |
| C3 | 🟡 | **CB-PAY / Wallet NFC** | ✅ Livré | v1.7.0 | `emv/tokenization.py` : Token Service Provider simulé. Token HCE format PAN LUHN-valide, préfixe 4999. Token Vault en mémoire PAN↔Token (hash SHA-256). Domaines : HCE_MOBILE, ECOMMERCE, WALLET, ANY. Cycle de vie ACTIVE→SUSPENDED→DELETED. Détokenisation transparente dans `authorize()` step 0 (avant blacklist). Compteur d'utilisations (max_uses). Endpoints CRUD : `POST /api/v1/tokens`, `GET /api/v1/tokens`, `GET /api/v1/tokens/<id>`, `POST /api/v1/tokens/<id>/suspend`, `POST /api/v1/tokens/<id>/resume`, `DELETE /api/v1/tokens/<id>`, `GET /api/v1/tokens/pan/<pan>`, `GET /api/v1/tokens/stats`. 56 tests. |
| C4 | 🟡 | **Issuer Script Processing (tag 71/72)** | ✅ Livré | v1.5.0 | `emv/issuer_scripts.py` : génération Tag 71 (avant transaction) / Tag 72 (après). UNBLOCK_PIN, UPDATE_RISK_PARAMS, PUT_DATA. Export hex + base64. 26 tests. |
| C5 | 🟢 | **Scoring risque temps réel** | ✅ Livré | v1.5.0 | `emv/risk_scoring.py` : 5 facteurs (montant 30pts, vélocité 25pts, MCC 20pts, sans-contact 15pts, horaire 10pts). Niveaux LOW/MEDIUM/HIGH/CRITICAL. Décisions ALLOW/CHALLENGE/BLOCK. 32 tests. |
| C6 | 🟢 | **Interface de Certification GIE CB** | ✅ Livré | v1.14.0 | `emv/certification.py` : `CertificationRunner` moteur de scénarios (CL_CUMUL_LIMIT, INVALID_ARQC, CARD_BLOCKED). Endpoints `/api/v1/certification/scenarios` et `/run/<id>`. Rapport détaillé des étapes. 12 tests. |

---

## 5. Dashboard & Monitoring

| # | Priorité | Évolution | Statut | Version | Notes |
|---|----------|-----------|--------|---------|-------|
| D1 | 🟡 | **Graphiques temps réel (SSE)** | ✅ Livré | v1.3.0 | Chart.js + Server-Sent Events sur `/api/v1/stats/stream`. |
| D2 | 🟡 | **Export CSV / TXT / JSON** | ✅ Livré | v1.3.0 → v1.12.0 | `GET /api/v1/transactions/export` : formats variés avec en-têtes métier complets. |
| D3 | 🟡 | **Documentation Swagger / OpenAPI 3.0** | ✅ Livré | v1.5.0 | Spec OpenAPI 3.0 sur `GET /api/v1/openapi.json`. Swagger UI interactif sur `GET /api/docs`. 13 tags, tous les nouveaux endpoints documentés. |
| D4 | 🟡 | **Simulation de scénarios batch** | ✅ Livré | v1.3.0 | `POST /api/v1/batch/simulate` : N transactions avec cartes et montants variés. |
| D5 | 🟢 | **Alertes visuelles** | ✅ Livré | v1.6.0 | `emv/alerts.py` : 7 types d'alertes (CONTACTLESS_CUMUL_HIGH, DAILY_LIMIT_APPROACHING, CARD_BLOCKED_HIGH, TRANSACTION_FAILURE_BURST, BIN_BLACKLIST_ACTIVITY, CHARGEBACK_SURGE, PREAUTH_EXPIRY_WARNING). Niveaux CRITICAL/WARNING/INFO. Endpoint `GET /api/v1/alerts`. Banner visuel CSS 3 couleurs. Polling JS 30 s. 23 tests. |
| D6 | 🟢 | **Mode sombre / clair** | ✅ Livré | v1.3.0 | Toggle thème dans le dashboard (CSS variables + localStorage). |
| D7 | 🟡 | **Statistiques SQL & Séries Temporelles** | ✅ Livré | v1.13.1 | `get_stats()` optimisé (SQL aggregations). `get_time_series_stats()` hourly. Endpoint `GET /api/v1/stats/time-series`. Gain perf massif sur gros volumes. 10 tests. |

---

## 6. Architecture & Intégration

| # | Priorité | Évolution | Statut | Version | Notes |
|---|----------|-----------|--------|---------|-------|
| A1 | 🟡 | **Webhooks sortants** | ✅ Livré | v1.5.0 | `emv/webhooks.py` : POST JSON asynchrone (thread daemon). 8 types d'événements. Journal 200 entrées. `WEBHOOK_URL` env var. Endpoints CRUD. 35 tests. |
| A2 | 🟡 | **Mode dégradé simulé** | ✅ Livré | v1.8.0 | `emv/degraded.py` : `DegradedModeManager` singleton thread-safe. 5 types de pannes : TIMEOUT, NETWORK_ERROR, INTERNAL_ERROR, PARTIAL_FAILURE, SLOW_RESPONSE. Taux configurable (0–100%), latence injectée (ms + jitter). Config globale ou par endpoint. Middleware Flask `@before_request` (bypass `/api/v1/chaos`). Endpoints : `GET /api/v1/chaos`, `POST /api/v1/chaos/enable`, `POST /api/v1/chaos/disable`, `POST /api/v1/chaos/reset`, `POST /api/v1/chaos/endpoint`, `DELETE /api/v1/chaos/endpoint/<tag>`, `GET /api/v1/chaos/stats`. 35 tests. |
| A3 | 🟡 | **Configuration YAML/TOML rechargeable** | ✅ Livré | v1.8.0 | `config_loader.py` : `ConfigManager` singleton. Charge `config.yaml` (PyYAML) ou `config.toml` (tomllib Python 3.11). Fusion profonde avec surcharge par variables d'environnement (`SEC__KEY` → `cfg.sec.key`). Hot-reload par thread de polling (10s). `config.yaml` par défaut inclus (11 sections). Endpoints : `GET /api/v1/config`, `POST /api/v1/config/reload`, `GET /api/v1/config/status`. 25 tests. |
| A4 | 🟢 | **Client Python CLI** | ✅ Livré | v1.3.0 | `cli.py` : envoi d'autorisations, consultation transactions et stats. |
| A5 | 🟢 | **Tests unitaires et d'intégration** | ✅ Livré | v1.14.0 | **1 720 tests** dans 38 fichiers. Crypto, TLV, CB rules, tranches, REST, TCP, chargebacks, préauths, BIN blacklist, devises, issuer scripts, risk scoring, webhooks, schemas Pydantic, alertes D5, ORM SQLAlchemy, 3DS2 (44), tokenisation (56), PKI (25), DDA/CDA (34), flux CB complet (45), mode dégradé (35), config loader (25), HSM (43), cache (30), persistance hybride (15), stats SQL (10), certification (12). Couverture > 90 %. |
| A6 | 🟢 | **Conteneurisation Docker** | ✅ Livré | v1.4.0 | `Dockerfile` multi-stage, `docker-compose.yml` avec ports 5000/8583, volume persistance, healthcheck. |

---

## 7. Fonctionnalités hors roadmap initiale — livrées

| # | Évolution | Version | Description |
|---|-----------|---------|-------------|
| X1 | **Interface TCP ISO 8583** | v1.3.0 | Serveur TCP port 8583 avec préfixe 4 octets. MTI 0100/0200/0400/0420/0800. Simulateur terminal `tools/terminal_simulator.py`. 57 tests TCP. |
| X2 | **Décomposition réponse TPA** | v1.2.0 | `models/tpa_response.py` : décomposition F38, F39, F55 ARPC, F60. Endpoint `GET /api/v1/transactions/<id>/tpa`. |
| X3 | **Journal d'audit détaillé** | v1.4.0 | Chaque transaction porte sa trace complète d'événements horodatés. Endpoint `GET /api/v1/transactions/<id>/log`. |
| X4 | **Recherche multi-critères** | v1.4.0 | `POST /api/v1/transactions/search` + filtres avancés GET : date, montant, terminal, merchant, cb_scheme, auth_path, RRN. |
| X5 | **Recherche par RRN** | v1.4.0 | `GET /api/v1/transactions/rrn/<rrn>` avec TPA response. |
| X6 | **Historique carte** | v1.4.0 | `GET /api/v1/cards/<pan>/history` : blocages/déblocages + statistiques des transactions associées. |
| X7 | **Mise à jour carte (PATCH)** | v1.4.0 | `PATCH /api/v1/cards/<pan>` : modifier balance, daily_limit, cardholder_name, pin_tries. |
| X8 | **Index de l'API** | v1.4.0 | `GET /api/v1` : liste dynamique de toutes les routes enregistrées. |

---

## Roadmap versionnée

| Version | Objectif | Statut | Priorité |
|---------|----------|--------|----------|
| v1.10.0 | Historique JSON 7 jours + import JSON → DB | ✅ Livré | Haute |
| v1.12.0 | API de récupération assistée des snapshots + archivage avancé | ✅ Livré | Haute |
| v1.13.0 | Persistance Hybride Robuste (PersistenceManager) | ✅ Livré | Haute |
| v1.14.0 | Simulateur de Certification GIE CB + Stats SQL Optimisées | ✅ Livré | Moyenne |
| v1.15.0 | Authentification PIN (Online/Offline) | 🟡 À faire | Moyenne |
| v1.16.0 | Gestion des clés rotatives (Key Rotation) | 🟡 À faire | Basse |

---

## Tableau de bord global

| Axe | Livré | Partiel | Non démarré | Total |
|-----|-------|---------|-------------|-------|
| Sécurité | 6 | 0 | 0 | 6 |
| Persistance | 5 | 0 | 0 | 5 |
| EMV | 8 | 0 | 0 | 8 |
| GIE CB | 6 | 0 | 0 | 6 |
| Dashboard | 7 | 0 | 0 | 7 |
| Architecture | 6 | 0 | 0 | 6 |
| Hors roadmap | 8 | — | — | 8 |
| **Total** | **46** | **0** | **0** | **46** |

---

*Roadmap initiée le 02/05/2026 — mise à jour le 06/05/2026 · v1.14.0 — **46/46 features livrées** ✅*
