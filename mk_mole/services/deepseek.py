"""DeepSeek 流式生成分子 POSCAR（OpenAI 兼容的 chat/completions SSE）。

构建分子原页面使用的是 Kimi；本地版按用户要求统一改为 DeepSeek：
默认 base_url = https://api.deepseek.com/v1，模型 deepseek-flash，
reasoning_effort = high（思考模式开启），可在设置中切换 deepseek-v4-pro
以及 none / low / high / max 思考强度。
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable

import requests

from ..config import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    REASONING_EFFORT_CHOICES,
    AppConfig,
)
from .poscar import POSCAR_RETRY_HINT, center_poscar_in_cell, extract_poscar

EventCallback = Callable[[str, str], None]  # (kind, text), kind: status/thinking/content


class DeepSeekError(RuntimeError):
    pass


class GenerationCancelled(Exception):
    pass


@dataclass
class GenerationResult:
    poscar: str
    reply: str
    content_chars: int
    thinking_chars: int
    finish_reason: str
    elapsed: float
    model: str


@dataclass
class ImageStructureResult:
    """从结构图片中识别出的化学结构。"""

    smiles: str
    formula: str = ""
    name: str = ""
    confidence: str = ""
    notes: str = ""
    raw: str = ""


SYSTEM_PROMPT = """你是计算材料学结构建模助手。你的唯一任务：根据用户提供的结构信息，构建一个合理的三维分子结构，并输出**唯一一个**完整、可解析的 VASP5 POSCAR。

【输入优先级（冲突时严格按此顺序）】
0. 用户可能只提供一张结构图片而不提供分子式；这是有效输入。不得要求用户补充分子式，也不得拒绝生成。
1. 结构编辑器 / 结构文件：Ketcher 导出的 molfile、用户上传的 SDF / MOL / XYZ / PDB。它们的连接表、原子种类、电荷和立体信息最精确，必须严格保留。
2. SMILES：严格按 SMILES 的连接、环、芳香性、顺反与手性标记建模；SMILES 与名称/分子式冲突时，以 SMILES 为准。
3. 结构图片：识别图片中的元素标签、键线、官能团、环、顺反/立体信息；图片可能是手绘或截图，看不清的标签按最常见价态和化学常识补全，并在正文说明。
4. 名称 / CAS / 英文名 / 分子式 / 补充说明：只用于校验和补全，不得覆盖上面更明确的连接信息。
如果结构图片与 molfile/SMILES 明显冲突：以 molfile/SMILES 的连接表为准，图片用于补充构象/官能团；如果只有图片，则以图片为准。
如果只有图片而没有分子式：先从图片识别元素、键线、官能团和电荷，再按化学常识补全氢原子并生成结构；不要因为缺少分子式而停止。
如果信息不足或存在歧义：选择最常见、中性、闭壳层的合理结构，并在代码块外的正文中明确说明你的假设。

【化学与立体化学规则】
- 原子守恒：每个元素的原子数必须与分子式/SMILES/molfile/图片严格一致；例如 C22H23NO7 必须是 22 个 C、23 个 H、1 个 N、7 个 O，共 53 个原子。
- 价态：H=1；B=3；C=4；N=3（铵/质子化为 4）；O=2；F=1；P=3 或 5；S=2、4 或 6；Cl/Br/I=1；Si=4。自由基、离子、配位化合物按其实际价态处理。
- 必须显式包含所有氢原子；不要省略 H，也不要用隐式氢。
- 芳香环（苯、吡啶、吡咯等）应为平面或近平面，C-C 约 1.39 Å；不要把芳香环画成非平面的扭曲结构。
- 立体化学：若 SMILES/molfile/图片给出顺反、R/S、E/Z 或手性中心，必须保持；若未给出，选择合理构型并在正文说明。
- 电荷与自旋：若用户给出电荷/自由基/氧化态，保持总电荷与未成对电子数合理；POSCAR 没有电荷字段，在注释行标注（如 "C6H6 cation +1"）。
- 2D molfile 可能所有 z=0：只把它当作连接表和相对平面位置，必须推断出合理的三维构象；除非分子本身确实是平面分子（苯、CO2、乙烯等），不要把三维分子简单压平。
- 不要把二维键线图中的线段长度直接当作键长；使用下面的典型键长和合理键角。

【典型键长（Å，初始结构用，后续优化会修正）】
C-H 1.09，N-H 1.01，O-H 0.96，S-H 1.34；
C-C 1.54，C=C 1.34，C≡C 1.20；
C-N 1.47，C=N 1.27，C≡N 1.16；
C-O 1.43，C=O 1.23（CO2 中 1.16）；
N-N 1.45，N=N 1.25，N≡N 1.10，N=O 1.20；
O-O 1.48，O=O 1.21，H-H 0.74，C-S 1.82。
原子坐标不必非常精确，但拓扑必须正确、相对位置合理；不要生成原子重叠（任意两原子距离应 > 0.5 Å）。

【POSCAR 格式（VASP5）】
第一行：注释（分子式/名称；有电荷或自旋时一并注明）。
第二行：缩放因子 1.0。
第三至五行：晶格矢量，单位 Å：
  30.0 0.0 0.0
  0.0 30.0 0.0
  0.0 0.0 30.0
第六行：元素符号（如 C H O；标准大小写）。
第七行：各元素原子数，必须与第六行一一对应且为正整数。
第八行：Direct。
之后每行：一个原子的分数坐标（三个 0~1 之间的小数），原子顺序与元素行/数目行一致。
要求：
- 只使用 Direct 分数坐标，不使用 Cartesian。
- 不要添加 Selective dynamics，不要输出 CIF/XYZ/第二个 POSCAR。
- 元素分组：同一元素的所有原子连续排列。
- 所有坐标在 [0, 1)，分子整体居中：几何中心接近 (0.5, 0.5, 0.5)，第三个分数坐标 c 约 0.5，不要贴盒底。
- 30×30×30 Å 的真空盒足够大，不要复制/周期性重复分子。
- 代码块内不要有空行、注释或多余文字。

【生成前强制自检】
在给出最终 POSCAR 前，请在内部逐条核对（不要把自检过程写进正文）：
a) 原子数：每个元素的原子数与 SMILES/molfile/图片/分子式一致；
b) 元素行与数目行一一对应，总数等于坐标行数；
c) 连接性、键级、环、官能团、形式电荷、自由基状态合理；
d) 立体化学（顺反/手性）与输入一致；
e) 坐标范围、居中、原子间最小距离合理；
f) 只有一个 ```poscar 代码块，且块内没有多余内容。
任何一项不通过都必须先修正再输出；如果确实无法满足，输出一个**完整**的最接近结构，并在正文说明限制，绝不能输出截断/半截 POSCAR。

【输出纪律】
- 只输出一个 ```poscar 代码块。
- 代码块之外用简洁中文说明：采用的输入来源、原子数核对、关键假设（如有）。
- 不要输出 Markdown 表格、CIF、XYZ、第二个代码块或工具调用。
- 不要反问用户；在信息不足时按上面的规则选择最合理结构并说明假设。"""


VISION_SYSTEM_PROMPT = """你是化学结构识别器。用户会提供一张化学结构图片（手绘、软件截图、论文图或反应式）。请识别图片中的主要化学结构，并只输出一个 JSON 对象，不要输出任何解释、Markdown 代码块或多余文字。

JSON 格式：
{
  "smiles": "有效的 SMILES；保留元素、电荷、芳香性、顺反/手性信息",
  "formula": "Hill 分子式，例如 C6H6；无法确定时留空",
  "name": "能确定的常用名；无法确定时留空",
  "confidence": "high / medium / low",
  "notes": "识别依据、歧义或假设；不超过 120 字"
}

规则：
- 图片中若有多个结构或反应式，优先识别箭头右侧的主要产物；在 notes 说明。
- SMILES 必须包含完整分子；盐/离子可用点号分隔；不要省略关键电荷。
- 看不清的原子标签不要臆造；在 notes 中标注不确定处，confidence 设为 medium/low。
- 如果图片不是化学结构或完全无法辨认，输出：
  {"smiles": "", "formula": "", "name": "", "confidence": "low", "notes": "无法识别的原因"}
- 不要反问，不要输出化学结构图，只输出 JSON。"""

VISION_USER_TEXT = "请识别这张图片中的主要化学结构，并按系统要求输出 JSON。"


def _messages(payload: dict) -> list[dict]:
    formula = (payload.get("formula") or "").strip()
    name = (payload.get("name") or "").strip()
    english = (payload.get("english_name") or "").strip()
    cas = (payload.get("cas") or "").strip()
    description = (payload.get("description") or "").strip()
    smiles = (payload.get("smiles") or "").strip()
    molfile = (payload.get("molfile") or "").strip()
    structure_source = (payload.get("structure_source") or "").strip()
    image_b64 = (payload.get("image_b64") or "").strip()

    has_structure_hint = bool(formula or image_b64 or smiles or molfile)
    formula_display = formula or (
        "（未提供；如已提供图片/SMILES/结构文件，请直接据此生成，不要要求补充分子式）"
        if has_structure_hint else "（未提供）"
    )
    user_text = (
        "请生成以下分子的 POSCAR 结构：\n"
        f"- 结构来源：{structure_source or '（未指定）'}\n"
        f"- 名称：{name or '（未提供）'}\n"
        f"- 英文名称：{english or '（未提供）'}\n"
        f"- CAS 号：{cas or '（未提供）'}\n"
        f"- 分子式：{formula_display}\n"
        f"- 补充说明：{description or '（无）'}\n"
        f"- 结构图片：{'已提供（见下图，请识别其中的结构式）' if image_b64 else '未提供'}\n"
        f"- 结构文件：{'已提供（见下方结构数据）' if molfile else '未提供'}\n"
    )
    if not formula and (image_b64 or smiles or molfile):
        user_text += (
            "\n- 用户没有提供分子式。这是允许的：请直接依据图片 / SMILES / 结构文件建模，"
            "不要反问或要求补充分子式；最后在正文说明你是如何识别元素与原子数的。\n"
        )
    user_text += (
        "\n请严格按系统提示中的输入优先级建模："
        "molfile/SMILES 的连接表与立体信息 > 结构图片 > 名称/CAS/分子式；"
        "若图片与连接表冲突，以连接表为准，并在正文说明。\n"
        "请在正文中简要列出各元素的原子数核对结果。\n"
    )
    if smiles:
        user_text += (
            f"- SMILES 结构：{smiles}\n"
            "（请严格依据该 SMILES 表示的分子构建三维结构：连接方式、原子种类与数目、"
            "官能团均须一致；若 SMILES 与分子式/名称不一致，以 SMILES 为准。）\n"
        )
    if molfile:
        user_text += (
            "\n- 结构文件数据（SDF / MOL / XYZ / PDB，含坐标与可能的连接表）：\n"
            f"{molfile[:12000]}\n"
            "（请读取其中的原子坐标与连接信息：坐标用于判断原子相对位置与空间排布，"
            "连接表用于确认化学键；生成三维结构时保持与之一致的原子拓扑与相对几何。"
            "若与分子式/名称不一致，以结构文件 / SMILES 的连接为准。）\n"
        )
    if image_b64:
        user_text += (
            "\n- 已提供结构图片。请优先依据图片中的连接关系、官能团、异构体与立体几何建模；"
            "若图片与文字描述冲突，以图片和 SMILES / 结构文件为准。\n"
        )
    if not image_b64:
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ]
    # deepseek-flash 支持图文输入，使用 OpenAI 兼容的 image_url 数据 URL
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": image_b64}},
            ],
        },
    ]


def _endpoint(base_url: str, path: str) -> str:
    base = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    return f"{base}/{path.lstrip('/')}"


def _headers(config: AppConfig) -> dict:
    return {
        "Authorization": f"Bearer {config.api_key.strip()}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "MK-MOLE/1.0",
    }


def _http_error(response: requests.Response) -> DeepSeekError:
    detail = ""
    try:
        payload = response.json()
        detail = ((payload or {}).get("error") or {}).get("message") or ""
    except ValueError:
        detail = (response.text or "").strip()[:300]
    status = response.status_code
    if status == 401:
        message = "DeepSeek API Key 无效或已过期，请在设置中重新填写"
    elif status == 402:
        message = "DeepSeek 账户余额不足，请先充值"
    elif status == 429:
        message = "请求过于频繁，已触发 DeepSeek 限流，请稍后重试"
    elif status >= 500:
        message = "DeepSeek 服务暂时不可用，请稍后重试"
    else:
        message = f"DeepSeek 请求失败（HTTP {status}）"
    if detail:
        message = f"{message}：{detail}"
    return DeepSeekError(message)


def test_connection(config: AppConfig) -> list[str]:
    """调用 /models 验证 Key 与网络，返回可用模型列表。"""
    if not config.api_key.strip():
        raise DeepSeekError("请先填写 DeepSeek API Key")
    url = _endpoint(config.base_url, "models")
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {config.api_key.strip()}",
                     "User-Agent": "MK-MOLE/1.0"},
            timeout=(10, 25),
        )
    except requests.exceptions.RequestException as exc:
        raise DeepSeekError(f"网络连接失败：{exc}") from exc
    if resp.status_code != 200:
        raise _http_error(resp)
    try:
        data = resp.json()
        return [item.get("id", "") for item in data.get("data", []) if item.get("id")]
    except ValueError:
        return []


def _extract_chunk(data: dict) -> tuple[str, str, str]:
    reasoning = ""
    content = ""
    finish = ""
    choices = data.get("choices") or []
    if not choices:
        return reasoning, content, finish
    choice = choices[0]
    finish = choice.get("finish_reason") or ""
    delta = choice.get("delta") or {}
    reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
    content = delta.get("content") or ""
    return reasoning, content, finish


def stream_chat(
    config: AppConfig,
    messages: list[dict],
    *,
    on_event: EventCallback | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
) -> tuple[str, str, str, str]:
    """流式调用 DeepSeek，返回 (content, reasoning, finish_reason, model)。"""
    if not config.api_key.strip():
        raise DeepSeekError("尚未配置 DeepSeek API Key，请先在设置中填写")
    model = (config.model or DEFAULT_MODEL).strip()
    effort = (reasoning_effort or getattr(config, "reasoning_effort", DEFAULT_REASONING_EFFORT)
              or DEFAULT_REASONING_EFFORT).strip().lower()
    if effort not in REASONING_EFFORT_CHOICES:
        effort = DEFAULT_REASONING_EFFORT
    body: dict = {
        "model": model,
        "messages": messages,
        "stream": True,
        "max_tokens": int(max_tokens or config.max_tokens or DEFAULT_MAX_TOKENS),
        # DeepSeek 官方参数：thinking 开关 + reasoning_effort 强度
        "thinking": {"type": "disabled" if effort == "none" else "enabled"},
        "reasoning_effort": effort,
    }
    # thinking 模式下 temperature 无效；仅在关闭思考时使用低温度提高确定性
    if effort == "none":
        body["temperature"] = 0.2

    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    finish_reason = ""
    try:
        response = requests.post(
            _endpoint(config.base_url, "chat/completions"),
            headers=_headers(config),
            json=body,
            stream=True,
            timeout=(20, 240),
        )
    except requests.exceptions.RequestException as exc:
        raise DeepSeekError(f"无法连接 DeepSeek：{exc}") from exc

    with response:
        if response.status_code != 200:
            raise _http_error(response)

        # 用户点「取消」时即使上游暂时没有新数据，也能立刻打断阻塞中的读取
        stop_watch = {"done": False}

        def watchdog() -> None:
            while not stop_watch["done"]:
                if is_cancelled and is_cancelled():
                    try:
                        response.close()
                    except Exception:  # noqa: BLE001
                        pass
                    return
                time.sleep(0.15)

        if is_cancelled:
            threading.Thread(target=watchdog, daemon=True).start()

        content_type = (response.headers.get("Content-Type") or "").lower()
        if "text/event-stream" not in content_type:
            # 少数代理会忽略 stream 参数，直接返回完整 JSON
            try:
                data = response.json()
                message = ((data.get("choices") or [{}])[0].get("message") or {})
                content_parts.append(message.get("content") or "")
                reasoning_parts.append(message.get("reasoning_content") or "")
                finish_reason = ((data.get("choices") or [{}])[0].get("finish_reason") or "")
            except (ValueError, IndexError) as exc:
                stop_watch["done"] = True
                raise DeepSeekError("DeepSeek 返回了无法解析的响应") from exc
            stop_watch["done"] = True
            return "".join(content_parts).strip(), "".join(reasoning_parts).strip(), finish_reason, model

        try:
            for raw in response.iter_lines(decode_unicode=False):
                if is_cancelled and is_cancelled():
                    raise GenerationCancelled()
                if not raw:
                    continue
                line = raw.decode("utf-8", "replace").strip()
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    break
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                reasoning, content, finish = _extract_chunk(data)
                if finish:
                    finish_reason = finish
                if reasoning:
                    reasoning_parts.append(reasoning)
                    if on_event:
                        on_event("thinking", reasoning)
                if content:
                    content_parts.append(content)
                    if on_event:
                        on_event("content", content)
        except GenerationCancelled:
            stop_watch["done"] = True
            raise
        except requests.exceptions.RequestException as exc:
            stop_watch["done"] = True
            if is_cancelled and is_cancelled():
                raise GenerationCancelled() from exc
            raise DeepSeekError(f"DeepSeek 流式响应中断：{exc}") from exc
        except Exception as exc:  # noqa: BLE001
            stop_watch["done"] = True
            if is_cancelled and is_cancelled():
                raise GenerationCancelled() from exc
            raise
        finally:
            stop_watch["done"] = True

    if is_cancelled and is_cancelled():
        raise GenerationCancelled()
    return "".join(content_parts).strip(), "".join(reasoning_parts).strip(), finish_reason, model


def _vision_json(text: str) -> dict:
    """从模型输出中提取 JSON；兼容 ```json 代码块与 SMILES: 文本。"""
    raw = (text or "").strip()
    if not raw:
        return {}
    candidates: list[str] = []
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S | re.I)
    if fenced:
        candidates.append(fenced.group(1))
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        candidates.append(raw[start:end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    # 模型偶尔只写一行 SMILES：不要猜测普通文本，只认显式字段
    match = re.search(r"(?im)^\s*smiles\s*[:：]\s*([^\s`]+)", raw)
    if match:
        return {"smiles": match.group(1), "notes": raw[:300]}
    return {}


def parse_structure_image(
    config: AppConfig,
    image_b64: str,
    *,
    on_event: EventCallback | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> ImageStructureResult:
    """让 DeepSeek 读取结构图片，返回可编辑的 SMILES / 分子式。

    这里关闭自由思考以降低延迟；识别结果只是草稿，必须由用户在界面中核对后
    才写入主结构字段。
    """
    if not (image_b64 or "").strip().startswith("data:image/"):
        raise DeepSeekError("图片数据无效，请重新选择结构图片")
    if on_event:
        on_event("status", "正在让 DeepSeek 识别结构图片…")
    messages = [
        {"role": "system", "content": VISION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": VISION_USER_TEXT},
                {"type": "image_url", "image_url": {"url": image_b64}},
            ],
        },
    ]
    content, reasoning, finish, _model = stream_chat(
        config,
        messages,
        is_cancelled=is_cancelled,
        max_tokens=4096,
        reasoning_effort="none",
    )
    raw = content or reasoning
    data = _vision_json(raw)
    smiles = str(data.get("smiles") or "").strip().strip("`").strip()
    if not smiles or smiles.lower() in {"none", "null", "n/a"}:
        note = str(data.get("notes") or data.get("error") or "").strip()
        if finish == "length":
            raise DeepSeekError("识别输出被截断，请换一张更清晰/更小的图片重试")
        raise DeepSeekError(
            "未能从图片中识别出结构式"
            + (f"：{note}" if note else "；请换一张更清晰的图片，或手动填写 SMILES")
        )
    if len(smiles) > 2000:
        raise DeepSeekError("识别出的 SMILES 过长，请换一张更聚焦的图片")
    formula = str(data.get("formula") or "").strip()
    name = str(data.get("name") or "").strip()
    confidence = str(data.get("confidence") or "").strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = ""
    notes = str(data.get("notes") or "").strip()[:500]
    if on_event:
        on_event("status", "结构图片识别完成")
    return ImageStructureResult(
        smiles=smiles,
        formula=formula,
        name=name,
        confidence=confidence,
        notes=notes,
        raw=raw[:4000],
    )


def generate_poscar(
    config: AppConfig,
    payload: dict,
    *,
    on_event: EventCallback | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> GenerationResult:
    """生成并校验 POSCAR；首轮没有完整结构时关闭“自由发挥”再重试一次。"""
    started = time.time()
    model = (config.model or DEFAULT_MODEL).strip()
    if on_event:
        on_event("status", f"正在连接 DeepSeek（{model}）…")
    messages = _messages(payload)
    content, reasoning, finish, model = stream_chat(
        config, messages, on_event=on_event, is_cancelled=is_cancelled,
    )
    poscar = extract_poscar(content) or extract_poscar(reasoning)

    if not poscar:
        if on_event:
            on_event("status", "首轮未产出完整 POSCAR，已临时关闭思考模式重试…")
        retry_messages = list(messages) + [
            {"role": "assistant", "content": content or "（上一轮无正文）"},
            {"role": "user", "content": POSCAR_RETRY_HINT},
        ]
        content2, reasoning2, finish2, _ = stream_chat(
            config, retry_messages, on_event=on_event, is_cancelled=is_cancelled,
            reasoning_effort="none",
        )
        content = f"{content}\n\n{content2}".strip()
        reasoning = f"{reasoning}\n\n{reasoning2}".strip()
        poscar = extract_poscar(content2) or extract_poscar(reasoning2)
        finish = finish2

    if not poscar:
        if finish == "length":
            raise DeepSeekError(
                "模型输出达到长度上限，仍未给出完整 POSCAR。"
                "请减少原子数、换用 deepseek-v4-pro，或重试。"
            )
        raise DeepSeekError("模型没有返回可解析的 POSCAR，请补充分子信息后重试")

    poscar = center_poscar_in_cell(poscar)
    if on_event:
        on_event("status", "已获得 POSCAR，正在解析结构…")
    return GenerationResult(
        poscar=poscar,
        reply=content or reasoning,
        content_chars=len(content),
        thinking_chars=len(reasoning),
        finish_reason=finish,
        elapsed=time.time() - started,
        model=model,
    )
