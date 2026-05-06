"""
EMV Authorization Server v1.12.0 — Entry Point — Roadmap 45/45 ✅
Intègre : P1 (PostgreSQL/SQLAlchemy), P2 (backup JSON + historique 7j + import DB),
          P4 (Cache Redis), S4 (Pydantic), S5 (HSM chiffrement RAM),
          D5 (Dashboard alertes), C1 (flux CB complet),
          A2 (chaos engineering), A3 (config YAML/TOML),
          M1 (Maintenance snapshots compressés GZIP + Pinning)
"""

import logging
from server import app
from config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("  Serveur d'Autorisation EMV v1.12.0 — Roadmap 45/45 ✅")
    logger.info("  EMV 4.3 | ISO 8583 | ARQC/ARPC | GIE CB | CVV")
    logger.info("  S1:APIKey | S2:RateLimit | S3:PANMask | S4:Pydantic | S5:HSM")
    logger.info("  D1:Charts | D2:CSV | D4:Batch | D5:Alertes | D6:DarkMode")
    logger.info("  E1:CVV | E2:3DS2 | E3:DDA/CDA | P1:PostgreSQL | P2:JSON+7j+Import | P4:Cache")
    logger.info("  C1:FluxCB | C2:PKI | C3:HCE/NFC | A2:Chaos | A3:ConfigYAML")
    logger.info("  M1:Snapshots GZIP + Pinning + API Maintenance")
    logger.info("=" * 60)

    # ── Initialisation de la Persistance Hybride ──────────────────────────────
    from persistence_manager import manager as persistence_mgr
    persistence_mgr.initialize()

    logger.info("Démarrage sur http://%s:%d", Config.HOST, Config.PORT)

    if Config.API_KEY:
        logger.info("API Key activée (S1) — X-Api-Key requis sur /api/v1/*")
    else:
        logger.info("API Key non configurée — mode dev sans auth (définir EMV_API_KEY)")

    # Serveur TCP ISO 8583 (interface terminaux de paiement)
    tcp_server = None
    if Config.TCP_ENABLED:
        try:
            from emv.tcp_server import TCPAuthorizationServer
            tcp_server = TCPAuthorizationServer(
                host=Config.TCP_HOST, port=Config.TCP_PORT)
            tcp_server.start()
            logger.info(
                "Interface TCP ISO 8583 démarrée sur %s:%d",
                Config.TCP_HOST, Config.TCP_PORT,
            )
            logger.info(
                "  → Protocole : [4 octets longueur][JSON UTF-8]"
            )
            logger.info(
                "  → Exemple   : tools/terminal_simulator.py"
            )
        except Exception as exc:
            logger.warning("Impossible de démarrer l'interface TCP : %s", exc)
    else:
        logger.info("Interface TCP désactivée (TCP_ENABLED=false)")

    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)

    if tcp_server:
        tcp_server.stop()
