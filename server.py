"""
EMV Authorization Server - Flask REST API
"""

import logging
import json
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string

from emv.authorization import authorize
from emv.tlv import parse, extract_emv_fields, encode, tlv_list_to_hex
from iso8583.message import ISO8583Message, parse_from_dict, build_authorization_request
from models.card import card_db, Card, CardStatus
from models.transaction import transaction_log
from config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["SECRET_KEY"] = Config.SECRET_KEY
app.config["JSON_SORT_KEYS"] = False

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Serveur d'Autorisation EMV</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Segoe UI', sans-serif; background: #0f1117; color: #e2e8f0; min-height: 100vh; }
        .header {
            background: linear-gradient(135deg, #1a1f2e 0%, #16213e 100%);
            border-bottom: 1px solid #2d3748;
            padding: 20px 40px;
            display: flex; align-items: center; gap: 16px;
        }
        .header .logo {
            width: 48px; height: 48px;
            background: linear-gradient(135deg, #667eea, #764ba2);
            border-radius: 12px;
            display: flex; align-items: center; justify-content: center;
            font-size: 24px;
        }
        .header h1 { font-size: 22px; font-weight: 700; color: #fff; }
        .header p { color: #94a3b8; font-size: 13px; margin-top: 2px; }
        .badge {
            margin-left: auto;
            background: #10b981;
            color: #fff;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            display: flex; align-items: center; gap: 6px;
        }
        .badge::before { content: ''; width: 8px; height: 8px; background: #fff; border-radius: 50%; animation: pulse 2s infinite; }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
        .container { max-width: 1200px; margin: 0 auto; padding: 30px 20px; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px,1fr)); gap: 16px; margin-bottom: 30px; }
        .stat-card {
            background: #1a1f2e;
            border: 1px solid #2d3748;
            border-radius: 12px;
            padding: 20px;
        }
        .stat-card .label { color: #94a3b8; font-size: 12px; text-transform: uppercase; letter-spacing: .5px; }
        .stat-card .value { font-size: 28px; font-weight: 700; color: #fff; margin: 8px 0 4px; }
        .stat-card .sub { color: #64748b; font-size: 13px; }
        .stat-card.green .value { color: #10b981; }
        .stat-card.blue .value { color: #60a5fa; }
        .stat-card.purple .value { color: #a78bfa; }
        .stat-card.orange .value { color: #f59e0b; }
        .section { background: #1a1f2e; border: 1px solid #2d3748; border-radius: 12px; margin-bottom: 24px; overflow: hidden; }
        .section-header { padding: 16px 24px; border-bottom: 1px solid #2d3748; display: flex; align-items: center; gap: 10px; }
        .section-header h2 { font-size: 15px; font-weight: 600; color: #fff; }
        .section-header .count { background: #2d3748; color: #94a3b8; font-size: 12px; padding: 2px 8px; border-radius: 10px; }
        .endpoint-list { padding: 0; }
        .endpoint { display: flex; align-items: flex-start; gap: 12px; padding: 14px 24px; border-bottom: 1px solid #1e2433; }
        .endpoint:last-child { border-bottom: none; }
        .method {
            font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 6px;
            min-width: 52px; text-align: center; flex-shrink: 0; margin-top: 1px;
        }
        .method.POST { background: #1a3a2a; color: #34d399; border: 1px solid #065f46; }
        .method.GET { background: #1a2a3a; color: #60a5fa; border: 1px solid #1e40af; }
        .method.DELETE { background: #3a1a1a; color: #f87171; border: 1px solid #991b1b; }
        .endpoint-path { font-family: monospace; color: #a78bfa; font-size: 13px; font-weight: 600; }
        .endpoint-desc { color: #64748b; font-size: 12px; margin-top: 3px; }
        .try-btn {
            margin-left: auto; flex-shrink: 0;
            background: #2d3748; color: #94a3b8; border: none;
            padding: 5px 12px; border-radius: 6px; font-size: 12px; cursor: pointer;
        }
        .try-btn:hover { background: #374151; color: #e2e8f0; }
        .demo-section { padding: 24px; }
        .demo-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        @media (max-width: 768px) { .demo-grid { grid-template-columns: 1fr; } }
        label { display: block; color: #94a3b8; font-size: 12px; margin-bottom: 6px; font-weight: 500; }
        input, select, textarea {
            width: 100%; background: #0f1117; border: 1px solid #2d3748; color: #e2e8f0;
            border-radius: 8px; padding: 9px 12px; font-size: 13px; font-family: inherit;
        }
        input:focus, select:focus, textarea:focus { outline: none; border-color: #667eea; }
        .form-group { margin-bottom: 14px; }
        .btn {
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: #fff; border: none; padding: 11px 24px; border-radius: 8px;
            font-size: 14px; font-weight: 600; cursor: pointer; width: 100%; margin-top: 4px;
        }
        .btn:hover { opacity: .9; }
        .btn:disabled { opacity: .5; cursor: not-allowed; }
        .result-box {
            background: #0f1117; border: 1px solid #2d3748; border-radius: 8px;
            padding: 16px; font-family: monospace; font-size: 12px;
            color: #94a3b8; min-height: 200px; white-space: pre-wrap; word-break: break-all;
            max-height: 400px; overflow-y: auto;
        }
        .result-box.approved { border-color: #10b981; color: #34d399; }
        .result-box.declined { border-color: #ef4444; color: #f87171; }
        .result-box.error { border-color: #f59e0b; color: #fbbf24; }
        .tabs { display: flex; gap: 4px; padding: 16px 24px 0; border-bottom: 1px solid #2d3748; }
        .tab {
            padding: 8px 16px; border-radius: 8px 8px 0 0; font-size: 13px; cursor: pointer;
            color: #64748b; background: transparent; border: none; border-bottom: 2px solid transparent;
        }
        .tab.active { color: #a78bfa; border-bottom-color: #a78bfa; background: #1a1520; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .txn-table { width: 100%; border-collapse: collapse; }
        .txn-table th { color: #64748b; font-size: 11px; text-transform: uppercase; padding: 10px 16px; text-align: left; border-bottom: 1px solid #2d3748; }
        .txn-table td { padding: 12px 16px; font-size: 13px; border-bottom: 1px solid #1e2433; }
        .txn-table tr:last-child td { border-bottom: none; }
        .txn-table tr:hover td { background: #151b2b; }
        .status-badge { padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
        .status-badge.APPROVED { background: #052e16; color: #34d399; border: 1px solid #065f46; }
        .status-badge.DECLINED { background: #2d0f0f; color: #f87171; border: 1px solid #991b1b; }
        .status-badge.ERROR { background: #2d1f0a; color: #fbbf24; border: 1px solid #92400e; }
        .card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px,1fr)); gap: 16px; padding: 24px; }
        .card-item {
            background: linear-gradient(135deg, #1e2a3a 0%, #1a2030 100%);
            border: 1px solid #2d3748; border-radius: 12px; padding: 16px;
        }
        .card-item .pan { font-family: monospace; font-size: 14px; color: #a78bfa; letter-spacing: 2px; }
        .card-item .name { color: #e2e8f0; font-weight: 600; margin: 8px 0 4px; }
        .card-item .details { color: #64748b; font-size: 12px; }
        .card-item .balance { color: #34d399; font-size: 18px; font-weight: 700; margin-top: 12px; }
        .refresh-btn { background: #2d3748; color: #94a3b8; border: none; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 12px; }
        .refresh-btn:hover { background: #374151; color: #e2e8f0; }
    </style>
</head>
<body>
<div class="header">
    <div class="logo">💳</div>
    <div>
        <h1>Serveur d'Autorisation EMV</h1>
        <p>ISO 8583 · EMV 4.3 · Vérification ARQC · Génération ARPC</p>
    </div>
    <div class="badge">En ligne</div>
</div>

<div class="container">
    <div class="stats-grid" id="statsGrid">
        <div class="stat-card blue">
            <div class="label">Transactions totales</div>
            <div class="value" id="statTotal">–</div>
            <div class="sub">depuis le démarrage</div>
        </div>
        <div class="stat-card green">
            <div class="label">Approuvées</div>
            <div class="value" id="statApproved">–</div>
            <div class="sub" id="statRate">taux d'approbation</div>
        </div>
        <div class="stat-card orange">
            <div class="label">Refusées</div>
            <div class="value" id="statDeclined">–</div>
            <div class="sub">transactions refusées</div>
        </div>
        <div class="stat-card purple">
            <div class="label">Montant approuvé</div>
            <div class="value" id="statAmount">–</div>
            <div class="sub">montant total traité</div>
        </div>
    </div>

    <div class="section">
        <div class="tabs">
            <button class="tab active" onclick="showTab('demo')">Démo Interactive</button>
            <button class="tab" onclick="showTab('transactions')">Transactions <span id="txnCount"></span></button>
            <button class="tab" onclick="showTab('cards')">Cartes de test</button>
            <button class="tab" onclick="showTab('api')">API Endpoints</button>
        </div>

        <div id="tab-demo" class="tab-content active">
            <div class="demo-section">
                <div class="demo-grid">
                    <div>
                        <div class="form-group">
                            <label>Numéro de carte (PAN)</label>
                            <select id="panSelect" onchange="fillCard()">
                                <option value="4111111111111111">4111 1111 1111 1111 — JEAN DUPONT (Actif)</option>
                                <option value="5500000000000004">5500 0000 0000 0004 — MARIE MARTIN (Actif)</option>
                                <option value="4000000000000002">4000 0000 0000 0002 — AHMED BENALI (Actif)</option>
                                <option value="4000000000000036">4000 0000 0000 0036 — Provision insuffisante</option>
                                <option value="4000000000000028">4000 0000 0000 0028 — Carte bloquée</option>
                                <option value="4000000000000010">4000 0000 0000 0010 — Carte expirée</option>
                                <option value="custom">Numéro personnalisé...</option>
                            </select>
                        </div>
                        <div class="form-group" id="customPanGroup" style="display:none">
                            <label>Numéro de carte personnalisé</label>
                            <input type="text" id="customPan" placeholder="Ex: 4111111111111111" maxlength="19">
                        </div>
                        <div class="form-group">
                            <label>Montant (en centimes)</label>
                            <input type="number" id="amount" value="5000" min="1" placeholder="5000 = 50.00">
                        </div>
                        <div class="form-group">
                            <label>Code devise (ISO 4217)</label>
                            <select id="currency">
                                <option value="840">840 — USD</option>
                                <option value="978">978 — EUR</option>
                                <option value="826">826 — GBP</option>
                                <option value="504">504 — MAD</option>
                                <option value="788">788 — TND</option>
                                <option value="012">012 — DZD</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Type de transaction</label>
                            <select id="txnType">
                                <option value="00">00 — Achat</option>
                                <option value="01">01 — Avance de liquidités</option>
                                <option value="09">09 — Achat avec cashback</option>
                                <option value="20">20 — Remboursement</option>
                                <option value="22">22 — Consultation de solde</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Terminal ID</label>
                            <input type="text" id="terminalId" value="TERM0001" maxlength="8">
                        </div>
                        <div class="form-group">
                            <label>Données EMV (champ 55, hex optionnel)</label>
                            <textarea id="emvData" rows="3" placeholder="Laisser vide pour un test sans cryptogramme"></textarea>
                        </div>
                        <button class="btn" onclick="sendAuthorization()">Envoyer la demande d'autorisation →</button>
                    </div>
                    <div>
                        <label>Réponse du serveur</label>
                        <div class="result-box" id="resultBox">En attente d'une demande...</div>
                        <div style="margin-top:16px">
                            <label>Message ISO 8583 envoyé</label>
                            <div class="result-box" id="requestBox" style="min-height:120px">–</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <div id="tab-transactions" class="tab-content">
            <div style="padding:16px 24px;display:flex;justify-content:space-between;align-items:center">
                <span style="color:#64748b;font-size:13px">Dernières transactions</span>
                <button class="refresh-btn" onclick="loadTransactions()">↻ Actualiser</button>
            </div>
            <div style="overflow-x:auto">
                <table class="txn-table">
                    <thead>
                        <tr>
                            <th>RRN</th>
                            <th>Carte</th>
                            <th>Montant</th>
                            <th>Devise</th>
                            <th>Type</th>
                            <th>Statut</th>
                            <th>Code</th>
                            <th>Auth</th>
                            <th>Date/Heure</th>
                        </tr>
                    </thead>
                    <tbody id="txnTableBody">
                        <tr><td colspan="9" style="text-align:center;color:#64748b;padding:30px">Cliquez sur "Actualiser" pour charger les transactions</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <div id="tab-cards" class="tab-content">
            <div class="card-grid" id="cardGrid">
                <div style="grid-column:1/-1;text-align:center;color:#64748b;padding:30px">Chargement...</div>
            </div>
        </div>

        <div id="tab-api" class="tab-content">
            <div class="endpoint-list">
                <div class="endpoint">
                    <span class="method POST">POST</span>
                    <div>
                        <div class="endpoint-path">/api/v1/authorize</div>
                        <div class="endpoint-desc">Demande d'autorisation EMV/ISO 8583 — traitement complet avec vérification ARQC</div>
                    </div>
                </div>
                <div class="endpoint">
                    <span class="method POST">POST</span>
                    <div>
                        <div class="endpoint-path">/api/v1/authorize/iso8583</div>
                        <div class="endpoint-desc">Autorisation via message ISO 8583 complet (format JSON)</div>
                    </div>
                </div>
                <div class="endpoint">
                    <span class="method POST">POST</span>
                    <div>
                        <div class="endpoint-path">/api/v1/tlv/parse</div>
                        <div class="endpoint-desc">Décodage BER-TLV des données EMV (champ 55)</div>
                    </div>
                </div>
                <div class="endpoint">
                    <span class="method GET">GET</span>
                    <div>
                        <div class="endpoint-path">/api/v1/transactions</div>
                        <div class="endpoint-desc">Liste paginée des transactions (?limit=50&offset=0)</div>
                    </div>
                </div>
                <div class="endpoint">
                    <span class="method GET">GET</span>
                    <div>
                        <div class="endpoint-path">/api/v1/transactions/&lt;id&gt;</div>
                        <div class="endpoint-desc">Détail d'une transaction par ID</div>
                    </div>
                </div>
                <div class="endpoint">
                    <span class="method GET">GET</span>
                    <div>
                        <div class="endpoint-path">/api/v1/cards</div>
                        <div class="endpoint-desc">Liste des cartes enregistrées (PAN masqué)</div>
                    </div>
                </div>
                <div class="endpoint">
                    <span class="method GET">GET</span>
                    <div>
                        <div class="endpoint-path">/api/v1/cards/&lt;pan&gt;</div>
                        <div class="endpoint-desc">Informations d'une carte par PAN</div>
                    </div>
                </div>
                <div class="endpoint">
                    <span class="method POST">POST</span>
                    <div>
                        <div class="endpoint-path">/api/v1/cards</div>
                        <div class="endpoint-desc">Enregistrer une nouvelle carte</div>
                    </div>
                </div>
                <div class="endpoint">
                    <span class="method POST">POST</span>
                    <div>
                        <div class="endpoint-path">/api/v1/cards/&lt;pan&gt;/block</div>
                        <div class="endpoint-desc">Bloquer une carte (liste chaude)</div>
                    </div>
                </div>
                <div class="endpoint">
                    <span class="method GET">GET</span>
                    <div>
                        <div class="endpoint-path">/api/v1/stats</div>
                        <div class="endpoint-desc">Statistiques globales du serveur d'autorisation</div>
                    </div>
                </div>
                <div class="endpoint">
                    <span class="method GET">GET</span>
                    <div>
                        <div class="endpoint-path">/api/v1/health</div>
                        <div class="endpoint-desc">Statut de santé du serveur</div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
function showTab(name) {
    document.querySelectorAll('.tab').forEach((t,i) => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    event.target.classList.add('active');
    document.getElementById('tab-' + name).classList.add('active');
    if (name === 'transactions') loadTransactions();
    if (name === 'cards') loadCards();
}

function fillCard() {
    const v = document.getElementById('panSelect').value;
    document.getElementById('customPanGroup').style.display = v === 'custom' ? 'block' : 'none';
}

function getPan() {
    const v = document.getElementById('panSelect').value;
    if (v === 'custom') return document.getElementById('customPan').value.replace(/\\s/g,'');
    return v;
}

async function sendAuthorization() {
    const btn = document.querySelector('.btn');
    btn.disabled = true;
    btn.textContent = 'Traitement en cours...';

    const payload = {
        pan: getPan(),
        amount: parseInt(document.getElementById('amount').value),
        currency: document.getElementById('currency').value,
        transaction_type: document.getElementById('txnType').value,
        terminal_id: document.getElementById('terminalId').value,
        merchant_id: 'MERCH001',
        merchant_name: 'BOUTIQUE TEST',
        field_55: document.getElementById('emvData').value.trim() || null,
        skip_crypto: !document.getElementById('emvData').value.trim()
    };

    document.getElementById('requestBox').textContent = JSON.stringify(payload, null, 2);

    try {
        const resp = await fetch('/api/v1/authorize', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        const data = await resp.json();
        const box = document.getElementById('resultBox');
        box.textContent = JSON.stringify(data, null, 2);
        box.className = 'result-box ' + (data.approved ? 'approved' : resp.ok ? 'declined' : 'error');
        loadStats();
    } catch(e) {
        const box = document.getElementById('resultBox');
        box.textContent = 'Erreur: ' + e.message;
        box.className = 'result-box error';
    }

    btn.disabled = false;
    btn.textContent = 'Envoyer la demande d\\'autorisation →';
}

async function loadStats() {
    try {
        const r = await fetch('/api/v1/stats');
        const d = await r.json();
        const ts = d.transaction_stats;
        document.getElementById('statTotal').textContent = ts.total;
        document.getElementById('statApproved').textContent = ts.approved;
        document.getElementById('statDeclined').textContent = ts.declined;
        document.getElementById('statRate').textContent = ts.approval_rate;
        document.getElementById('statAmount').textContent = ts.total_approved_amount_formatted;
        document.getElementById('txnCount').textContent = ts.total > 0 ? '(' + ts.total + ')' : '';
    } catch(e) {}
}

async function loadTransactions() {
    try {
        const r = await fetch('/api/v1/transactions?limit=50');
        const d = await r.json();
        const tbody = document.getElementById('txnTableBody');
        if (!d.transactions || !d.transactions.length) {
            tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#64748b;padding:30px">Aucune transaction</td></tr>';
            return;
        }
        tbody.innerHTML = d.transactions.map(t => `
            <tr>
                <td style="font-family:monospace;font-size:11px;color:#94a3b8">${t.rrn}</td>
                <td style="font-family:monospace;color:#a78bfa">${t.pan}</td>
                <td style="color:#e2e8f0;font-weight:600">${t.amount_formatted} ${t.currency}</td>
                <td style="color:#64748b">${t.currency}</td>
                <td style="color:#64748b">${t.transaction_type}</td>
                <td><span class="status-badge ${t.status}">${t.status}</span></td>
                <td style="font-family:monospace;font-weight:600;color:${t.response_code==='00'?'#34d399':'#f87171'}">${t.response_code || '–'}</td>
                <td style="font-family:monospace;color:#60a5fa">${t.auth_code || '–'}</td>
                <td style="color:#64748b;font-size:11px">${t.created_at ? t.created_at.split('T').join(' ').split('.')[0] : '–'}</td>
            </tr>
        `).join('');
    } catch(e) {}
}

async function loadCards() {
    try {
        const r = await fetch('/api/v1/cards');
        const d = await r.json();
        const grid = document.getElementById('cardGrid');
        if (!d.cards || !d.cards.length) {
            grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;color:#64748b;padding:30px">Aucune carte</div>';
            return;
        }
        const statusColors = {ACTIVE:'#34d399',BLOCKED:'#f87171',EXPIRED:'#f59e0b',LOST:'#fb923c',STOLEN:'#ef4444',RESTRICTED:'#94a3b8'};
        grid.innerHTML = d.cards.map(c => `
            <div class="card-item">
                <div class="pan">${c.pan.replace(/(\\d{4})/g,'$1 ').trim()}</div>
                <div class="name">${c.cardholder_name}</div>
                <div class="details">Expire: ${c.expiry.slice(0,2)}/${c.expiry.slice(2)} &nbsp;·&nbsp; PSN: ${c.psn}</div>
                <div class="details" style="margin-top:4px">
                    <span style="color:${statusColors[c.status]||'#94a3b8'};font-weight:600">● ${c.status}</span>
                    &nbsp;·&nbsp; ATC: ${c.last_atc}
                </div>
                <div class="balance">${(c.balance/100).toFixed(2)}</div>
                <div class="details">Limite jour: ${(c.daily_limit/100).toFixed(2)} &nbsp;·&nbsp; Dépensé: ${(c.daily_spent/100).toFixed(2)}</div>
            </div>
        `).join('');
    } catch(e) {}
}

loadStats();
setInterval(loadStats, 10000);
</script>
</body>
</html>
"""


@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/v1/health", methods=["GET"])
def health():
    return jsonify({
        "status": "UP",
        "service": "EMV Authorization Server",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "standards": ["EMV 4.3", "ISO 8583", "ISO 9564"],
    })


@app.route("/api/v1/authorize", methods=["POST"])
def authorize_endpoint():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    pan = data.get("pan", "").replace(" ", "")
    if not pan:
        return jsonify({"error": "PAN is required"}), 400

    try:
        amount = int(data.get("amount", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid amount"}), 400

    currency = str(data.get("currency", "840")).zfill(3)
    transaction_type = str(data.get("transaction_type", "00")).zfill(2)
    terminal_id = data.get("terminal_id")
    merchant_id = data.get("merchant_id")
    merchant_name = data.get("merchant_name")
    field_55 = data.get("field_55") or data.get("emv_data")
    pos_entry_mode = data.get("pos_entry_mode", "051")
    skip_crypto = data.get("skip_crypto", False)

    result = authorize(
        pan=pan,
        amount=amount,
        currency=currency,
        transaction_type=transaction_type,
        field_55=field_55,
        terminal_id=terminal_id,
        merchant_id=merchant_id,
        merchant_name=merchant_name,
        pos_entry_mode=pos_entry_mode,
        skip_crypto=skip_crypto,
    )

    response_data = result.to_dict()
    status_code = 200 if result.approved else 200
    return jsonify(response_data), status_code


@app.route("/api/v1/authorize/iso8583", methods=["POST"])
def authorize_iso8583():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    try:
        msg = parse_from_dict(data)
    except Exception as e:
        return jsonify({"error": "Failed to parse ISO 8583 message: " + str(e)}), 400

    pan = msg.pan
    amount = msg.amount
    currency = msg.currency_code
    transaction_type = msg.transaction_type
    terminal_id = msg.terminal_id
    merchant_id = msg.merchant_id
    merchant_name = msg.merchant_name
    field_55 = msg.emv_data

    result = authorize(
        pan=pan,
        amount=amount,
        currency=currency,
        transaction_type=transaction_type,
        field_55=field_55,
        terminal_id=terminal_id,
        merchant_id=merchant_id,
        merchant_name=merchant_name,
    )

    response_msg = msg.to_response(
        response_code=result.response_code,
        auth_code=result.auth_code,
        field_55_response=result.issuer_auth_data,
    )

    return jsonify({
        "request": msg.to_dict(),
        "response": response_msg.to_dict(),
        "authorization": result.to_dict(),
    })


@app.route("/api/v1/tlv/parse", methods=["POST"])
def parse_tlv():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    hex_data = data.get("data") or data.get("hex")
    if not hex_data:
        return jsonify({"error": "'data' field with hex string is required"}), 400

    hex_data = hex_data.replace(" ", "")
    try:
        tlv_list = parse(hex_data)
        fields = extract_emv_fields(hex_data)
        return jsonify({
            "input": hex_data.upper(),
            "total_elements": len(tlv_list),
            "parsed": [tlv.to_dict() for tlv in tlv_list],
            "flat_fields": fields,
        })
    except Exception as e:
        return jsonify({"error": "TLV parse error: " + str(e)}), 400


@app.route("/api/v1/transactions", methods=["GET"])
def list_transactions():
    try:
        limit = min(int(request.args.get("limit", 50)), 200)
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid pagination parameters"}), 400

    transactions = transaction_log.get_all(limit=limit, offset=offset)
    return jsonify({
        "transactions": [t.to_dict() for t in transactions],
        "count": len(transactions),
        "limit": limit,
        "offset": offset,
    })


@app.route("/api/v1/transactions/<transaction_id>", methods=["GET"])
def get_transaction(transaction_id):
    txn = transaction_log.get(transaction_id)
    if not txn:
        return jsonify({"error": "Transaction not found"}), 404
    return jsonify(txn.to_dict())


@app.route("/api/v1/transactions/pan/<pan>", methods=["GET"])
def get_transactions_by_pan(pan):
    pan = pan.replace(" ", "")
    limit = min(int(request.args.get("limit", 20)), 100)
    transactions = transaction_log.get_by_pan(pan, limit=limit)
    return jsonify({
        "pan": "*" * (len(pan) - 4) + pan[-4:],
        "transactions": [t.to_dict() for t in transactions],
        "count": len(transactions),
    })


@app.route("/api/v1/cards", methods=["GET"])
def list_cards():
    cards = card_db.all_cards()
    return jsonify({
        "cards": [c.to_dict(masked=True) for c in cards],
        "count": len(cards),
    })


@app.route("/api/v1/cards/<pan>", methods=["GET"])
def get_card(pan):
    pan = pan.replace(" ", "")
    card = card_db.get_card(pan)
    if not card:
        return jsonify({"error": "Card not found"}), 404
    return jsonify(card.to_dict(masked=True))


@app.route("/api/v1/cards", methods=["POST"])
def create_card():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    pan = data.get("pan", "").replace(" ", "")
    expiry = data.get("expiry", "")
    cardholder_name = data.get("cardholder_name", "")

    if not pan or not expiry or not cardholder_name:
        return jsonify({"error": "pan, expiry, and cardholder_name are required"}), 400

    if card_db.get_card(pan):
        return jsonify({"error": "Card already exists"}), 409

    card = Card(
        pan=pan,
        expiry=expiry,
        cardholder_name=cardholder_name.upper(),
        psn=data.get("psn", "01"),
        status=data.get("status", CardStatus.ACTIVE),
        balance=int(data.get("balance", 100000)),
        daily_limit=int(data.get("daily_limit", 500000)),
    )
    card_db.add_card(card)

    return jsonify({
        "message": "Card created successfully",
        "card": card.to_dict(masked=True),
    }), 201


@app.route("/api/v1/cards/<pan>/block", methods=["POST"])
def block_card(pan):
    pan = pan.replace(" ", "")
    if card_db.block_card(pan):
        return jsonify({"message": "Card blocked successfully", "pan": pan})
    return jsonify({"error": "Card not found"}), 404


@app.route("/api/v1/stats", methods=["GET"])
def get_stats():
    return jsonify({
        "transaction_stats": transaction_log.get_stats(),
        "card_stats": card_db.get_stats(),
        "server": {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "max_transaction_amount": Config.MAX_TRANSACTION_AMOUNT,
            "daily_limit": Config.DAILY_LIMIT,
            "supported_currencies": Config.CURRENCY_CODES,
            "response_codes": Config.RESPONSE_CODES,
        },
    })


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found"}), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Method not allowed"}), 405


@app.errorhandler(500)
def internal_error(e):
    logger.exception("Internal server error")
    return jsonify({"error": "Internal server error"}), 500
