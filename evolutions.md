# Évolutions — Serveur d'Autorisation EMV GIE CB

> Dernière mise à jour : **03 mai 2026** — Version courante : **v1.5.0**  
> Suite de tests : **1 213 tests** (toutes catégories)  
> Légende : ✅ Livré · ⚠️ Partiel · ❌ Non démarré  
> Priorité : 🔴 Haute · 🟡 Moyenne · 🟢 Basse

---

## 1. Sécurité

| # | Priorité | Évolution | Statut | Version | Notes |
|---|----------|-----------|--------|---------|-------|
| S1 | 🔴 | **Authentification API Key** | ✅ Livré | v1.3.0 | Header `X-Api-Key` activable via `EMV_API_KEY`. Sans clé → mode dev sans auth. |
| S2 | 🔴 | **Rate limiting** | ✅ Livré | v1.3.0 | `Flask-Limiter 4.1.1`. 300 req/min global, 30/min sur `/authorize`, 5/min batch. HTTP 429. |
| S3 | 🟡 | **Masquage PAN dans les logs** | ✅ Livré | v1.0.0 | PAN masqué (`************NNNN`) dans toutes les réponses REST et journaux d'audit. |
| S4 | 🟡 | **Validation stricte des entrées** | ⚠️ Partiel | — | Validations manuelles en place (PAN, amount, currency). Pydantic/marshmallow non intégrés. |
| S5 | 🟡 | **Chiffrement données sensibles en RAM** | ❌ Non démarré | — | MDK et PAN stockés en clair en mémoire. HSM simulé non implémenté. |
| S6 | 🟢 | **Journal d'audit immuable** | ✅ Livré | v1.4.0 | `Transaction.log_event()` enregistre chaque étape. Endpoint `GET /api/v1/transactions/<id>/log`. |

---

## 2. Persistance des données

| # | Priorité | Évolution | Statut | Version | Notes |
|---|----------|-----------|--------|---------|-------|
| P1 | 🔴 | **Base de données SQLite / PostgreSQL** | ❌ Non démarré | — | Données en RAM. SQLAlchemy + Alembic non intégrés. |
| P2 | 🟡 | **Sauvegarde JSON périodique** | ✅ Livré | v1.3.0 | `persistence.py` : snapshot toutes les 120 s, sauvegarde SIGTERM, rechargement au démarrage. |
| P3 | 🟡 | **Migrations de schéma** | ❌ Non démarré | — | Dépend de P1. Alembic non intégré. |
| P4 | 🟢 | **Cache Redis** | ❌ Non démarré | — | Utile uniquement en déploiement multi-instances. |

---

## 3. Fonctionnalités EMV

| # | Priorité | Évolution | Statut | Version | Notes |
|---|----------|-----------|--------|---------|-------|
| E1 | 🔴 | **Vérification CVV/CVC** | ✅ Livré | v1.2.0 | `emv/cvv.py` : CVV1 (piste 2), CVV2 (DOS), iCVV (puce) via 3DES. |
| E2 | 🔴 | **3-D Secure 2.x (3DS2)** | ❌ Non démarré | — | Flux DSP2 AReq/ARes/CReq/CRes non implémenté. |
| E3 | 🟡 | **DDA / CDA** | ❌ Non démarré | — | Authentification dynamique (RSA par carte) non simulée. |
| E4 | 🟡 | **Préautorisation + capture différée** | ✅ Livré | v1.5.0 | `emv/preauth.py` : MTI 0100/0200/0400. Statuts PENDING/CAPTURED/PARTIAL/CANCELLED/EXPIRED. Capture partielle. 34 tests. |
| E5 | 🟡 | **Redressements et avis** | ✅ Livré | v1.3.1 | `emv/reversal.py` : complet, partiel, avis (0420). TCP MTI 0400→0410 et 0420→0430. 74 tests. |
| E6 | 🟡 | **Disputes / chargebacks** | ✅ Livré | v1.5.0 | `emv/chargeback.py` : MTI 0620/0630. 12 codes motif CB01–CB12. Résolution ACCEPTED/REJECTED/ARBITRATION. 37 tests. |
| E7 | 🟢 | **Blackliste BIN/PAN** | ✅ Livré | v1.5.0 | `emv/bin_blacklist.py` : BIN (préfixe) + PAN complet. Code réponse 63. Intégré en step 0 de `authorize()`. CRUD REST complet. 38 tests. |
| E8 | 🟢 | **Multi-devises avec conversion** | ✅ Livré | v1.5.0 | `emv/currency.py` : 12 devises (EUR/USD/GBP/CHF/JPY/MAD/DZD/DKK/SEK/NOK/CAD/TND). Taux croisés, formatage. 28 tests. |

---

## 4. Règles GIE CB

| # | Priorité | Évolution | Statut | Version | Notes |
|---|----------|-----------|--------|---------|-------|
| C1 | 🔴 | **Simulation flux CB complet** | ⚠️ Partiel | v1.2.0 | `emv/giecb.py` : identification réseau, règles sans contact, cumul offline, SCA. |
| C2 | 🟡 | **Certificats émetteurs CB** | ❌ Non démarré | — | PKI simulée non intégrée. |
| C3 | 🟡 | **CB-PAY / Wallet NFC** | ❌ Non démarré | — | Tokens HCE non implémentés. |
| C4 | 🟡 | **Issuer Script Processing (tag 71/72)** | ✅ Livré | v1.5.0 | `emv/issuer_scripts.py` : génération Tag 71 (avant transaction) / Tag 72 (après). UNBLOCK_PIN, UPDATE_RISK_PARAMS, PUT_DATA. Export hex + base64. 26 tests. |
| C5 | 🟢 | **Scoring risque temps réel** | ✅ Livré | v1.5.0 | `emv/risk_scoring.py` : 5 facteurs (montant 30pts, vélocité 25pts, MCC 20pts, sans-contact 15pts, horaire 10pts). Niveaux LOW/MEDIUM/HIGH/CRITICAL. Décisions ALLOW/CHALLENGE/BLOCK. 32 tests. |

---

## 5. Dashboard & Monitoring

| # | Priorité | Évolution | Statut | Version | Notes |
|---|----------|-----------|--------|---------|-------|
| D1 | 🟡 | **Graphiques temps réel (SSE)** | ✅ Livré | v1.3.0 | Chart.js + Server-Sent Events sur `/api/v1/stats/stream`. |
| D2 | 🟡 | **Export CSV** | ✅ Livré | v1.3.0 | `GET /api/v1/transactions/export` : CSV avec en-têtes métier complets. |
| D3 | 🟡 | **Documentation Swagger / OpenAPI 3.0** | ✅ Livré | v1.5.0 | Spec OpenAPI 3.0 sur `GET /api/v1/openapi.json`. Swagger UI interactif sur `GET /api/docs`. 13 tags, tous les nouveaux endpoints documentés. |
| D4 | 🟡 | **Simulation de scénarios batch** | ✅ Livré | v1.3.0 | `POST /api/v1/batch/simulate` : N transactions avec cartes et montants variés. |
| D5 | 🟢 | **Alertes visuelles** | ❌ Non démarré | — | Notifications dashboard non implémentées. |
| D6 | 🟢 | **Mode sombre / clair** | ✅ Livré | v1.3.0 | Toggle thème dans le dashboard (CSS variables + localStorage). |

---

## 6. Architecture & Intégration

| # | Priorité | Évolution | Statut | Version | Notes |
|---|----------|-----------|--------|---------|-------|
| A1 | 🟡 | **Webhooks sortants** | ✅ Livré | v1.5.0 | `emv/webhooks.py` : POST JSON asynchrone (thread daemon). 8 types d'événements. Journal 200 entrées. `WEBHOOK_URL` env var. Endpoints CRUD. 35 tests. |
| A2 | 🟡 | **Mode dégradé simulé** | ❌ Non démarré | — | Injection d'erreurs réseau / timeouts aléatoires non implémentée. |
| A3 | 🟡 | **Configuration YAML/TOML rechargeable** | ❌ Non démarré | — | Paramètres dans `config.py` via variables d'environnement. Rechargement à chaud non supporté. |
| A4 | 🟢 | **Client Python CLI** | ✅ Livré | v1.3.0 | `cli.py` : envoi d'autorisations, consultation transactions et stats. |
| A5 | 🟢 | **Tests unitaires et d'intégration** | ✅ Livré | v1.5.0 | **1 213 tests** dans 20 fichiers. Crypto, TLV, CB rules, tranches, REST, TCP, chargebacks, préauths, BIN blacklist, devises, issuer scripts, risk scoring, webhooks. Couverture > 90 %. |
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

## Tableau de bord global

| Axe | Livré | Partiel | Non démarré | Total |
|-----|-------|---------|-------------|-------|
| Sécurité | 4 | 1 | 1 | 6 |
| Persistance | 1 | 0 | 3 | 4 |
| EMV | 6 | 0 | 2 | 8 |
| GIE CB | 2 | 1 | 2 | 5 |
| Dashboard | 5 | 0 | 1 | 6 |
| Architecture | 4 | 0 | 2 | 6 |
| Hors roadmap | 8 | — | — | 8 |
| **Total** | **30** | **2** | **11** | **43** |

---

## Prochaines priorités recommandées (post v1.5.0)

| Rang | # | Évolution | Justification |
|------|---|-----------|---------------|
| 1 | P1 | Base de données SQLite/PostgreSQL | Persistance fiable sans dépendre du snapshot JSON |
| 2 | E2 | 3-D Secure 2.x | Obligatoire DSP2 pour transactions e-commerce |
| 3 | S4 | Validation stricte (Pydantic) | Renforcer la robustesse des entrées API |
| 4 | A2 | Mode dégradé simulé | Tester la résilience (chaos engineering) |
| 5 | D5 | Alertes visuelles dashboard | Supervision temps réel cumul sans contact / quota |

---

*Roadmap initiée le 02/05/2026 — mise à jour le 03/05/2026 · v1.5.0*
