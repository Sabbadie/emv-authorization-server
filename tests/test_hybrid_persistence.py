"""
Tests pour PersistenceManager — Persistance hybride (v1.12.0).
"""
import pytest
from unittest.mock import MagicMock, patch
from persistence_manager import PersistenceManager
from config import Config

@pytest.fixture
def mock_persistence_components():
    with patch("persistence_manager.init_db") as mock_init, \
         patch("persistence_manager.load_snapshot") as mock_load, \
         patch("persistence_manager.PeriodicSnapshot") as mock_periodic, \
         patch("persistence_manager.register_shutdown_handler") as mock_shutdown, \
         patch("persistence_manager.auto_recover") as mock_recover, \
         patch("persistence_manager.card_db") as mock_card_db, \
         patch("persistence_manager.transaction_log") as mock_tlog:
        
        yield {
            "init_db": mock_init,
            "load_snapshot": mock_load,
            "periodic": mock_periodic,
            "shutdown": mock_shutdown,
            "recover": mock_recover,
            "card_db": mock_card_db,
            "tlog": mock_tlog
        }

def test_initialize_memory_mode(mock_persistence_components):
    """Vérifie le démarrage en mode mémoire si DATABASE_URL est absent."""
    Config.DATABASE_URL = None
    Config.SNAPSHOT_ENABLED = True
    
    mgr = PersistenceManager()
    mgr.initialize()
    
    assert mgr.db_active is False
    mock_persistence_components["init_db"].assert_not_called()
    mock_persistence_components["load_snapshot"].assert_called_once()
    mock_persistence_components["periodic"].assert_called_once()
    mock_persistence_components["recover"].assert_not_called()

def test_initialize_db_mode_empty(mock_persistence_components):
    """Vérifie le passage en mode DB et l'auto_recover si la DB est vide."""
    Config.DATABASE_URL = "sqlite:///:memory:"
    Config.SNAPSHOT_ENABLED = False
    
    mock_persistence_components["init_db"].return_value = True
    mock_persistence_components["tlog"].get_stats.return_value = {"total": 0}
    
    mgr = PersistenceManager()
    with patch("models.card_repository.DBCardDatabase"), \
         patch("models.transaction_repository.DBTransactionLog"):
        mgr.initialize()
    
    assert mgr.db_active is True
    mock_persistence_components["card_db"]._swap.assert_called_once()
    mock_persistence_components["tlog"]._swap.assert_called_once()
    mock_persistence_components["recover"].assert_called_once()

def test_initialize_db_mode_populated(mock_persistence_components):
    """Vérifie que auto_recover n'est pas appelé si la DB contient déjà des données."""
    Config.DATABASE_URL = "sqlite:///:memory:"
    
    mock_persistence_components["init_db"].return_value = True
    mock_persistence_components["tlog"].get_stats.return_value = {"total": 150}
    
    mgr = PersistenceManager()
    with patch("models.card_repository.DBCardDatabase"), \
         patch("models.transaction_repository.DBTransactionLog"):
        mgr.initialize()
    
    assert mgr.db_active is True
    mock_persistence_components["recover"].assert_not_called()

def test_initialize_db_failure_fallback(mock_persistence_components):
    """Vérifie le fallback en mode mémoire si la connexion DB échoue."""
    Config.DATABASE_URL = "sqlite:///:memory:"
    mock_persistence_components["init_db"].return_value = False
    
    mgr = PersistenceManager()
    mgr.initialize()
    
    assert mgr.db_active is False
    mock_persistence_components["load_snapshot"].assert_called_once()
    mock_persistence_components["card_db"]._swap.assert_not_called()
