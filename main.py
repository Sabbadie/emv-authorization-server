"""
EMV Authorization Server — Entry Point
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
    logger.info("  Serveur d'Autorisation EMV")
    logger.info("  EMV 4.3 | ISO 8583 | ARQC/ARPC")
    logger.info("=" * 60)
    logger.info("Démarrage sur http://%s:%d", Config.HOST, Config.PORT)
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
