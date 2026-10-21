"""DeepSeek 流式客户端测试：使用本地 mock SSE 服务，不访问外网。"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from mk_mole.config import AppConfig
from mk_mole.services.deepseek import DeepSeekError, generate_poscar, parse_structure_image
from tests.test_poscar import BENZENE

CONTENT = "结构如下：\n```poscar\n" + BENZENE + "```\n"
VISION_CONTENT = (
    '```json\n{"smiles":"c1ccccc1","formula":"C6H6","name":"苯",'
    '"confidence":"high","notes":"平面芳香环"}\n```'
)


class _Handler(BaseHTTPRequestHandler):
    last_body: dict = {}

    def log_message(self, *args):  # noqa: D401
        return

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            _Handler.last_body = json.loads(raw or b"{}")
        except ValueError:
            _Handler.last_body = {}
        if self.path.endswith("/unauthorized/chat/completions"):
            payload = json.dumps({"error": {"message": "Authentication Fails"}}).encode()
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if "/vision/" in self.path:
            for index in range(0, len(VISION_CONTENT), 48):
                chunk = {"choices": [{"delta": {"content": VISION_CONTENT[index:index + 48]}}]}
                line = "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"
                self.wfile.write(line.encode())
                self.wfile.flush()
                time.sleep(0.003)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        for piece in ("苯环是平面正六边形。", "C-C 1.39 Å。"):
            chunk = {"choices": [{"delta": {"reasoning_content": piece}}]}
            line = "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"
            self.wfile.write(line.encode())
            self.wfile.flush()
            time.sleep(0.005)
        for index in range(0, len(CONTENT), 64):
            chunk = {"choices": [{"delta": {"content": CONTENT[index:index + 64]}}]}
            line = "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"
            self.wfile.write(line.encode())
            self.wfile.flush()
            time.sleep(0.005)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


@pytest.fixture()
def server():
    _Handler.last_body = {}
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def _config(server, path: str = "v1", *, effort: str = "high") -> AppConfig:
    port = server.server_address[1]
    return AppConfig(
        api_key="test-key",
        base_url=f"http://127.0.0.1:{port}/{path}",
        model="deepseek-flash",
        reasoning_effort=effort,
    )


def test_stream_generates_poscar(server) -> None:
    events: list[str] = []
    result = generate_poscar(
        _config(server),
        {"formula": "C6H6", "name": "苯"},
        on_event=lambda kind, text: events.append(kind),
    )
    assert result.poscar.startswith("benzene")
    assert "C H" in result.poscar
    assert "thinking" in events and "content" in events
    assert result.model == "deepseek-flash"
    assert result.thinking_chars > 0 and result.content_chars > 0
    assert _Handler.last_body["model"] == "deepseek-flash"
    assert _Handler.last_body["reasoning_effort"] == "high"
    assert _Handler.last_body["thinking"] == {"type": "enabled"}
    assert _Handler.last_body["max_tokens"] == 65536
    assert "temperature" not in _Handler.last_body


def test_effort_none_disables_thinking(server) -> None:
    generate_poscar(
        _config(server, effort="none"),
        {"formula": "C6H6"},
    )
    assert _Handler.last_body["reasoning_effort"] == "none"
    assert _Handler.last_body["thinking"] == {"type": "disabled"}
    assert _Handler.last_body["temperature"] == 0.2


def test_image_is_sent_as_image_url(server) -> None:
    image = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    generate_poscar(
        _config(server),
        {"formula": "C6H6", "image_b64": image},
    )
    user = _Handler.last_body["messages"][-1]
    assert user["role"] == "user"
    assert isinstance(user["content"], list)
    assert any(
        part.get("type") == "image_url" and part.get("image_url", {}).get("url") == image
        for part in user["content"]
    )
    text = next(part["text"] for part in user["content"] if part.get("type") == "text")
    assert "已提供结构图片" in text


def test_image_only_prompt_allows_missing_formula(server) -> None:
    image = "data:image/png;base64,AAAA"
    result = generate_poscar(_config(server), {"formula": "", "image_b64": image})
    assert result.poscar.startswith("benzene")
    user = _Handler.last_body["messages"][-1]
    assert isinstance(user["content"], list)
    text = next(part["text"] for part in user["content"] if part.get("type") == "text")
    assert "用户没有提供分子式" in text
    assert "不要反问" in text
    assert any(part.get("type") == "image_url" for part in user["content"])


def test_parse_structure_image(server) -> None:
    image = "data:image/png;base64,AAAA"
    result = parse_structure_image(_config(server, "vision"), image)
    assert result.smiles == "c1ccccc1"
    assert result.formula == "C6H6"
    assert result.name == "苯"
    assert result.confidence == "high"
    assert "芳香" in result.notes
    body = _Handler.last_body
    assert body["reasoning_effort"] == "none"
    assert body["thinking"] == {"type": "disabled"}
    user = body["messages"][-1]
    assert isinstance(user["content"], list)
    assert any(
        part.get("type") == "image_url" and part["image_url"]["url"] == image
        for part in user["content"]
    )


def test_prompt_priority_and_source(server) -> None:
    generate_poscar(
        _config(server),
        {
            "formula": "C6H6",
            "smiles": "c1ccccc1",
            "structure_source": "Ketcher 结构编辑",
        },
    )
    messages = _Handler.last_body["messages"]
    system = messages[0]["content"]
    user = messages[1]["content"]
    assert "输入优先级" in system
    assert "结构编辑器" in system
    assert "30.0 0.0 0.0" in system
    assert "结构来源：Ketcher 结构编辑" in user
    assert "SMILES 结构：c1ccccc1" in user
    assert "原子数核对" in user


def test_http_error_is_friendly(server) -> None:
    with pytest.raises(DeepSeekError) as exc:
        generate_poscar(
            _config(server, "unauthorized"),
            {"formula": "C6H6"},
        )
    assert "API Key 无效" in str(exc.value)
