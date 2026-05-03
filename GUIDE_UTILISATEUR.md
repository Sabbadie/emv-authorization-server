# Guide Utilisateur — EMV Authorization Server v1.9.0

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
15. [Cartes de test](#15-cartes-de-test)
16. [Codes réponse](#16-codes-réponse)

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
  "status": "ok",
  "version": "1.9.0",
  "database": "postgresql",
  "transactions": 0,
  "cards": 7
}
```

### Première autorisation

```bash
curl -s -X POST http://localhost:5000/api/v1/authorize \
  -H "Content-Type: application/json" \
  -d '{
    "pan": "4111111111111111",
    "amount": 5000,
    "currency": "978",
    "transaction_type": "00",
    "terminal_id": "TERM0001",
    "merchant_id": "MERCH001",
    "pos_entry_mode": "051"
  }' | python -m json.tool
```

---

## 2. Authentification

### Sans authentification (mode développement)

Par défaut, aucune clé API n'est requise. Le serveur accepte toutes les requêtes.

### Avec clé API (mode production)

Définir la variable d'environnement :
```bash
export EMV_API_KEY="votre-cle-secrete"
```

Toutes les requêtes doivent inclure le header :
```bash
curl -H "X-Api-Key: votre-cle-secrete" http://localhost:5000/api/v1/stats
```

Sans clé valide, le serveur retourne `HTTP 401 Unauthorized`.

---

## 3. Autorisation de paiement

### Champs disponibles

| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `pan` | string | ✓ | Numéro de carte (PAN 13–19 chiffres) |
| `amount` | integer | ✓ | Montant en centimes (ex: 5000 = 50,00€) |
| `currency` | string | ✓ | Code ISO 4217 (978=EUR, 840=USD, 826=GBP) |
| `transaction_type` | string | ✓ | 00=Achat, 01=Retrait, 20=Remboursement, 10=Préauth |
| `terminal_id` | string | ✓ | Identifiant du terminal (8 car.) |
| `merchant_id` | string | ✓ | Identifiant du commerçant |
| `pos_entry_mode` | string | — | Mode de saisie POS (051=puce, 071=NFC, 010=mag) |
| `mcc` | string | — | Code MCC du commerçant |
| `expiry_date` | string | — | Date d'expiration YYMM |
| `cvv2` | string | — | Code CVV2 à 3 chiffres |
| `pin_block_hex` | string | — | Bloc PIN chiffré (hex) |
| `field_55_hex` | string | — | Données EMV champ 55 (hex TLV) |
| `atc` | integer | — | Application Transaction Counter (EMV) |
| `arqc_hex` | string | — | ARQC à vérifier (hex) |

### Exemples par type de transaction

#### Achat puce contact
```bash
curl -s -X POST http://localhost:5000/api/v1/authorize \
  -H "Content-Type: application/json" \
  -d '{
    "pan": "4111111111111111",
    "amount": 12000,
    "currency": "978",
    "transaction_type": "00",
    "terminal_id": "TERM0001",
    "merchant_id": "SUPERMARCHE01",
    "pos_entry_mode": "051",
    "mcc": "5411",
    "expiry_date": "2812"
  }'
```

#### Paiement sans contact NFC
```bash
curl -s -X POST http://localhost:5000/api/v1/authorize \
  -H "Content-Type: application/json" \
  -d '{
    "pan": "4970100000000154",
    "amount": 2500,
    "currency": "978",
    "transaction_type": "00",
    "terminal_id": "TERM_NFC",
    "merchant_id": "BOULANGERIE",
    "pos_entry_mode": "071",
    "mcc": "5814"
  }'
```

#### Remboursement
```bash
curl -s -X POST http://localhost:5000/api/v1/authorize \
  -H "Content-Type: application/json" \
  -d '{
    "pan": "4111111111111111",
    "amount": 5000,
    "currency": "978",
    "transaction_type": "20",
    "terminal_id": "TERM0001",
    "merchant_id": "MERCH001",
    "pos_entry_mode": "010"
  }'
```

### Réponse d'autorisation

```json
{
  "approved": true,
  "response_code": "00",
  "response_message": "Approved",
  "transaction_id": "TXN-20260503-001",
  "rrn": "260503123456",
  "auth_code": "A12345",
  "amount": 12000,
  "currency": "978",
  "timestamp": "2026-05-03T11:30:00Z",
  "cb_scheme": "VISA",
  "auth_path": "ONLINE",
  "risk_score": 25,
  "token_used": false
}
```

---

## 4. 3-D Secure 2.x (3DS2)

### Flux complet 3DS2

#### Étape 1 — Initier l'authentification

```bash
curl -s -X POST http://localhost:5000/api/v1/3ds/authenticate \
  -H "Content-Type: application/json" \
  -d '{
    "pan": "4111111111111111",
    "amount": 20000,
    "currency": "978",
    "merchant_id": "SHOP_ONLINE",
    "notification_url": "https://shop.example.com/3ds/callback",
    "device_channel": "02"
  }'
```

**Cas frictionless** (montant ≤ 30€, historique favorable) :
```json
{
  "threeds_id": "3DS-abc123",
  "status": "FRICTIONLESS",
  "eci": "05",
  "cavv": "AABBCCDD...",
  "acs_url": null
}
```

**Cas challenge** (montant élevé ou risque) :
```json
{
  "threeds_id": "3DS-def456",
  "status": "CHALLENGE_REQUIRED",
  "acs_url": "https://acs.bank.fr/challenge",
  "threeds_id": "3DS-def456"
}
```

#### Étape 2 — Soumettre le challenge OTP

```bash
curl -s -X POST http://localhost:5000/api/v1/3ds/3DS-def456/challenge \
  -H "Content-Type: application/json" \
  -d '{"otp": "1234"}'
```

```json
{
  "status": "AUTHENTICATED",
  "eci": "05",
  "cavv": "AABBCCDD..."
}
```

#### Étape 3 — Consulter une session 3DS2

```bash
curl -s http://localhost:5000/api/v1/3ds/3DS-def456
```

### Exemptions SCA DSP2

| Code | Nom | Condition |
|------|-----|-----------|
| `LVP` | Low Value Payment | Montant ≤ 30€ |
| `MIT` | Merchant Initiated | Transaction récurrente commerçant |
| `TRA` | Transaction Risk Analysis | Montant ≤ 250€, historique favorable |
| `TTP` | Trusted Third Party | Bénéficiaire de confiance |

### Statistiques 3DS2

```bash
curl -s http://localhost:5000/api/v1/3ds/stats
```

---

## 5. Tokenisation HCE/NFC (CB-PAY)

### Créer un token

```bash
curl -s -X POST http://localhost:5000/api/v1/tokens \
  -H "Content-Type: application/json" \
  -d '{
    "pan": "4111111111111111",
    "domain": "HCE_MOBILE",
    "requestor_id": "CBPAY_APP_V2",
    "max_uses": 50
  }'
```

Domaines disponibles : `HCE_MOBILE`, `ECOMMERCE`, `WALLET`, `ANY`

```json
{
  "token_id": "tok-uuid-123",
  "token": "4999123456789012",
  "status": "ACTIVE",
  "domain": "HCE_MOBILE",
  "created_at": "2026-05-03T11:00:00Z"
}
```

### Payer avec un token

Le token est utilisé comme un PAN normal. La détokenisation est transparente.

```bash
curl -s -X POST http://localhost:5000/api/v1/authorize \
  -H "Content-Type: application/json" \
  -d '{
    "pan": "4999123456789012",
    "amount": 1500,
    "currency": "978",
    "transaction_type": "00",
    "terminal_id": "TERM_NFC",
    "merchant_id": "MERCH_NFC",
    "pos_entry_mode": "071"
  }'
```

### Gestion du cycle de vie

```bash
# Suspendre
curl -s -X POST http://localhost:5000/api/v1/tokens/tok-uuid-123/suspend

# Réactiver
curl -s -X POST http://localhost:5000/api/v1/tokens/tok-uuid-123/resume

# Supprimer
curl -s -X DELETE http://localhost:5000/api/v1/tokens/tok-uuid-123

# Tokens pour un PAN
curl -s http://localhost:5000/api/v1/tokens/pan/4111111111111111

# Statistiques
curl -s http://localhost:5000/api/v1/tokens/stats
```

---

## 6. Règles GIE CB

### Routage domestique

```bash
curl -s -X POST http://localhost:5000/api/v1/cb/routing \
  -H "Content-Type: application/json" \
  -d '{"pan": "4111111111111111", "country_code": "250"}'
```

```json
{
  "preferred_network": "CB",
  "actual_scheme": "VISA",
  "routing_reason": "Routage CB national prioritaire (pays=250, scheme=VISA)",
  "is_domestic": true
}
```

### Vérification vélocité

```bash
curl -s -X POST http://localhost:5000/api/v1/cb/velocity \
  -H "Content-Type: application/json" \
  -d '{
    "amount": 1000,
    "transaction_type": "00",
    "recent_transactions": [
      {"timestamp": "2026-05-03T10:45:00Z", "amount": 500, "type": "00"},
      {"timestamp": "2026-05-03T10:50:00Z", "amount": 750, "type": "00"}
    ]
  }'
```

### Vérification MCC

```bash
# MCC autorisé
curl -s -X POST http://localhost:5000/api/v1/cb/mcc-check \
  -H "Content-Type: application/json" \
  -d '{"mcc": "5411"}'

# MCC bloqué (jeux d'argent)
curl -s -X POST http://localhost:5000/api/v1/cb/mcc-check \
  -H "Content-Type: application/json" \
  -d '{"mcc": "7995"}'
```

### Statut PIN

```bash
curl -s -X POST http://localhost:5000/api/v1/cb/pin-status \
  -H "Content-Type: application/json" \
  -d '{"pin_tries_remaining": 1}'
```

### Indicateurs de service CB

```bash
curl -s http://localhost:5000/api/v1/cb/service-indicators
```

---

## 7. PKI et authentification offline (DDA/CDA)

### Obtenir les certificats PKI d'une carte

```bash
curl -s http://localhost:5000/api/v1/pki/4111111111111111 | python -m json.tool
```

Retourne la chaîne : **CA Root → Issuer → ICC** avec les tags EMV (0x8F, 0x90, 0x9F32, etc.)

### Signature DDA

```bash
curl -s -X POST http://localhost:5000/api/v1/dda/sign \
  -H "Content-Type: application/json" \
  -d '{
    "pan": "4111111111111111",
    "data_to_sign_hex": "0102030405060708090A0B0C0D0E0F10"
  }'
```

### Vérification DDA

```bash
curl -s -X POST http://localhost:5000/api/v1/dda/verify \
  -H "Content-Type: application/json" \
  -d '{
    "pan": "4111111111111111",
    "sdad_hex": "...",
    "unpredictable_number_hex": "A1B2C3D4"
  }'
```

### Signature CDA (avec ARQC)

```bash
curl -s -X POST http://localhost:5000/api/v1/cda/sign \
  -H "Content-Type: application/json" \
  -d '{
    "pan": "4111111111111111",
    "data_to_sign_hex": "0102030405060708090A0B0C0D0E0F10",
    "arqc_hex": "AABBCCDDEEFF0011"
  }'
```

---

## 8. Préautorisations et captures

### Créer une préautorisation

```bash
curl -s -X POST http://localhost:5000/api/v1/preauthorizations \
  -H "Content-Type: application/json" \
  -d '{
    "pan": "5500000000000004",
    "amount": 20000,
    "currency": "978",
    "terminal_id": "HOTEL001",
    "merchant_id": "HOTEL_PARIS",
    "mcc": "7011"
  }'
```

### Capturer une préautorisation

```bash
curl -s -X POST http://localhost:5000/api/v1/preauthorizations/{id}/capture \
  -H "Content-Type: application/json" \
  -d '{"amount": 18500}'
```

### Annuler une préautorisation

```bash
curl -s -X POST http://localhost:5000/api/v1/preauthorizations/{id}/cancel
```

---

## 9. Chargebacks et litiges

### Créer un chargeback

```bash
curl -s -X POST http://localhost:5000/api/v1/transactions/{txn_id}/chargeback \
  -H "Content-Type: application/json" \
  -d '{
    "reason_code": "CB01",
    "amount": 5000,
    "description": "Transaction non reconnue par le porteur"
  }'
```

Codes motif disponibles : `CB01` (impayé), `CB02` (marchandise non reçue), `CB03` (annulation), etc.

### Consulter les chargebacks

```bash
curl -s http://localhost:5000/api/v1/chargebacks
```

### Résoudre un chargeback

```bash
curl -s -X POST http://localhost:5000/api/v1/chargebacks/{id}/resolve \
  -H "Content-Type: application/json" \
  -d '{"decision": "ACCEPTED", "notes": "Remboursement accordé"}'
```

---

## 10. Mode dégradé / Chaos Engineering

### Activer le mode dégradé

```bash
curl -s -X POST http://localhost:5000/api/v1/chaos/enable \
  -H "Content-Type: application/json" \
  -d '{
    "failure_rate": 0.3,
    "failure_types": ["TIMEOUT", "NETWORK_ERROR"],
    "latency_ms": 500
  }'
```

**Types de panne** : `TIMEOUT`, `NETWORK_ERROR`, `INTERNAL_ERROR`, `PARTIAL_FAILURE`, `SLOW_RESPONSE`

### Configurer par endpoint

```bash
curl -s -X POST http://localhost:5000/api/v1/chaos/endpoint \
  -H "Content-Type: application/json" \
  -d '{
    "endpoint_tag": "authorize",
    "failure_rate": 0.5,
    "failure_types": ["INTERNAL_ERROR"],
    "latency_ms": 200,
    "latency_jitter_ms": 100
  }'
```

### Consulter les statistiques

```bash
curl -s http://localhost:5000/api/v1/chaos/stats
```

### Désactiver / Réinitialiser

```bash
curl -s -X POST http://localhost:5000/api/v1/chaos/disable
curl -s -X POST http://localhost:5000/api/v1/chaos/reset
```

### Réponse en mode dégradé

Quand une panne est injectée, le serveur retourne :
```json
{
  "error": "mode_degrade",
  "failure_type": "TIMEOUT",
  "message": "Timeout réseau simulé — aucune réponse de l'émetteur",
  "endpoint": "authorize"
}
```
avec le code HTTP correspondant (503 pour timeout, 500 pour erreur interne).

---

## 11. Configuration YAML/TOML

### Fichier de configuration

Modifier `config.yaml` dans le répertoire racine :

```yaml
server:
  port: 5000
  debug: false

cb:
  contactless_single_limit: 5000   # 50€ en centimes
  low_value_threshold: 3000        # 30€

velocity:
  max_txn_per_30min: 10
  max_amount_per_hour: 200000

chaos:
  enabled: false
  failure_rate: 0.1
```

### Recharger la configuration à chaud

Sans redémarrer le serveur :

```bash
curl -s -X POST http://localhost:5000/api/v1/config/reload
```

```json
{
  "reloaded": true,
  "config_path": "config.yaml",
  "reload_count": 2
}
```

La configuration est aussi rechargée automatiquement dès qu'une modification du fichier est détectée (polling toutes les 10 secondes).

### Consulter la configuration active

```bash
curl -s http://localhost:5000/api/v1/config | python -m json.tool
```

Les valeurs sensibles (`api_key`, `password`, etc.) sont masquées : `[REDACTED]`.

### Surcharge par variables d'environnement

```bash
# Syntaxe : SECTION__CLE=valeur
export SERVER__PORT=9000
export CB__CONTACTLESS_SINGLE_LIMIT=3000
export CHAOS__ENABLED=true
```

---

## 12. HSM — Protection des clés

### Consulter le statut du HSM

```bash
curl -s http://localhost:5000/api/v1/hsm/status | python -m json.tool
```

```json
{
  "initialized": true,
  "keys_loaded": 5,
  "keys_active": 5,
  "kek_algorithm": "Fernet (AES-128-CBC + HMAC-SHA256)",
  "kek_ephemeral": true,
  "kek_persisted": false,
  "hsm_type": "Simulated HSM (Fernet KEK)",
  "compliance": ["FIPS-140-2 compatible (simulation)", "PCI-DSS key protection"]
}
```

### Inventaire des clés

```bash
curl -s http://localhost:5000/api/v1/hsm/keys | python -m json.tool
```

Retourne les métadonnées des clés (ID, type, date de chargement, compteur d'usages) sans jamais exposer les valeurs.

### Rotation de la KEK

```bash
curl -s -X POST http://localhost:5000/api/v1/hsm/rotate-kek
```

Re-chiffre toutes les clés avec une nouvelle KEK éphémère. Opération atomique et transparente.

### Journal d'accès HSM

```bash
curl -s http://localhost:5000/api/v1/hsm/access-log | python -m json.tool
```

---

## 13. Cache distribué

### Statut du cache

```bash
curl -s http://localhost:5000/api/v1/cache/stats | python -m json.tool
```

**Mode in-memory** (par défaut) :
```json
{
  "backend": "in_memory",
  "keys": 12,
  "hits": 450,
  "misses": 23,
  "hit_rate": 0.951
}
```

**Mode Redis** (si `REDIS_URL` configuré) :
```json
{
  "backend": "redis",
  "version": "7.2.0",
  "connected_clients": 3,
  "used_memory_human": "2.5M"
}
```

### Configurer Redis

```bash
export REDIS_URL="redis://localhost:6379/0"
# ou avec authentification :
export REDIS_URL="redis://:password@redis-host:6379/0"
```

### Vider le cache

```bash
# Tout vider
curl -s -X DELETE http://localhost:5000/api/v1/cache/flush

# Vider un préfixe
curl -s -X DELETE "http://localhost:5000/api/v1/cache/flush?prefix=3ds"
```

---

## 14. Monitoring et statistiques

### Statistiques globales

```bash
curl -s http://localhost:5000/api/v1/stats | python -m json.tool
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

### Historique des transactions

```bash
# Liste complète
curl -s http://localhost:5000/api/v1/transactions

# Par PAN
curl -s http://localhost:5000/api/v1/transactions/pan/4111111111111111

# Par RRN
curl -s http://localhost:5000/api/v1/transactions/rrn/260503123456

# Recherche avancée
curl -s -X POST http://localhost:5000/api/v1/transactions/search \
  -H "Content-Type: application/json" \
  -d '{
    "min_amount": 5000,
    "max_amount": 50000,
    "response_code": "00",
    "from_date": "2026-05-01"
  }'

# Export CSV
curl -s http://localhost:5000/api/v1/transactions/export > transactions.csv
```

### Documentation interactive

```bash
# Interface Swagger UI
open http://localhost:5000/api/docs

# Spec OpenAPI JSON
curl -s http://localhost:5000/api/v1/openapi.json | python -m json.tool
```

---

## 15. Cartes de test

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

## 16. Codes réponse

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

## Annexe — Jeu d'essai automatisé

```bash
# Lister les scénarios disponibles
python tools/load_test_data.py --list

# Exécuter tous les scénarios
python tools/load_test_data.py --url http://localhost:5000

# Exécuter un scénario spécifique
python tools/load_test_data.py --scenario SC01

# Avec authentification API
python tools/load_test_data.py --api-key "votre-cle"
```

---

*EMV Authorization Server v1.9.0 — GIE CB | EMV 4.3 | ISO 8583 | 3DS2 | HCE/NFC*
