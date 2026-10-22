"""CAS 号检索（PubChem PUG REST）与本地缓存。

CAS 检索只用于给 DeepSeek 补充 SMILES / molfile 参考信息，以及向用户展示
二维结构；真正的三维结构由 DeepSeek 生成。网络不可用时返回明确错误。
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from ..config import config_dir


class PubChemError(RuntimeError):
    pass


@dataclass
class CompoundInfo:
    cid: int | None = None
    cas: str = ""
    formula: str = ""
    molecular_weight: float | None = None
    smiles: str = ""
    iupac_name: str = ""
    title: str = ""
    synonyms: list[str] = field(default_factory=list)
    atom_count: int | None = None
    sdf: str = ""
    png: bytes = b""
    svg: str = ""
    source: str = "PubChem"

    @property
    def display_name(self) -> str:
        if self.title or self.iupac_name or self.formula:
            return self.title or self.iupac_name or self.formula
        return f"CID {self.cid}" if self.cid else f"CAS {self.cas}"


CACHE_DAYS = 30
_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "MK-MOLE/1.0 (local molecule builder)",
    "Accept": "application/json",
})


def cache_dir() -> Path:
    path = config_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_key(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _is_fresh(path: Path) -> bool:
    try:
        return (time.time() - path.stat().st_mtime) < CACHE_DAYS * 86400
    except OSError:
        return False


def _request(url: str, *, params: dict | None = None, timeout: tuple[int, int] = (10, 25)) -> requests.Response:
    try:
        resp = _SESSION.get(url, params=params, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        raise PubChemError(f"无法连接 PubChem：{exc}") from exc
    if resp.status_code == 404:
        raise PubChemError("PubChem 中未找到该 CAS 号或化合物")
    if resp.status_code != 200:
        raise PubChemError(f"PubChem 请求失败（HTTP {resp.status_code}）")
    return resp


def _count_atoms(sdf: str) -> int | None:
    lines = (sdf or "").splitlines()
    if len(lines) < 4:
        return None
    counts = lines[3]
    try:
        return int(counts[0:3])
    except ValueError:
        return None


def _parse_synonyms(data: dict) -> list[str]:
    try:
        info = data["InformationList"]["Information"]
        for item in info:
            names = item.get("Synonym") or []
            if names:
                return list(names)
    except (KeyError, TypeError, IndexError):
        pass
    return []


def lookup_cas(cas: str) -> CompoundInfo:
    cas = (cas or "").strip()
    if not cas:
        raise PubChemError("请先填写 CAS 号")

    # 1) CAS -> CID（同时尝试直接取属性，减少往返）
    props_url = (
        "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
        f"{requests.utils.quote(cas, safe='')}/property/"
        "MolecularFormula,MolecularWeight,ConnectivitySMILES,IUPACName,Title/JSON"
    )
    try:
        resp = _request(props_url)
        payload = resp.json()
        prop = payload["PropertyTable"]["Properties"][0]
    except (ValueError, KeyError, IndexError) as exc:
        raise PubChemError("PubChem 返回了无法解析的检索结果") from exc
    cid = int(prop.get("CID") or 0)
    if not cid:
        raise PubChemError("未获得有效的 PubChem CID")

    info = CompoundInfo(
        cid=cid,
        cas=cas,
        formula=prop.get("MolecularFormula") or "",
        molecular_weight=_to_float(prop.get("MolecularWeight")),
        smiles=prop.get("ConnectivitySMILES") or prop.get("CanonicalSMILES") or prop.get("SMILES") or "",
        iupac_name=prop.get("IUPACName") or "",
        title=prop.get("Title") or "",
    )

    # 2) 同义词（可选）
    try:
        syn = _SESSION.get(
            f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/synonyms/JSON",
            timeout=(6, 15),
        )
        if syn.status_code == 200:
            info.synonyms = _parse_synonyms(syn.json())[:12]
    except (requests.exceptions.RequestException, ValueError):
        pass

    # 3) 2D SDF（给 LLM 当 molfile 参考）与 2D PNG
    key = _cache_key("cid", str(cid))
    sdf_path = cache_dir() / f"{key}.sdf"
    png_path = cache_dir() / f"{key}.png"
    meta_path = cache_dir() / f"{key}.json"

    if _is_fresh(sdf_path):
        info.sdf = sdf_path.read_text(encoding="utf-8", errors="replace")
    else:
        try:
            sdf_resp = _request(
                f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/record/SDF",
                params={"record_type": "2d"},
            )
            info.sdf = sdf_resp.text
            sdf_path.write_text(info.sdf, encoding="utf-8")
        except PubChemError:
            info.sdf = ""

    if _is_fresh(png_path):
        info.png = png_path.read_bytes()
    else:
        try:
            png_resp = _request(
                f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/PNG",
                params={"record_type": "2d", "image_size": "420x420"},
            )
            info.png = png_resp.content
            png_path.write_bytes(info.png)
        except PubChemError:
            info.png = b""

    info.atom_count = _count_atoms(info.sdf)
    try:
        meta = {
            "cid": info.cid, "cas": info.cas, "formula": info.formula,
            "molecular_weight": info.molecular_weight, "smiles": info.smiles,
            "iupac_name": info.iupac_name, "title": info.title,
            "synonyms": info.synonyms, "atom_count": info.atom_count,
            "cached_at": time.time(),
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return info


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
