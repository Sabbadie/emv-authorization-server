"""
EMV Authorization Server v1.3.0 — Entry Point
Intègre : P2 (backup JSON périodique), SIGTERM handler
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
    logger.info("  Serveur d'Autorisation EMV v1.3.0")
    logger.info("  EMV 4.3 | ISO 8583 | ARQC/ARPC | GIE CB | CVV")
    logger.info("  S1:APIKey | S2:RateLimit | S3:PANMask")
    logger.info("  D1:Charts | D2:CSV | D4:Batch | D6:DarkMode")
    logger.info("  E1:CVV | P2:JSONBackup")
    logger.info("=" * 60)
    logger.info("Démarrage sur http://%s:%d", Config.HOST, Config.PORT)

    # P2 — Backup JSON périodique
    if Config.SNAPSHOT_ENABLED:
        try:
            from persistence import load_snapshot, PeriodicSnapshot, register_shutdown_handler
            from models.card import card_db
            from models.transaction import transaction_log

            load_snapshot(card_db, transaction_log)

            snapshot_worker = PeriodicSnapshot(
                card_db, transaction_log, interval=Config.SNAPSHOT_INTERVAL)
            snapshot_worker.start()
            register_shutdown_handler(snapshot_worker)
        except Exception as e:
            logger.warning("Impossible d'initialiser le backup JSON : %s", str(e))
    else:
        logger.info("Backup JSON désactivé (SNAPSHOT_ENABLED=false)")

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
