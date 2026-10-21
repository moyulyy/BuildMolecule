"""默认配置、便携目录与迁移测试。"""

from __future__ import annotations

from mk_mole.config import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    AppConfig,
    config_dir,
    config_path,
)


def test_deepseek_flash_high_defaults() -> None:
    cfg = AppConfig()
    assert cfg.model == "deepseek-flash"
    assert DEFAULT_MODEL == "deepseek-flash"
    assert cfg.reasoning_effort == "high"
    assert DEFAULT_REASONING_EFFORT == "high"
    assert cfg.max_tokens == 65536
    assert DEFAULT_MAX_TOKENS == 65536
    assert cfg.auto_relax is True
    assert cfg.chgnet_max_steps == 300
    assert cfg.chgnet_fmax == 0.05


def test_portable_data_dir_override(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MK_MOLE_DATA_DIR", str(tmp_path))
    assert config_dir() == tmp_path.resolve()
    assert config_path() == tmp_path.resolve() / "config.json"


def test_config_roundtrip_in_portable_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MK_MOLE_DATA_DIR", str(tmp_path))
    cfg = AppConfig(
        api_key="sk-test-portable",
        model="deepseek-flash",
        reasoning_effort="high",
        auto_relax=False,
        chgnet_max_steps=500,
        chgnet_fmax=0.02,
        last_formula="C6H6",
    )
    cfg.save()
    assert (tmp_path / "config.json").exists()

    loaded = AppConfig.load()
    assert loaded.api_key == "sk-test-portable"
    assert loaded.model == "deepseek-flash"
    assert loaded.reasoning_effort == "high"
    assert loaded.max_tokens == 65536
    assert loaded.auto_relax is False
    assert loaded.chgnet_max_steps == 500
    assert loaded.chgnet_fmax == 0.02
    assert loaded.last_formula == "C6H6"
