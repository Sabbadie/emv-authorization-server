# Guide Utilisateur — EMV Authorization Server v1.14.0

> Serveur d'autorisation de paiement conforme EMV 4.3, ISO 8583 et règles GIE CB.
> Interface REST HTTP (port 5000) et TCP ISO 8583 (port 8583).

---

## Table des matières

1. [Démarrage rapide](#1-démarrage-rapide)
2. [Authentification](#2-authentification)
3. [Autorisation de paiement](#3-autorisation-de-paiement)
4. [3-D Secure 2.x (3DS2)](#4-3-d-secure-2x-3ds2)
5. [Tokenisation HCE/NFC (CB-PAY)](#5-tokenisation-hcenfc-cb-pay)
6. [Règles GIE CB](#6-règles-gie-cb)
7. [PKI et authentification offline (DDA/CDA)](#7-pki-et-authentification-offline-ddacda)
8. [Préautorisations et captures](#8-préautorisations-et-captures)
9. [Chargebacks et litiges](#9-chargebacks-et-litiges)
10. [Mode dégradé / Chaos Engineering](#10-mode-dégradé--chaos-engineering)
11. [Configuration YAML/TOML](#11-configuration-yamltom)
12. [HSM — Protection des clés](#12-hsm--protection-des-clés)
13. [Cache distribué](#13-cache-distribué)
14. [Monitoring et statistiques](#14-monitoring-et-statistiques)
15. [Interface de Certification GIE CB](#15-interface-de-certification-gie-cb)
16. [Gestion de la Persistance Hybride](#16-gestion-de-la-persistance-hybride)
17. [Cartes de test](#17-cartes-de-test)
18. [Codes réponse](#18-codes-réponse)

---

## 1. Démarrage rapide

### Lancer le serveur

```bash
python main.py
```

Le serveur démarre sur :
- **HTTP** : http://localhost:5000
- **TCP ISO 8583** : localhost:8583
- **Dashboard** : http://localhost:5000

### Vérifier la santé du serveur

```bash
curl -s http://localhost:5000/api/v1/health | python -m json.tool
```

Réponse :
```json
{
  "status": "UP",
  "version": "1.14.0",
  "database": "postgresql",
  "api_key_enabled": false
}
```

---

## 14. Monitoring et statistiques

### Statistiques globales (Optimisées SQL)

```bash
curl -s http://localhost:5000/api/v1/stats | python -m json.tool
```

### Séries Temporelles (Hourly Stats)

Récupère le nombre de transactions par heure sur les N dernières heures (max 168h / 1 semaine).

```bash
# Dernières 24 heures (défaut)
curl -s http://localhost:5000/api/v1/stats/time-series

# Dernières 48 heures
curl -s "http://localhost:5000/api/v1/stats/time-series?hours=48"
```

### Stream SSE temps réel

```bash
curl -s http://localhost:5000/api/v1/stats/stream
```

### Alertes visuelles

```bash
curl -s http://localhost:5000/api/v1/alerts | python -m json.tool
```

7 types d'alertes : `CONTACTLESS_CUMUL_HIGH`, `DAILY_LIMIT_APPROACHING`, `CARD_BLOCKED_HIGH`, `TRANSACTION_FAILURE_BURST`, `BIN_BLACKLIST_ACTIVITY`, `CHARGEBACK_SURGE`, `PREAUTH_EXPIRY_WARNING`

---

## 15. Interface de Certification GIE CB

Le serveur intègre un moteur de conformité pour valider les implémentations de terminaux.

### Lister les scénarios de test

```bash
curl -s http://localhost:5000/api/v1/certification/scenarios | python -m json.tool
```

### Lancer un scénario

Exécute une séquence de transactions et vérifie la conformité des réponses (codes RC, indicateurs de service, etc.).

```bash
# Exemple : Test de dépassement du cumul sans contact
curl -s -X POST http://localhost:5000/api/v1/certification/run/CL_CUMUL_LIMIT | python -m json.tool
```

Scénarios disponibles :
- `CL_CUMUL_LIMIT` : Validation du blocage après 150€ de cumul NFC.
- `INVALID_ARQC` : Détection et refus des cryptogrammes erronés.
- `CARD_BLOCKED` : Vérification du refus immédiat des cartes en opposition.

---

## 16. Gestion de la Persistance Hybride

Le serveur gère automatiquement le basculement entre la base de données et le stockage JSON.

### Import manuel de snapshot

Utile pour synchroniser la base de données à partir d'un fichier de sauvegarde.

```bash
# Lister les fichiers disponibles
curl -s http://localhost:5000/api/v1/snapshots

# Importer un fichier spécifique
curl -s -X POST http://localhost:5000/api/v1/snapshots/snapshot_20260506_120000.json.gz/import
```

### Auto-Recover

Au démarrage, si `DATABASE_URL` est présent mais que la base est vide, le `PersistenceManager` importe automatiquement le dernier snapshot disponible.

---

## 17. Cartes de test

| PAN | Titulaire | Statut | Solde | Notes |
|-----|-----------|--------|-------|-------|
| 4111 1111 1111 1111 | JEAN DUPONT | ACTIVE | 500,00€ | Visa CB — usage général |
| 5500 0000 0000 0004 | MARIE MARTIN | ACTIVE | 1 000,00€ | MC CB — haut solde |
| 4000 0000 0000 0002 | ALICE ADVANCED | ACTIVE | 250,00€ | Visa CB — tests avancés |
| 4970 1000 0000 0154 | CLAIRE CB | ACTIVE | 300,00€ | CB natif (AID A0000000421010) |
| 4000 0000 0000 0036 | PAUL PETIT | ACTIVE | 0,01€ | Visa CB — solde insuffisant |
| 4000 0000 0000 0010 | SOPHIE EXPIRY | ACTIVE | 500,00€ | Visa CB — **expirée** |
| 4000 0000 0000 0028 | LUC BLOCKED | BLOCKED | 300,00€ | Visa CB — **bloquée** |

---

## 18. Codes réponse

| Code | Message | Cause fréquente |
|------|---------|-----------------|
| `00` | Approuvé | Transaction acceptée |
| `01` | Référer à l'émetteur | Montant > 5000€ |
| `05` | Ne pas honorer | Refus générique |
| `12` | Transaction invalide | Paramètres incorrects |
| `14` | Numéro de carte invalide | PAN invalide ou inconnu |
| `51` | Provision insuffisante | Solde < montant |
| `54` | Carte expirée | Date d'expiration dépassée |
| `55` | Code PIN incorrect | PIN erroné |
| `57` | Transaction non autorisée | MCC bloqué, 3DS non satisfait |
| `61` | Plafond dépassé | Limite journalière atteinte |
| `62` | Carte avec restriction | Sans contact dépassé, carte bloquée |
| `65` | Fréquence dépassée | Vélocité CB excédée |
| `75` | PIN bloqué | 3 tentatives échouées |
| `1A` | SCA requise (CB) | Authentification forte obligatoire |
| `A5` | Cumul sans contact | Cumul hors ligne 150€ dépassé |
| `P1` | Plafond sans contact | Montant > 50€ en NFC |

---

*EMV Authorization Server v1.14.0 — GIE CB | EMV 4.3 | ISO 8583 | 3DS2 | HCE/NFC*
