import os
import time

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql://postgres@localhost:5432/collab_test")
from app.main import create_app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def recv(ws, type_):
    while True:
        msg = ws.receive_json()
        if msg["type"] == type_:
            return msg


def ins(pos, text):
    return [{"type": "insert", "pos": pos, "text": text}]


def test_document_crud(client):
    doc = client.post("/documents", json={"title": "Notes"}).json()
    assert doc["version"] == 0 and doc["content"] == ""
    assert client.get(f"/documents/{doc['id']}").json()["title"] == "Notes"
    assert any(d["id"] == doc["id"] for d in client.get("/documents").json())
    assert client.get("/documents/not-a-uuid").status_code == 404
    assert client.post("/documents", json={"title": ""}).status_code == 422


def test_concurrent_edits_converge_and_persist(client):
    doc_id = client.post("/documents", json={"title": "t"}).json()["id"]
    with client.websocket_connect(f"/ws/documents/{doc_id}?name=ann") as a, \
         client.websocket_connect(f"/ws/documents/{doc_id}?name=bob") as b:
        assert recv(a, "snapshot")["version"] == 0
        assert recv(b, "snapshot")["version"] == 0
        # both edit version 0 without seeing each other's change
        a.send_json({"type": "op", "version": 0, "op": ins(0, "hello"), "client_op_id": "a1"})
        first = recv(a, "op")
        b.send_json({"type": "op", "version": 0, "op": ins(0, "world"), "client_op_id": "b1"})
        second = recv(b, "op")
        while second["client_op_id"] != "b1":
            second = recv(b, "op")
        assert (first["version"], second["version"]) == (1, 2)
        assert second["op"] == ins(5, "world")  # transformed past ann's insert
    assert client.get(f"/documents/{doc_id}").json()["content"] == "helloworld"


def test_bad_op_is_rejected(client):
    doc_id = client.post("/documents", json={"title": "t"}).json()["id"]
    with client.websocket_connect(f"/ws/documents/{doc_id}") as ws:
        recv(ws, "snapshot")
        ws.send_json({"type": "op", "version": 0, "op": ins(3, "x"), "client_op_id": "c"})
        assert recv(ws, "error")["client_op_id"] == "c"
        ws.send_json({"type": "op", "version": 9, "op": ins(0, "x")})
        assert recv(ws, "error")["message"] == "bad base version"


def test_two_instances_share_edits_and_presence_via_redis():
    with TestClient(create_app()) as one, TestClient(create_app()) as two:
        doc_id = one.post("/documents", json={"title": "t"}).json()["id"]
        with one.websocket_connect(f"/ws/documents/{doc_id}?name=ann") as a:
            recv(a, "snapshot")
            with two.websocket_connect(f"/ws/documents/{doc_id}?name=bob") as b:
                snap = recv(b, "snapshot")
                assert sorted(snap["users"].values()) == ["ann", "bob"]
                assert recv(a, "join")["name"] == "bob"
                b.send_json({"type": "op", "version": 0, "op": ins(0, "hi"), "client_op_id": "x"})
                got = recv(a, "op")
                assert got["op"] == ins(0, "hi") and got["author"] == "bob"
            assert recv(a, "leave")["id"] == snap["you"]
