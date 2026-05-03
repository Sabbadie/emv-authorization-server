# Serveur d'Autorisation EMV

Un serveur d'autorisation EMV complet conforme aux normes EMV 4.3 et ISO 8583, développé en Python/Flask.
Supporte deux interfaces de connexion : REST HTTP (port 5000) et TCP ISO 8583 (port 8583).

## Architecture

```
emv-auth-server/
├── main.py                 # Point d'entrée (HTTP + TCP)
├── server.py               # API REST Flask + tableau de bord
├── config.py               # Configuration (clés, limites, ports)
├── emv/
│   ├── tlv.py              # Parser/encodeur BER-TLV
│   ├── crypto.py           # Opérations cryptographiques (ARQC/ARPC, 3DES)
│   ├── authorization.py    # Logique d'autorisation principale
│   ├── amount_rules.py     # Règles par tranches (6 tranches)
│   ├── giecb.py            # Règles réseau GIE CB
│   ├── cvv.py              # Calcul/vérification CVV/CVV2/iCVV
│   └── tcp_server.py       # Serveur TCP ISO 8583 (terminaux)
├── iso8583/
│   └── message.py          # Traitement des messages ISO 8583
├── models/
│   ├── card.py             # Modèle carte et base de données en mémoire
│   ├── transaction.py      # Modèle transaction et journal
│   └── tpa_response.py     # Décomposition réponse TPA (champs F00–FEn)
├── tools/
│   └── terminal_simulator.py  # Exemple de client TCP (simulateur terminal)
└── tests/
    ├── test_tcp_server.py  # Tests interface TCP
    ├── test_api.py         # Tests API REST
    └── ...                 # 12 fichiers de tests (739 tests)
```

## Deux interfaces de connexion

### 1. API REST HTTP (port 5000)
Idéale pour les applications web, intégrations backend, outils de monitoring.

### 2. Interface TCP ISO 8583 (port 8583)
Idéale pour les **simulateurs de terminaux de paiement**, les tests de connexion réseau
bout-en-bout et les environnements de certification.

---

## Interface TCP — Comment connecter un terminal

### Protocole fil de fer

Chaque message (requête et réponse) est précédé d'un **préfixe de 4 octets** (big-endian)
indiquant la longueur du corps JSON :

```
┌───────────────────────────────────────────────────────────┐
│  [4 octets big-endian : longueur du corps]                │
│  [corps UTF-8 JSON]                                       │
└───────────────────────────────────────────────────────────┘
```

### Format de requête — Format natif (recommandé)

```json
{
  "pan":              "4111111111111111",
  "amount":           5000,
  "currency":         "978",
  "transaction_type": "00",
  "terminal_id":      "TERM0001",
  "merchant_id":      "MERCH0001",
  "merchant_name":    "MA BOUTIQUE",
  "is_contactless":   false,
  "pos_entry_mode":   "05",
  "skip_crypto":      true
}
```

### Format de requête — ISO 8583 dict (MTI 0100)

```json
{
  "mti": "0100",
  "fields": {
    "2":  "4111111111111111",
    "3":  "000000",
    "4":  "000000005000",
    "7":  "0523143015",
    "11": "000042",
    "22": "051",
    "37": "123456789012",
    "41": "TERM0001",
    "49": "978"
  }
}
```

### Format de réponse

```json
{
  "mti":            "0110",
  "approved":       true,
  "response_code":  "00",
  "auth_code":      "123456",
  "amount":         5000,
  "currency":       "978",
  "pan_masked":     "411111****1111",
  "transaction_id": "txn-uuid-...",
  "tier":           "SMALL",
  "cb_allowed":     true,
  "message":        "Approuvée"
}
```

### Exemple Python minimal

```python
import json, socket, struct

def send_recv(host, port, payload):
    body = json.dumps(payload).encode()
    sock = socket.create_connection((host, port), timeout=5)
    sock.sendall(struct.pack(">I", len(body)) + body)
    hdr = sock.recv(4)
    n = struct.unpack(">I", hdr)[0]
    data = b""
    while len(data) < n:
        data += sock.recv(n - len(data))
    sock.close()
    return json.loads(data)

resp = send_recv("localhost", 8583, {
    "pan": "4111111111111111",
    "amount": 5000,
    "currency": "978",
    "transaction_type": "00",
    "skip_crypto": True,
})
print(resp)
# → {"mti": "0110", "approved": True, "response_code": "00", ...}
```

### Utiliser le simulateur de terminal fourni

```bash
# Achat simple
python tools/terminal_simulator.py --scenario basic

# Paiement sans contact NFC
python tools/terminal_simulator.py --scenario contactless

# Achat avec données EMV (champ 55)
python tools/terminal_simulator.py --scenario emv

# Requête ISO 8583 dict (MTI 0100)
python tools/terminal_simulator.py --scenario iso8583

# Lot de 10 transactions variées
python tools/terminal_simulator.py --scenario batch

# Mode interactif (saisie JSON libre)
python tools/terminal_simulator.py --scenario interactive

# Serveur distant
python tools/terminal_simulator.py --host 192.168.1.10 --port 8583 --scenario batch
```

---

## API REST HTTP

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `POST` | `/api/v1/authorize` | Demande d'autorisation EMV |
| `GET`  | `/api/v1/transactions` | Liste des transactions |
| `GET`  | `/api/v1/transactions/export` | Export CSV/JSON |
| `GET`  | `/api/v1/cards` | Liste des cartes |
| `POST` | `/api/v1/cards` | Créer une carte |
| `POST` | `/api/v1/cards/<pan>/block` | Bloquer une carte |
| `POST` | `/api/v1/cards/<pan>/unblock` | Débloquer une carte |
| `GET`  | `/api/v1/stats` | Statistiques serveur |
| `GET`  | `/api/v1/health` | Santé du serveur |
| `GET`  | `/api/v1/amount-tiers` | Tranches de montants |
| `GET`  | `/api/v1/amount-tiers/evaluate` | Évaluer un montant |
| `POST` | `/api/v1/batch/simulate` | Simulation en lot |
| `GET`  | `/api/v1/cvv/generate` | Générer CVV/CVV2/iCVV |
| `POST` | `/api/v1/cvv/verify` | Vérifier un CVV |
| `POST` | `/api/v1/tlv/parse` | Décodage BER-TLV |
| `GET`  | `/api/v1/giecb/rules` | Règles GIE CB |
| `POST` | `/api/v1/giecb/evaluate` | Évaluer règles CB |
| `GET`  | `/api/v1/tpa/fields` | Champs TPA |

---

## Variables d'environnement

| Variable | Défaut | Description |
|----------|--------|-------------|
| `PORT` | `5000` | Port HTTP REST |
| `TCP_PORT` | `8583` | Port TCP ISO 8583 |
| `TCP_ENABLED` | `true` | Activer l'interface TCP |
| `HOST` | `0.0.0.0` | Adresse d'écoute |
| `EMV_API_KEY` | *(vide)* | Clé API pour sécuriser REST |
| `MDK_AC` | *(test)* | Master Derived Key AC |
| `CVK1` / `CVK2` | *(test)* | Clés CVV |
| `SNAPSHOT_ENABLED` | `true` | Backup JSON périodique |
| `DEBUG` | `false` | Mode debug Flask |

---

## Cartes de test

| PAN | Statut | Scénario |
|-----|--------|----------|
| `4111111111111111` | ACTIVE | Approbation normale (VISA, solde 5000€) |
| `5500000000000004` | ACTIVE | Limite élevée (MC, solde 10000€) |
| `4000000000000002` | ACTIVE | Solde modéré (VISA, solde 2500€) |
| `4970100000000154` | ACTIVE | Carte CB native (AID A0000000421010) |
| `4000000000000036` | ACTIVE | Provision insuffisante (solde 1€) |
| `4000000000000028` | BLOCKED | Carte bloquée → RC 62 |
| `4000000000000010` | ACTIVE | Carte expirée (2112) → RC 54 |

---

## Tranches de montants (règles GIE CB)

| Tranche | Plage (centimes) | Chemin | Risque |
|---------|-----------------|--------|--------|
| MICRO | 1 – 500 | OFFLINE | LOW |
| SMALL | 501 – 5 000 | OFFLINE | LOW |
| STANDARD | 5 001 – 15 000 | ONLINE | MEDIUM |
| HIGH | 15 001 – 50 000 | ONLINE | HIGH |
| VERY_HIGH | 50 001 – 500 000 | ONLINE + ARQC | VERY_HIGH |
| CRITICAL | > 500 000 | REFERRAL | CRITICAL |

---

## Fonctionnalités

### Cryptographie EMV
- Dérivation UDK + clés de session par ATC
- Vérification ARQC (3DES CBC-MAC)
- Génération ARPC (Method 1) + Issuer Authentication Data (tag 91)

### Traitement ISO 8583
- Messages 0100/0110 (JSON-framed TCP ou HTTP)
- Parsing champ 55 (BER-TLV)
- Codes de réponse standard

### Règles GIE CB
- Identification réseau (VISA / MC / CB / AMEX)
- Limites sans contact (cumul, compteur offline)
- SCA exemptions (CBPII, low-value, TRA)
- Floor limits par MCC

### Tableau de bord
- Interface web française en temps réel (port 5000)
- Graphiques, export CSV, simulation batch, mode sombre

---

## Dépendances

- **Flask 3.x** + **flask-limiter** : API REST + rate limiting
- **pycryptodome** : Cryptographie 3DES/DES (ARQC/ARPC)
- **Python 3.11**

## Standards implémentés

- EMV 4.3 (Book 1, 2, 3)
- ISO 8583 Financial Transaction Messages
- ISO 9564 PIN Management
- BER-TLV encoding (ISO 8825-1)
- Spécifications GIE Cartes Bancaires
