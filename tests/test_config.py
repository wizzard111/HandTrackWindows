import json

from handtrack import config, paths


def test_settings_roundtrip_and_v6_migration(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "SETTINGS_PATH", str(tmp_path / "s.json"))
    (tmp_path / "s.json").write_text(json.dumps({
        "hide_face_var": True, "threshold_var": 0.8, "resolution_var": "1920x1080",
        "lang_var": "en", "bogus": 1,
    }), encoding="utf-8")
    s = config.Settings.load()
    assert s.hide_face is True and s.threshold == 0.8
    assert s.resolution == "1920x1080" and s.lang == "en"
    s.gaze = False
    s.save()
    again = config.Settings.load()
    assert again.gaze is False and again.hide_face is True


def test_invalid_settings_fall_back(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "SETTINGS_PATH", str(tmp_path / "s.json"))
    (tmp_path / "s.json").write_text("{not json", encoding="utf-8")
    assert config.Settings.load() == config.Settings()


def test_custom_gestures_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "CUSTOM_GESTURES_PATH", str(tmp_path / "g.json"))
    (tmp_path / "g.json").write_text(json.dumps([
        {"name": "ok", "pattern": [0, 1, 0, 0, 0], "action_type": "mute"},
        {"name": "bad action", "pattern": [0, 1, 0, 0, 0], "action_type": "rm -rf"},
        {"name": "short", "pattern": [1], "action_type": "mute"},
    ]), encoding="utf-8")
    gestures = config.load_custom_gestures()
    assert [g["name"] for g in gestures] == ["ok"]
    assert gestures[0]["pattern"] == (False, True, False, False, False)
