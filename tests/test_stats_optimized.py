"""
Tests pour les statistiques optimisées et temporelles (v1.13.0).
"""
import pytest
from datetime import datetime, timedelta
from models.transaction import Transaction, TransactionStatus, TransactionLog

def test_time_series_in_memory():
    """Vérifie le calcul des séries temporelles en mémoire."""
    tlog = TransactionLog()
    
    # Création de transactions sur plusieurs heures
    now = datetime.utcnow()
    
    t1 = Transaction("1", 100, "978", "00")
    t1.created_at = (now - timedelta(hours=2)).isoformat()
    
    t2 = Transaction("2", 200, "978", "00")
    t2.created_at = (now - timedelta(hours=1)).isoformat()
    
    t3 = Transaction("3", 300, "978", "00")
    t3.created_at = (now - timedelta(hours=1)).isoformat()
    
    tlog.add(t1)
    tlog.add(t2)
    tlog.add(t3)
    
    stats = tlog.get_time_series_stats(hours=5)
    
    # On s'attend à 2 points dans la série (H-2 et H-1)
    assert len(stats) == 2
    assert stats[0]["count"] == 1 # H-2
    assert stats[1]["count"] == 2 # H-1

def test_get_stats_consistency(fresh_transaction_log):
    """Vérifie que get_stats retourne bien tous les champs attendus."""
    tlog = fresh_transaction_log
    
    txn = Transaction("4111", 5000, "978", "00")
    txn.approve("123456")
    txn.amount_tier = "STANDARD"
    tlog.add(txn)
    
    stats = tlog.get_stats()
    assert stats["total"] == 1
    assert stats["approved"] == 1
    assert stats["total_approved_amount"] == 5000
    assert "by_tier" in stats
    assert stats["by_tier"].get("STANDARD") == 1
