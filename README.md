# EMV Authorization Server — v1.14.0

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0+-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

Un serveur d'autorisation de transactions bancaires ultra-complet, conforme aux spécifications **EMV 4.3** et aux règles du **GIE CB**. Conçu pour la simulation, le test et la certification de terminaux de paiement (TPE) et d'applications HCE.

## 🚀 Fonctionnalités Clés

### 💳 Core EMV & GIE CB
- **Moteur de règles GIE CB** : Identification AID/BIN, plafonds sans contact (NFC), cumuls hors ligne, SCA (DSP2), floor limits MCC.
- **Cryptographie EMV** : Vérification d'ARQC (SHA-1/DES), génération d'ARPC, support DDA/CDA.
- **Gestion des Cartes** : CRUD complet, blocage/déblocage, historique de cycle de vie.
- **Support Multi-Schéma** : CB, VISA, MasterCard, AMEX, Maestro.

### 📊 Persistance & Data
- **Persistance Hybride** : Basculement dynamique entre base de données (PostgreSQL/SQLite) et snapshots JSON compressés.
- **Statistiques SQL Optimisées** : Agrégations performantes et séries temporelles heure par heure pour le monitoring.
- **Backup & Recovery** : Snapshots automatiques avec système de rétention et import assisté.

### 🛠️ Outils de Test & Certification
- **Simulateur de Certification GIE CB** : Moteur d'exécution de scénarios automatisés (Cumul CL, ARQC invalide, etc.).
- **Simulateur de Terminal** : Client TCP ISO 8583 pour simuler des flux réels de terminaux.
- **Dashboard Web** : Interface de monitoring en temps réel avec graphiques (SSE).

### 🛡️ Sécurité & API
- **Sécurité** : Authentification par API Key, Rate Limiting, HSM simulé pour le chiffrement des clés en RAM.
- **API REST & TCP** : Interface double (JSON REST et ISO 8583 TCP port 8583).
- **Audit Log** : Journalisation détaillée par transaction avec masquage automatique des PANs.

## 📦 Installation

```bash
# Cloner le dépôt
git clone https://github.com/Sabbadie/emv-authorization-server.git
cd emv-authorization-server

# Installer les dépendances
pip install -r requirements.txt

# Configurer l'environnement (optionnel)
cp .env.example .env

# Lancer le serveur
python main.py
```

## 🔌 API Quick Start

### Autorisation Simple (REST)
`POST /api/v1/authorize`
```json
{
  "pan": "4111111111111111",
  "amount": 5000,
  "currency": "978",
  "transaction_type": "00"
}
```

### Lancer un scénario de certification
`POST /api/v1/certification/run/CL_CUMUL_LIMIT`

## 🧪 Tests

Le projet inclut une suite exhaustive de plus de **1720 tests unitaires et d'intégration**.
```bash
pytest
```

## 📝 Documentation
- [AVANCEMENT.md](./AVANCEMENT.md) : Suivi détaillé des fonctionnalités et roadmap.
- [GUIDE_UTILISATEUR.md](./GUIDE_UTILISATEUR.md) : Documentation complète de l'utilisateur.

---
© 2026 EMV Authorization Server — Produit par Sabbadie.
