from __future__ import annotations

import threading
import time
import types

from renforge.tools import live


def test_inspect_screen_forwards_name_to_bridge_client(tmp_path, monkeypatch):
    (tmp_path / "game").mkdir()
    calls = {}

    class FakeClient:
        def inspect_screen(self, name):
            calls["name"] = name
            return {"ok": True, "active": False, "name": name}

    monkeypatch.setattr(live, "_client", lambda _path: FakeClient())

    result = live.inspect_screen(str(tmp_path), "custom")

    assert result == {"ok": True, "active": False, "name": "custom"}
    assert calls == {"name": "custom"}


def test_start_launch_echoes_requested_language(tmp_path):
    (tmp_path / "game").mkdir()

    result = live.start_launch(
        str(tmp_path),
        lambda _project_root, _cancel_event: {
            "ok": True,
            "ready": True,
            "current_label": "main_menu",
        },
        language="japanese",
        wait_timeout=1.0,
    )

    assert result["ok"] is True
    assert result["ready"] is True
    assert result["requested_language"] == "japanese"
    assert result["active_language"] is None


def test_launch_status_reports_requested_language_while_starting(tmp_path):
    (tmp_path / "game").mkdir()
    release = threading.Event()
    started = threading.Event()

    def delayed_launch(_project_root, _cancel_event):
        started.set()
        assert release.wait(2.0)
        return {"ok": True, "ready": True, "current_label": "main_menu"}

    result = live.start_launch(
        str(tmp_path),
        delayed_launch,
        language="japanese",
        wait_timeout=0.0,
    )
    assert started.wait(1.0)
    assert result["status"] == "starting"
    assert result["requested_language"] == "japanese"

    release.set()
    deadline = time.monotonic() + 2.0
    final = result
    while time.monotonic() < deadline:
        final = live.launch_status(str(tmp_path))
        if final.get("ready"):
            break
        time.sleep(0.01)

    assert final["ready"] is True
    assert final["requested_language"] == "japanese"
    assert final["active_language"] is None


def test_start_launch_does_not_claim_a_new_language_for_a_running_task(tmp_path):
    (tmp_path / "game").mkdir()
    release = threading.Event()
    started = threading.Event()

    def delayed_launch(_project_root, _cancel_event):
        started.set()
        assert release.wait(2.0)
        return {"ok": True, "ready": True, "current_label": "main_menu"}

    live.start_launch(
        str(tmp_path),
        delayed_launch,
        language="japanese",
        wait_timeout=0.0,
    )
    assert started.wait(1.0)
    try:
        conflict = live.start_launch(
            str(tmp_path),
            lambda _project_root, _cancel_event: {"ok": True, "ready": True},
            language="german",
            wait_timeout=0.0,
        )

        assert conflict["code"] == "LAUNCH_IN_PROGRESS"
        assert conflict["requested_language"] == "german"
        assert conflict["language_applied"] is False
    finally:
        release.set()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if live.launch_status(str(tmp_path)).get("ready"):
                break
            time.sleep(0.01)
        live.stop_game(str(tmp_path))


def test_launch_game_echoes_language_from_a_fresh_session(tmp_path, monkeypatch):
    (tmp_path / "game").mkdir()
    calls = {}
    session = types.SimpleNamespace(
        editor=True,
        display_mode="native",
        startup_ms=1,
        phases=[],
        environment={},
        temporary_savedir=None,
        headless=False,
        process=types.SimpleNamespace(poll=lambda: None),
        client=types.SimpleNamespace(
            get_state=lambda: {"current_label": "start", "language": "japanese"}
        ),
    )
    monkeypatch.setattr(live, "get_or_install_sdk", lambda *_args, **_kwargs: object())

    def fake_launch_with_bridge(_sdk, _project, **kwargs):
        calls.update(kwargs)
        return session

    monkeypatch.setattr(live, "launch_with_bridge", fake_launch_with_bridge)

    result = live.launch_game(str(tmp_path), language="japanese")

    assert calls["language"] == "japanese"
    assert result["requested_language"] == "japanese"
    assert result["active_language"] == "japanese"
    live._SESSIONS.pop(live._key(tmp_path), None)


def test_launch_game_reports_language_cannot_change_a_running_session(tmp_path, monkeypatch):
    (tmp_path / "game").mkdir()
    session = types.SimpleNamespace(
        editor=True,
        process=types.SimpleNamespace(poll=lambda: None),
        client=types.SimpleNamespace(
            get_state=lambda: {"current_label": "start", "language": "english"}
        ),
    )
    monkeypatch.setitem(live._SESSIONS, live._key(tmp_path), session)

    result = live.launch_game(str(tmp_path), language="japanese")

    assert result["already_running"] is True
    assert result["requested_language"] == "japanese"
    assert result["active_language"] == "english"
    assert result["language_applied"] is False
    assert "cannot be applied" in result["message"]


def test_launch_game_reports_language_cannot_apply_when_project_is_locked(tmp_path, monkeypatch):
    (tmp_path / "game").mkdir()
    monkeypatch.setattr(live, "_SESSIONS", {})
    monkeypatch.setattr(
        live,
        "_client",
        lambda _path: types.SimpleNamespace(
            get_state=lambda: {"current_label": "start", "language": "english"}
        ),
    )

    result = live.launch_game(str(tmp_path), warp="game/script.rpy:1", language="japanese")

    assert result["code"] == "BRIDGE_PROJECT_LOCKED"
    assert result["requested_language"] == "japanese"
    assert result["language_applied"] is False
    assert "cannot be applied" in result["message"]
