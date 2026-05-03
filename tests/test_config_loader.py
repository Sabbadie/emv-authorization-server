"""
Tests A3 — Configuration YAML/TOML rechargeable.
Couvre : ConfigManager, chargement YAML, chargement TOML, get(), get_section(),
set(), reload(), hot-reload détection, fusion env vars, get_config() global.
"""

import os
import time
import tempfile
import pytest
from config_loader import ConfigManager, get_config, _load_yaml, _load_toml, _deep_merge


@pytest.fixture(autouse=True)
def reset_singleton():
    """Réinitialise le singleton avant chaque test."""
    ConfigManager.reset_instance()
    yield
    ConfigManager.reset_instance()


# ── _deep_merge ───────────────────────────────────────────────────────────────

class TestDeepMerge:
    def test_simple_override(self):
        result = _deep_merge({"a": 1}, {"a": 2})
        assert result["a"] == 2

    def test_new_key_added(self):
        result = _deep_merge({"a": 1}, {"b": 2})
        assert result["a"] == 1
        assert result["b"] == 2

    def test_nested_merge(self):
        base = {"s": {"x": 1, "y": 2}}
        over = {"s": {"y": 99, "z": 3}}
        result = _deep_merge(base, over)
        assert result["s"]["x"] == 1
        assert result["s"]["y"] == 99
        assert result["s"]["z"] == 3

    def test_non_dict_value_overrides(self):
        result = _deep_merge({"a": {"b": 1}}, {"a": "string"})
        assert result["a"] == "string"


# ── ConfigManager sans fichier ────────────────────────────────────────────────

class TestConfigManagerNoFile:
    def test_instantiate_no_file(self):
        mgr = ConfigManager(config_path="/nonexistent/config.yaml", watch=False)
        assert mgr is not None

    def test_get_returns_default(self):
        mgr = ConfigManager(config_path="/nonexistent/config.yaml", watch=False)
        assert mgr.get("server.port", 5000) == 5000

    def test_get_all_empty_or_dict(self):
        mgr = ConfigManager(config_path="/nonexistent/config.yaml", watch=False)
        cfg = mgr.get_all()
        assert isinstance(cfg, dict)

    def test_set_and_get(self):
        mgr = ConfigManager(config_path="/nonexistent/config.yaml", watch=False)
        mgr.set("custom.key", "hello")
        assert mgr.get("custom.key") == "hello"

    def test_get_section_empty(self):
        mgr = ConfigManager(config_path="/nonexistent/config.yaml", watch=False)
        section = mgr.get_section("server")
        assert isinstance(section, dict)


# ── ConfigManager avec fichier YAML ──────────────────────────────────────────

class TestConfigManagerYAML:
    @pytest.fixture
    def yaml_file(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("""
server:
  host: "127.0.0.1"
  port: 9000
  debug: true
emv:
  max_transaction_amount: 500000
""")
        return str(f)

    def test_load_yaml(self, yaml_file):
        mgr = ConfigManager(config_path=yaml_file, watch=False)
        assert mgr.get("server.port") == 9000

    def test_yaml_host(self, yaml_file):
        mgr = ConfigManager(config_path=yaml_file, watch=False)
        assert mgr.get("server.host") == "127.0.0.1"

    def test_yaml_debug(self, yaml_file):
        mgr = ConfigManager(config_path=yaml_file, watch=False)
        assert mgr.get("server.debug") is True

    def test_yaml_nested(self, yaml_file):
        mgr = ConfigManager(config_path=yaml_file, watch=False)
        assert mgr.get("emv.max_transaction_amount") == 500000

    def test_get_section(self, yaml_file):
        mgr = ConfigManager(config_path=yaml_file, watch=False)
        section = mgr.get_section("server")
        assert section["port"] == 9000

    def test_reload_count_increments(self, yaml_file):
        mgr = ConfigManager(config_path=yaml_file, watch=False)
        count_before = mgr.get_status()["reload_count"]
        mgr.reload()
        assert mgr.get_status()["reload_count"] == count_before + 1

    def test_reload_picks_up_changes(self, yaml_file):
        mgr = ConfigManager(config_path=yaml_file, watch=False)
        assert mgr.get("server.port") == 9000
        with open(yaml_file, "w") as f:
            f.write("server:\n  port: 8888\n")
        mgr.reload()
        assert mgr.get("server.port") == 8888

    def test_status_structure(self, yaml_file):
        mgr = ConfigManager(config_path=yaml_file, watch=False)
        status = mgr.get_status()
        assert "config_path" in status
        assert "reload_count" in status
        assert "reload_errors" in status
        assert "watch_enabled" in status
        assert "yaml_available" in status
        assert "toml_available" in status
        assert "keys_loaded" in status


# ── ConfigManager avec fichier TOML ──────────────────────────────────────────

class TestConfigManagerTOML:
    @pytest.fixture
    def toml_file(self, tmp_path):
        f = tmp_path / "config.toml"
        f.write_text("""
[server]
host = "0.0.0.0"
port = 7000
debug = false

[emv]
max_transaction_amount = 999999
""")
        return str(f)

    def test_load_toml(self, toml_file):
        mgr = ConfigManager(config_path=toml_file, watch=False)
        assert mgr.get("server.port") == 7000

    def test_toml_emv(self, toml_file):
        mgr = ConfigManager(config_path=toml_file, watch=False)
        assert mgr.get("emv.max_transaction_amount") == 999999

    def test_toml_host(self, toml_file):
        mgr = ConfigManager(config_path=toml_file, watch=False)
        assert mgr.get("server.host") == "0.0.0.0"


# ── Singleton ────────────────────────────────────────────────────────────────

class TestConfigManagerSingleton:
    def test_get_instance_returns_same(self):
        m1 = ConfigManager.get_instance(watch=False)
        m2 = ConfigManager.get_instance(watch=False)
        assert m1 is m2

    def test_reset_clears_singleton(self):
        m1 = ConfigManager.get_instance(watch=False)
        ConfigManager.reset_instance()
        m2 = ConfigManager.get_instance(watch=False)
        assert m1 is not m2


# ── get_config() global ───────────────────────────────────────────────────────

class TestGetConfigGlobal:
    def test_get_config_returns_default(self):
        val = get_config("nonexistent.key", "default_val")
        assert val == "default_val"

    def test_get_config_none_default(self):
        val = get_config("nonexistent")
        assert val is None


# ── config.yaml par défaut ───────────────────────────────────────────────────

class TestDefaultConfigYAML:
    def test_default_config_file_exists(self):
        assert os.path.isfile("config.yaml")

    def test_default_config_loadable(self):
        data = _load_yaml("config.yaml")
        assert isinstance(data, dict)
        assert "server" in data

    def test_default_config_has_server_section(self):
        data = _load_yaml("config.yaml")
        assert "port" in data["server"]

    def test_default_config_has_cb_section(self):
        data = _load_yaml("config.yaml")
        assert "cb" in data

    def test_default_config_has_chaos_section(self):
        data = _load_yaml("config.yaml")
        assert "chaos" in data

    def test_default_config_chaos_disabled(self):
        data = _load_yaml("config.yaml")
        assert data["chaos"]["enabled"] is False


# ── Hot-reload ───────────────────────────────────────────────────────────────

class TestHotReload:
    def test_hot_reload_on_file_change(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("server:\n  port: 6000\n")
        mgr = ConfigManager(config_path=str(f), watch=True, reload_interval=1)
        assert mgr.get("server.port") == 6000
        time.sleep(0.1)
        f.write_text("server:\n  port: 6001\n")
        time.sleep(1.5)
        assert mgr.get("server.port") == 6001
        mgr._watch = False

    def test_reload_report(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("key: value\n")
        mgr = ConfigManager(config_path=str(f), watch=False)
        report = mgr.reload()
        assert report["reloaded"] is True
        assert report["config_path"] == str(f)
        assert "reload_count" in report
