"""
PersistenceManager — Gestionnaire de cycle de vie de la persistance hybride.
Coordonne le basculement entre In-Memory (Snapshots) et Database (PostgreSQL/SQLite).
"""
import logging
from config import Config
from database import init_db, is_db_available
from db_import import auto_recover
from models.card import card_db
from models.transaction import transaction_log
from persistence import load_snapshot, PeriodicSnapshot, register_shutdown_handler

logger = logging.getLogger(__name__)

class PersistenceManager:
    def __init__(self):
        self.db_active = False
        self.snapshot_worker = None

    def initialize(self):
        """
        Initialise la persistance selon la configuration et la disponibilité.
        """
        logger.info("=" * 60)
        logger.info("Initialisation de la Persistance Hybride...")
        
        # 1. Tentative d'initialisation de la DB
        if Config.DATABASE_URL:
            try:
                self.db_active = init_db()
                if self.db_active:
                    self._setup_db_mode()
                else:
                    logger.warning("DB configurée mais indisponible. Passage en mode mémoire.")
                    self._setup_memory_mode()
            except Exception as exc:
                logger.error("Erreur critique init DB : %s. Fallback mémoire.", exc)
                self._setup_memory_mode()
        else:
            logger.info("DATABASE_URL non défini. Mode mémoire par défaut.")
            self._setup_memory_mode()

        # 2. Gestion des snapshots (backup secondaire ou source primaire)
        if Config.SNAPSHOT_ENABLED:
            self._setup_snapshots()
        
        logger.info("Persistance initialisée. Mode DB: %s", self.db_active)
        logger.info("=" * 60)

    def _setup_db_mode(self):
        """Configure le serveur pour utiliser la base de données."""
        logger.info("Activation des repositories DB-backed (P1)")
        from models.card_repository import DBCardDatabase
        from models.transaction_repository import DBTransactionLog
        
        card_db._swap(DBCardDatabase())
        transaction_log._swap(DBTransactionLog())
        
        # Vérification si la DB est vide et nécessite une récupération
        stats = transaction_log.get_stats()
        if stats.get("total", 0) == 0:
            logger.info("Base de données vide. Tentative de récupération automatique (auto_recover)...")
            auto_recover()
        else:
            logger.info("Base de données déjà peuplée (%d transactions).", stats.get("total"))

    def _setup_memory_mode(self):
        """Configure le serveur pour utiliser le stockage en mémoire avec snapshots."""
        logger.info("Activation des repositories In-Memory (P2)")
        # Les repositories sont déjà en mode mémoire par défaut via _CardDBProxy/_TransactionLogProxy
        # On charge le dernier snapshot si disponible
        load_snapshot(card_db, transaction_log)

    def _setup_snapshots(self):
        """Active la sauvegarde périodique JSON (v1.12.0)."""
        try:
            self.snapshot_worker = PeriodicSnapshot(
                card_db, transaction_log, interval=Config.SNAPSHOT_INTERVAL)
            self.snapshot_worker.start()
            register_shutdown_handler(self.snapshot_worker)
            logger.info("Backup JSON périodique activé (intervalle: %ds)", Config.SNAPSHOT_INTERVAL)
        except Exception as e:
            logger.warning("Impossible d'initialiser le backup JSON : %s", e)

    def stop(self):
        """Arrête proprement les services de persistance."""
        if self.snapshot_worker:
            self.snapshot_worker.stop()
            logger.info("Services de persistance arrêtés.")

# Singleton global
manager = PersistenceManager()
