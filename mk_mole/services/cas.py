"""CAS Common Chemistry 官方检索（可选 API Key）。

CAS Common Chemistry API 需要单独的 Key（与 DeepSeek Key 无关）。在设置中
填写后，CAS 检索会优先使用 CAS 官方数据；未配置、未收录或服务暂不可用时
自动回退到 PubChem（免费、无需 Key）。

申请地址：https://www.cas.org/services/commonchemistry-api
CAS 审核后会通过邮件发送 API Key。请求时通过 ``X-API-KEY`` 头携带。
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote

import requests

from .pubchem import CompoundInfo, PubChemError, lookup_cas as lookup_pubchem

CAS_API_BASE = "https://commonchemistry.cas.org/direct-api"
CAS_ORIGIN = "https://commonchemistry.cas.org/api-overview"
CAS_KEY_URL = "https://www.cas.org/services/commonchemistry-api"
_TIMEOUT = (10, 25)


class CASError(RuntimeError):
    """CAS 官方检索失败。"""


class CASAuthError(CASError):
    """API Key 缺失、无效或过期。"""


class CASNotFound(CASError):
    """CAS Common Chemistry 未收录该物质。"""


class CASUnavailable(CASError):
    """CAS 服务暂不可用（网络/服务端错误）。"""


_TAG_RE = re.compile(r"<[^>]+>")
_SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", _SVG_NS)
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _svg_number(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value).replace("px", ""))
    except (TypeError, ValueError):
        return default


def _needs_black_stroke(elem: ET.Element) -> bool:
    """CAS 的键线只靠根节点 style 继承 stroke，QtSvg 不会继承，需显式补上。"""
    style = (elem.get("style") or "").replace(" ", "").lower()
    if elem.get("stroke") or "stroke:" in style:
        return False
    tag = _local_tag(elem.tag)
    if tag in {"line", "polyline"}:
        return True
    if tag == "path":
        return "fill:none" in style or "fill" not in style
    return False


def _flatten_svg_element(elem: ET.Element, *, root: bool = False) -> ET.Element:
    tag = _local_tag(elem.tag)
    attrs = dict(elem.attrib)
    if tag == "svg" and not root:
        x = _svg_number(attrs.pop("x", 0))
        y = _svg_number(attrs.pop("y", 0))
        width = attrs.pop("width", None)
        height = attrs.pop("height", None)
        viewbox = attrs.pop("viewBox", None)
        attrs.pop("preserveAspectRatio", None)
        attrs.pop("class", None)
        transform = f"translate({x:g},{y:g})"
        if viewbox:
            parts = [part for part in viewbox.replace(",", " ").split() if part]
            if len(parts) == 4:
                vx, vy, vw, vh = (float(part) for part in parts)
                if vw and vh:
                    sx = _svg_number(width, vw) / vw
                    sy = _svg_number(height, vh) / vh
                    transform += (
                        f" scale({sx:g},{sy:g}) translate({-vx:g},{-vy:g})"
                    )
        new = ET.Element(f"{{{_SVG_NS}}}g", attrs)
        if transform != "translate(0,0)":
            new.set("transform", transform)
    else:
        new = ET.Element(elem.tag, attrs)

    if _needs_black_stroke(elem):
        new.set("stroke", "black")
    for child in elem:
        new.append(_flatten_svg_element(child))
        if child.tail and child.tail.strip():
            new[-1].tail = child.tail
    if elem.text and elem.text.strip():
        new.text = elem.text
    return new


def _flatten_cas_svg(svg: str) -> str:
    """展平 CAS 返回的嵌套 <svg>，否则 QtSvg 会渲染成空白。

    CAS 的结构图是「外层 svg → 多个嵌套 svg（带 class/viewBox）→ g」，
    且键线的 stroke 只写在根节点 style 上。QtSvg 对嵌套 viewBox 和 style
    继承支持有限，这里把它们转换成等价的 <g transform> 并补全 stroke。
    """
    if not (svg or "").strip():
        return ""
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return svg
    if _local_tag(root.tag) != "svg":
        return svg
    return ET.tostring(_flatten_svg_element(root, root=True), encoding="unicode")


def _clean_text(value: object) -> str:
    """去掉 CAS 名称中可能出现的 <em> 高亮标签并还原 HTML 实体。"""
    text = _TAG_RE.sub("", str(value or ""))
    return html.unescape(text).strip()


def _to_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _detail_url(base_url: str, cas: str) -> str:
    return f"{base_url.rstrip('/')}/detail?cas_rn={quote(cas, safe='')}"


def _headers(api_key: str) -> dict[str, str]:
    # CAS 官方 API 除了 Key，还要求 x-origin（Swagger 中的隐藏参数）。
    return {
        "X-API-KEY": api_key,
        "x-origin": CAS_ORIGIN,
        "Accept": "application/json",
        "User-Agent": "MK-MOLE/1.0 (local molecule builder)",
    }


def _count_atoms(sdf: str) -> int | None:
    lines = (sdf or "").splitlines()
    if len(lines) < 4:
        return None
    try:
        return int(lines[3][0:3])
    except ValueError:
        return None


def _fetch_molfile(
    base_url: str,
    uri: str,
    api_key: str,
    *,
    timeout: tuple[int, int],
) -> str:
    """通过 ``/export`` 取回 V2000 molfile（详情接口只返回 hasMolfile 标记）。"""
    try:
        resp = requests.get(
            f"{base_url.rstrip('/')}/export",
            params={"uri": uri},
            headers=_headers(api_key),
            timeout=timeout,
        )
    except requests.exceptions.RequestException:
        return ""
    if resp.status_code != 200:
        return ""
    return resp.text.strip()


def lookup_cas_official(
    cas: str,
    api_key: str,
    *,
    base_url: str = CAS_API_BASE,
    timeout: tuple[int, int] = _TIMEOUT,
) -> CompoundInfo:
    """调用 CAS Common Chemistry ``/detail`` 接口。"""
    cas = (cas or "").strip()
    api_key = (api_key or "").strip()
    if not cas:
        raise PubChemError("请先填写 CAS 号")
    if not api_key:
        raise CASAuthError("请先在设置中填写 CAS API Key")

    try:
        resp = requests.get(
            _detail_url(base_url, cas),
            headers=_headers(api_key),
            timeout=timeout,
        )
    except requests.exceptions.RequestException as exc:
        raise CASUnavailable(f"无法连接 CAS Common Chemistry：{exc}") from exc

    if resp.status_code in (401, 403):
        raise CASAuthError("CAS API Key 无效、已过期或没有访问权限，请在设置中重新填写")
    if resp.status_code == 404:
        raise CASNotFound(f"CAS Common Chemistry 未收录 {cas}")
    if resp.status_code != 200:
        raise CASUnavailable(f"CAS Common Chemistry 请求失败（HTTP {resp.status_code}）")

    try:
        data = resp.json()
    except ValueError as exc:
        raise CASUnavailable("CAS Common Chemistry 返回了无法解析的结果") from exc
    if not isinstance(data, dict):
        raise CASUnavailable("CAS Common Chemistry 返回了无法解析的结果")

    message = str(data.get("message") or "").strip()
    if not data.get("rn"):
        lowered = message.lower()
        if "api key" in lowered or "unauthorized" in lowered:
            raise CASAuthError("CAS API Key 无效、已过期或没有访问权限，请在设置中重新填写")
        if "not found" in lowered or "no records" in lowered:
            raise CASNotFound(f"CAS Common Chemistry 未收录 {cas}")
        raise CASUnavailable(message or "CAS Common Chemistry 未返回有效记录")

    synonyms = [
        cleaned for cleaned in (_clean_text(item) for item in data.get("synonyms") or [])
        if cleaned and not cleaned.lower().startswith("mesh id:")
    ]
    # 新版 detail 返回 images 数组；旧版/兼容字段为单个 image。
    images = data.get("images")
    svg = ""
    if isinstance(images, list) and images:
        svg = str(images[0] or "")
    if not svg and isinstance(data.get("image"), str):
        svg = data["image"]
    if svg:
        svg = _flatten_cas_svg(svg)

    info = CompoundInfo(
        cid=None,
        cas=_clean_text(data.get("rn")) or cas,
        formula=_clean_text(data.get("molecularFormula")),
        molecular_weight=_to_float(
            data.get("molecularMass") or data.get("molecularWeight")
        ),
        smiles=_clean_text(
            data.get("canonicalSmile")
            or data.get("canonicalSmiles")
            or data.get("canonicalSMILES")
            or data.get("isomericSmile")
            or data.get("isomericSmiles")
            or data.get("smile")
        ),
        iupac_name=_clean_text(data.get("iupacName")),
        title=_clean_text(data.get("name")),
        synonyms=synonyms[:12],
        svg=svg,
        source="CAS Common Chemistry",
    )

    uri = _clean_text(data.get("uri"))
    if uri and data.get("hasMolfile", True):
        sdf = _fetch_molfile(base_url, uri, api_key, timeout=timeout)
        if sdf:
            info.sdf = sdf
            info.atom_count = _count_atoms(sdf)
    return info


def lookup_compound(
    cas: str,
    api_key: str = "",
    *,
    base_url: str = CAS_API_BASE,
    timeout: tuple[int, int] = _TIMEOUT,
) -> CompoundInfo:
    """按配置选择数据源：有 CAS Key 时优先 CAS，否则/未收录时用 PubChem。

    Key 无效会直接报错（提醒用户修正），网络或服务端故障则静默回退 PubChem，
    保证检索仍能完成。
    """
    cas = (cas or "").strip()
    if not cas:
        raise PubChemError("请先填写 CAS 号")

    if (api_key or "").strip():
        try:
            return lookup_cas_official(cas, api_key, base_url=base_url, timeout=timeout)
        except CASAuthError:
            raise
        except (CASNotFound, CASUnavailable):
            pass
    return lookup_pubchem(cas)
