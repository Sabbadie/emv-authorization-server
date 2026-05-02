# Serveur d'Autorisation EMV

Un serveur d'autorisation EMV complet conforme aux normes EMV 4.3 et ISO 8583, développé en Python/Flask.

## Architecture

```
emv-auth-server/
├── main.py                 # Point d'entrée
├── server.py               # API REST Flask + tableau de bord
├── config.py               # Configuration (clés, limites, codes)
├── emv/
│   ├── tlv.py              # Parser/encodeur BER-TLV
│   ├── crypto.py           # Opérations cryptographiques (ARQC/ARPC, 3DES)
│   ├── data_elements.py    # Définitions des tags EMV
│   └── authorization.py   # Logique d'autorisation principale
├── iso8583/
│   └── message.py          # Traitement des messages ISO 8583
└── models/
    ├── card.py             # Modèle carte et base de données en mémoire
    └── transaction.py      # Modèle transaction et journal
```

## Fonctionnalités

### Cryptographie EMV
- **Dérivation de clés UDK** : Unique Derived Key par PAN + PSN
- **Dérivation de clés de session** : Basée sur l'ATC (Application Transaction Counter)
- **Vérification ARQC** : Application Request Cryptogram via 3DES CBC-MAC
- **Génération ARPC** : Authorization Response Cryptogram (Method 1)
- **Issuer Authentication Data** : Tag 91 pour l'authentification en ligne

### Traitement ISO 8583
- Messages d'autorisation 0100/0110
- Parsing du champ 55 (données EMV)
- Gestion des codes de réponse standard

### Décodage TLV
- Parser BER-TLV conforme EMV
- Support des tags multi-octets
- Extraction des éléments de données EMV

### Logique d'autorisation
- Validation du statut de carte (active, bloquée, expirée, perdue, volée)
- Vérification des fonds disponibles
- Contrôle des limites journalières
- Détection de rejeu ATC
- Analyse des TVR (Terminal Verification Results)
- Vérification cryptographique ARQC
- Génération de codes d'autorisation

## API REST

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `POST` | `/api/v1/authorize` | Demande d'autorisation EMV |
| `POST` | `/api/v1/authorize/iso8583` | Autorisation via message ISO 8583 |
| `POST` | `/api/v1/tlv/parse` | Décodage BER-TLV |
| `GET`  | `/api/v1/transactions` | Liste des transactions |
| `GET`  | `/api/v1/transactions/<id>` | Détail d'une transaction |
| `GET`  | `/api/v1/cards` | Liste des cartes |
| `POST` | `/api/v1/cards` | Créer une carte |
| `POST` | `/api/v1/cards/<pan>/block` | Bloquer une carte |
| `GET`  | `/api/v1/stats` | Statistiques |
| `GET`  | `/api/v1/health` | Santé du serveur |

## Exemple d'utilisation

### Autorisation simple
```json
POST /api/v1/authorize
{
  "pan": "4111111111111111",
  "amount": 5000,
  "currency": "978",
  "transaction_type": "00",
  "terminal_id": "TERM0001",
  "skip_crypto": true
}
```

### Autorisation avec données EMV (champ 55)
```json
POST /api/v1/authorize
{
  "pan": "4111111111111111",
  "amount": 10000,
  "currency": "840",
  "transaction_type": "00",
  "field_55": "9F2608...<hex>...",
  "terminal_id": "TERM0001"
}
```

## Cartes de test

| PAN | Statut | Scénario |
|-----|--------|----------|
| 4111111111111111 | ACTIVE | Approbation normale |
| 5500000000000004 | ACTIVE | Limite élevée |
| 4000000000000002 | ACTIVE | Solde modéré |
| 4000000000000036 | ACTIVE | Provision insuffisante |
| 4000000000000028 | BLOCKED | Carte bloquée |
| 4000000000000010 | ACTIVE | Carte expirée (2112) |

## Dépendances

- **Flask 3.x** : Serveur web
- **pycryptodome** : Cryptographie 3DES/DES pour ARQC/ARPC
- **Python 3.11**

## Standards implémentés

- EMV 4.3 (Book 1, Book 2, Book 3)
- ISO 8583 Financial Transaction Messages
- ISO 9564 PIN Management
- BER-TLV encoding (ISO 8825-1)
