# Évolutions — Serveur d'Autorisation EMV GIE CB

> Dernière mise à jour : **03 mai 2026** — Version courante : **v1.4.0**  
> Suite de tests : **901 tests** (sans TCP)  
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
| S6 | 🟢 | **Journal d'audit immuable** | ✅ Livré | v1.4.0 | `Transaction.log_event()` enregistre chaque étape (TRANSACTION_CREATED → AUTHORIZATION_DECISION). Endpoint `GET /api/v1/transactions/<id>/log`. |

---

## 2. Persistance des données

| # | Priorité | Évolution | Statut | Version | Notes |
|---|----------|-----------|--------|---------|-------|
| P1 | 🔴 | **Base de données SQLite / PostgreSQL** | ❌ Non démarré | — | Données en RAM. SQLAlchemy + Alembic non intégrés. Volume Docker `emv-data` atténue la perte au redémarrage via snapshot JSON. |
| P2 | 🟡 | **Sauvegarde JSON périodique** | ✅ Livré | v1.3.0 | `persistence.py` : snapshot toutes les 120 s (configurable), sauvegarde SIGTERM, rechargement au démarrage. Fichier `data/snapshot.json`. |
| P3 | 🟡 | **Migrations de schéma** | ❌ Non démarré | — | Dépend de P1. Alembic non intégré. |
| P4 | 🟢 | **Cache Redis** | ❌ Non démarré | — | Utile uniquement en déploiement multi-instances. |

---

## 3. Fonctionnalités EMV

| # | Priorité | Évolution | Statut | Version | Notes |
|---|----------|-----------|--------|---------|-------|
| E1 | 🔴 | **Vérification CVV/CVC** | ✅ Livré | v1.2.0 | `emv/cvv.py` : CVV1 (piste 2), CVV2 (DOS), iCVV (puce) via 3DES. Endpoints `GET /cvv/generate` et `POST /cvv/verify`. |
| E2 | 🔴 | **3-D Secure 2.x (3DS2)** | ❌ Non démarré | — | Flux DSP2 AReq/ARes/CReq/CRes non implémenté. Exemptions SCA gérées côté GIE CB (LVP/TRA/MIT). |
| E3 | 🟡 | **DDA / CDA** | ❌ Non démarré | — | Authentification dynamique (RSA par carte) non simulée. |
| E4 | 🟡 | **Préautorisation + capture différée** | ❌ Non démarré | — | MTI 0100 / 0200 et statut PREAUTHORIZED non implémentés. |
| E5 | 🟡 | **Redressements et avis** | ✅ Livré | v1.3.1 | `emv/reversal.py` : complet, partiel, avis (0420). TCP MTI 0400→0410 et 0420→0430. Endpoint `POST /reverse`. 74 tests. |
| E6 | 🟡 | **Disputes / chargebacks** | ❌ Non démarré | — | MTI 0620/0630 non implémentés. |
| E7 | 🟢 | **Blackliste BIN** | ❌ Non démarré | — | |
| E8 | 🟢 | **Multi-devises avec conversion** | ⚠️ Partiel | v1.0.0 | 10 devises supportées (EUR, USD, GBP…). Conversion automatique par taux de change non implémentée. |

---

## 4. Règles GIE CB

| # | Priorité | Évolution | Statut | Version | Notes |
|---|----------|-----------|--------|---------|-------|
| C1 | 🔴 | **Simulation flux CB complet** | ⚠️ Partiel | v1.2.0 | `emv/giecb.py` : identification réseau (VISA CB / MC CB / CB natif), règles sans contact, cumul offline, SCA. Compensation CFONB 160 non simulée. |
| C2 | 🟡 | **Certificats émetteurs CB** | ❌ Non démarré | — | PKI simulée avec clés publiques CB non intégrée. |
| C3 | 🟡 | **CB-PAY / Wallet NFC** | ❌ Non démarré | — | Tokens HCE non implémentés. |
| C4 | 🟡 | **Issuer Script Processing (tag 71/72)** | ❌ Non démarré | — | Scripts émetteur dans la réponse non supportés. |
| C5 | 🟢 | **Scoring risque temps réel** | ⚠️ Partiel | v1.2.0 | Moteur de tranches (6 niveaux MICRO→BLOCKED) + règles GIE CB (floor limit, vélocité). Scoring ML non implémenté. |

---

## 5. Dashboard & Monitoring

| # | Priorité | Évolution | Statut | Version | Notes |
|---|----------|-----------|--------|---------|-------|
| D1 | 🟡 | **Graphiques temps réel (SSE)** | ✅ Livré | v1.3.0 | Chart.js + Server-Sent Events sur `/api/v1/stats/stream`. Courbe transactions/min, camembert schémas CB, histogramme tranches. |
| D2 | 🟡 | **Export CSV** | ✅ Livré | v1.3.0 | `GET /api/v1/transactions/export` : CSV avec en-têtes métier (RRN, PAN masqué, montant, code réponse, tranche, schéma CB…). |
| D3 | 🟡 | **Documentation Swagger / OpenAPI 3.0** | ❌ Non démarré | — | `flask-smorest` ou `flasgger` non intégrés. L'endpoint `GET /api/v1` liste toutes les routes disponibles (v1.4.0). |
| D4 | 🟡 | **Simulation de scénarios batch** | ✅ Livré | v1.3.0 | `POST /api/v1/batch/simulate` : N transactions avec cartes et montants variés configurables. |
| D5 | 🟢 | **Alertes visuelles** | ❌ Non démarré | — | Notifications dashboard (cumul sans contact, quota journalier) non implémentées. |
| D6 | 🟢 | **Mode sombre / clair** | ✅ Livré | v1.3.0 | Toggle thème dans le dashboard (CSS variables + localStorage). |

---

## 6. Architecture & Intégration

| # | Priorité | Évolution | Statut | Version | Notes |
|---|----------|-----------|--------|---------|-------|
| A1 | 🟡 | **Webhooks sortants** | ❌ Non démarré | — | Notification POST JSON sur décision d'autorisation non implémentée. |
| A2 | 🟡 | **Mode dégradé simulé** | ❌ Non démarré | — | Injection d'erreurs réseau / timeouts aléatoires non implémentée. |
| A3 | 🟡 | **Configuration YAML/TOML rechargeable** | ❌ Non démarré | — | Paramètres dans `config.py` via variables d'environnement. Rechargement à chaud non supporté. |
| A4 | 🟢 | **Client Python CLI** | ✅ Livré | v1.3.0 | `cli.py` : envoi d'autorisations, consultation transactions et stats depuis la ligne de commande. |
| A5 | 🟢 | **Tests unitaires et d'intégration** | ✅ Livré | v1.4.0 | **901 tests** dans 13 fichiers. Crypto, TLV, CB rules, tranches, REST, TCP, redressements, journal d'audit. Couverture > 90 %. |
| A6 | 🟢 | **Conteneurisation Docker** | ✅ Livré | v1.4.0 | `Dockerfile` multi-stage (builder + runtime Python 3.11-slim), `docker-compose.yml` avec ports 5000/8583, volume persistance, healthcheck et toutes les variables d'environnement. |

---

## 7. Fonctionnalités hors roadmap initiale — livrées

Ces évolutions ont été implémentées en dehors de la roadmap originale (v1.2.0).

| # | Évolution | Version | Description |
|---|-----------|---------|-------------|
| X1 | **Interface TCP ISO 8583** | v1.3.0 | Serveur TCP port 8583 avec préfixe 4 octets. MTI 0100/0200/0400/0420/0800. Simulateur terminal `tools/terminal_simulator.py`. 57 tests TCP. |
| X2 | **Décomposition réponse TPA** | v1.2.0 | `models/tpa_response.py` : décomposition des champs de réponse TPA (F38, F39, F55 ARPC, F60). Endpoint `GET /api/v1/transactions/<id>/tpa`. |
| X3 | **Journal d'audit détaillé** | v1.4.0 | Chaque transaction porte sa trace complète d'événements horodatés (stage, level INFO/WARN/ERROR, data). Endpoint `GET /api/v1/transactions/<id>/log`. |
| X4 | **Recherche multi-critères** | v1.4.0 | `POST /api/v1/transactions/search` (JSON body) et filtres avancés sur `GET /api/v1/transactions` : date, montant, terminal, merchant, cb_scheme, auth_path, RRN. |
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
| EMV | 3 | 1 | 4 | 8 |
| GIE CB | 0 | 2 | 3 | 5 |
| Dashboard | 4 | 0 | 2 | 6 |
| Architecture | 3 | 0 | 3 | 6 |
| Hors roadmap | 8 | — | — | 8 |
| **Total** | **23** | **4** | **16** | **43** |

---

## Prochaines priorités recommandées

| Rang | # | Évolution | Justification |
|------|---|-----------|---------------|
| 1 | P1 | Base de données SQLite/PostgreSQL | Persistance fiable sans dépendre du snapshot JSON |
| 2 | D3 | Documentation Swagger / OpenAPI | Facilite l'intégration pour les consommateurs de l'API |
| 3 | E4 | Préautorisation + capture différée | Cas d'usage hôtel/location très répandu |
| 4 | E2 | 3-D Secure 2.x | Obligatoire DSP2 pour transactions e-commerce |
| 5 | A1 | Webhooks sortants | Intégration back-office sans polling |

---

*Roadmap initiée le 02/05/2026 — mise à jour le 03/05/2026 · v1.4.0*
