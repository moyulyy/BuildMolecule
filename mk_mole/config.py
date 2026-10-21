"""本地配置：DeepSeek 连接信息与生成参数。

默认采用**便携式目录**：配置文件、PubChem 缓存和错误日志都放在
项目根目录（源码运行）或 exe 所在目录（打包运行）下的 `data/` 中，
不再写入 %APPDATA%。可用环境变量 `MK_MOLE_DATA_DIR` 覆盖。

旧版本保存于 %APPDATA%\\MK-MOLE\\config.json 的配置会在首次启动时
自动复制到新的 `data/` 目录，便于平滑迁移。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-flash"
MODEL_CHOICES = ("deepseek-flash", "deepseek-v4-pro")
DEFAULT_REASONING_EFFORT = "high"
REASONING_EFFORT_CHOICES = ("none", "low", "high", "max")
# 思考模式默认 64K 输出预算（DeepSeek 文档：thinking 模式默认 64K）
DEFAULT_MAX_TOKENS = 65536


def app_root() -> Path:
    """源码运行时为项目根目录；PyInstaller 打包后为 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """便携式数据目录：<项目根或 exe 目录>/data，可用环境变量覆盖。"""
    override = os.environ.get("MK_MOLE_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return app_root() / "data"


def config_dir() -> Path:
    return data_dir()


def config_path() -> Path:
    return config_dir() / "config.json"


def legacy_config_path() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "MK-MOLE" / "config.json"


def _migrate_legacy_config(path: Path) -> None:
    """把旧 %APPDATA% 配置与 CAS 缓存复制到便携 data 目录（只复制，不删除）。"""
    if os.environ.get("MK_MOLE_DATA_DIR", "").strip():
        return  # 测试/自定义目录不做隐式迁移
    legacy = legacy_config_path()
    if path.exists() or not legacy.exists() or legacy == path:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, path)
        legacy_cache = legacy.parent / "cache"
        if legacy_cache.is_dir():
            shutil.copytree(legacy_cache, path.parent / "cache", dirs_exist_ok=True)
    except OSError:
        pass


@dataclass
class AppConfig:
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    reasoning_effort: str = DEFAULT_REASONING_EFFORT
    max_tokens: int = DEFAULT_MAX_TOKENS
    auto_relax: bool = True
    chgnet_python: str = ""
    chgnet_max_steps: int = 300
    chgnet_fmax: float = 0.05
    last_formula: str = ""
    last_name: str = ""
    last_english_name: str = ""
    last_cas: str = ""
    last_description: str = ""
    last_smiles: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip())

    @classmethod
    def load(cls) -> "AppConfig":
        cfg = cls()
        path = config_path()
        _migrate_legacy_config(path)
        data: dict = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
                    for key, value in data.items():
                        if hasattr(cfg, key) and key != "extra":
                            setattr(cfg, key, value)
            except (OSError, ValueError):
                pass

        # 环境变量兜底（配置文件中的显式值优先）
        if not cfg.api_key:
            cfg.api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not data.get("base_url") and os.environ.get("DEEPSEEK_BASE_URL"):
            cfg.base_url = os.environ["DEEPSEEK_BASE_URL"].strip()

        env_model = os.environ.get("DEEPSEEK_MODEL", "").strip()
        if not data.get("model") and env_model:
            cfg.model = env_model
        elif cfg.model not in MODEL_CHOICES:
            # 旧版本的 deepseek-chat / deepseek-reasoner 迁移到当前默认模型
            cfg.model = env_model if env_model in MODEL_CHOICES else DEFAULT_MODEL

        env_effort = os.environ.get("DEEPSEEK_REASONING_EFFORT", "").strip().lower()
        if not data.get("reasoning_effort") and env_effort in REASONING_EFFORT_CHOICES:
            cfg.reasoning_effort = env_effort
        if cfg.reasoning_effort not in REASONING_EFFORT_CHOICES:
            cfg.reasoning_effort = DEFAULT_REASONING_EFFORT

        try:
            cfg.max_tokens = int(cfg.max_tokens)
        except (TypeError, ValueError):
            cfg.max_tokens = DEFAULT_MAX_TOKENS
        if cfg.max_tokens <= 0:
            cfg.max_tokens = DEFAULT_MAX_TOKENS
        # 旧版本默认 8192；thinking 模式的 POSCAR 生成使用 64K 预算
        if cfg.max_tokens == 8192:
            cfg.max_tokens = DEFAULT_MAX_TOKENS

        # CHGNet 自动弛豫设置
        cfg.auto_relax = bool(cfg.auto_relax)
        cfg.chgnet_python = str(cfg.chgnet_python or "").strip()
        try:
            cfg.chgnet_max_steps = max(10, min(5000, int(cfg.chgnet_max_steps)))
        except (TypeError, ValueError):
            cfg.chgnet_max_steps = 300
        try:
            cfg.chgnet_fmax = max(0.005, min(1.0, float(cfg.chgnet_fmax)))
        except (TypeError, ValueError):
            cfg.chgnet_fmax = 0.05
        return cfg

    def save(self) -> None:
        directory = config_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "config.json"
        tmp = path.with_suffix(".json.tmp")
        payload = asdict(self)
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def snapshot_form(self, formula: str, name: str, english_name: str, cas: str,
                      description: str, smiles: str) -> None:
        self.last_formula = formula
        self.last_name = name
        self.last_english_name = english_name
        self.last_cas = cas
        self.last_description = description
        self.last_smiles = smiles
