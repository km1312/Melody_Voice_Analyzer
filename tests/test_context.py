import json

from revolv.interpret import context as context_module


def test_defaults_are_valid():
    assert context_module.validate(context_module.default_context()) == []


def test_round_trip(tmp_path):
    path = tmp_path / "call.context.json"
    context = context_module.default_context()
    context["meeting_type"] = "investor_pitch"
    context["goal"] = "Close the round"
    context["me"] = "SPEAKER_00"
    context["speaker_names"] = {"SPEAKER_00": "Me", "SPEAKER_01": "Brian"}
    context["consent"] = {"all_parties_knew": "yes", "cloud_ok": False}
    assert context_module.save(context, path) == []
    loaded = context_module.load(path)
    for key in ("meeting_type", "goal", "me", "speaker_names", "consent"):
        assert loaded[key] == context[key]


def test_save_keeps_a_bak(tmp_path):
    path = tmp_path / "call.context.json"
    first = context_module.default_context()
    first["goal"] = "first"
    context_module.save(first, path)
    second = context_module.default_context()
    second["goal"] = "second"
    context_module.save(second, path)
    bak = tmp_path / "call.context.json.bak"
    assert bak.exists()
    assert json.loads(bak.read_text(encoding="utf-8"))["goal"] == "first"
    assert context_module.load(path)["goal"] == "second"


def test_missing_file_yields_defaults(tmp_path):
    assert context_module.load(tmp_path / "nope.context.json") == \
        context_module.default_context()


def test_corrupt_file_yields_defaults(tmp_path):
    path = tmp_path / "call.context.json"
    path.write_text("{not json", encoding="utf-8")
    assert context_module.load(path) == context_module.default_context()


def test_validation_speaks_plain_words():
    bad = context_module.default_context()
    bad["meeting_type"] = "party"
    bad["consent"] = {"all_parties_knew": "perhaps", "cloud_ok": "yes"}
    problems = context_module.validate(bad)
    assert len(problems) == 3
    assert any("meeting type" in p for p in problems)
    # save() surfaces the same problems and writes nothing.
    assert context_module.save(bad, "unused.context.json") == problems


def test_unknown_keys_are_dropped(tmp_path):
    path = tmp_path / "call.context.json"
    path.write_text(json.dumps({"goal": "kept", "surprise": True}),
                    encoding="utf-8")
    loaded = context_module.load(path)
    assert loaded["goal"] == "kept"
    assert "surprise" not in loaded


def test_context_path():
    assert context_module.context_path("out/call.json").name == "call.context.json"
    assert context_module.context_path("out/call.mp4").name == "call.context.json"
