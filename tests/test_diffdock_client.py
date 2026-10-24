import json

import pytest
import requests

from diffdock_client import DiffDockClient, DiffDockError, parse_response

CFG = {"url": "https://example.invalid/diffdock", "max_retries": 2, "backoff_s": 0, "timeout_s": 5,
       "poll_url": "https://example.invalid/status/{req_id}", "poll_interval_s": 0, "max_wait_s": 5}
OK = {"status": "success", "ligand_positions": ["A\n$$$$", "B\n$$$$"], "position_confidence": [0.5, -1.2]}


class Resp:
    def __init__(self, code, body=None, headers=None):
        self.status_code, self._body, self.headers = code, body or {}, headers or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, posts, gets=()):
        self.posts, self.gets, self.calls = list(posts), list(gets), []

    def post(self, url, headers, json, timeout):
        self.calls.append(("POST", url, headers, json))
        r = self.posts.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def get(self, url, headers, timeout):
        self.calls.append(("GET", url))
        return self.gets.pop(0)


def test_parse_flat_and_batch():
    assert parse_response(OK) == (["A\n$$$$", "B\n$$$$"], [0.5, -1.2])
    nested = {"status": ["success"], "ligand_positions": [["A"]], "position_confidence": [[0.1]]}
    assert parse_response(nested) == (["A"], [0.1])
    with pytest.raises(DiffDockError, match="fail"):
        parse_response({"status": "fail", "details": "bad ligand"})
    with pytest.raises(DiffDockError, match="poses but"):
        parse_response({"ligand_positions": ["A"], "position_confidence": [1, 2]})


def test_request_payload_auth_and_cache(tmp_path):
    s = FakeSession([Resp(200, OK)])
    c = DiffDockClient("nvapi-test", CFG, tmp_path, session=s)
    r1 = c.dock("PDB", "SDF", 5)
    _, url, headers, payload = s.calls[0]
    assert headers["Authorization"] == "Bearer nvapi-test"
    assert payload == {"protein": "PDB", "ligand": "SDF", "ligand_file_type": "sdf", "num_poses": 5,
                       "time_divisions": 20, "steps": 18, "save_trajectory": False}
    assert not r1.from_cache and r1.confidences == [0.5, -1.2]
    r2 = c.dock("PDB", "SDF", 5)            # served from disk, no HTTP
    assert r2.from_cache and len(s.calls) == 1
    assert json.loads(open(r2.cache_file).read()) == OK


def test_cache_works_without_key(tmp_path):
    DiffDockClient("k", CFG, tmp_path, session=FakeSession([Resp(200, OK)])).dock("P", "L", 5)
    assert DiffDockClient(None, CFG, tmp_path, session=FakeSession([])).dock("P", "L", 5).from_cache
    with pytest.raises(DiffDockError, match="NVIDIA_API_KEY"):
        DiffDockClient(None, CFG, tmp_path, session=FakeSession([])).dock("P", "other", 5)


def test_retry_on_503_and_connection_error(tmp_path):
    s = FakeSession([Resp(503), requests.ConnectionError("boom"), Resp(200, OK)])
    assert DiffDockClient("k", CFG, tmp_path, session=s).dock("P", "L", 2).poses
    assert len(s.calls) == 3


def test_retries_are_limited(tmp_path):
    s = FakeSession([Resp(503)] * 3)
    with pytest.raises(DiffDockError, match="after 3 attempts"):
        DiffDockClient("k", CFG, tmp_path, session=s).dock("P", "L", 2)
    assert not list(tmp_path.glob("*.json"))   # failures are not cached


def test_no_retry_on_auth_or_validation_error(tmp_path):
    with pytest.raises(DiffDockError, match="authentication"):
        DiffDockClient("k", CFG, tmp_path, session=FakeSession([Resp(401)])).dock("P", "L", 2)
    s = FakeSession([Resp(422, {"detail": [{"msg": "bad"}]})])
    with pytest.raises(DiffDockError, match="422"):
        DiffDockClient("k", CFG, tmp_path, session=s).dock("P", "L", 2)
    assert len(s.calls) == 1


def test_async_202_polling(tmp_path):
    s = FakeSession([Resp(202, headers={"NVCF-REQID": "abc"})], gets=[Resp(202), Resp(200, OK)])
    r = DiffDockClient("k", CFG, tmp_path, session=s).dock("P", "L", 2)
    assert r.poses and s.calls[1] == ("GET", "https://example.invalid/status/abc")
