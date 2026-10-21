"""CHGNet 环境检测与后台弛豫任务。

CHGNet/PyTorch 安装在独立 Python 环境（chgnet_env）中，GUI 进程只通过
子进程调用 runner 脚本，因此主程序可以保持轻量、快速启动，并在没有
CHGNet 的机器上正常使用其他功能。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..config import AppConfig, app_root, config_dir
from .poscar import StructureData

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class ChgnetError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChgnetEnvironment:
    python: str
    device: str = "cpu"
    gpu: str = ""
    torch: str = ""
    chgnet: str = ""
    pymatgen: str = ""
    ase: str = ""

    @property
    def label(self) -> str:
        if self.device == "cuda":
            return f"CUDA · {self.gpu}" if self.gpu else "CUDA"
        return "CPU"

    @property
    def short_label(self) -> str:
        return "CUDA" if self.device == "cuda" else "CPU"


def _runner_path() -> Path:
    return Path(__file__).resolve().parent.parent / "tools" / "chgnet_runner.py"


def _probe_path() -> Path:
    return Path(__file__).resolve().parent.parent / "tools" / "chgnet_probe.py"


def _path_from_file() -> str:
    path = config_dir() / "chgnet_python.txt"
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line:
                return line
    except OSError:
        pass
    return ""


def candidate_pythons(config: AppConfig | None = None) -> list[Path]:
    paths: list[str] = []
    env_py = os.environ.get("MK_MOLE_CHGNET_PYTHON", "").strip()
    if env_py:
        paths.append(env_py)
    if config and config.chgnet_python.strip():
        paths.append(config.chgnet_python.strip())
    file_py = _path_from_file()
    if file_py:
        paths.append(file_py)

    root = app_root()
    paths.extend([
        str(root / "chgnet_env" / "Scripts" / "python.exe"),
        str(root / "chgnet_env" / "bin" / "python"),
        str(root / ".venv-chgnet" / "Scripts" / "python.exe"),
        str(root / ".venv-chgnet" / "bin" / "python"),
    ])
    if not getattr(sys, "frozen", False):
        paths.append(sys.executable)
    # Compatibility with the reference chgnet-opt environment, when present.
    paths.append(r"D:\miniconda3\envs\chem_env\python.exe")

    result: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        if not raw:
            continue
        p = Path(raw).expanduser()
        try:
            key = str(p.resolve())
        except OSError:
            key = str(p)
        if key in seen:
            continue
        seen.add(key)
        if p.is_file():
            result.append(p)
    return result


def probe_python(python: Path, *, timeout: int = 120) -> ChgnetEnvironment:
    probe = _probe_path()
    if not probe.is_file():
        raise ChgnetError("缺少 CHGNet 检测脚本")
    try:
        proc = subprocess.run(
            [str(python), str(probe)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise ChgnetError(f"检测 CHGNet 超时：{python}") from exc
    except (OSError, ValueError) as exc:
        raise ChgnetError(f"无法运行 {python}：{exc}") from exc

    payload = None
    for line in reversed((proc.stdout or "").splitlines()):
        if line.startswith("MKMOLE_CHGNET="):
            try:
                payload = json.loads(line.split("=", 1)[1])
            except ValueError:
                payload = None
            break
    if not isinstance(payload, dict) or not payload.get("ok"):
        detail = (payload or {}).get("error") or (proc.stderr or "").strip()[-300:]
        raise ChgnetError(detail or f"{python} 中未找到可用的 CHGNet/torch")
    return ChgnetEnvironment(
        python=str(python),
        device=str(payload.get("device") or "cpu"),
        gpu=str(payload.get("gpu") or ""),
        torch=str(payload.get("torch") or ""),
        chgnet=str(payload.get("chgnet") or ""),
        pymatgen=str(payload.get("pymatgen") or ""),
        ase=str(payload.get("ase") or ""),
    )


def detect_environment(config: AppConfig | None = None) -> ChgnetEnvironment:
    candidates = candidate_pythons(config)
    if not candidates:
        raise ChgnetError("未找到 CHGNet Python 环境，请运行 install_chgnet.bat")
    errors: list[str] = []
    for python in candidates:
        try:
            return probe_python(python)
        except ChgnetError as exc:
            errors.append(f"{python}: {exc}")
    raise ChgnetError("未检测到可用的 CHGNet 环境；" + "；".join(errors[-3:]))


class ChgnetProbeWorker(QThread):
    detected = Signal(object)
    unavailable = Signal(str)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config

    def run(self) -> None:  # noqa: D401
        try:
            env = detect_environment(self.config)
            self.detected.emit(env)
        except ChgnetError as exc:
            self.unavailable.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.unavailable.emit(f"CHGNet 检测失败：{exc}")


class ChgnetRelaxWorker(QThread):
    log = Signal(str)
    succeeded = Signal(object, dict)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        structure: StructureData,
        env: ChgnetEnvironment,
        *,
        max_steps: int = 300,
        fmax: float = 0.05,
        parent=None,
    ):
        super().__init__(parent)
        self.structure = structure
        self.env = env
        self.max_steps = int(max_steps)
        self.fmax = float(fmax)
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None

    def cancel(self) -> None:
        self._cancel.set()
        with self._lock:
            proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def run(self) -> None:  # noqa: D401
        runner = _runner_path()
        if not runner.is_file():
            self.failed.emit("缺少 CHGNet runner 脚本，请重新安装/打包。")
            return
        try:
            with tempfile.TemporaryDirectory(prefix="mk_mole_chgnet_") as tmp:
                work = Path(tmp)
                input_path = work / "POSCAR"
                input_path.write_text(self.structure.poscar, encoding="utf-8", newline="\n")
                cmd = [
                    self.env.python,
                    str(runner),
                    "--input", str(input_path),
                    "--outdir", str(work),
                    "--max-steps", str(self.max_steps),
                    "--fmax", str(self.fmax),
                ]
                self.log.emit(
                    f"启动 CHGNet：{self.env.label} · max_steps={self.max_steps} · "
                    f"fmax={self.fmax} eV/Å"
                )
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(work),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=_CREATE_NO_WINDOW,
                )
                with self._lock:
                    self._proc = proc
                tail: list[str] = []
                try:
                    if proc.stdout is not None:
                        for line in proc.stdout:
                            line = line.rstrip()
                            if line:
                                tail.append(line)
                                if len(tail) > 40:
                                    tail.pop(0)
                                self.log.emit(line)
                            if self._cancel.is_set() and proc.poll() is None:
                                proc.terminate()
                                break
                    proc.wait()
                finally:
                    with self._lock:
                        self._proc = None

                if self._cancel.is_set():
                    self.cancelled.emit()
                    return
                if proc.returncode != 0:
                    self.failed.emit(
                        "CHGNet 弛豫失败：" + ("\n".join(tail[-6:]) or f"退出码 {proc.returncode}")
                    )
                    return

                result_path = work / "result.json"
                contcar_path = work / "CONTCAR"
                if not result_path.exists():
                    self.failed.emit("CHGNet 未生成 result.json")
                    return
                try:
                    info = json.loads(result_path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    self.failed.emit(f"读取 CHGNet 结果失败：{exc}")
                    return
                if not info.get("ok"):
                    self.failed.emit(str(info.get("error") or "CHGNet 返回失败"))
                    return
                if not contcar_path.exists():
                    self.failed.emit("CHGNet 未生成 CONTCAR")
                    return
                relaxed = StructureData.from_poscar(
                    contcar_path.read_text(encoding="utf-8", errors="replace"),
                    source=f"CHGNet · {self.env.label} · relaxed",
                    expected_formula=self.structure.formula,
                )
                self.succeeded.emit(relaxed, info)
        except Exception as exc:  # noqa: BLE001
            if self._cancel.is_set():
                self.cancelled.emit()
            else:
                self.failed.emit(f"CHGNet 弛豫异常：{exc}")
