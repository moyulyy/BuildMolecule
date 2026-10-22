"""CAS Common Chemistry 检索测试：使用本地 mock 服务，不访问外网。"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from mk_mole.services import cas
from mk_mole.services.pubchem import CompoundInfo, PubChemError

MOLFILE = (
    "Benzene\n"
    "C6H6\n"
    "71-43-2\n"
    "  6  6  0  0  0  0  0  0  0  0999 V2000\n"
    "    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\n"
    "M  END\n"
)


class _Handler(BaseHTTPRequestHandler):
    record: dict = {}
    requests_made: list = []
    status = 200
    payload: dict = {}
    export_status = 200
    export_text = MOLFILE

    def log_message(self, *args):  # noqa: D401
        return

    def do_GET(self):  # noqa: N802
        _Handler.record = {"path": self.path, "headers": dict(self.headers)}
        _Handler.requests_made.append(_Handler.record)
        if "/export" in self.path:
            body = _Handler.export_text.encode("utf-8")
            content_type = "text/plain"
            status = _Handler.export_status
        else:
            body = json.dumps(_Handler.payload).encode("utf-8")
            content_type = "application/json"
            status = _Handler.status
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def cas_server():
    _Handler.record = {}
    _Handler.requests_made = []
    _Handler.status = 200
    _Handler.payload = {}
    _Handler.export_status = 200
    _Handler.export_text = MOLFILE
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    yield f"http://127.0.0.1:{httpd.server_address[1]}/api"
    httpd.shutdown()
    httpd.server_close()


def test_cas_uses_official_direct_api() -> None:
    assert cas.CAS_API_BASE == "https://commonchemistry.cas.org/direct-api"
    assert cas.CAS_ORIGIN == "https://commonchemistry.cas.org/api-overview"


def test_flatten_cas_svg_for_qt_svg() -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="90" '
        'viewBox="0 0 100 90" style="stroke:black;">'
        '<svg><svg x="6" y="0" width="88" height="90" viewBox="0 0 88 90">'
        '<line x1="0" y1="0" x2="10" y2="10" style="fill:none;" />'
        '</svg></svg></svg>'
    )

    flat = cas._flatten_cas_svg(svg)

    assert flat.count("<svg") == 1
    assert 'stroke="black"' in flat
    assert "translate(6,0)" in flat
    assert cas._flatten_cas_svg("not an svg") == "not an svg"


def test_lookup_cas_official_parses_detail(cas_server) -> None:
    _Handler.payload = {
        "uri": "substance/pt/71432",
        "rn": "71-43-2",
        "name": "Benzene",
        "images": ["<svg xmlns='http://www.w3.org/2000/svg'></svg>"],
        "canonicalSmile": "C=1C=CC=CC1",
        "molecularFormula": "C<sub>6</sub>H<sub>6</sub>",
        "molecularMass": "78.11",
        "synonyms": ["Benzene", "MeSH ID: D001554", "<em>1</em>,3-Cyclopentadiene"],
        "hasMolfile": True,
    }

    info = cas.lookup_cas_official("71-43-2", "test-cas-key", base_url=cas_server)

    assert info.cid is None
    assert info.cas == "71-43-2"
    assert info.formula == "C6H6"
    assert info.molecular_weight == pytest.approx(78.11)
    assert info.smiles == "C=1C=CC=CC1"
    assert info.title == "Benzene"
    assert info.synonyms == ["Benzene", "1,3-Cyclopentadiene"]
    assert info.svg.startswith("<svg")
    assert info.source == "CAS Common Chemistry"
    assert info.sdf.startswith("Benzene")
    assert info.atom_count == 6
    detail_request = next(
        item for item in _Handler.requests_made if "/detail" in item["path"]
    )
    assert detail_request["headers"].get("X-API-KEY") == "test-cas-key"
    assert detail_request["headers"].get("x-origin") == cas.CAS_ORIGIN
    assert "cas_rn=71-43-2" in detail_request["path"]
    assert any("/export" in item["path"] for item in _Handler.requests_made)


def test_lookup_cas_official_rejects_invalid_key(cas_server) -> None:
    _Handler.status = 401
    _Handler.payload = {"message": "Unauthorized"}

    with pytest.raises(cas.CASAuthError):
        cas.lookup_cas_official("71-43-2", "bad-key", base_url=cas_server)


def test_lookup_compound_falls_back_to_pubchem_when_not_found(cas_server, monkeypatch) -> None:
    _Handler.status = 404
    expected = CompoundInfo(cid=241, cas="71-43-2", formula="C6H6")
    monkeypatch.setattr(cas, "lookup_pubchem", lambda value: expected)

    assert cas.lookup_compound("71-43-2", "test-key", base_url=cas_server) is expected


def test_lookup_compound_uses_pubchem_without_key(monkeypatch) -> None:
    expected = CompoundInfo(cid=241, cas="71-43-2", formula="C6H6")
    monkeypatch.setattr(cas, "lookup_pubchem", lambda value: expected)

    assert cas.lookup_compound("71-43-2") is expected


def test_lookup_compound_does_not_hide_invalid_key(cas_server, monkeypatch) -> None:
    _Handler.status = 401
    monkeypatch.setattr(
        cas, "lookup_pubchem",
        lambda value: pytest.fail("Key 无效时不应回退到 PubChem"),
    )

    with pytest.raises(cas.CASAuthError):
        cas.lookup_compound("71-43-2", "bad-key", base_url=cas_server)


def test_lookup_compound_requires_cas(monkeypatch) -> None:
    monkeypatch.setattr(cas, "lookup_pubchem", lambda value: pytest.fail("不应调用 PubChem"))

    with pytest.raises(PubChemError):
        cas.lookup_compound("  ")
