"""
EMV Authorization Server - Flask REST API
Inclut : historique, gestion par montant, réponses TPA
"""

import logging
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string

from emv.authorization import authorize
from emv.tlv import parse, extract_emv_fields
from emv.amount_rules import get_all_tiers, get_tier, add_custom_tier, delete_custom_tier
from iso8583.message import parse_from_dict
from models.card import card_db, Card, CardStatus
from models.transaction import transaction_log, TransactionStatus
from models.tpa_response import TPAResponse, TPA_FIELD_DEFINITIONS
from config import Config

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["SECRET_KEY"] = Config.SECRET_KEY
app.config["JSON_SORT_KEYS"] = False

# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD HTML
# ═══════════════════════════════════════════════════════════════════════════════
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Serveur d'Autorisation EMV</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',sans-serif;background:#0a0d14;color:#e2e8f0;min-height:100vh}
.header{background:linear-gradient(135deg,#1a1f2e,#16213e);border-bottom:1px solid #2d3748;padding:18px 32px;display:flex;align-items:center;gap:14px}
.logo{width:44px;height:44px;background:linear-gradient(135deg,#667eea,#764ba2);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0}
.header h1{font-size:20px;font-weight:700;color:#fff}
.header p{color:#94a3b8;font-size:12px;margin-top:2px}
.online-badge{margin-left:auto;background:#10b981;color:#fff;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600;display:flex;align-items:center;gap:6px}
.online-badge::before{content:'';width:7px;height:7px;background:#fff;border-radius:50%;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.container{max-width:1400px;margin:0 auto;padding:24px 16px}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:24px}
.stat{background:#1a1f2e;border:1px solid #2d3748;border-radius:10px;padding:16px}
.stat .lbl{color:#64748b;font-size:11px;text-transform:uppercase;letter-spacing:.5px}
.stat .val{font-size:26px;font-weight:700;margin:6px 0 3px}
.stat .sub{color:#64748b;font-size:12px}
.stat.blue .val{color:#60a5fa}.stat.green .val{color:#10b981}.stat.orange .val{color:#f59e0b}.stat.purple .val{color:#a78bfa}.stat.red .val{color:#f87171}.stat.teal .val{color:#2dd4bf}
.section{background:#1a1f2e;border:1px solid #2d3748;border-radius:10px;margin-bottom:20px;overflow:hidden}
.tabs{display:flex;gap:2px;padding:14px 20px 0;border-bottom:1px solid #2d3748;flex-wrap:wrap}
.tab{padding:7px 14px;border-radius:8px 8px 0 0;font-size:13px;cursor:pointer;color:#64748b;background:transparent;border:none;border-bottom:2px solid transparent;white-space:nowrap}
.tab.active{color:#a78bfa;border-bottom-color:#a78bfa;background:#150f20}
.tab-content{display:none}.tab-content.active{display:block}
label{display:block;color:#94a3b8;font-size:12px;margin-bottom:5px;font-weight:500}
input,select,textarea{width:100%;background:#0a0d14;border:1px solid #2d3748;color:#e2e8f0;border-radius:7px;padding:8px 11px;font-size:13px;font-family:inherit}
input:focus,select:focus,textarea:focus{outline:none;border-color:#667eea}
.form-group{margin-bottom:12px}
.btn{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;border:none;padding:10px 20px;border-radius:7px;font-size:14px;font-weight:600;cursor:pointer;width:100%;margin-top:3px}
.btn:hover{opacity:.9}.btn:disabled{opacity:.5;cursor:not-allowed}
.btn-sm{background:#2d3748;color:#94a3b8;border:none;padding:5px 12px;border-radius:6px;font-size:12px;cursor:pointer}
.btn-sm:hover{background:#374151;color:#e2e8f0}
.btn-danger{background:#7f1d1d;color:#fca5a5;border:1px solid #991b1b}
.btn-danger:hover{background:#991b1b}
.result-box{background:#0a0d14;border:1px solid #2d3748;border-radius:7px;padding:14px;font-family:monospace;font-size:11.5px;color:#94a3b8;min-height:180px;white-space:pre-wrap;word-break:break-all;max-height:380px;overflow-y:auto}
.result-box.approved{border-color:#10b981;color:#34d399}
.result-box.declined{border-color:#ef4444;color:#f87171}
.result-box.error{border-color:#f59e0b;color:#fbbf24}
.demo-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;padding:20px}
@media(max-width:800px){.demo-grid{grid-template-columns:1fr}}
/* Tables */
table{width:100%;border-collapse:collapse}
th{color:#64748b;font-size:11px;text-transform:uppercase;padding:10px 14px;text-align:left;border-bottom:1px solid #2d3748;white-space:nowrap}
td{padding:10px 14px;font-size:13px;border-bottom:1px solid #1a2133;vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:#111827}
.badge{display:inline-flex;align-items:center;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap}
.badge.APPROVED,.badge.approved{background:#052e16;color:#34d399;border:1px solid #065f46}
.badge.DECLINED,.badge.declined{background:#2d0f0f;color:#f87171;border:1px solid #991b1b}
.badge.ERROR,.badge.error{background:#2d1f0a;color:#fbbf24;border:1px solid #92400e}
.badge.ONLINE{background:#1e2a4a;color:#60a5fa;border:1px solid #1e40af}
.badge.OFFLINE{background:#1a2a1a;color:#6ee7b7;border:1px solid #065f46}
.badge.LOW{background:#052e16;color:#34d399;border:1px solid #065f46}
.badge.MEDIUM{background:#1a2a1a;color:#fbbf24;border:1px solid #92400e}
.badge.HIGH{background:#2d1f0a;color:#f97316;border:1px solid #c2410c}
.badge.VERY_HIGH,.badge.CRITICAL{background:#2d0f0f;color:#f87171;border:1px solid #991b1b}
.badge.REFERRAL{background:#1f1a3a;color:#c4b5fd;border:1px solid #7c3aed}
/* Tier cards */
.tier-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px;padding:20px}
.tier-card{background:#111827;border:1px solid #2d3748;border-radius:10px;padding:16px}
.tier-card .tier-name{font-weight:700;font-size:15px;color:#fff;margin-bottom:4px}
.tier-card .tier-range{font-family:monospace;font-size:13px;color:#a78bfa}
.tier-card .tier-desc{color:#64748b;font-size:12px;margin:8px 0}
.tier-card .tier-flags{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.tier-card .flag{background:#1a1f2e;border:1px solid #2d3748;color:#94a3b8;font-size:11px;padding:2px 7px;border-radius:4px}
.tier-card .flag.on{background:#1a3a2a;border-color:#065f46;color:#34d399}
/* TPA champs */
.tpa-table td:first-child{font-family:monospace;color:#a78bfa;font-weight:700;width:60px}
.tpa-table td:nth-child(2){color:#64748b;font-size:11px;width:220px}
.tpa-table td:nth-child(3){font-family:monospace;color:#e2e8f0;word-break:break-all}
/* Historique */
.hist-filters{display:flex;gap:10px;padding:14px 20px;border-bottom:1px solid #2d3748;flex-wrap:wrap;align-items:flex-end}
.hist-filters .filter-group{display:flex;flex-direction:column;gap:4px;min-width:120px}
.hist-filters label{margin-bottom:0}
.detail-panel{background:#0a0d14;border:1px solid #2d3748;border-radius:8px;padding:16px;margin:14px 20px;display:none}
.detail-panel.open{display:block}
.detail-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-bottom:14px}
.detail-field .df-label{color:#64748b;font-size:11px;text-transform:uppercase;letter-spacing:.3px}
.detail-field .df-value{color:#e2e8f0;font-family:monospace;font-size:12px;margin-top:3px;word-break:break-all}
.pagination{display:flex;gap:8px;align-items:center;padding:12px 20px;border-top:1px solid #2d3748}
.page-btn{background:#1a1f2e;border:1px solid #2d3748;color:#94a3b8;padding:4px 12px;border-radius:6px;cursor:pointer;font-size:12px}
.page-btn:hover{border-color:#667eea;color:#a78bfa}
.page-btn:disabled{opacity:.4;cursor:not-allowed}
/* Card grid */
.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px;padding:20px}
.card-item{background:linear-gradient(135deg,#1e2a3a,#1a2030);border:1px solid #2d3748;border-radius:10px;padding:15px}
.card-item .pan{font-family:monospace;font-size:13px;color:#a78bfa;letter-spacing:2px}
.card-item .name{color:#e2e8f0;font-weight:600;margin:7px 0 3px}
.card-item .details{color:#64748b;font-size:12px}
.card-item .balance{color:#34d399;font-size:17px;font-weight:700;margin-top:10px}
/* API list */
.ep{display:flex;align-items:flex-start;gap:10px;padding:12px 20px;border-bottom:1px solid #1a2133}
.ep:last-child{border-bottom:none}
.method{font-size:11px;font-weight:700;padding:3px 7px;border-radius:5px;min-width:50px;text-align:center;flex-shrink:0;margin-top:1px}
.method.POST{background:#1a3a2a;color:#34d399;border:1px solid #065f46}
.method.GET{background:#1a2a3a;color:#60a5fa;border:1px solid #1e40af}
.method.DELETE{background:#3a1a1a;color:#f87171;border:1px solid #991b1b}
.method.PUT{background:#2a2a1a;color:#fbbf24;border:1px solid #92400e}
.ep-path{font-family:monospace;color:#a78bfa;font-size:13px;font-weight:600}
.ep-desc{color:#64748b;font-size:12px;margin-top:2px}
.section-hdr{padding:14px 20px;border-bottom:1px solid #2d3748;display:flex;align-items:center;justify-content:space-between}
.section-hdr h2{font-size:14px;font-weight:600;color:#fff}
</style>
</head>
<body>
<div class="header">
  <div class="logo">💳</div>
  <div>
    <h1>Serveur d'Autorisation EMV</h1>
    <p>ISO 8583 · EMV 4.3 · ARQC/ARPC · Gestion par montant · Format TPA</p>
  </div>
  <div class="online-badge">En ligne</div>
</div>

<div class="container">
  <div class="stats-grid" id="statsGrid">
    <div class="stat blue"><div class="lbl">Total</div><div class="val" id="sTotal">–</div><div class="sub">transactions</div></div>
    <div class="stat green"><div class="lbl">Approuvées</div><div class="val" id="sApproved">–</div><div class="sub" id="sRate">–</div></div>
    <div class="stat red"><div class="lbl">Refusées</div><div class="val" id="sDeclined">–</div><div class="sub">refus</div></div>
    <div class="stat purple"><div class="lbl">Montant approuvé</div><div class="val" id="sAmount">–</div><div class="sub">total cumulé</div></div>
    <div class="stat teal"><div class="lbl">Chemin ONLINE</div><div class="val" id="sOnline">–</div><div class="sub">autorisations</div></div>
    <div class="stat orange"><div class="lbl">Chemin OFFLINE</div><div class="val" id="sOffline">–</div><div class="sub">autorisations</div></div>
  </div>

  <div class="section">
    <div class="tabs">
      <button class="tab active" onclick="showTab('demo',this)">Démo</button>
      <button class="tab" onclick="showTab('history',this)">Historique</button>
      <button class="tab" onclick="showTab('tpa',this)">Réponse TPA</button>
      <button class="tab" onclick="showTab('tiers',this)">Tranches montant</button>
      <button class="tab" onclick="showTab('cards',this)">Cartes</button>
      <button class="tab" onclick="showTab('api',this)">API</button>
    </div>

    <!-- ═══ DÉMO ═══ -->
    <div id="tab-demo" class="tab-content active">
      <div class="demo-grid">
        <div>
          <div class="form-group">
            <label>Carte (PAN)</label>
            <select id="panSelect" onchange="fillCard()">
              <option value="4111111111111111">4111 1111 1111 1111 — JEAN DUPONT (Actif)</option>
              <option value="5500000000000004">5500 0000 0000 0004 — MARIE MARTIN (Actif)</option>
              <option value="4000000000000002">4000 0000 0000 0002 — AHMED BENALI (Actif)</option>
              <option value="4000000000000036">4000 0000 0000 0036 — Provision insuffisante</option>
              <option value="4000000000000028">4000 0000 0000 0028 — Carte bloquée</option>
              <option value="4000000000000010">4000 0000 0000 0010 — Carte expirée</option>
              <option value="custom">Numéro personnalisé…</option>
            </select>
          </div>
          <div class="form-group" id="customPanGroup" style="display:none">
            <label>PAN personnalisé</label>
            <input type="text" id="customPan" placeholder="4111111111111111" maxlength="19">
          </div>
          <div class="form-group">
            <label>Montant (centimes) — ex: 5000 = 50,00</label>
            <input type="number" id="amount" value="5000" min="1">
          </div>
          <div class="form-group">
            <label>Devise (ISO 4217)</label>
            <select id="currency">
              <option value="840">840 — USD</option><option value="978">978 — EUR</option>
              <option value="826">826 — GBP</option><option value="504">504 — MAD</option>
              <option value="788">788 — TND</option><option value="012">012 — DZD</option>
            </select>
          </div>
          <div class="form-group">
            <label>Type de transaction</label>
            <select id="txnType">
              <option value="00">00 — Achat</option>
              <option value="01">01 — Avance liquidités</option>
              <option value="09">09 — Achat + cashback</option>
              <option value="20">20 — Remboursement</option>
              <option value="22">22 — Consultation solde</option>
            </select>
          </div>
          <div class="form-group">
            <label>Terminal ID</label>
            <input type="text" id="terminalId" value="TERM0001" maxlength="8">
          </div>
          <div class="form-group">
            <label>Données EMV champ 55 (hex, optionnel)</label>
            <textarea id="emvData" rows="2" placeholder="Laisser vide pour test sans cryptogramme"></textarea>
          </div>
          <button class="btn" id="authBtn" onclick="sendAuthorization()">Envoyer la demande d'autorisation →</button>
        </div>
        <div>
          <div class="form-group">
            <label>Tranche détectée</label>
            <div id="tierBox" style="background:#111827;border:1px solid #2d3748;border-radius:7px;padding:10px;font-size:12px;color:#64748b;min-height:44px">—</div>
          </div>
          <div class="form-group">
            <label>Réponse serveur (JSON)</label>
            <div class="result-box" id="resultBox">En attente…</div>
          </div>
          <div class="form-group" style="margin-top:12px">
            <label>Réponse TPA (champs structurés)</label>
            <div class="result-box" id="tpaBox" style="min-height:120px">—</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══ HISTORIQUE ═══ -->
    <div id="tab-history" class="tab-content">
      <div class="hist-filters">
        <div class="filter-group">
          <label>Statut</label>
          <select id="fStatus" onchange="loadHistory()">
            <option value="">Tous</option>
            <option value="APPROVED">Approuvé</option>
            <option value="DECLINED">Refusé</option>
            <option value="ERROR">Erreur</option>
          </select>
        </div>
        <div class="filter-group">
          <label>Tranche</label>
          <select id="fTier" onchange="loadHistory()">
            <option value="">Toutes</option>
            <option value="MICRO">MICRO</option>
            <option value="SMALL">SMALL</option>
            <option value="STANDARD">STANDARD</option>
            <option value="HIGH">HIGH</option>
            <option value="VERY_HIGH">VERY_HIGH</option>
            <option value="CRITICAL">CRITICAL</option>
          </select>
        </div>
        <div class="filter-group" style="min-width:80px">
          <label>Par page</label>
          <select id="fLimit" onchange="loadHistory()">
            <option value="20">20</option>
            <option value="50">50</option>
            <option value="100">100</option>
          </select>
        </div>
        <button class="btn-sm" onclick="loadHistory()" style="align-self:flex-end">↻ Actualiser</button>
        <button class="btn-sm" onclick="exportHistory()" style="align-self:flex-end">⬇ Export JSON</button>
      </div>

      <div id="histDetailPanel" class="detail-panel"></div>

      <div style="overflow-x:auto">
        <table>
          <thead><tr>
            <th></th><th>RRN</th><th>Carte</th><th>Montant</th>
            <th>Tranche</th><th>Risque</th><th>Chemin</th>
            <th>Statut</th><th>Code</th><th>Auth</th><th>Date/Heure</th>
          </tr></thead>
          <tbody id="histTableBody">
            <tr><td colspan="11" style="text-align:center;color:#64748b;padding:30px">Cliquez Actualiser</td></tr>
          </tbody>
        </table>
      </div>
      <div class="pagination">
        <button class="page-btn" id="prevBtn" onclick="histPage(-1)" disabled>← Préc.</button>
        <span id="pageInfo" style="color:#64748b;font-size:12px">Page 1</span>
        <button class="page-btn" id="nextBtn" onclick="histPage(1)">Suiv. →</button>
        <span id="histTotal" style="color:#64748b;font-size:12px;margin-left:auto"></span>
      </div>
    </div>

    <!-- ═══ RÉPONSE TPA ═══ -->
    <div id="tab-tpa" class="tab-content">
      <div class="section-hdr">
        <h2>Découpage TPA — Dernière transaction</h2>
        <button class="btn-sm" onclick="loadLastTPA()">↻ Rafraîchir</button>
      </div>
      <div id="tpaFullPanel" style="padding:16px">
        <div style="color:#64748b;font-size:13px">Effectuez une autorisation pour voir le découpage TPA.</div>
      </div>
    </div>

    <!-- ═══ TRANCHES MONTANT ═══ -->
    <div id="tab-tiers" class="tab-content">
      <div class="section-hdr">
        <h2>Tranches de montant — Règles d'autorisation</h2>
        <button class="btn-sm" onclick="toggleAddTier()">+ Ajouter tranche</button>
      </div>
      <div id="addTierForm" style="display:none;padding:16px;border-bottom:1px solid #2d3748;background:#0a0d14">
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px">
          <div class="form-group"><label>Nom (ex: PREMIUM)</label><input type="text" id="tName" placeholder="CUSTOM"></div>
          <div class="form-group"><label>Label</label><input type="text" id="tLabel" placeholder="Ma tranche"></div>
          <div class="form-group"><label>Montant min (centimes)</label><input type="number" id="tMin" placeholder="0"></div>
          <div class="form-group"><label>Montant max (centimes)</label><input type="number" id="tMax" placeholder="100000"></div>
          <div class="form-group"><label>Niveau risque</label>
            <select id="tRisk"><option>LOW</option><option>MEDIUM</option><option>HIGH</option><option>VERY_HIGH</option><option>CRITICAL</option></select>
          </div>
          <div class="form-group"><label>Limite journalière (nombre)</label><input type="number" id="tDailyCount" placeholder="vide = illimité"></div>
          <div class="form-group"><label>Options</label>
            <label style="display:flex;gap:6px;align-items:center;margin-top:6px"><input type="checkbox" id="tOnline" checked> Requiert online</label>
            <label style="display:flex;gap:6px;align-items:center;margin-top:4px"><input type="checkbox" id="tArqc" checked> Requiert ARQC</label>
            <label style="display:flex;gap:6px;align-items:center;margin-top:4px"><input type="checkbox" id="tOffline"> Auto-approve offline</label>
          </div>
        </div>
        <div class="form-group"><label>Description</label><input type="text" id="tDesc" placeholder="Description de la tranche"></div>
        <div style="display:flex;gap:10px;margin-top:8px">
          <button class="btn-sm" onclick="addTier()" style="background:#667eea;color:#fff">Créer la tranche</button>
          <button class="btn-sm" onclick="toggleAddTier()">Annuler</button>
        </div>
      </div>
      <div class="tier-grid" id="tierGrid">Chargement…</div>
    </div>

    <!-- ═══ CARTES ═══ -->
    <div id="tab-cards" class="tab-content">
      <div class="section-hdr">
        <h2>Cartes de test</h2>
        <button class="btn-sm" onclick="loadCards()">↻ Actualiser</button>
      </div>
      <div class="card-grid" id="cardGrid"><div style="color:#64748b;padding:20px">Chargement…</div></div>
    </div>

    <!-- ═══ API ═══ -->
    <div id="tab-api" class="tab-content">
      <div class="ep"><span class="method POST">POST</span><div><div class="ep-path">/api/v1/authorize</div><div class="ep-desc">Autorisation EMV — vérifie tranche, carte, ARQC. Retourne réponse TPA complète.</div></div></div>
      <div class="ep"><span class="method POST">POST</span><div><div class="ep-path">/api/v1/authorize/iso8583</div><div class="ep-desc">Autorisation via message ISO 8583 complet</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/transactions</div><div class="ep-desc">Historique paginé avec filtres ?status=&tier=&limit=&offset=</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/transactions/&lt;id&gt;</div><div class="ep-desc">Détail complet d'une transaction avec champs TPA</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/transactions/&lt;id&gt;/tpa</div><div class="ep-desc">Réponse TPA découpée en champs pour une transaction</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/transactions/pan/&lt;pan&gt;</div><div class="ep-desc">Historique d'une carte par PAN</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/amount-tiers</div><div class="ep-desc">Liste toutes les tranches de montant configurées</div></div></div>
      <div class="ep"><span class="method POST">POST</span><div><div class="ep-path">/api/v1/amount-tiers</div><div class="ep-desc">Créer une tranche personnalisée</div></div></div>
      <div class="ep"><span class="method DELETE">DELETE</span><div><div class="ep-path">/api/v1/amount-tiers/&lt;name&gt;</div><div class="ep-desc">Supprimer une tranche personnalisée</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/amount-tiers/evaluate?amount=5000</div><div class="ep-desc">Évaluer la tranche pour un montant donné</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/tpa/fields</div><div class="ep-desc">Définitions de tous les champs TPA</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/cards</div><div class="ep-desc">Liste des cartes (PAN masqué)</div></div></div>
      <div class="ep"><span class="method POST">POST</span><div><div class="ep-path">/api/v1/cards</div><div class="ep-desc">Créer une nouvelle carte</div></div></div>
      <div class="ep"><span class="method POST">POST</span><div><div class="ep-path">/api/v1/cards/&lt;pan&gt;/block</div><div class="ep-desc">Bloquer une carte</div></div></div>
      <div class="ep"><span class="method POST">POST</span><div><div class="ep-path">/api/v1/tlv/parse</div><div class="ep-desc">Décodage BER-TLV du champ 55</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/stats</div><div class="ep-desc">Statistiques globales par tranche, chemin, risque</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/health</div><div class="ep-desc">Santé du serveur</div></div></div>
    </div>
  </div>
</div>

<script>
let histOffset = 0, histLimit = 20, histTotal = 0;
let lastTxnId = null;

/* ── Onglets ── */
function showTab(name, el) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  if(el) el.classList.add('active');
  document.getElementById('tab-'+name).classList.add('active');
  if(name==='history') loadHistory();
  if(name==='tpa') loadLastTPA();
  if(name==='tiers') loadTiers();
  if(name==='cards') loadCards();
}

/* ── Carte sélectionnée ── */
function fillCard(){
  const v=document.getElementById('panSelect').value;
  document.getElementById('customPanGroup').style.display=v==='custom'?'block':'none';
}
function getPan(){
  const v=document.getElementById('panSelect').value;
  return v==='custom'?document.getElementById('customPan').value.replace(/\\s/g,''):v;
}

/* ── Évaluation tranche en temps réel ── */
document.getElementById('amount').addEventListener('input', async function(){
  const amt = parseInt(this.value)||0;
  if(!amt) return;
  try {
    const r = await fetch('/api/v1/amount-tiers/evaluate?amount='+amt);
    const d = await r.json();
    const t = d.tier;
    const riskCls = {'LOW':'#10b981','MEDIUM':'#f59e0b','HIGH':'#f97316','VERY_HIGH':'#ef4444','CRITICAL':'#dc2626'}[t.risk_level]||'#94a3b8';
    document.getElementById('tierBox').innerHTML =
      '<span style="font-weight:700;color:'+riskCls+'">'+t.name+'</span> — '+t.label+
      ' &nbsp;|&nbsp; <span style="color:#64748b">'+t.description+'</span>'+
      ' &nbsp;|&nbsp; Risque: <span style="color:'+riskCls+'">'+t.risk_level+'</span>'+
      (t.require_online?' &nbsp;<span style="color:#60a5fa">ONLINE</span>':' &nbsp;<span style="color:#6ee7b7">OFFLINE</span>')+
      (t.max_daily_count?(' &nbsp;Limite: <span style="color:#fbbf24">'+t.max_daily_count+'/j</span>'):'');
  } catch(e){}
});

/* ── Autorisation ── */
async function sendAuthorization() {
  const btn = document.getElementById('authBtn');
  btn.disabled=true; btn.textContent='Traitement…';
  const payload = {
    pan: getPan(),
    amount: parseInt(document.getElementById('amount').value),
    currency: document.getElementById('currency').value,
    transaction_type: document.getElementById('txnType').value,
    terminal_id: document.getElementById('terminalId').value,
    merchant_id: 'MERCH001', merchant_name: 'BOUTIQUE TEST',
    field_55: document.getElementById('emvData').value.trim()||null,
    skip_crypto: !document.getElementById('emvData').value.trim()
  };
  try {
    const resp = await fetch('/api/v1/authorize', {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)
    });
    const data = await resp.json();
    const box = document.getElementById('resultBox');
    const display = {...data}; delete display.tpa_response;
    box.textContent = JSON.stringify(display, null, 2);
    box.className = 'result-box '+(data.approved?'approved':'declined');
    if(data.tpa_response) {
      const tpaBox = document.getElementById('tpaBox');
      tpaBox.textContent = formatTPA(data.tpa_response);
      tpaBox.className = 'result-box';
    }
    if(data.transaction) { lastTxnId = data.transaction.id; }
    loadStats();
  } catch(e) {
    document.getElementById('resultBox').textContent='Erreur: '+e.message;
    document.getElementById('resultBox').className='result-box error';
  }
  btn.disabled=false; btn.textContent="Envoyer la demande d\\'autorisation →";
}

function formatTPA(tpa) {
  const lines = ['┌──────┬────────────────────────────────┬────────────────────────┐',
                 '│ Chmp │ Nom                            │ Valeur                 │',
                 '├──────┼────────────────────────────────┼────────────────────────┤'];
  for(const [k,v] of Object.entries(tpa)) {
    const name = (v.name||k).slice(0,30).padEnd(30);
    let val = (v.value||'');
    if(Array.isArray(val)) val=val.join('; ');
    val = String(val).slice(0,22).padEnd(22);
    lines.push('│ '+k.padEnd(4)+' │ '+name+' │ '+val+' │');
  }
  lines.push('└──────┴────────────────────────────────┴────────────────────────┘');
  return lines.join('\\n');
}

/* ── Stats ── */
async function loadStats() {
  try {
    const r=await fetch('/api/v1/stats'); const d=await r.json(); const ts=d.transaction_stats;
    document.getElementById('sTotal').textContent=ts.total;
    document.getElementById('sApproved').textContent=ts.approved;
    document.getElementById('sDeclined').textContent=ts.declined;
    document.getElementById('sRate').textContent=ts.approval_rate;
    document.getElementById('sAmount').textContent=ts.total_approved_amount_formatted;
    document.getElementById('sOnline').textContent=ts.by_auth_path?.ONLINE||0;
    document.getElementById('sOffline').textContent=ts.by_auth_path?.OFFLINE||0;
  } catch(e){}
}

/* ── Historique ── */
async function loadHistory() {
  histOffset=0; await fetchHistory();
}
async function histPage(dir) {
  histOffset=Math.max(0,histOffset+dir*histLimit); await fetchHistory();
}
async function fetchHistory() {
  const status=document.getElementById('fStatus').value;
  const tier=document.getElementById('fTier').value;
  histLimit=parseInt(document.getElementById('fLimit').value)||20;
  let url='/api/v1/transactions?limit='+histLimit+'&offset='+histOffset;
  if(status) url+='&status='+status;
  if(tier) url+='&tier='+tier;
  try {
    const r=await fetch(url); const d=await r.json();
    histTotal=d.total_filtered||d.count||0;
    const page=Math.floor(histOffset/histLimit)+1;
    document.getElementById('pageInfo').textContent='Page '+page;
    document.getElementById('histTotal').textContent=histTotal+' résultats';
    document.getElementById('prevBtn').disabled=histOffset===0;
    document.getElementById('nextBtn').disabled=histOffset+histLimit>=histTotal;
    const tbody=document.getElementById('histTableBody');
    if(!d.transactions||!d.transactions.length){
      tbody.innerHTML='<tr><td colspan="11" style="text-align:center;color:#64748b;padding:24px">Aucune transaction</td></tr>';
      return;
    }
    const riskCls={'LOW':'#10b981','MEDIUM':'#f59e0b','HIGH':'#f97316','VERY_HIGH':'#ef4444','CRITICAL':'#dc2626'};
    tbody.innerHTML=d.transactions.map((t,i)=>`
      <tr style="cursor:pointer" onclick="toggleDetail('${t.id}',${i})">
        <td style="color:#64748b;font-size:11px">▶</td>
        <td style="font-family:monospace;font-size:11px;color:#94a3b8">${t.rrn||'—'}</td>
        <td style="font-family:monospace;color:#a78bfa">${t.pan}</td>
        <td style="font-weight:600;color:#e2e8f0">${t.amount_formatted} ${t.currency}</td>
        <td><span style="font-family:monospace;font-size:11px;color:#c4b5fd">${t.amount_tier||'—'}</span></td>
        <td><span class="badge ${t.risk_level||''}">${t.risk_level||'—'}</span></td>
        <td><span class="badge ${t.auth_path||''}">${t.auth_path||'—'}</span></td>
        <td><span class="badge ${t.status}">${t.status}</span></td>
        <td style="font-family:monospace;font-weight:700;color:${t.response_code==='00'?'#34d399':'#f87171'}">${t.response_code||'—'}</td>
        <td style="font-family:monospace;color:#60a5fa;font-size:11px">${t.auth_code||'—'}</td>
        <td style="color:#64748b;font-size:11px">${(t.created_at||'').replace('T',' ').split('.')[0]}</td>
      </tr>
      <tr id="detail-${t.id}" style="display:none">
        <td colspan="11" style="padding:0">
          <div style="background:#0a0d14;border-top:1px solid #2d3748;padding:14px 20px">
            <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-bottom:12px">
              ${fieldRow('ID',t.id)}${fieldRow('RRN',t.rrn)}${fieldRow('Commerçant',t.merchant_name)}
              ${fieldRow('Terminal',t.terminal_id)}${fieldRow('Motif refus',t.decline_reason)}
              ${fieldRow('ARQC',t.arqc)}${fieldRow('ARPC',t.arpc)}${fieldRow('Tag 91',t.issuer_auth_data)}
              ${fieldRow('Traité le',t.processed_at?t.processed_at.replace('T',' ').split('.')[0]:null)}
            </div>
            <button class="btn-sm" onclick="loadTPA('${t.id}')">Voir réponse TPA complète</button>
          </div>
        </td>
      </tr>
    `).join('');
  } catch(e){console.error(e)}
}

function fieldRow(label,val){
  if(!val) return '';
  return '<div><div style="color:#64748b;font-size:10px;text-transform:uppercase">'+label+'</div><div style="font-family:monospace;font-size:11px;color:#e2e8f0;word-break:break-all;margin-top:2px">'+val+'</div></div>';
}

const openDetails={};
function toggleDetail(id,i){
  const row=document.getElementById('detail-'+id);
  if(!row) return;
  if(openDetails[id]){row.style.display='none';delete openDetails[id];}
  else{row.style.display='table-row';openDetails[id]=true;}
}

/* ── TPA ── */
async function loadLastTPA(){
  if(!lastTxnId){
    const r=await fetch('/api/v1/transactions?limit=1');
    const d=await r.json();
    if(d.transactions&&d.transactions.length) lastTxnId=d.transactions[0].id;
    else return;
  }
  await loadTPA(lastTxnId);
}
async function loadTPA(id){
  try{
    const r=await fetch('/api/v1/transactions/'+id+'/tpa');
    const d=await r.json();
    const panel=document.getElementById('tpaFullPanel');
    const rows=Object.entries(d.tpa_fields||{}).map(([k,v])=>{
      let val=v.value; if(Array.isArray(val)) val=val.join('; ');
      return '<tr class="tpa-table"><td>'+k+'</td><td>'+escHtml(v.name||k)+'</td><td>'+escHtml(v.description||'')+'</td><td style="font-family:monospace;font-size:12px;color:#e2e8f0;word-break:break-all">'+escHtml(String(val||''))+'</td></tr>';
    }).join('');
    panel.innerHTML='<div style="font-size:12px;color:#64748b;margin-bottom:12px">Transaction: <span style="font-family:monospace;color:#a78bfa">'+id+'</span></div>'+
      '<div style="overflow-x:auto"><table><thead><tr><th>Champ</th><th>Nom</th><th>Description</th><th>Valeur</th></tr></thead><tbody>'+rows+'</tbody></table></div>';
    document.querySelector('[onclick*="showTab(\\'tpa\\'"]')&&null;
    const tpaTab=document.querySelector('.tab:nth-child(3)');
    if(tpaTab&&!tpaTab.classList.contains('active')){
      showTab('tpa',tpaTab);
    }
  }catch(e){console.error(e)}
}

/* ── Tranches ── */
async function loadTiers(){
  try{
    const r=await fetch('/api/v1/amount-tiers'); const d=await r.json();
    const riskColor={'LOW':'#10b981','MEDIUM':'#f59e0b','HIGH':'#f97316','VERY_HIGH':'#ef4444','CRITICAL':'#dc2626'};
    document.getElementById('tierGrid').innerHTML=d.tiers.map(t=>`
      <div class="tier-card">
        <div class="tier-name" style="color:${riskColor[t.risk_level]||'#fff'}">${t.name}</div>
        <div style="color:#94a3b8;font-size:13px">${t.label}</div>
        <div class="tier-range">${fmt(t.min_amount)} — ${t.max_amount>99999999?'∞':fmt(t.max_amount)}</div>
        <div class="tier-desc">${t.description}</div>
        <div class="tier-flags">
          <span class="flag ${t.require_online?'on':''}">Online</span>
          <span class="flag ${t.require_arqc?'on':''}">ARQC</span>
          <span class="flag ${t.auto_approve_offline?'on':''}">Offline OK</span>
          ${t.max_daily_count?'<span class="flag on">Max '+t.max_daily_count+'/j</span>':''}
        </div>
        ${t.is_custom?'<button class="btn-sm btn-danger" style="margin-top:10px;width:100%" onclick="deleteTier(\\''+t.name+'\\')">Supprimer</button>':''}
      </div>
    `).join('');
  }catch(e){}
}
function fmt(n){return (n/100).toLocaleString('fr-FR',{minimumFractionDigits:2});}
function toggleAddTier(){
  const f=document.getElementById('addTierForm');
  f.style.display=f.style.display==='none'?'block':'none';
}
async function addTier(){
  const daily=document.getElementById('tDailyCount').value;
  const payload={
    name:document.getElementById('tName').value,
    label:document.getElementById('tLabel').value,
    min_amount:parseInt(document.getElementById('tMin').value)||0,
    max_amount:parseInt(document.getElementById('tMax').value)||100000,
    risk_level:document.getElementById('tRisk').value,
    require_online:document.getElementById('tOnline').checked,
    require_arqc:document.getElementById('tArqc').checked,
    auto_approve_offline:document.getElementById('tOffline').checked,
    max_daily_count:daily?parseInt(daily):null,
    description:document.getElementById('tDesc').value,
    velocity_check:true, require_pin:true, floor_limit:0,
  };
  const r=await fetch('/api/v1/amount-tiers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  if(r.ok){toggleAddTier();loadTiers();}
  else alert('Erreur: '+(await r.json()).error);
}
async function deleteTier(name){
  if(!confirm('Supprimer la tranche '+name+' ?')) return;
  await fetch('/api/v1/amount-tiers/'+name,{method:'DELETE'});
  loadTiers();
}

/* ── Cartes ── */
async function loadCards(){
  try{
    const r=await fetch('/api/v1/cards'); const d=await r.json();
    const sc={ACTIVE:'#34d399',BLOCKED:'#f87171',EXPIRED:'#f59e0b',LOST:'#fb923c',STOLEN:'#ef4444',RESTRICTED:'#94a3b8'};
    document.getElementById('cardGrid').innerHTML=d.cards.map(c=>`
      <div class="card-item">
        <div class="pan">${c.pan.replace(/(\\d{4})/g,'$1 ').trim()}</div>
        <div class="name">${c.cardholder_name}</div>
        <div class="details">Expire: ${c.expiry.slice(0,2)}/${c.expiry.slice(2)} · PSN: ${c.psn}</div>
        <div class="details" style="margin-top:4px">
          <span style="color:${sc[c.status]||'#94a3b8'};font-weight:600">● ${c.status}</span> · ATC: ${c.last_atc}
        </div>
        <div class="balance">${(c.balance/100).toFixed(2)}</div>
        <div class="details">Limite/j: ${(c.daily_limit/100).toFixed(2)} · Dépensé: ${(c.daily_spent/100).toFixed(2)}</div>
      </div>
    `).join('');
  }catch(e){}
}

function escHtml(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
async function exportHistory(){
  const r=await fetch('/api/v1/transactions?limit=200');
  const d=await r.json();
  const blob=new Blob([JSON.stringify(d,null,2)],{type:'application/json'});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download='historique_autorisations_'+new Date().toISOString().slice(0,10)+'.json';
  a.click();
}

loadStats();
setInterval(loadStats,10000);
</script>
</body>
</html>
"""


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/v1/health", methods=["GET"])
def health():
    return jsonify({
        "status": "UP",
        "service": "EMV Authorization Server",
        "version": "1.1.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "features": ["EMV 4.3", "ISO 8583", "ARQC/ARPC", "TPA Response", "Amount Tiers"],
    })


# ── Autorisation ──────────────────────────────────────────────────────────────

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

    result = authorize(
        pan=pan, amount=amount, currency=currency,
        transaction_type=transaction_type,
        field_55=data.get("field_55") or data.get("emv_data"),
        terminal_id=data.get("terminal_id"),
        merchant_id=data.get("merchant_id"),
        merchant_name=data.get("merchant_name"),
        pos_entry_mode=data.get("pos_entry_mode", "051"),
        skip_crypto=data.get("skip_crypto", False),
    )
    return jsonify(result.to_dict(include_tpa=True))


@app.route("/api/v1/authorize/iso8583", methods=["POST"])
def authorize_iso8583():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400
    try:
        msg = parse_from_dict(data)
    except Exception as e:
        return jsonify({"error": "ISO 8583 parse error: " + str(e)}), 400

    result = authorize(
        pan=msg.pan, amount=msg.amount, currency=msg.currency_code,
        transaction_type=msg.transaction_type,
        field_55=msg.emv_data, terminal_id=msg.terminal_id,
        merchant_id=msg.merchant_id, merchant_name=msg.merchant_name,
    )
    resp_msg = msg.to_response(
        response_code=result.response_code,
        auth_code=result.auth_code,
        field_55_response=result.issuer_auth_data,
    )
    return jsonify({
        "request": msg.to_dict(),
        "response": resp_msg.to_dict(),
        "authorization": result.to_dict(include_tpa=True),
    })


# ── Historique ────────────────────────────────────────────────────────────────

@app.route("/api/v1/transactions", methods=["GET"])
def list_transactions():
    try:
        limit = min(int(request.args.get("limit", 20)), 200)
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid pagination parameters"}), 400

    status_filter = request.args.get("status")
    tier_filter = request.args.get("tier")

    transactions = transaction_log.get_all(
        limit=limit, offset=offset,
        status=status_filter, tier=tier_filter)

    all_filtered = transaction_log.get_all(
        limit=99999, offset=0,
        status=status_filter, tier=tier_filter)

    return jsonify({
        "transactions": [t.to_dict() for t in transactions],
        "count": len(transactions),
        "total_filtered": len(all_filtered),
        "limit": limit,
        "offset": offset,
        "filters": {"status": status_filter, "tier": tier_filter},
    })


@app.route("/api/v1/transactions/<transaction_id>", methods=["GET"])
def get_transaction(transaction_id):
    txn = transaction_log.get(transaction_id)
    if not txn:
        return jsonify({"error": "Transaction not found"}), 404

    result = txn.to_dict()
    tpa = TPAResponse(txn, type("R", (), {
        "approved": txn.status == "APPROVED",
        "response_code": txn.response_code,
        "auth_code": txn.auth_code,
        "issuer_auth_data": txn.issuer_auth_data,
        "arpc": txn.arpc,
    })())
    result["tpa_response"] = tpa.to_dict(include_definitions=True)
    return jsonify(result)


@app.route("/api/v1/transactions/<transaction_id>/tpa", methods=["GET"])
def get_transaction_tpa(transaction_id):
    txn = transaction_log.get(transaction_id)
    if not txn:
        return jsonify({"error": "Transaction not found"}), 404

    tpa = TPAResponse(txn, type("R", (), {
        "approved": txn.status == "APPROVED",
        "response_code": txn.response_code,
        "auth_code": txn.auth_code,
        "issuer_auth_data": txn.issuer_auth_data,
        "arpc": txn.arpc,
    })())
    return jsonify({
        "transaction_id": transaction_id,
        "rrn": txn.rrn,
        "tpa_fields": tpa.to_dict(include_definitions=True),
        "tpa_flat": tpa.to_flat(),
        "iso8583_view": tpa.to_iso8583_like(),
    })


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


# ── Tranches de montant ───────────────────────────────────────────────────────

@app.route("/api/v1/amount-tiers", methods=["GET"])
def list_amount_tiers():
    tiers = get_all_tiers()
    return jsonify({
        "tiers": [
            {
                "name": t.name, "label": t.label,
                "min_amount": t.min_amount, "max_amount": t.max_amount,
                "require_online": t.require_online, "require_arqc": t.require_arqc,
                "require_pin": t.require_pin,
                "auto_approve_offline": t.auto_approve_offline,
                "risk_level": t.risk_level, "floor_limit": t.floor_limit,
                "velocity_check": t.velocity_check,
                "max_daily_count": t.max_daily_count,
                "description": t.description,
                "is_custom": False,
            }
            for t in tiers
        ],
        "count": len(tiers),
    })


@app.route("/api/v1/amount-tiers", methods=["POST"])
def create_amount_tier():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400
    try:
        tier = add_custom_tier(data)
        return jsonify({
            "message": "Tier created",
            "tier": {
                "name": tier.name, "label": tier.label,
                "min_amount": tier.min_amount, "max_amount": tier.max_amount,
                "risk_level": tier.risk_level, "description": tier.description,
                "is_custom": True,
            }
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/v1/amount-tiers/<name>", methods=["DELETE"])
def delete_amount_tier(name):
    if delete_custom_tier(name):
        return jsonify({"message": "Tier deleted", "name": name})
    return jsonify({"error": "Tier not found or not a custom tier"}), 404


@app.route("/api/v1/amount-tiers/evaluate", methods=["GET"])
def evaluate_tier():
    try:
        amount = int(request.args.get("amount", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid amount"}), 400

    from emv.amount_rules import evaluate_amount
    decision = evaluate_amount(amount, "00", has_arqc=bool(request.args.get("has_arqc")))
    t = decision.tier
    return jsonify({
        "amount": amount,
        "amount_formatted": "{:.2f}".format(amount / 100),
        "tier": {
            "name": t.name, "label": t.label,
            "risk_level": t.risk_level, "description": t.description,
            "require_online": t.require_online, "require_arqc": t.require_arqc,
            "auto_approve_offline": t.auto_approve_offline,
            "max_daily_count": t.max_daily_count,
        },
        "decision": decision.to_dict(),
    })


# ── TPA ───────────────────────────────────────────────────────────────────────

@app.route("/api/v1/tpa/fields", methods=["GET"])
def get_tpa_fields():
    return jsonify({
        "fields": TPA_FIELD_DEFINITIONS,
        "count": len(TPA_FIELD_DEFINITIONS),
    })


# ── TLV ───────────────────────────────────────────────────────────────────────

@app.route("/api/v1/tlv/parse", methods=["POST"])
def parse_tlv():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400
    hex_data = (data.get("data") or data.get("hex", "")).replace(" ", "")
    if not hex_data:
        return jsonify({"error": "'data' field required"}), 400
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


# ── Cartes ────────────────────────────────────────────────────────────────────

@app.route("/api/v1/cards", methods=["GET"])
def list_cards():
    cards = card_db.all_cards()
    return jsonify({"cards": [c.to_dict(masked=True) for c in cards], "count": len(cards)})


@app.route("/api/v1/cards/<pan>", methods=["GET"])
def get_card(pan):
    card = card_db.get_card(pan.replace(" ", ""))
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
        return jsonify({"error": "pan, expiry, cardholder_name required"}), 400
    if card_db.get_card(pan):
        return jsonify({"error": "Card already exists"}), 409
    card = Card(
        pan=pan, expiry=expiry,
        cardholder_name=cardholder_name.upper(),
        psn=data.get("psn", "01"),
        status=data.get("status", CardStatus.ACTIVE),
        balance=int(data.get("balance", 100000)),
        daily_limit=int(data.get("daily_limit", 500000)),
    )
    card_db.add_card(card)
    return jsonify({"message": "Card created", "card": card.to_dict(masked=True)}), 201


@app.route("/api/v1/cards/<pan>/block", methods=["POST"])
def block_card(pan):
    if card_db.block_card(pan.replace(" ", "")):
        return jsonify({"message": "Card blocked"})
    return jsonify({"error": "Card not found"}), 404


# ── Stats ─────────────────────────────────────────────────────────────────────

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
