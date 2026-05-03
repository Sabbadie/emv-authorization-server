"""
EMV Authorization Server v1.8.0 — Entry Point
Intègre : P1 (PostgreSQL + SQLAlchemy), P2 (backup JSON),
          S4 (Pydantic validation), D5 (Dashboard alertes),
          C1 (flux CB complet), A2 (mode dégradé/chaos), A3 (config YAML/TOML)
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
    logger.info("  Serveur d'Autorisation EMV v1.8.0")
    logger.info("  EMV 4.3 | ISO 8583 | ARQC/ARPC | GIE CB | CVV")
    logger.info("  S1:APIKey | S2:RateLimit | S3:PANMask | S4:Pydantic")
    logger.info("  D1:Charts | D2:CSV | D4:Batch | D5:Alertes | D6:DarkMode")
    logger.info("  E1:CVV | P1:PostgreSQL | P2:JSONBackup")
    logger.info("  C1:FluxCB | A2:ChaosMode | A3:ConfigYAML")
    logger.info("=" * 60)

    # ── P1 : Initialisation base de données ────────────────────────────────────
    if Config.DATABASE_URL:
        try:
            from database import init_db
            db_ok = init_db()
            if db_ok:
                logger.info("P1 — Base de données PostgreSQL connectée")
                # Permute les singletons vers les implémentations DB-backed
                from models.card_repository import DBCardDatabase
                from models.transaction_repository import DBTransactionLog
                from models.card import card_db
                from models.transaction import transaction_log
                card_db._swap(DBCardDatabase())
                transaction_log._swap(DBTransactionLog())
                logger.info("P1 — Repositories DB-backed activés (Card + Transaction)")
            else:
                logger.warning("P1 — DB indisponible, mode in-memory actif")
        except Exception as exc:
            logger.warning("P1 — Erreur init DB, mode in-memory : %s", exc)
    else:
        logger.info("P1 — DATABASE_URL non défini — stockage en mémoire actif")

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
