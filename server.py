"""
EMV Authorization Server v1.3.0 — Flask REST API
Évolutions intégrées : S1 (API Key), S2 (Rate Limit), S3 (PAN masking),
  D1 (Charts SSE), D2 (CSV export), D4 (Batch simulation), D6 (Dark/Light),
  E1 (CVV verification), P2 (JSON backup)
"""

import csv
import io
import json
import logging
import random
import re
import time
from datetime import datetime

from flask import Flask, request, jsonify, render_template_string, Response, stream_with_context
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from emv.authorization import authorize
from emv.tlv import parse, extract_emv_fields
from emv.amount_rules import get_all_tiers, evaluate_amount, add_custom_tier, delete_custom_tier
from emv.giecb import (CB_AIDS, CB_MCC_FLOOR_LIMITS, CB_CONTACTLESS, CB_CAP, CB_TAP,
                        CB_RESPONSE_CODES, CB_SCA_EXEMPTIONS, CB_SERVICE_INDICATORS,
                        identify_card, evaluate_cb_rules)
from emv.cvv import verify_cvv, generate_cvv_set
from iso8583.message import parse_from_dict
from models.card import card_db, Card, CardStatus
from models.transaction import transaction_log, TransactionStatus
from models.tpa_response import TPAResponse, TPA_FIELD_DEFINITIONS
from config import Config

# ── S3 : Masquage PAN dans les logs ─────────────────────────────────────────
_PAN_RE = re.compile(r'\b([3-6]\d{5})\d{6,10}(\d{4})\b')

class PANMaskingFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = _PAN_RE.sub(r'\1******\2', record.msg)
        if record.args:
            try:
                args = record.args
                if isinstance(args, (tuple, list)):
                    record.args = tuple(
                        _PAN_RE.sub(r'\1******\2', a) if isinstance(a, str) else a
                        for a in args)
                elif isinstance(args, dict):
                    record.args = {
                        k: _PAN_RE.sub(r'\1******\2', v) if isinstance(v, str) else v
                        for k, v in args.items()}
            except Exception:
                pass
        return True

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)
for h in logging.root.handlers:
    h.addFilter(PANMaskingFilter())

app = Flask(__name__)
app.config["SECRET_KEY"] = Config.SECRET_KEY
app.config["JSON_SORT_KEYS"] = False

# ── S2 : Rate Limiting ────────────────────────────────────────────────────────
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[Config.RATE_LIMIT_DEFAULT],
    storage_uri="memory://",
    strategy="fixed-window",
)

# ── S1 : Authentification API Key ─────────────────────────────────────────────
EXEMPT_PATHS = {"/", "/api/v1/health", "/api/v1/stats/stream"}

@app.before_request
def check_api_key():
    if not Config.API_KEY:
        return
    if request.path in EXEMPT_PATHS or not request.path.startswith("/api/"):
        return
    provided = request.headers.get("X-Api-Key", "")
    if provided != Config.API_KEY:
        return jsonify({"error": "Unauthorized — X-Api-Key invalide ou manquante"}), 401

# ── Scénarios batch pré-définis ───────────────────────────────────────────────
BATCH_TEST_PANS = [
    "4111111111111111",
    "5500000000000004",
    "4000000000000002",
    "4970100000000154",
    "4000000000000036",
]
BATCH_AMOUNTS = [100, 500, 1000, 2500, 5000, 9999, 15000, 30000,
                 50000, 100000, 200000, 500000, 1000000]
BATCH_MCCS    = [None, "5411", "5541", "5912", "5812", "7011", "4784"]
BATCH_MODES   = ["051", "071", "011"]
BATCH_TYPES   = ["00", "00", "00", "00", "01", "09"]

# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD HTML
# ═══════════════════════════════════════════════════════════════════════════════
DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="fr" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Serveur d'Autorisation EMV — GIE CB</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{
  --bg:#0a0d14;--surface:#1a1f2e;--surface2:#111827;--border:#2d3748;
  --text:#e2e8f0;--text2:#94a3b8;--text3:#64748b;
  --accent:#667eea;--accent2:#764ba2;
}
[data-theme="light"]{
  --bg:#f1f5f9;--surface:#ffffff;--surface2:#f8fafc;--border:#e2e8f0;
  --text:#1e293b;--text2:#475569;--text3:#94a3b8;
  --accent:#4f46e5;--accent2:#7c3aed;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;transition:background .2s,color .2s}
.header{background:linear-gradient(135deg,var(--surface),#16213e);border-bottom:1px solid var(--border);padding:16px 28px;display:flex;align-items:center;gap:12px}
[data-theme="light"] .header{background:linear-gradient(135deg,#4f46e5,#7c3aed)}
[data-theme="light"] .header h1,[data-theme="light"] .header p{color:#fff}
.logo{width:42px;height:42px;background:linear-gradient(135deg,var(--accent),var(--accent2));border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0}
.header h1{font-size:19px;font-weight:700;color:#fff}
.header p{color:rgba(255,255,255,.7);font-size:11px;margin-top:2px}
.header-right{margin-left:auto;display:flex;align-items:center;gap:10px}
.online-badge{background:#10b981;color:#fff;padding:4px 11px;border-radius:20px;font-size:11px;font-weight:600;display:flex;align-items:center;gap:5px}
.online-badge::before{content:'';width:6px;height:6px;background:#fff;border-radius:50%;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.theme-btn{background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.25);color:#fff;border-radius:7px;padding:5px 10px;cursor:pointer;font-size:12px;display:flex;align-items:center;gap:5px}
.theme-btn:hover{background:rgba(255,255,255,.25)}
.container{max-width:1440px;margin:0 auto;padding:20px 14px}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-bottom:18px}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;transition:background .2s}
.stat .lbl{color:var(--text3);font-size:10px;text-transform:uppercase;letter-spacing:.5px}
.stat .val{font-size:24px;font-weight:700;margin:4px 0 2px}
.stat .sub{color:var(--text3);font-size:11px}
.stat.blue .val{color:#60a5fa}.stat.green .val{color:#10b981}.stat.orange .val{color:#f59e0b}
.stat.purple .val{color:#a78bfa}.stat.red .val{color:#f87171}.stat.teal .val{color:#2dd4bf}
.stat.cb .val{color:#fbbf24}
.section{background:var(--surface);border:1px solid var(--border);border-radius:10px;margin-bottom:18px;overflow:hidden;transition:background .2s}
.tabs{display:flex;gap:1px;padding:12px 18px 0;border-bottom:1px solid var(--border);flex-wrap:wrap}
.tab{padding:6px 12px;border-radius:8px 8px 0 0;font-size:12px;cursor:pointer;color:var(--text3);background:transparent;border:none;border-bottom:2px solid transparent;white-space:nowrap}
.tab.active{color:#a78bfa;border-bottom-color:#a78bfa;background:rgba(167,139,250,.08)}
.tab-content{display:none}.tab-content.active{display:block}
label{display:block;color:var(--text2);font-size:12px;margin-bottom:4px;font-weight:500}
input,select,textarea{width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:6px;padding:7px 10px;font-size:13px;font-family:inherit;transition:background .2s,border-color .2s}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--accent)}
.form-group{margin-bottom:10px}
.btn{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;border:none;padding:9px 18px;border-radius:7px;font-size:13px;font-weight:600;cursor:pointer;width:100%;margin-top:2px}
.btn:hover{opacity:.9}.btn:disabled{opacity:.5;cursor:not-allowed}
.btn-sm{background:var(--surface2);color:var(--text2);border:1px solid var(--border);padding:4px 11px;border-radius:5px;font-size:12px;cursor:pointer}
.btn-sm:hover{border-color:var(--accent);color:var(--text)}
.btn-sm.success{background:#065f46;color:#34d399;border-color:#065f46}
.btn-sm.danger{background:#7f1d1d;color:#fca5a5;border:1px solid #991b1b}
.btn-sm.danger:hover{background:#991b1b}
.btn-sm.csv{background:#1a3a2a;color:#34d399;border-color:#065f46}
.btn-sm.batch{background:#1a2a4a;color:#60a5fa;border-color:#1e40af}
.result-box{background:var(--bg);border:1px solid var(--border);border-radius:7px;padding:12px;font-family:monospace;font-size:11px;color:var(--text2);min-height:160px;white-space:pre-wrap;word-break:break-all;max-height:360px;overflow-y:auto;transition:background .2s}
.result-box.approved{border-color:#10b981;color:#34d399}
.result-box.declined{border-color:#ef4444;color:#f87171}
.result-box.error{border-color:#f59e0b;color:#fbbf24}
.demo-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:18px}
@media(max-width:860px){.demo-grid{grid-template-columns:1fr}}
table{width:100%;border-collapse:collapse}
th{color:var(--text3);font-size:10px;text-transform:uppercase;padding:9px 12px;text-align:left;border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:9px 12px;font-size:12px;border-bottom:1px solid rgba(45,55,72,.4);vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(0,0,0,.15)}
.badge{display:inline-flex;align-items:center;padding:2px 7px;border-radius:9px;font-size:10px;font-weight:600;white-space:nowrap}
.badge.APPROVED,.badge.approved{background:#052e16;color:#34d399;border:1px solid #065f46}
.badge.DECLINED,.badge.declined{background:#2d0f0f;color:#f87171;border:1px solid #991b1b}
.badge.ERROR{background:#2d1f0a;color:#fbbf24;border:1px solid #92400e}
.badge.ONLINE{background:#1e2a4a;color:#60a5fa;border:1px solid #1e40af}
.badge.OFFLINE{background:#1a2a1a;color:#6ee7b7;border:1px solid #065f46}
.badge.LOW{background:#052e16;color:#34d399;border:1px solid #065f46}
.badge.MEDIUM{background:#2a2a0a;color:#fbbf24;border:1px solid #92400e}
.badge.HIGH{background:#2d1a0a;color:#f97316;border:1px solid #c2410c}
.badge.VERY_HIGH,.badge.CRITICAL{background:#2d0f0f;color:#f87171;border:1px solid #991b1b}
.badge.REFERRAL{background:#1f1a3a;color:#c4b5fd;border:1px solid #7c3aed}
.badge.ACTIVE{background:#052e16;color:#34d399;border:1px solid #065f46}
.badge.BLOCKED{background:#2d0f0f;color:#f87171;border:1px solid #991b1b}
.badge.EXPIRED{background:#2d1f0a;color:#fbbf24;border:1px solid #92400e}
.tier-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px;padding:16px}
.tier-card{background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:14px}
.tier-card .tier-name{font-weight:700;font-size:14px;color:var(--text)}
.tier-card .tier-range{font-family:monospace;font-size:12px;color:#a78bfa;margin:3px 0}
.tier-card .tier-desc{color:var(--text3);font-size:11px;margin:6px 0}
.tier-card .tier-flags{display:flex;flex-wrap:wrap;gap:4px;margin-top:8px}
.tier-card .flag{background:var(--surface);border:1px solid var(--border);color:var(--text2);font-size:10px;padding:1px 6px;border-radius:4px}
.tier-card .flag.on{background:#1a3a2a;border-color:#065f46;color:#34d399}
.cb-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;padding:16px}
.cb-card{background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:14px}
.cb-card h3{font-size:13px;font-weight:700;color:#fbbf24;margin-bottom:8px;display:flex;align-items:center;gap:6px}
.cb-param{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(45,55,72,.4);font-size:12px}
.cb-param:last-child{border-bottom:none}
.cb-param .k{color:var(--text3)}.cb-param .v{color:var(--text);font-family:monospace;font-weight:600;text-align:right;max-width:55%}
.cb-param .v.ok{color:#34d399}.cb-param .v.warn{color:#f59e0b}.cb-param .v.crit{color:#f87171}
.aid-tag{background:#1a1a3a;color:#a78bfa;font-family:monospace;font-size:11px;padding:1px 6px;border-radius:4px}
.hist-filters{display:flex;gap:8px;padding:12px 18px;border-bottom:1px solid var(--border);flex-wrap:wrap;align-items:flex-end}
.filter-group{display:flex;flex-direction:column;gap:3px;min-width:100px}
.filter-group label{margin-bottom:0}
.pagination{display:flex;gap:6px;align-items:center;padding:10px 18px;border-top:1px solid var(--border)}
.page-btn{background:var(--surface2);border:1px solid var(--border);color:var(--text2);padding:3px 11px;border-radius:5px;cursor:pointer;font-size:11px}
.page-btn:hover{border-color:var(--accent);color:var(--text)}
.page-btn:disabled{opacity:.4;cursor:not-allowed}
.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px;padding:16px}
.card-item{background:linear-gradient(135deg,var(--surface),var(--surface2));border:1px solid var(--border);border-radius:10px;padding:13px}
.card-item .pan{font-family:monospace;font-size:12px;color:#a78bfa;letter-spacing:2px}
.card-item .name{color:var(--text);font-weight:600;margin:5px 0 2px;font-size:13px}
.card-item .details{color:var(--text3);font-size:11px}
.card-item .balance{color:#34d399;font-size:16px;font-weight:700;margin-top:8px}
.card-actions{display:flex;gap:6px;margin-top:8px}
.ep{display:flex;align-items:flex-start;gap:8px;padding:10px 18px;border-bottom:1px solid rgba(45,55,72,.4)}
.ep:last-child{border-bottom:none}
.method{font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;min-width:48px;text-align:center;flex-shrink:0;margin-top:1px}
.method.POST{background:#1a3a2a;color:#34d399;border:1px solid #065f46}
.method.GET{background:#1a2a3a;color:#60a5fa;border:1px solid #1e40af}
.method.DELETE{background:#3a1a1a;color:#f87171;border:1px solid #991b1b}
.method.PUT{background:#2a2a1a;color:#fbbf24;border:1px solid #92400e}
.ep-path{font-family:monospace;color:#a78bfa;font-size:12px;font-weight:600}
.ep-desc{color:var(--text3);font-size:11px;margin-top:1px}
.section-hdr{padding:12px 18px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px}
.section-hdr h2{font-size:13px;font-weight:600;color:var(--text)}
.cb-eval-box{background:var(--bg);border:1px solid #fbbf24;border-radius:8px;padding:12px;font-family:monospace;font-size:11px;color:#fbbf24;white-space:pre-wrap;word-break:break-all;max-height:300px;overflow-y:auto;display:none}
/* Alertes visuelles (D5) */
.alert-banner{display:none;background:#2d1a0a;border:1px solid #c2410c;border-radius:8px;padding:10px 14px;margin:12px 18px;font-size:11px;color:#f97316}
.alert-banner.show{display:flex;align-items:center;gap:8px}
/* Charts */
.charts-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;padding:16px}
.chart-card{background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:14px}
.chart-card h3{font-size:12px;font-weight:600;color:var(--text2);text-transform:uppercase;letter-spacing:.5px;margin-bottom:12px}
.chart-wrap{position:relative;height:220px}
/* Batch panel */
.batch-panel{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:12px;margin-top:8px;display:none}
.batch-result{font-family:monospace;font-size:11px;color:var(--text2);white-space:pre-wrap;max-height:200px;overflow-y:auto;margin-top:8px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px}
/* CVV champ */
.cvv-row{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}
</style>
</head>
<body>
<div class="header">
  <div class="logo">💳</div>
  <div>
    <h1>Serveur d'Autorisation EMV — GIE CB</h1>
    <p>ISO 8583 · EMV 4.3 · ARQC/ARPC · GIE CB · CVV · Rate Limit · Backup JSON</p>
  </div>
  <div class="header-right">
    <button class="theme-btn" onclick="toggleTheme()" id="themeBtn">☀ Mode clair</button>
    <div class="online-badge">En ligne</div>
  </div>
</div>

<div class="container">
  <div class="stats-grid" id="statsGrid">
    <div class="stat blue"><div class="lbl">Total</div><div class="val" id="sTotal">–</div><div class="sub">transactions</div></div>
    <div class="stat green"><div class="lbl">Approuvées</div><div class="val" id="sApproved">–</div><div class="sub" id="sRate">–</div></div>
    <div class="stat red"><div class="lbl">Refusées</div><div class="val" id="sDeclined">–</div><div class="sub">refus</div></div>
    <div class="stat purple"><div class="lbl">Montant approuvé</div><div class="val" id="sAmount">–</div><div class="sub">total cumulé</div></div>
    <div class="stat teal"><div class="lbl">Chemin ONLINE</div><div class="val" id="sOnline">–</div><div class="sub">autorisations</div></div>
    <div class="stat cb"><div class="lbl">Schémas CB</div><div class="val" id="sCB">–</div><div class="sub" id="sCBDetail">—</div></div>
  </div>

  <!-- D5 : Alertes visuelles -->
  <div class="alert-banner" id="alertBanner">⚠ <span id="alertText"></span></div>

  <div class="section">
    <div class="tabs">
      <button class="tab active" onclick="showTab('demo',this)">Démo</button>
      <button class="tab" onclick="showTab('history',this)">Historique</button>
      <button class="tab" onclick="showTab('tpa',this)">Réponse TPA</button>
      <button class="tab" onclick="showTab('tiers',this)">Tranches</button>
      <button class="tab" onclick="showTab('giecb',this)">GIE CB</button>
      <button class="tab" onclick="showTab('stats',this)">Statistiques</button>
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
              <option value="4111111111111111">4111 1111 1111 1111 — JEAN DUPONT (Visa CB)</option>
              <option value="5500000000000004">5500 0000 0000 0004 — MARIE MARTIN (MC CB)</option>
              <option value="4000000000000002">4000 0000 0000 0002 — AHMED BENALI (Visa CB)</option>
              <option value="4970100000000154">4970 1000 0000 0154 — CB NATIVE TEST (CB)</option>
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
          <div class="cvv-row">
            <div class="form-group">
              <label>CVV2 (optionnel — vérification E1)</label>
              <input type="text" id="cvv2" placeholder="123" maxlength="4" pattern="\d{3,4}">
            </div>
            <div class="form-group">
              <label>Expiration carte (YYMM)</label>
              <input type="text" id="expiry" value="2812" maxlength="4">
            </div>
          </div>
          <div class="form-group">
            <label>Montant (centimes) — ex: 5000 = 50,00</label>
            <input type="number" id="amount" value="5000" min="1">
          </div>
          <div class="form-group">
            <label>Devise (ISO 4217)</label>
            <select id="currency">
              <option value="840">840 — USD</option><option value="978" selected>978 — EUR</option>
              <option value="826">826 — GBP</option><option value="504">504 — MAD</option>
              <option value="788">788 — TND</option><option value="012">012 — DZD</option>
            </select>
          </div>
          <div class="form-group">
            <label>Type de transaction</label>
            <select id="txnType">
              <option value="00">00 — Achat</option>
              <option value="01">01 — Avance liquidités (DAB)</option>
              <option value="09">09 — Achat + cashback</option>
              <option value="20">20 — Remboursement</option>
              <option value="22">22 — Consultation solde</option>
            </select>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
            <div class="form-group">
              <label>Mode saisie POS</label>
              <select id="posMode">
                <option value="051">051 — Puce contact</option>
                <option value="071">071 — Sans contact NFC</option>
                <option value="011">011 — Bande magnétique</option>
                <option value="010">010 — Manuel (MOTO)</option>
              </select>
            </div>
            <div class="form-group">
              <label>MCC commerçant</label>
              <select id="mcc">
                <option value="">— Défaut —</option>
                <option value="5411">5411 — Supermarché</option>
                <option value="5541">5541 — Station service</option>
                <option value="5912">5912 — Pharmacie</option>
                <option value="5812">5812 — Restaurant</option>
                <option value="7011">7011 — Hôtel</option>
                <option value="4111">4111 — Transport</option>
                <option value="4784">4784 — Péage</option>
              </select>
            </div>
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

          <!-- D4 — Simulation batch -->
          <div style="margin-top:12px;display:flex;gap:8px;align-items:center">
            <button class="btn-sm batch" onclick="toggleBatch()">⚡ Simulation batch</button>
            <span style="color:var(--text3);font-size:11px">Générer N transactions aléatoires</span>
          </div>
          <div class="batch-panel" id="batchPanel">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">
              <div class="form-group">
                <label>Nombre de transactions</label>
                <input type="number" id="batchCount" value="20" min="1" max="100">
              </div>
              <div class="form-group">
                <label>Graine aléatoire</label>
                <input type="number" id="batchSeed" placeholder="aléatoire">
              </div>
            </div>
            <button class="btn-sm batch" style="width:100%" onclick="runBatch()">▶ Lancer la simulation</button>
            <div class="batch-result" id="batchResult" style="display:none"></div>
          </div>
        </div>
        <div>
          <div class="form-group">
            <label>Tranche + règles GIE CB détectées</label>
            <div id="tierBox" style="background:var(--surface2);border:1px solid var(--border);border-radius:7px;padding:9px;font-size:11px;color:var(--text3);min-height:44px">—</div>
          </div>
          <div class="form-group">
            <label>Réponse serveur (JSON)</label>
            <div class="result-box" id="resultBox">En attente…</div>
          </div>
          <div class="form-group" style="margin-top:10px">
            <label>Réponse TPA — champs F00–CBA</label>
            <div class="result-box" id="tpaBox" style="min-height:100px">—</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══ HISTORIQUE ═══ -->
    <div id="tab-history" class="tab-content">
      <div class="hist-filters">
        <div class="filter-group"><label>Statut</label>
          <select id="fStatus" onchange="loadHistory()">
            <option value="">Tous</option><option value="APPROVED">Approuvé</option>
            <option value="DECLINED">Refusé</option><option value="ERROR">Erreur</option>
          </select></div>
        <div class="filter-group"><label>Tranche</label>
          <select id="fTier" onchange="loadHistory()">
            <option value="">Toutes</option><option value="MICRO">MICRO</option>
            <option value="SMALL">SMALL</option><option value="STANDARD">STANDARD</option>
            <option value="HIGH">HIGH</option><option value="VERY_HIGH">VERY_HIGH</option>
            <option value="CRITICAL">CRITICAL</option>
          </select></div>
        <div class="filter-group" style="min-width:70px"><label>/ page</label>
          <select id="fLimit" onchange="loadHistory()">
            <option value="20">20</option><option value="50">50</option><option value="100">100</option>
          </select></div>
        <button class="btn-sm" onclick="loadHistory()" style="align-self:flex-end">↻ Actualiser</button>
        <button class="btn-sm" onclick="exportJSON()" style="align-self:flex-end">⬇ JSON</button>
        <button class="btn-sm csv" onclick="exportCSV()" style="align-self:flex-end">⬇ CSV</button>
      </div>
      <div style="overflow-x:auto">
        <table>
          <thead><tr>
            <th></th><th>RRN</th><th>Carte</th><th>Montant</th>
            <th>Tranche</th><th>Risque</th><th>CB</th><th>SCA</th>
            <th>Chemin</th><th>Statut</th><th>Code</th><th>Date/Heure</th>
          </tr></thead>
          <tbody id="histTableBody">
            <tr><td colspan="12" style="text-align:center;color:var(--text3);padding:24px">Cliquez Actualiser</td></tr>
          </tbody>
        </table>
      </div>
      <div class="pagination">
        <button class="page-btn" id="prevBtn" onclick="histPage(-1)" disabled>← Préc.</button>
        <span id="pageInfo" style="color:var(--text3);font-size:11px">Page 1</span>
        <button class="page-btn" id="nextBtn" onclick="histPage(1)">Suiv. →</button>
        <span id="histTotal" style="color:var(--text3);font-size:11px;margin-left:auto"></span>
      </div>
    </div>

    <!-- ═══ RÉPONSE TPA ═══ -->
    <div id="tab-tpa" class="tab-content">
      <div class="section-hdr">
        <h2>Découpage TPA — Dernière transaction (champs F00–CBA)</h2>
        <button class="btn-sm" onclick="loadLastTPA()">↻ Rafraîchir</button>
      </div>
      <div id="tpaFullPanel" style="padding:14px">
        <div style="color:var(--text3);font-size:12px">Effectuez une autorisation pour voir le découpage TPA complet.</div>
      </div>
    </div>

    <!-- ═══ TRANCHES MONTANT ═══ -->
    <div id="tab-tiers" class="tab-content">
      <div class="section-hdr">
        <h2>Tranches de montant — Règles d'autorisation</h2>
        <button class="btn-sm" onclick="toggleAddTier()">+ Ajouter tranche</button>
      </div>
      <div id="addTierForm" style="display:none;padding:14px;border-bottom:1px solid var(--border);background:var(--bg)">
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:10px">
          <div class="form-group"><label>Nom</label><input type="text" id="tName" placeholder="CUSTOM"></div>
          <div class="form-group"><label>Label</label><input type="text" id="tLabel" placeholder="Ma tranche"></div>
          <div class="form-group"><label>Min (centimes)</label><input type="number" id="tMin" placeholder="0"></div>
          <div class="form-group"><label>Max (centimes)</label><input type="number" id="tMax" placeholder="100000"></div>
          <div class="form-group"><label>Niveau risque</label>
            <select id="tRisk"><option>LOW</option><option>MEDIUM</option><option>HIGH</option><option>VERY_HIGH</option><option>CRITICAL</option></select></div>
          <div class="form-group"><label>Limite/jour (nb)</label><input type="number" id="tDailyCount" placeholder="illimité"></div>
          <div class="form-group"><label>Options</label>
            <label style="display:flex;gap:5px;align-items:center;margin-top:4px"><input type="checkbox" id="tOnline" checked> Online</label>
            <label style="display:flex;gap:5px;align-items:center;margin-top:3px"><input type="checkbox" id="tArqc" checked> ARQC</label>
            <label style="display:flex;gap:5px;align-items:center;margin-top:3px"><input type="checkbox" id="tOffline"> Offline OK</label></div>
        </div>
        <div class="form-group"><label>Description</label><input type="text" id="tDesc" placeholder="Description"></div>
        <div style="display:flex;gap:8px;margin-top:6px">
          <button class="btn-sm" onclick="addTier()" style="background:var(--accent);color:#fff;border-color:var(--accent)">Créer</button>
          <button class="btn-sm" onclick="toggleAddTier()">Annuler</button>
        </div>
      </div>
      <div class="tier-grid" id="tierGrid">Chargement…</div>
    </div>

    <!-- ═══ GIE CB ═══ -->
    <div id="tab-giecb" class="tab-content">
      <div class="section-hdr">
        <h2>Règles GIE CB — Paramètres d'autorisation</h2>
        <button class="btn-sm" onclick="loadCBRules()">↻ Actualiser</button>
      </div>
      <div style="padding:14px;border-bottom:1px solid var(--border);background:var(--bg)">
        <div style="font-size:12px;color:#fbbf24;font-weight:600;margin-bottom:10px">⚡ Évaluateur de règles CB en temps réel</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px;margin-bottom:8px">
          <div class="form-group"><label>PAN</label><input type="text" id="cbPan" value="4111111111111111" placeholder="PAN"></div>
          <div class="form-group"><label>Montant (centimes)</label><input type="number" id="cbAmt" value="5000"></div>
          <div class="form-group"><label>MCC</label>
            <select id="cbMcc"><option value="">Défaut</option><option value="5411">5411 Supermarché</option>
              <option value="5541">5541 Station service</option><option value="5912">5912 Pharmacie</option>
              <option value="5812">5812 Restaurant</option><option value="7011">7011 Hôtel</option>
            </select></div>
          <div class="form-group"><label>Mode</label>
            <select id="cbMode"><option value="051">Contact</option><option value="071">Sans contact NFC</option><option value="011">Bande magnétique</option></select></div>
          <div class="form-group"><label>Type</label>
            <select id="cbType"><option value="00">Achat</option><option value="01">DAB</option><option value="20">Remboursement</option></select></div>
        </div>
        <button class="btn-sm" onclick="evalCB()" style="background:#b45309;color:#fef3c7;border-color:#b45309">Évaluer les règles CB →</button>
        <div class="cb-eval-box" id="cbEvalBox" style="margin-top:10px"></div>
      </div>
      <div class="cb-grid" id="cbGrid">Chargement…</div>
      <div style="padding:14px;border-top:1px solid var(--border)">
        <div style="font-size:12px;font-weight:600;color:#fbbf24;margin-bottom:10px">AIDs CB reconnus</div>
        <div style="overflow-x:auto">
          <table id="aidTable">
            <thead><tr><th>AID</th><th>Nom application</th><th>Schéma</th><th>Brand</th><th>Contactless</th></tr></thead>
            <tbody id="aidBody"></tbody>
          </table>
        </div>
      </div>
      <div style="padding:14px;border-top:1px solid var(--border)">
        <div style="font-size:12px;font-weight:600;color:#fbbf24;margin-bottom:10px">Floor Limits CB par MCC</div>
        <div style="overflow-x:auto">
          <table id="floorTable">
            <thead><tr><th>MCC</th><th>Catégorie</th><th>Floor Limit</th><th>Remarque</th></tr></thead>
            <tbody id="floorBody"></tbody>
          </table>
        </div>
      </div>
      <div style="padding:14px;border-top:1px solid var(--border)">
        <div style="font-size:12px;font-weight:600;color:#fbbf24;margin-bottom:10px">Codes réponse GIE CB</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:6px" id="cbCodesGrid"></div>
      </div>
    </div>

    <!-- ═══ STATISTIQUES (D1) ═══ -->
    <div id="tab-stats" class="tab-content">
      <div class="section-hdr">
        <h2>Statistiques — Graphiques temps réel</h2>
        <div style="display:flex;gap:8px;align-items:center">
          <span id="sseStatus" style="font-size:11px;color:var(--text3)">● En attente</span>
          <button class="btn-sm" onclick="loadStats();renderCharts()">↻ Forcer mise à jour</button>
        </div>
      </div>
      <div class="charts-grid">
        <div class="chart-card">
          <h3>Résultats des transactions</h3>
          <div class="chart-wrap"><canvas id="chartStatus"></canvas></div>
        </div>
        <div class="chart-card">
          <h3>Répartition par tranche de montant</h3>
          <div class="chart-wrap"><canvas id="chartTiers"></canvas></div>
        </div>
        <div class="chart-card">
          <h3>Schémas CB</h3>
          <div class="chart-wrap"><canvas id="chartSchemes"></canvas></div>
        </div>
        <div class="chart-card">
          <h3>Chemins d'autorisation</h3>
          <div class="chart-wrap"><canvas id="chartPaths"></canvas></div>
        </div>
      </div>
      <!-- Snapshot info -->
      <div style="padding:14px 18px;border-top:1px solid var(--border)">
        <div style="font-size:12px;color:var(--text3)">
          💾 Backup JSON automatique toutes les 2 min — fichier : <code style="color:#a78bfa">data/snapshot.json</code>
        </div>
      </div>
    </div>

    <!-- ═══ CARTES ═══ -->
    <div id="tab-cards" class="tab-content">
      <div class="section-hdr">
        <h2>Cartes de test</h2>
        <div style="display:flex;gap:8px">
          <button class="btn-sm" onclick="loadCards()">↻ Actualiser</button>
          <button class="btn-sm" onclick="showCVVPanel()" style="background:#1a1a3a;color:#a78bfa;border-color:#4c1d95">🔑 Vérif. CVV</button>
        </div>
      </div>
      <!-- CVV check panel -->
      <div id="cvvPanel" style="display:none;padding:14px;border-bottom:1px solid var(--border);background:var(--bg)">
        <div style="font-size:12px;color:#a78bfa;font-weight:600;margin-bottom:10px">🔑 Vérification CVV — E1</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px;margin-bottom:8px">
          <div class="form-group"><label>PAN</label><input type="text" id="cvvCheckPan" value="4111111111111111"></div>
          <div class="form-group"><label>Expiration (YYMM)</label><input type="text" id="cvvCheckExpiry" value="2812" maxlength="4"></div>
          <div class="form-group"><label>Code CVV</label><input type="text" id="cvvCheckCode" placeholder="123" maxlength="4"></div>
          <div class="form-group"><label>Type</label>
            <select id="cvvCheckType"><option value="CVV2">CVV2 (e-commerce)</option><option value="CVV1">CVV1 (mag strip)</option><option value="iCVV">iCVV (puce)</option></select></div>
        </div>
        <div style="display:flex;gap:8px">
          <button class="btn-sm" onclick="checkCVV()" style="background:#4c1d95;color:#c4b5fd;border-color:#7c3aed">Vérifier →</button>
          <button class="btn-sm" onclick="generateCVV()">Générer les codes CVV</button>
        </div>
        <div id="cvvResult" style="margin-top:10px;font-size:12px;display:none"></div>
      </div>
      <div class="card-grid" id="cardGrid"><div style="color:var(--text3);padding:16px">Chargement…</div></div>
    </div>

    <!-- ═══ API ═══ -->
    <div id="tab-api" class="tab-content">
      <div style="padding:12px 18px;border-bottom:1px solid var(--border);font-size:11px;color:var(--text3)">
        Version <strong style="color:#a78bfa">1.3.0-GIE-CB</strong> —
        Auth: <span id="apiKeyStatus" style="color:#fbbf24">Vérification…</span> —
        Rate limit: <span style="color:#60a5fa">300/min global · 30/min /authorize · 5/min /batch</span>
      </div>
      <div class="ep"><span class="method POST">POST</span><div><div class="ep-path">/api/v1/authorize</div><div class="ep-desc">Autorisation EMV (tranche + règles GIE CB + TPA + vérification CVV optionnelle)</div></div></div>
      <div class="ep"><span class="method POST">POST</span><div><div class="ep-path">/api/v1/authorize/iso8583</div><div class="ep-desc">Autorisation via message ISO 8583 complet</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/transactions</div><div class="ep-desc">Historique paginé — ?status=&tier=&limit=&offset=</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/transactions/export</div><div class="ep-desc">Export CSV ou JSON — ?format=csv|json&limit=&status=</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/transactions/&lt;id&gt;</div><div class="ep-desc">Détail complet + champs TPA CB d'une transaction</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/transactions/&lt;id&gt;/tpa</div><div class="ep-desc">Réponse TPA découpée (F00–CBA)</div></div></div>
      <div class="ep"><span class="method POST">POST</span><div><div class="ep-path">/api/v1/batch/simulate</div><div class="ep-desc">Simuler N transactions aléatoires — body: {count, seed}</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/stats/stream</div><div class="ep-desc">Statistiques temps réel — Server-Sent Events (text/event-stream)</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/amount-tiers</div><div class="ep-desc">Liste toutes les tranches de montant</div></div></div>
      <div class="ep"><span class="method POST">POST</span><div><div class="ep-path">/api/v1/amount-tiers</div><div class="ep-desc">Créer une tranche personnalisée</div></div></div>
      <div class="ep"><span class="method DELETE">DELETE</span><div><div class="ep-path">/api/v1/amount-tiers/&lt;name&gt;</div><div class="ep-desc">Supprimer une tranche personnalisée</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/amount-tiers/evaluate?amount=5000</div><div class="ep-desc">Évaluer la tranche pour un montant</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/giecb/rules</div><div class="ep-desc">Tous les paramètres GIE CB (CAP, TAP, contactless, SCA)</div></div></div>
      <div class="ep"><span class="method POST">POST</span><div><div class="ep-path">/api/v1/giecb/evaluate</div><div class="ep-desc">Évaluer les règles CB pour un contexte de transaction</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/giecb/aids</div><div class="ep-desc">Liste tous les AIDs CB connus</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/giecb/floor-limits</div><div class="ep-desc">Floor limits CB par MCC</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/giecb/response-codes</div><div class="ep-desc">Codes réponse GIE CB</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/cvv/generate</div><div class="ep-desc">Générer CVV1+CVV2+iCVV pour un PAN+expiry (test seulement)</div></div></div>
      <div class="ep"><span class="method POST">POST</span><div><div class="ep-path">/api/v1/cvv/verify</div><div class="ep-desc">Vérifier un CVV — body: {pan,expiry_yymm,cvv,cvv_type}</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/tpa/fields</div><div class="ep-desc">Définitions de tous les champs TPA (F00–CBA)</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/cards</div><div class="ep-desc">Liste des cartes (PAN masqué, infos CB)</div></div></div>
      <div class="ep"><span class="method POST">POST</span><div><div class="ep-path">/api/v1/cards</div><div class="ep-desc">Créer une nouvelle carte</div></div></div>
      <div class="ep"><span class="method POST">POST</span><div><div class="ep-path">/api/v1/cards/&lt;pan&gt;/block</div><div class="ep-desc">Bloquer une carte</div></div></div>
      <div class="ep"><span class="method POST">POST</span><div><div class="ep-path">/api/v1/cards/&lt;pan&gt;/unblock</div><div class="ep-desc">Débloquer une carte BLOCKED ou RESTRICTED</div></div></div>
      <div class="ep"><span class="method POST">POST</span><div><div class="ep-path">/api/v1/tlv/parse</div><div class="ep-desc">Décodage BER-TLV du champ 55</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/stats</div><div class="ep-desc">Statistiques globales</div></div></div>
      <div class="ep"><span class="method GET">GET</span><div><div class="ep-path">/api/v1/health</div><div class="ep-desc">Santé du serveur</div></div></div>
    </div>
  </div>
</div>

<script>
let histOffset=0,histLimit=20,histTotal=0,lastTxnId=null;
let chartStatus=null,chartTiers=null,chartSchemes=null,chartPaths=null;
let sseSource=null;

// ── D6 : Thème clair/sombre ──────────────────────────────────────────────────
function toggleTheme(){
  const html=document.documentElement;
  const isLight=html.getAttribute('data-theme')==='light';
  html.setAttribute('data-theme',isLight?'dark':'light');
  document.getElementById('themeBtn').textContent=isLight?'☀ Mode clair':'🌙 Mode sombre';
  updateChartsTheme();
  localStorage.setItem('emv-theme',isLight?'dark':'light');
}
(function(){
  const saved=localStorage.getItem('emv-theme');
  if(saved==='light'){
    document.documentElement.setAttribute('data-theme','light');
    document.getElementById('themeBtn').textContent='🌙 Mode sombre';
  }
})();

function showTab(n,el){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t=>t.classList.remove('active'));
  if(el)el.classList.add('active');
  document.getElementById('tab-'+n).classList.add('active');
  if(n==='history')loadHistory();
  if(n==='tpa')loadLastTPA();
  if(n==='tiers')loadTiers();
  if(n==='giecb')loadCBRules();
  if(n==='stats')renderCharts();
  if(n==='cards')loadCards();
  if(n==='api')checkAPIKeyStatus();
}

function fillCard(){
  const v=document.getElementById('panSelect').value;
  document.getElementById('customPanGroup').style.display=v==='custom'?'block':'none';
}
function getPan(){
  const v=document.getElementById('panSelect').value;
  return v==='custom'?document.getElementById('customPan').value.replace(/\s/g,''):v;
}

// Évaluation tranche en temps réel
document.getElementById('amount').addEventListener('input',async function(){
  const amt=parseInt(this.value)||0; if(!amt)return;
  try{
    const r=await fetch('/api/v1/amount-tiers/evaluate?amount='+amt);
    const d=await r.json(); const t=d.tier;
    const rc={'LOW':'#10b981','MEDIUM':'#f59e0b','HIGH':'#f97316','VERY_HIGH':'#ef4444','CRITICAL':'#dc2626'}[t.risk_level]||'#94a3b8';
    document.getElementById('tierBox').innerHTML=
      '<span style="font-weight:700;color:'+rc+'">'+t.name+'</span> — '+t.label+
      ' | Risque: <span style="color:'+rc+'">'+t.risk_level+'</span>'+
      (t.require_online?' | <span style="color:#60a5fa">ONLINE</span>':' | <span style="color:#6ee7b7">OFFLINE</span>')+
      (t.max_daily_count?' | <span style="color:#fbbf24">Max '+t.max_daily_count+'/j</span>':'');
  }catch(e){}
});

// ── Autorisation ─────────────────────────────────────────────────────────────
async function sendAuthorization(){
  const btn=document.getElementById('authBtn');
  btn.disabled=true;btn.textContent='Traitement…';
  const cvv2=document.getElementById('cvv2').value.trim();
  const expiry=document.getElementById('expiry').value.trim();
  const payload={
    pan:getPan(),amount:parseInt(document.getElementById('amount').value),
    currency:document.getElementById('currency').value,
    transaction_type:document.getElementById('txnType').value,
    terminal_id:document.getElementById('terminalId').value,
    pos_entry_mode:document.getElementById('posMode').value,
    mcc:document.getElementById('mcc').value||null,
    is_contactless:document.getElementById('posMode').value==='071',
    merchant_id:'MERCH001',merchant_name:'BOUTIQUE TEST',
    field_55:document.getElementById('emvData').value.trim()||null,
    skip_crypto:!document.getElementById('emvData').value.trim(),
  };
  if(cvv2)payload.cvv2=cvv2;
  if(expiry)payload.expiry_yymm=expiry;
  try{
    const resp=await fetch('/api/v1/authorize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const data=await resp.json();
    const box=document.getElementById('resultBox');
    const disp={...data};delete disp.tpa_response;
    box.textContent=JSON.stringify(disp,null,2);
    box.className='result-box '+(data.approved?'approved':'declined');
    if(data.tpa_response){
      document.getElementById('tpaBox').textContent=formatTPA(data.tpa_response);
    }
    if(data.transaction)lastTxnId=data.transaction.id;
    loadStats();checkAlerts();
  }catch(e){
    document.getElementById('resultBox').textContent='Erreur: '+e.message;
    document.getElementById('resultBox').className='result-box error';
  }
  btn.disabled=false;btn.textContent="Envoyer la demande d'autorisation →";
}

function formatTPA(tpa){
  const lines=['┌──────┬────────────────────────────┬──────────────────────────┐',
               '│ Chmp │ Nom                        │ Valeur                   │',
               '├──────┼────────────────────────────┼──────────────────────────┤'];
  for(const[k,v]of Object.entries(tpa)){
    const name=(v.name||k).slice(0,28).padEnd(28);
    let val=v.value; if(Array.isArray(val))val=val.join('; ');
    val=String(val||'').slice(0,24).padEnd(24);
    lines.push('│ '+k.padEnd(4)+' │ '+name+' │ '+val+' │');
  }
  lines.push('└──────┴────────────────────────────┴──────────────────────────┘');
  return lines.join('\n');
}

// ── Stats ─────────────────────────────────────────────────────────────────────
let _lastStats=null;
async function loadStats(){
  try{
    const r=await fetch('/api/v1/stats');const d=await r.json();const ts=d.transaction_stats;
    _lastStats=ts;
    document.getElementById('sTotal').textContent=ts.total;
    document.getElementById('sApproved').textContent=ts.approved;
    document.getElementById('sDeclined').textContent=ts.declined;
    document.getElementById('sRate').textContent=ts.approval_rate;
    document.getElementById('sAmount').textContent=(ts.total_approved_amount/100).toLocaleString('fr-FR',{minimumFractionDigits:2})+'€';
    document.getElementById('sOnline').textContent=ts.by_auth_path?.ONLINE||0;
    const cb=ts.by_cb_scheme||{};
    const total=Object.values(cb).reduce((a,b)=>a+b,0);
    document.getElementById('sCB').textContent=total;
    document.getElementById('sCBDetail').textContent=Object.entries(cb).map(([k,v])=>k+':'+v).join(' ');
    if(document.getElementById('tab-stats').classList.contains('active'))updateChartsData(ts);
  }catch(e){}
}

function checkAlerts(){
  if(!_lastStats)return;
  const banner=document.getElementById('alertBanner');
  const msgs=[];
  const total=_lastStats.total||0;
  const approved=_lastStats.approved||0;
  if(total>5&&approved/total<0.5)msgs.push('⚠ Taux d\'approbation bas ('+_lastStats.approval_rate+')');
  if(msgs.length>0){
    document.getElementById('alertText').textContent=msgs.join(' | ');
    banner.classList.add('show');
  }else{
    banner.classList.remove('show');
  }
}

// ── D1 : SSE temps réel ───────────────────────────────────────────────────────
function startSSE(){
  if(sseSource)return;
  try{
    sseSource=new EventSource('/api/v1/stats/stream');
    sseSource.onmessage=function(e){
      try{
        const ts=JSON.parse(e.data);
        _lastStats=ts;
        document.getElementById('sTotal').textContent=ts.total||0;
        document.getElementById('sApproved').textContent=ts.approved||0;
        document.getElementById('sDeclined').textContent=ts.declined||0;
        document.getElementById('sRate').textContent=ts.approval_rate||'0%';
        document.getElementById('sAmount').textContent=((ts.total_approved_amount||0)/100).toLocaleString('fr-FR',{minimumFractionDigits:2})+'€';
        document.getElementById('sOnline').textContent=(ts.by_auth_path||{}).ONLINE||0;
        const cb=ts.by_cb_scheme||{};
        document.getElementById('sCB').textContent=Object.values(cb).reduce((a,b)=>a+b,0);
        document.getElementById('sCBDetail').textContent=Object.entries(cb).map(([k,v])=>k+':'+v).join(' ');
        document.getElementById('sseStatus').textContent='● SSE actif';
        document.getElementById('sseStatus').style.color='#10b981';
        if(document.getElementById('tab-stats').classList.contains('active'))updateChartsData(ts);
        checkAlerts();
      }catch(err){}
    };
    sseSource.onerror=function(){
      document.getElementById('sseStatus').textContent='● SSE déconnecté';
      document.getElementById('sseStatus').style.color='#f87171';
    };
  }catch(e){}
}

// ── D1 : Charts.js ────────────────────────────────────────────────────────────
function getChartTextColor(){
  return getComputedStyle(document.documentElement).getPropertyValue('--text2').trim()||'#94a3b8';
}
function getChartGridColor(){
  return getComputedStyle(document.documentElement).getPropertyValue('--border').trim()||'#2d3748';
}

function renderCharts(){
  loadStats();
  const tc=getChartTextColor();
  const gc=getChartGridColor();
  const defaults={
    plugins:{legend:{labels:{color:tc,font:{size:11}}}},
    responsive:true,maintainAspectRatio:false,
  };
  const barDefaults={...defaults,scales:{x:{ticks:{color:tc},grid:{color:gc}},y:{ticks:{color:tc},grid:{color:gc}}}};

  if(!chartStatus){
    chartStatus=new Chart(document.getElementById('chartStatus'),{
      type:'doughnut',data:{labels:['Approuvées','Refusées','Erreurs'],
        datasets:[{data:[0,0,0],backgroundColor:['#10b981','#ef4444','#f59e0b'],borderWidth:0}]},
      options:{...defaults}});
  }
  if(!chartTiers){
    chartTiers=new Chart(document.getElementById('chartTiers'),{
      type:'bar',data:{labels:[],datasets:[{label:'Transactions',data:[],backgroundColor:'#667eea',borderRadius:4}]},
      options:{...barDefaults}});
  }
  if(!chartSchemes){
    chartSchemes=new Chart(document.getElementById('chartSchemes'),{
      type:'doughnut',data:{labels:[],datasets:[{data:[],backgroundColor:['#fbbf24','#60a5fa','#10b981','#f87171','#a78bfa'],borderWidth:0}]},
      options:{...defaults}});
  }
  if(!chartPaths){
    chartPaths=new Chart(document.getElementById('chartPaths'),{
      type:'bar',data:{labels:['ONLINE','OFFLINE','REFERRAL'],datasets:[{label:'Transactions',data:[0,0,0],backgroundColor:['#60a5fa','#6ee7b7','#c4b5fd'],borderRadius:4}]},
      options:{...barDefaults}});
  }
}

function updateChartsData(ts){
  if(!chartStatus)return;
  chartStatus.data.datasets[0].data=[ts.approved||0,ts.declined||0,ts.errors||0];
  chartStatus.update('none');

  const tiers=ts.by_tier||{};
  chartTiers.data.labels=Object.keys(tiers);
  chartTiers.data.datasets[0].data=Object.values(tiers);
  chartTiers.update('none');

  const schemes=ts.by_cb_scheme||{};
  chartSchemes.data.labels=Object.keys(schemes);
  chartSchemes.data.datasets[0].data=Object.values(schemes);
  chartSchemes.update('none');

  const paths=ts.by_auth_path||{};
  chartPaths.data.datasets[0].data=[(paths.ONLINE||0),(paths.OFFLINE||0),(paths.REFERRAL||0)];
  chartPaths.update('none');
}

function updateChartsTheme(){
  const tc=getChartTextColor();
  const gc=getChartGridColor();
  [chartStatus,chartTiers,chartSchemes,chartPaths].forEach(c=>{
    if(!c)return;
    if(c.options.plugins?.legend?.labels)c.options.plugins.legend.labels.color=tc;
    if(c.options.scales?.x){c.options.scales.x.ticks.color=tc;c.options.scales.x.grid.color=gc;}
    if(c.options.scales?.y){c.options.scales.y.ticks.color=tc;c.options.scales.y.grid.color=gc;}
    c.update();
  });
}

// ── D4 : Batch simulation ─────────────────────────────────────────────────────
function toggleBatch(){
  const p=document.getElementById('batchPanel');
  p.style.display=p.style.display==='none'?'block':'none';
}
async function runBatch(){
  const count=parseInt(document.getElementById('batchCount').value)||20;
  const seed=document.getElementById('batchSeed').value;
  const btn=event.target;
  btn.disabled=true;btn.textContent='Simulation en cours…';
  const payload={count:Math.min(count,100)};
  if(seed)payload.seed=parseInt(seed);
  try{
    const r=await fetch('/api/v1/batch/simulate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const d=await r.json();
    const results=d.results||[];
    const approved=results.filter(x=>x.approved).length;
    const declined=results.length-approved;
    let txt='Simulation terminée : '+results.length+' transactions\n';
    txt+='Approuvées: '+approved+' | Refusées: '+declined+'\n';
    txt+='Montant total approuvé: '+(d.total_approved_amount/100).toLocaleString('fr-FR',{minimumFractionDigits:2})+'€\n\n';
    results.forEach(r=>{
      const sym=r.approved?'✓':'✗';
      txt+=sym+' PAN:...'+r.pan.slice(-4)+' '+String(r.amount/100).padStart(8)+' € '+r.response_code+' '+r.tier+'\n';
    });
    const res=document.getElementById('batchResult');
    res.style.display='block';res.textContent=txt;
    loadStats();checkAlerts();
  }catch(e){alert('Erreur batch: '+e.message);}
  btn.disabled=false;btn.textContent='▶ Lancer la simulation';
}

// ── D2 : Export CSV / JSON ─────────────────────────────────────────────────────
async function exportJSON(){
  const r=await fetch('/api/v1/transactions?limit=2000');const d=await r.json();
  const blob=new Blob([JSON.stringify(d,null,2)],{type:'application/json'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);
  a.download='historique_'+new Date().toISOString().slice(0,10)+'.json';a.click();
}
async function exportCSV(){
  const status=document.getElementById('fStatus').value;
  const tier=document.getElementById('fTier').value;
  let url='/api/v1/transactions/export?format=csv&limit=2000';
  if(status)url+='&status='+status;
  if(tier)url+='&tier='+tier;
  const r=await fetch(url);
  const text=await r.text();
  const blob=new Blob(['\uFEFF'+text],{type:'text/csv;charset=utf-8'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);
  a.download='historique_'+new Date().toISOString().slice(0,10)+'.csv';a.click();
}

// ── Historique ─────────────────────────────────────────────────────────────────
async function loadHistory(){histOffset=0;await fetchHistory();}
async function histPage(dir){histOffset=Math.max(0,histOffset+dir*histLimit);await fetchHistory();}
async function fetchHistory(){
  const status=document.getElementById('fStatus').value;
  const tier=document.getElementById('fTier').value;
  histLimit=parseInt(document.getElementById('fLimit').value)||20;
  let url='/api/v1/transactions?limit='+histLimit+'&offset='+histOffset;
  if(status)url+='&status='+status; if(tier)url+='&tier='+tier;
  try{
    const r=await fetch(url);const d=await r.json();
    histTotal=d.total_filtered||0;
    document.getElementById('pageInfo').textContent='Page '+(Math.floor(histOffset/histLimit)+1);
    document.getElementById('histTotal').textContent=histTotal+' résultats';
    document.getElementById('prevBtn').disabled=histOffset===0;
    document.getElementById('nextBtn').disabled=histOffset+histLimit>=histTotal;
    const tbody=document.getElementById('histTableBody');
    if(!d.transactions?.length){
      tbody.innerHTML='<tr><td colspan="12" style="text-align:center;color:var(--text3);padding:20px">Aucune transaction</td></tr>';return;
    }
    const rc={'LOW':'#10b981','MEDIUM':'#f59e0b','HIGH':'#f97316','VERY_HIGH':'#ef4444','CRITICAL':'#dc2626'};
    tbody.innerHTML=d.transactions.map(t=>`
      <tr style="cursor:pointer" onclick="toggleDetail('${t.id}')">
        <td style="color:var(--text3);font-size:10px">▶</td>
        <td style="font-family:monospace;font-size:10px;color:var(--text2)">${t.rrn||'—'}</td>
        <td style="font-family:monospace;color:#a78bfa;font-size:11px">${t.pan}</td>
        <td style="font-weight:600;color:var(--text)">${t.amount_formatted} ${t.currency}</td>
        <td style="font-family:monospace;font-size:10px;color:#c4b5fd">${t.amount_tier||'—'}</td>
        <td><span class="badge ${t.risk_level||''}">${t.risk_level||'—'}</span></td>
        <td style="font-size:11px;color:#fbbf24">${t.cb_brand||'—'}</td>
        <td style="font-size:10px;color:var(--text2)">${t.cb_sca_exemption||'—'}</td>
        <td><span class="badge ${t.auth_path||''}">${t.auth_path||'—'}</span></td>
        <td><span class="badge ${t.status}">${t.status}</span></td>
        <td style="font-family:monospace;font-weight:700;color:${t.response_code==='00'?'#34d399':'#f87171'}">${t.response_code||'—'}</td>
        <td style="color:var(--text3);font-size:10px">${(t.created_at||'').replace('T',' ').split('.')[0]}</td>
      </tr>
      <tr id="detail-${t.id}" style="display:none">
        <td colspan="12" style="padding:0">
          <div style="background:var(--bg);border-top:1px solid var(--border);padding:12px 18px">
            <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px;margin-bottom:10px">
              ${fr('ID',t.id)}${fr('RRN',t.rrn)}${fr('Commerçant',t.merchant_name)}
              ${fr('Terminal',t.terminal_id)}${fr('Motif refus',t.decline_reason)}
              ${fr('CB Schéma',t.cb_scheme)}${fr('CB SCA',t.cb_sca_exemption)}
              ${fr('Contactless',t.cb_is_contactless?'OUI':'NON')}
              ${fr('Code CB',t.cb_response_code)}${fr('Motif CB',t.cb_decline_reason)}
              ${fr('ARQC',t.arqc)}${fr('ARPC',t.arpc)}
            </div>
            <button class="btn-sm" onclick="loadTPA('${t.id}')">Voir TPA complet</button>
          </div>
        </td>
      </tr>
    `).join('');
  }catch(e){console.error(e)}
}
function fr(label,val){
  if(!val)return '';
  return '<div><div style="color:var(--text3);font-size:9px;text-transform:uppercase">'+label+'</div><div style="font-family:monospace;font-size:10px;color:var(--text);word-break:break-all;margin-top:1px">'+val+'</div></div>';
}
const _open={};
function toggleDetail(id){
  const row=document.getElementById('detail-'+id);
  if(!row)return;
  if(_open[id]){row.style.display='none';delete _open[id];}
  else{row.style.display='table-row';_open[id]=1;}
}

// ── TPA ────────────────────────────────────────────────────────────────────────
async function loadLastTPA(){
  if(!lastTxnId){const r=await fetch('/api/v1/transactions?limit=1');const d=await r.json();
    if(d.transactions?.length)lastTxnId=d.transactions[0].id;else return;}
  await loadTPA(lastTxnId);
}
async function loadTPA(id){
  try{
    const r=await fetch('/api/v1/transactions/'+id+'/tpa');const d=await r.json();
    const panel=document.getElementById('tpaFullPanel');
    const rows=Object.entries(d.tpa_fields||{}).map(([k,v])=>{
      let val=v.value;if(Array.isArray(val))val=val.join('; ');
      const isCB=k.startsWith('CB')?'style="background:rgba(251,191,36,.05)"':'';
      return '<tr '+isCB+'><td style="font-family:monospace;color:#fbbf24;font-weight:700;width:55px">'+k+'</td><td style="color:var(--text3);font-size:10px;width:200px">'+esc(v.name||k)+'</td><td style="color:var(--text2);font-size:10px;width:240px">'+esc(v.description||'')+'</td><td style="font-family:monospace;font-size:11px;color:var(--text);word-break:break-all">'+esc(String(val||''))+'</td></tr>';
    }).join('');
    panel.innerHTML='<div style="font-size:11px;color:var(--text3);margin-bottom:10px">Transaction: <span style="font-family:monospace;color:#a78bfa">'+id+'</span> — <span style="color:#fbbf24">champs CB en surbrillance</span></div>'+
      '<div style="overflow-x:auto"><table><thead><tr><th>Champ</th><th>Nom</th><th>Description</th><th>Valeur</th></tr></thead><tbody>'+rows+'</tbody></table></div>';
  }catch(e){console.error(e)}
}

// ── Tranches ───────────────────────────────────────────────────────────────────
async function loadTiers(){
  try{
    const r=await fetch('/api/v1/amount-tiers');const d=await r.json();
    const rc={'LOW':'#10b981','MEDIUM':'#f59e0b','HIGH':'#f97316','VERY_HIGH':'#ef4444','CRITICAL':'#dc2626'};
    document.getElementById('tierGrid').innerHTML=d.tiers.map(t=>`
      <div class="tier-card">
        <div class="tier-name" style="color:${rc[t.risk_level]||'var(--text)'}">${t.name}</div>
        <div style="color:var(--text2);font-size:12px">${t.label}</div>
        <div class="tier-range">${fmt(t.min_amount)} — ${t.max_amount>99999999?'∞':fmt(t.max_amount)}</div>
        <div class="tier-desc">${t.description}</div>
        <div class="tier-flags">
          <span class="flag ${t.require_online?'on':''}">Online</span>
          <span class="flag ${t.require_arqc?'on':''}">ARQC</span>
          <span class="flag ${t.auto_approve_offline?'on':''}">Offline OK</span>
          ${t.max_daily_count?'<span class="flag on">Max '+t.max_daily_count+'/j</span>':''}
        </div>
        ${t.is_custom?'<button class="btn-sm danger" style="margin-top:8px;width:100%" onclick="deleteTier(\''+t.name+'\')">Supprimer</button>':''}
      </div>`).join('');
  }catch(e){}
}
function fmt(n){return (n/100).toLocaleString('fr-FR',{minimumFractionDigits:2})+'€';}
function toggleAddTier(){const f=document.getElementById('addTierForm');f.style.display=f.style.display==='none'?'block':'none';}
async function addTier(){
  const daily=document.getElementById('tDailyCount').value;
  const payload={name:document.getElementById('tName').value,label:document.getElementById('tLabel').value,
    min_amount:parseInt(document.getElementById('tMin').value)||0,max_amount:parseInt(document.getElementById('tMax').value)||100000,
    risk_level:document.getElementById('tRisk').value,require_online:document.getElementById('tOnline').checked,
    require_arqc:document.getElementById('tArqc').checked,auto_approve_offline:document.getElementById('tOffline').checked,
    max_daily_count:daily?parseInt(daily):null,description:document.getElementById('tDesc').value,
    velocity_check:true,require_pin:true,floor_limit:0};
  const r=await fetch('/api/v1/amount-tiers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  if(r.ok){toggleAddTier();loadTiers();}else alert('Erreur: '+(await r.json()).error);
}
async function deleteTier(name){
  if(!confirm('Supprimer la tranche '+name+' ?'))return;
  await fetch('/api/v1/amount-tiers/'+name,{method:'DELETE'});loadTiers();
}

// ── GIE CB ─────────────────────────────────────────────────────────────────────
async function loadCBRules(){
  try{
    const r=await fetch('/api/v1/giecb/rules');const d=await r.json();
    const cap=d.cap;const tap=d.tap;const cl=d.contactless;
    document.getElementById('cbGrid').innerHTML=`
      <div class="cb-card">
        <h3>💳 CAP — Card Acceptor Parameters</h3>
        <div class="cb-param"><span class="k">Floor limit offline</span><span class="v ok">${fmtE(cap.offline_floor_limit)}</span></div>
        <div class="cb-param"><span class="k">Max montant offline</span><span class="v warn">${fmtE(cap.max_offline_amount)}</span></div>
        <div class="cb-param"><span class="k">Max montant online</span><span class="v warn">${fmtE(cap.max_online_amount)}</span></div>
        <div class="cb-param"><span class="k">Seuil référer</span><span class="v crit">${fmtE(cap.referral_threshold)}</span></div>
        <div class="cb-param"><span class="k">Seuil montant élevé</span><span class="v warn">${fmtE(cap.high_value_threshold)}</span></div>
      </div>
      <div class="cb-card">
        <h3>📟 TAP — Terminal Application Parameters</h3>
        <div class="cb-param"><span class="k">TAP1 Floor limit</span><span class="v ok">${fmtE(tap.TAP1_offline_floor_limit)}</span></div>
        <div class="cb-param"><span class="k">TAP2 Cumul offline</span><span class="v warn">${fmtE(tap.TAP2_cumulative_offline_limit)}</span></div>
        <div class="cb-param"><span class="k">TAP3 Max/transaction</span><span class="v warn">${fmtE(tap.TAP3_max_per_transaction)}</span></div>
        <div class="cb-param"><span class="k">TAP4 Max tx offline</span><span class="v crit">${tap.TAP4_max_offline_count} txns</span></div>
        <div class="cb-param"><span class="k">TAP5 Seuil risque term.</span><span class="v warn">${fmtE(tap.TAP5_terminal_risk_threshold)}</span></div>
      </div>
      <div class="cb-card">
        <h3>📶 Sans contact NFC (DSP2)</h3>
        <div class="cb-param"><span class="k">Plafond par tx</span><span class="v warn">${fmtE(cl.single_txn_limit)}</span></div>
        <div class="cb-param"><span class="k">Sans PIN max</span><span class="v warn">${fmtE(cl.single_txn_limit_no_pin)}</span></div>
        <div class="cb-param"><span class="k">Cumul offline max</span><span class="v crit">${fmtE(cl.cumulative_offline_limit)}</span></div>
        <div class="cb-param"><span class="k">Tx offline consécutives</span><span class="v crit">${cl.max_consecutive_offline} max</span></div>
        <div class="cb-param"><span class="k">Seuil low-value (SCA)</span><span class="v ok">${fmtE(cl.low_value_threshold)}</span></div>
      </div>
      <div class="cb-card">
        <h3>🔐 Exemptions SCA (DSP2)</h3>
        ${d.sca_exemptions.map(e=>'<div class="cb-param"><span class="k">'+e.code+'</span><span class="v ok" style="font-size:10px;text-align:right">'+e.name+(e.max_amount?' ≤'+fmtE(e.max_amount):'')+'</span></div>').join('')}
      </div>`;
    document.getElementById('aidBody').innerHTML=d.aids.map(a=>
      '<tr><td><span class="aid-tag">'+a.aid+'</span></td><td>'+a.name+'</td><td>'+a.scheme+'</td><td>'+a.brand+'</td><td>'+(a.contactless?'<span class="badge APPROVED">OUI</span>':'<span class="badge DECLINED">NON</span>')+'</td></tr>'
    ).join('');
    const mccNames={'5411':'Supermarché','5412':'Convenience','5541':'Station service','5542':'Pompe auto',
      '5912':'Pharmacie','5812':'Restaurant','5813':'Bar / tabac','5814':'Fast-food',
      '5999':'Divers détail','7011':'Hôtel','7996':'Parc attractions','4111':'Transport local',
      '4112':'Train','4121':'Taxi','4131':'Bus','4784':'Péage','DEFAULT':'Défaut'};
    document.getElementById('floorBody').innerHTML=Object.entries(d.floor_limits).map(([mcc,amt])=>
      '<tr><td style="font-family:monospace;color:#fbbf24">'+mcc+'</td><td>'+(mccNames[mcc]||mcc)+'</td><td style="color:'+(amt===0?'#f87171':'#34d399')+'">'+fmtE(amt)+'</td><td style="color:var(--text3);font-size:10px">'+(amt===0?'⚠ Toujours en ligne':'Floor limit standard')+'</td></tr>'
    ).join('');
    document.getElementById('cbCodesGrid').innerHTML=Object.entries(d.response_codes).map(([code,label])=>
      '<div style="background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:7px 10px;display:flex;align-items:center;gap:8px"><span style="font-family:monospace;font-weight:700;color:#fbbf24;min-width:24px">'+code+'</span><span style="color:var(--text2);font-size:11px">'+label+'</span></div>'
    ).join('');
  }catch(e){console.error(e)}
}
function fmtE(n){return (n/100).toLocaleString('fr-FR',{minimumFractionDigits:2})+'€';}
async function evalCB(){
  const payload={pan:document.getElementById('cbPan').value,amount:parseInt(document.getElementById('cbAmt').value)||0,
    currency:'978',transaction_type:document.getElementById('cbType').value,
    mcc:document.getElementById('cbMcc').value||null,pos_entry_mode:document.getElementById('cbMode').value,
    is_contactless:document.getElementById('cbMode').value==='071'};
  const r=await fetch('/api/v1/giecb/evaluate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const d=await r.json();
  const box=document.getElementById('cbEvalBox');
  box.style.display='block';
  box.style.borderColor=d.cb_result?.allowed?'#10b981':'#ef4444';
  box.style.color=d.cb_result?.allowed?'#34d399':'#f87171';
  box.textContent=JSON.stringify(d,null,2);
}

// ── E1 : CVV ───────────────────────────────────────────────────────────────────
function showCVVPanel(){
  const p=document.getElementById('cvvPanel');
  p.style.display=p.style.display==='none'?'block':'none';
}
async function checkCVV(){
  const payload={
    pan:document.getElementById('cvvCheckPan').value.replace(/\s/g,''),
    expiry_yymm:document.getElementById('cvvCheckExpiry').value,
    cvv:document.getElementById('cvvCheckCode').value,
    cvv_type:document.getElementById('cvvCheckType').value,
  };
  const r=await fetch('/api/v1/cvv/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const d=await r.json();
  const res=document.getElementById('cvvResult');
  res.style.display='block';
  if(d.valid){
    res.innerHTML='<span style="color:#34d399;font-weight:700">✓ CVV valide</span> — '+d.cvv_type;
  }else{
    res.innerHTML='<span style="color:#f87171;font-weight:700">✗ CVV invalide</span>';
    if(d.error)res.innerHTML+=' — '+d.error;
  }
}
async function generateCVV(){
  const pan=document.getElementById('cvvCheckPan').value.replace(/\s/g,'');
  const expiry=document.getElementById('cvvCheckExpiry').value;
  const r=await fetch('/api/v1/cvv/generate?pan='+pan+'&expiry_yymm='+expiry);
  const d=await r.json();
  const res=document.getElementById('cvvResult');
  res.style.display='block';
  if(d.cvv1){
    res.innerHTML='<span style="color:#fbbf24">CVV1:</span> '+d.cvv1+
      ' &nbsp; <span style="color:#a78bfa">CVV2:</span> '+d.cvv2+
      ' &nbsp; <span style="color:#60a5fa">iCVV:</span> '+d.icvv;
  }else{
    res.innerHTML='<span style="color:#f87171">Erreur: '+esc(d.error||'?')+'</span>';
  }
}

// ── Cartes ─────────────────────────────────────────────────────────────────────
async function loadCards(){
  try{
    const r=await fetch('/api/v1/cards');const d=await r.json();
    const statusColors={ACTIVE:'#34d399',BLOCKED:'#f87171',EXPIRED:'#f59e0b',LOST:'#f87171',STOLEN:'#f87171',RESTRICTED:'#f59e0b'};
    document.getElementById('cardGrid').innerHTML=d.cards.map(c=>`
      <div class="card-item">
        <div class="pan">${c.pan}</div>
        <div class="name">${c.cardholder_name}</div>
        <div class="details">${c.expiry} · ${c.cb_brand||c.cb_scheme||'—'} · PSN ${c.psn}</div>
        <div class="balance">${(c.balance/100).toLocaleString('fr-FR',{minimumFractionDigits:2})}€</div>
        <div style="font-size:10px;color:var(--text3);margin-top:3px">
          Dépensé/j: ${(c.daily_spent/100).toLocaleString('fr-FR',{minimumFractionDigits:2})}€ / ${(c.daily_limit/100).toLocaleString('fr-FR',{minimumFractionDigits:2})}€<br>
          NFC cumul: ${(c.contactless_cumul/100).toFixed(2)}€ · Offline consec.: ${c.consecutive_offline}
        </div>
        <div class="card-actions">
          <span class="badge ${c.status}">${c.status}</span>
          ${c.status==='ACTIVE'?'<button class="btn-sm danger" onclick="blockCard(\''+c.pan+'\')">Bloquer</button>':''}
          ${(c.status==='BLOCKED'||c.status==='RESTRICTED')?'<button class="btn-sm success" onclick="unblockCard(\''+c.pan+'\')">Débloquer</button>':''}
        </div>
      </div>`).join('');
  }catch(e){console.error(e)}
}
async function blockCard(pan){
  const reason=prompt('Motif de blocage:','Blocage manuel');
  if(reason===null)return;
  await fetch('/api/v1/cards/'+pan+'/block',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason})});
  loadCards();loadStats();
}
async function unblockCard(pan){
  const reason=prompt('Motif de déblocage (optionnel):','Déblocage manuel');
  if(reason===null)return;
  const r=await fetch('/api/v1/cards/'+pan+'/unblock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason})});
  const d=await r.json();
  if(!r.ok){alert('Erreur: '+d.error);return;}
  loadCards();loadStats();
}

async function checkAPIKeyStatus(){
  try{
    const r=await fetch('/api/v1/health');
    const d=await r.json();
    const el=document.getElementById('apiKeyStatus');
    if(d.api_key_enabled){
      el.textContent='API Key activée (X-Api-Key requis)';
      el.style.color='#34d399';
    }else{
      el.textContent='Aucune auth (mode dev — définir EMV_API_KEY pour activer)';
      el.style.color='#f59e0b';
    }
  }catch(e){}
}

function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

loadStats();
startSSE();
setInterval(loadStats,15000);
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
        "version": "1.3.0-GIE-CB",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "api_key_enabled": bool(Config.API_KEY),
        "features": ["EMV 4.3", "ISO 8583", "ARQC/ARPC",
                     "TPA Response", "Amount Tiers", "GIE CB Rules",
                     "Card Block/Unblock", "CVV/CVC E1",
                     "Rate Limiting S2", "API Key S1",
                     "CSV Export D2", "Batch Sim D4",
                     "SSE Charts D1", "Dark/Light D6",
                     "JSON Backup P2"],
    })


# ── Autorisation ──────────────────────────────────────────────────────────────

@app.route("/api/v1/authorize", methods=["POST"])
@limiter.limit(Config.RATE_LIMIT_AUTHORIZE)
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
    pos_entry_mode = data.get("pos_entry_mode", "051")
    is_contactless = data.get("is_contactless", pos_entry_mode[:2] in ("07", "91"))

    # E1 — Vérification CVV optionnelle
    cvv2 = data.get("cvv2") or data.get("cvv")
    expiry_yymm = data.get("expiry_yymm") or data.get("expiry", "")
    cvv_valid = None
    if cvv2 and expiry_yymm:
        try:
            cvv_valid = verify_cvv(
                provided=str(cvv2),
                pan=pan,
                expiry_yymm=str(expiry_yymm),
                cvk1=Config.CVK1,
                cvk2=Config.CVK2,
                cvv_type="CVV2",
            )
        except Exception:
            cvv_valid = None

    result = authorize(
        pan=pan, amount=amount, currency=currency,
        transaction_type=transaction_type,
        field_55=data.get("field_55") or data.get("emv_data"),
        terminal_id=data.get("terminal_id"),
        merchant_id=data.get("merchant_id"),
        merchant_name=data.get("merchant_name"),
        pos_entry_mode=pos_entry_mode,
        skip_crypto=data.get("skip_crypto", False),
        mcc=data.get("mcc"),
        is_contactless=is_contactless,
    )
    result_dict = result.to_dict(include_tpa=True)
    if cvv_valid is not None:
        result_dict["cvv_check"] = {"provided": True, "valid": cvv_valid}
    return jsonify(result_dict)


@app.route("/api/v1/authorize/iso8583", methods=["POST"])
@limiter.limit(Config.RATE_LIMIT_AUTHORIZE)
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


# ── D4 : Simulation batch ─────────────────────────────────────────────────────

@app.route("/api/v1/batch/simulate", methods=["POST"])
@limiter.limit(Config.RATE_LIMIT_BATCH)
def batch_simulate():
    data = request.get_json() or {}
    count = min(int(data.get("count", 20)), 100)
    seed = data.get("seed")
    if seed is not None:
        random.seed(int(seed))
    else:
        random.seed()

    results = []
    total_approved = 0

    for _ in range(count):
        pan = random.choice(BATCH_TEST_PANS)
        amount = random.choice(BATCH_AMOUNTS)
        mcc = random.choice(BATCH_MCCS)
        pos_mode = random.choice(BATCH_MODES)
        txn_type = random.choice(BATCH_TYPES)
        is_nfc = pos_mode == "071"

        try:
            result = authorize(
                pan=pan, amount=amount, currency="978",
                transaction_type=txn_type,
                terminal_id="BATCH001",
                merchant_id="BATCH_MERCH",
                merchant_name="SIMULATION BATCH",
                pos_entry_mode=pos_mode,
                skip_crypto=True,
                mcc=mcc,
                is_contactless=is_nfc,
            )
            tier = result.amount_decision.tier.name if result.amount_decision else None
            if result.approved:
                total_approved += amount
            results.append({
                "pan": "*" * (len(pan) - 4) + pan[-4:],
                "amount": amount,
                "approved": result.approved,
                "response_code": result.response_code,
                "tier": tier,
                "pos_mode": pos_mode,
                "mcc": mcc,
            })
        except Exception as e:
            results.append({
                "pan": "*" * (len(pan) - 4) + pan[-4:],
                "amount": amount,
                "approved": False,
                "response_code": "96",
                "error": str(e),
            })

    approved_count = sum(1 for r in results if r.get("approved"))
    return jsonify({
        "count": count,
        "results": results,
        "approved": approved_count,
        "declined": count - approved_count,
        "total_approved_amount": total_approved,
        "total_approved_formatted": "{:.2f}".format(total_approved / 100),
        "approval_rate": "{:.1f}%".format(approved_count / count * 100 if count else 0),
    })


# ── D1 : SSE — stats temps réel ───────────────────────────────────────────────

@app.route("/api/v1/stats/stream", methods=["GET"])
def stats_stream():
    def generate():
        while True:
            try:
                stats = transaction_log.get_stats()
                yield "data: {}\n\n".format(json.dumps(stats))
                time.sleep(3)
            except GeneratorExit:
                break
            except Exception:
                yield "data: {}\n\n".format(json.dumps({"error": "stream error"}))
                time.sleep(5)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


# ── D2 : Export CSV / JSON ────────────────────────────────────────────────────

@app.route("/api/v1/transactions/export", methods=["GET"])
def export_transactions():
    fmt = request.args.get("format", "json").lower()
    try:
        limit = min(int(request.args.get("limit", 2000)), 5000)
    except (ValueError, TypeError):
        limit = 2000
    status_filter = request.args.get("status")
    tier_filter = request.args.get("tier")

    transactions = transaction_log.get_all(
        limit=limit, offset=0,
        status=status_filter, tier=tier_filter)

    if fmt == "csv":
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writerow([
            "ID", "RRN", "PAN", "Montant", "Devise", "Type",
            "Tranche", "Risque", "Chemin", "Statut", "Code",
            "CB Schéma", "CB Brand", "SCA", "Contactless",
            "Code CB", "Terminal", "Commerçant", "ARQC", "ARPC",
            "Créé le", "Traité le",
        ])
        for t in transactions:
            writer.writerow([
                t.id, t.rrn,
                "*" * (len(t.pan) - 4) + t.pan[-4:],
                "{:.2f}".format(t.amount / 100), t.currency,
                t.transaction_type,
                t.amount_tier or "", t.risk_level or "", t.auth_path or "",
                t.status, t.response_code or "",
                t.cb_scheme or "", t.cb_brand or "",
                t.cb_sca_exemption or "",
                "OUI" if t.cb_is_contactless else "NON",
                t.cb_response_code or "",
                t.terminal_id or "", t.merchant_name or "",
                t.arqc or "", t.arpc or "",
                t.created_at or "", t.processed_at or "",
            ])
        csv_content = output.getvalue()
        return Response(
            csv_content,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition":
                     "attachment; filename=transactions_{}.csv".format(
                         datetime.utcnow().strftime("%Y%m%d_%H%M%S"))})
    else:
        return jsonify({
            "transactions": [t.to_dict() for t in transactions],
            "count": len(transactions),
            "exported_at": datetime.utcnow().isoformat() + "Z",
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
        "tiers": [{
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
        } for t in tiers],
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
    decision = evaluate_amount(amount, "00",
                               has_arqc=bool(request.args.get("has_arqc")))
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


# ── GIE CB ────────────────────────────────────────────────────────────────────

@app.route("/api/v1/giecb/rules", methods=["GET"])
def giecb_rules():
    return jsonify({
        "cap": CB_CAP,
        "tap": CB_TAP,
        "contactless": CB_CONTACTLESS,
        "sca_exemptions": CB_SCA_EXEMPTIONS,
        "service_indicators": CB_SERVICE_INDICATORS,
        "response_codes": CB_RESPONSE_CODES,
        "aids": [{"aid": k, **v} for k, v in CB_AIDS.items()],
        "floor_limits": CB_MCC_FLOOR_LIMITS,
    })


@app.route("/api/v1/giecb/evaluate", methods=["POST"])
def giecb_evaluate():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400
    pan = data.get("pan", "").replace(" ", "")
    try:
        amount = int(data.get("amount", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid amount"}), 400
    card = card_db.get_card(pan)
    cl_cumul = card.contactless_cumul if card else 0
    cl_consec = card.consecutive_offline if card else 0
    aid = data.get("aid") or (card.aid if card else None)
    result = evaluate_cb_rules(
        pan=pan, amount=amount,
        currency=data.get("currency", "978"),
        transaction_type=data.get("transaction_type", "00"),
        mcc=data.get("mcc"),
        aid_hex=aid,
        is_contactless=data.get("is_contactless", False),
        contactless_cumul=cl_cumul,
        consecutive_offline=cl_consec,
        pos_entry_mode=data.get("pos_entry_mode", "051"),
    )
    card_info = identify_card(pan, aid)
    return jsonify({
        "pan_masked": "*" * (len(pan) - 4) + pan[-4:] if len(pan) > 4 else pan,
        "amount": amount,
        "amount_formatted": "{:.2f}€".format(amount / 100),
        "card_info": {
            "scheme": card_info.scheme,
            "brand": card_info.brand,
            "aid_name": card_info.aid_name,
            "supports_contactless": card_info.supports_contactless,
        },
        "cb_result": result.to_dict(),
    })


@app.route("/api/v1/giecb/aids", methods=["GET"])
def giecb_aids():
    return jsonify({
        "aids": [{"aid": k, **v} for k, v in CB_AIDS.items()],
        "count": len(CB_AIDS),
    })


@app.route("/api/v1/giecb/floor-limits", methods=["GET"])
def giecb_floor_limits():
    return jsonify({
        "floor_limits": CB_MCC_FLOOR_LIMITS,
        "count": len(CB_MCC_FLOOR_LIMITS),
        "description": "Floor limits CB en centimes par MCC. Valeur 0 = autorisation en ligne obligatoire.",
    })


@app.route("/api/v1/giecb/response-codes", methods=["GET"])
def giecb_response_codes():
    return jsonify({
        "response_codes": CB_RESPONSE_CODES,
        "count": len(CB_RESPONSE_CODES),
    })


# ── E1 : CVV/CVC ──────────────────────────────────────────────────────────────

@app.route("/api/v1/cvv/generate", methods=["GET"])
def cvv_generate():
    pan = request.args.get("pan", "").replace(" ", "")
    expiry_yymm = request.args.get("expiry_yymm", "")
    if not pan or not expiry_yymm:
        return jsonify({"error": "pan et expiry_yymm requis"}), 400
    result = generate_cvv_set(pan, expiry_yymm, Config.CVK1, Config.CVK2)
    if "error" in result:
        return jsonify(result), 400
    return jsonify({
        "pan_masked": "*" * (len(pan) - 4) + pan[-4:],
        "expiry_yymm": expiry_yymm,
        **result,
        "note": "Valeurs de TEST uniquement — clés CVK de démonstration",
    })


@app.route("/api/v1/cvv/verify", methods=["POST"])
def cvv_verify():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400
    pan = data.get("pan", "").replace(" ", "")
    expiry_yymm = data.get("expiry_yymm", "")
    cvv = str(data.get("cvv", ""))
    cvv_type = data.get("cvv_type", "CVV2")
    service_code = data.get("service_code", "101")
    if not pan or not expiry_yymm or not cvv:
        return jsonify({"error": "pan, expiry_yymm, cvv requis"}), 400
    try:
        valid = verify_cvv(
            provided=cvv, pan=pan, expiry_yymm=expiry_yymm,
            cvk1=Config.CVK1, cvk2=Config.CVK2,
            cvv_type=cvv_type, service_code=service_code)
        return jsonify({
            "pan_masked": "*" * (len(pan) - 4) + pan[-4:],
            "cvv_type": cvv_type,
            "valid": valid,
        })
    except Exception as e:
        return jsonify({"error": str(e), "valid": False}), 400


# ── TPA ───────────────────────────────────────────────────────────────────────

@app.route("/api/v1/tpa/fields", methods=["GET"])
def get_tpa_fields():
    return jsonify({
        "fields": TPA_FIELD_DEFINITIONS,
        "count": len(TPA_FIELD_DEFINITIONS),
        "cb_fields": [k for k in TPA_FIELD_DEFINITIONS if k.startswith("CB")],
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
    return jsonify({"cards": [c.to_dict(masked=True) for c in cards],
                    "count": len(cards)})


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
        cb_scheme=data.get("cb_scheme", "VISA"),
        cb_brand=data.get("cb_brand", "VISA CB"),
        aid=data.get("aid"),
    )
    card_db.add_card(card)
    return jsonify({"message": "Card created", "card": card.to_dict(masked=True)}), 201


@app.route("/api/v1/cards/<pan>/block", methods=["POST"])
def block_card(pan):
    data = request.get_json() or {}
    reason = data.get("reason", "Blocage via API")
    if card_db.block_card(pan.replace(" ", ""), reason=reason):
        return jsonify({"message": "Card blocked", "reason": reason})
    return jsonify({"error": "Card not found"}), 404


@app.route("/api/v1/cards/<pan>/unblock", methods=["POST"])
def unblock_card(pan):
    data = request.get_json() or {}
    reason = data.get("reason", "Déblocage via API")
    success, message = card_db.unblock_card(pan.replace(" ", ""), reason=reason)
    if success:
        card = card_db.get_card(pan.replace(" ", ""))
        return jsonify({
            "message": message,
            "reason": reason,
            "card": card.to_dict(masked=True) if card else None,
        })
    return jsonify({"error": message}), 400


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.route("/api/v1/stats", methods=["GET"])
def get_stats():
    return jsonify({
        "transaction_stats": transaction_log.get_stats(),
        "card_stats": card_db.get_stats(),
        "server": {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "version": "1.3.0-GIE-CB",
            "max_transaction_amount": Config.MAX_TRANSACTION_AMOUNT,
            "daily_limit": Config.DAILY_LIMIT,
            "supported_currencies": Config.CURRENCY_CODES,
            "api_key_enabled": bool(Config.API_KEY),
        },
    })


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found"}), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Method not allowed"}), 405


@app.errorhandler(429)
def rate_limit_exceeded(e):
    return jsonify({
        "error": "Trop de requêtes — rate limit dépassé",
        "retry_after": str(e.description),
    }), 429


@app.errorhandler(500)
def internal_error(e):
    logger.exception("Internal server error")
    return jsonify({"error": "Internal server error"}), 500
