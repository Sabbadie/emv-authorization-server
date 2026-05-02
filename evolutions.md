# Évolutions possibles — Serveur d'Autorisation EMV GIE CB

> Document de roadmap technique listant les améliorations identifiées après la version `1.2.0-GIE-CB`.  
> Classées par axe et par priorité estimée : 🔴 Haute · 🟡 Moyenne · 🟢 Basse

---

## 1. Sécurité

| # | Priorité | Évolution | Description |
|---|----------|-----------|-------------|
| S1 | 🔴 | **Authentification API (JWT / API Key)** | En l'état, tous les endpoints `/api/v1/*` sont accessibles sans authentification. Ajouter un mécanisme de clé API (header `X-Api-Key`) ou un token JWT signé (HS256/RS256) avec expiration. |
| S2 | 🔴 | **Rate limiting** | Protéger contre les attaques par force brute et l'énumération de PAN. Exemple : 100 req/min par IP via `Flask-Limiter`. Codes HTTP `429 Too Many Requests`. |
| S3 | 🟡 | **Masquage PAN dans les logs** | Les logs Werkzeug/Flask peuvent exposer le PAN en clair dans les URL ou corps de requête. Implémenter un filtre de log masquant les PAN (`XXXXXXXXXXXXNNNN`). |
| S4 | 🟡 | **Validation stricte des entrées** | Remplacer les validations manuelles par des schémas Pydantic v2 ou marshmallow. Rejeter proprement les payloads malformés avec messages d'erreur structurés. |
| S5 | 🟡 | **Chiffrement des données sensibles en RAM** | Les clés MDK et PAN sont stockés en mémoire en clair. Utiliser un HSM simulé ou chiffrer les attributs sensibles avec une clé dérivée de l'environnement. |
| S6 | 🟢 | **Journal d'audit immuable** | Écrire chaque décision d'autorisation dans un log structuré (JSON Lines) signé numériquement, non modifiable, pour traçabilité réglementaire (PCI-DSS). |

---

## 2. Persistance des données

| # | Priorité | Évolution | Description |
|---|----------|-----------|-------------|
| P1 | 🔴 | **Base de données SQLite / PostgreSQL** | Actuellement toutes les données (transactions, cartes) sont en RAM et perdues au redémarrage. Intégrer SQLAlchemy avec modèles ORM pour cartes, transactions et événements d'audit. |
| P2 | 🟡 | **Sauvegarde JSON périodique** | Solution légère sans base de données : sérialiser l'état complet en JSON chiffré toutes les N minutes et à l'arrêt propre du serveur (`SIGTERM`). |
| P3 | 🟡 | **Migrations de schéma** | Si SQLAlchemy est adopté, ajouter Alembic pour gérer les migrations de schéma de façon reproductible entre versions. |
| P4 | 🟢 | **Cache Redis** | Pour les déploiements multi-instances : externaliser les compteurs de vélocité (ATC, cumul sans contact, dépenses journalières) dans Redis. |

---

## 3. Fonctionnalités EMV manquantes

| # | Priorité | Évolution | Description |
|---|----------|-----------|-------------|
| E1 | 🔴 | **Vérification CVV/CVC** | Implémenter la vérification du Code de Vérification de la Carte (CVV1 piste 2, CVV2 DOS, iCVV puce) via 3DES. |
| E2 | 🔴 | **3-D Secure 2.x (3DS2)** | Implémenter le flux SCA complet DSP2 : `AReq` → `ARes` → `CReq` → `CRes` avec frictionless flow et challenge flow. Exemptions LVP/TRA/MIT supportées par le moteur GIE CB actuel. |
| E3 | 🟡 | **DDA / CDA — Authentification dynamique** | Actuellement seule l'authentification SDA (statique) est simulée. Ajouter DDA (Dynamic Data Authentication) et CDA (Combined DDA/AC) avec paires de clés RSA par carte. |
| E4 | 🟡 | **Préautorisation + capture différée** | Flux hôtel / location de voiture : MTI `0100` (préautorisation), puis `0200` (capture) avec montant final différent. Gérer le statut `PREAUTHORIZED`. |
| E5 | 🟡 | **Annulations et remboursements complets** | MTI `0400` (reversal) et `0420` (reversal advice). Créditer automatiquement le solde carte et mettre à jour l'historique. |
| E6 | 🟡 | **Disputes / chargebacks** | Implémenter le flux ISO 8583 de réclamation : `0620` (chargeback), `0630` (chargeback reversal) avec motifs CB (`R01`–`R12`). |
| E7 | 🟢 | **Blackliste BIN** | Maintenir une liste de BIN/PAN refusés globalement (fraude connue) avec codes réponse `63` (violation de sécurité). |
| E8 | 🟢 | **Support multi-devises avec conversion** | Conversion automatique via taux de change (ECB ou API externe) pour les transactions en devise étrangère. |

---

## 4. Règles GIE CB supplémentaires

| # | Priorité | Évolution | Description |
|---|----------|-----------|-------------|
| C1 | 🔴 | **Simulation flux CB complet** | Implémenter le cycle complet : demande → réponse → compensation → règlement. Fichiers de compensation CB (`CFONB 160`) simulés. |
| C2 | 🟡 | **Certificats émetteurs CB** | Intégrer les clés publiques des émetteurs CB pour vérification ODA (Offline Data Authentication) réelle avec PKI simulée. |
| C3 | 🟡 | **CB-PAY / Wallet NFC** | Simulation de transactions CB-PAY (token HCE) avec dépersonnalisation et gestion du cycle de vie des tokens. |
| C4 | 🟡 | **Gestion des paramètres issuer (ILP/ISP)** | Issuer Script Processing : envoyer des scripts émetteur (tag `71`/`72`) dans la réponse pour mettre à jour les paramètres de la carte. |
| C5 | 🟢 | **CB Scoring risque temps réel** | Moteur de scoring basé sur les règles GIE CB : géolocalisation, MCC, historique, vélocité, profil comportemental. |

---

## 5. Dashboard & Monitoring

| # | Priorité | Évolution | Description |
|---|----------|-----------|-------------|
| D1 | 🟡 | **Graphiques temps réel (WebSocket / SSE)** | Courbe de transactions par minute, camembert des schémas CB (VISA/MC/CB), histogramme des tranches de montant. Utiliser Chart.js côté frontend et Server-Sent Events côté Flask. |
| D2 | 🟡 | **Export CSV** | En complément du JSON : export CSV de l'historique avec en-têtes métier (RRN, PAN masqué, montant, code CB, etc.). |
| D3 | 🟡 | **Documentation Swagger / OpenAPI 3.0** | Générer automatiquement la spec OpenAPI depuis les routes Flask (`flask-smorest` ou `flasgger`). Interface Swagger UI intégrée sur `/api/docs`. |
| D4 | 🟡 | **Simulation de scénarios batch** | Bouton « Lancer 50 transactions de test » avec cartes et montants variés pour peupler l'historique et tester les règles. |
| D5 | 🟢 | **Alertes visuelles** | Notifier dans le dashboard les événements critiques : cumul sans contact proche du plafond, quota journalier atteint, ARQC invalide détecté. |
| D6 | 🟢 | **Mode sombre / clair** | Toggle thème dans le dashboard (le thème sombre est l'unique option actuelle). |

---

## 6. Architecture & Intégration

| # | Priorité | Évolution | Description |
|---|----------|-----------|-------------|
| A1 | 🟡 | **Webhooks sortants** | Notifier une URL externe (configurable) à chaque décision d'autorisation via `POST` JSON. Utile pour intégration avec des systèmes back-office. |
| A2 | 🟡 | **Mode dégradé simulé** | Injecter des erreurs réseau / timeouts aléatoires (configurable par taux) pour tester la résilience des terminaux face à un émetteur indisponible (`91`). |
| A3 | 🟡 | **Configuration YAML/TOML** | Externaliser les paramètres (MDK, plafonds, règles CB, floor limits) dans un fichier de configuration rechargeable sans redémarrage. |
| A4 | 🟢 | **Client Python CLI** | Script `cli.py` pour envoyer des autorisations depuis la ligne de commande, utile pour tests automatisés et intégration CI. |
| A5 | 🟢 | **Tests unitaires et d'intégration** | Suite pytest couvrant : crypto (ARQC/ARPC), TLV parser, moteur CB, règles tranches, endpoints REST. Objectif : couverture ≥ 80 %. |
| A6 | 🟢 | **Conteneurisation Docker** | `Dockerfile` + `docker-compose.yml` pour déploiement reproductible avec optionnellement PostgreSQL et Redis. |

---

## Résumé par effort estimé

| Effort | Évolutions |
|--------|-----------|
| **Court terme** (1–2 jours) | S1, S2, P2, D2, D3, D4, A3 |
| **Moyen terme** (1–2 semaines) | S4, P1, E1, E2, E4, E5, D1, C4, A1 |
| **Long terme** (1+ mois) | E3, E6, C1, C2, C3, C5, P4, A5, A6 |

---

*Document généré le 02/05/2026 — Serveur EMV v1.2.0-GIE-CB*
