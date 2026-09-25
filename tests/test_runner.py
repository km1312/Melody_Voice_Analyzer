"""The runner over a fake provider, and the openai_compat transport (M9)."""

import json
import urllib.error

import pytest

from revolv.interpret.providers.base import Completion
from revolv.interpret.providers.openai_compat import OpenAICompatProvider
from revolv.interpret.runner import (RunError, provider_from_settings,
                                     run_interpretation)
from revolv.netguard import EgressError
from test_gui_results import _valid_response


def _draft(report):
    return json.loads(_valid_response(report))


class FakeProvider:
    """Answers each pass with canned JSON, tracking the order of calls."""

    id = "fake"
    egress = "none"
    model = "fake-1"

    def __init__(self, report, fail_first=False):
        self.report = report
        self.calls = []
        self.fail_first = fail_first
        draft = _draft(report)
        insight = draft["insights"][0]
        self.answers = {
            "PASS A: OBSERVE": {
                "topics": draft["topics"],
                "facts": {"decisions": draft["notes"]["decisions"],
                          "action_items": [], "open_questions": [],
                          "key_numbers": []},
                "observations": [
                    {"id": "ob1", "turn_id": e["turn_id"],
                     "speaker": insight["speaker"], "quote": e.get("quote", ""),
                     "channel": e["channel"], "description": e["description"],
                     "moment_ids": e.get("moment_ids", []), "topic_id": "tp1"}
                    for e in insight["evidence"]],
                "per_speaker": [{"speaker": insight["speaker"],
                                 "most_words_on": ["tp1"], "raised_first": [],
                                 "returned_to": [], "asked_about": []}],
            },
            "PASS B: COMPETING": {
                "clusters": [{
                    "id": "cl1", "speaker": insight["speaker"],
                    "topic_id": "tp1", "layer": "unsaid",
                    "readings": [
                        {"id": "r1", "text": insight["claim"],
                         "ordinary": False, "supports": ["ob1"],
                         "against": []},
                        {"id": "r2", "text": insight["alternatives"][0],
                         "ordinary": True, "supports": ["ob1"],
                         "against": []}],
                    "favoured": "r1",
                    "likelihood": "roughly even chance",
                    "evidence_confidence": "low", "why": "clustered"}],
                "nothing_notable": ["SPEAKER_00"],
            },
            "PASS C: SCEPTICAL": {
                "reviews": [{"cluster_id": "cl1", "verdict": "keep",
                             "likelihood": "roughly even chance",
                             "evidence_confidence": "low",
                             "claim": insight["claim"], "reason": ""}],
            },
            "PASS D: WRITE UP": draft,
            "SINGLE PASS": draft,
        }

    def _answer_for(self, user):
        for marker, answer in self.answers.items():
            if marker in user:
                return answer
        raise AssertionError("Unrecognised prompt")

    def complete(self, *, system, user, json_schema=None, temperature=0.3,
                 seed=None, max_tokens=6000):
        self.calls.append({"user": user, "temperature": temperature})
        if self.fail_first and len(self.calls) == 1:
            text = "this is not json"
        else:
            text = json.dumps(self._answer_for(user))
        return Completion(text=text, tokens_in=1000, tokens_out=500,
                          seconds=0.1, model=self.model, provider=self.id)


@pytest.fixture()
def meta(fixture_meta, fixture_report):
    return dict(fixture_meta, analysis=fixture_report, numbers_file=True)


def test_single_pass_end_to_end(tmp_path, fixture_segments, meta,
                                fixture_report):
    provider = FakeProvider(fixture_report)
    result = run_interpretation(fixture_segments, meta, tmp_path, "call",
                                provider)
    assert result.problems == []
    document = json.loads(result.insights_path.read_text(encoding="utf-8"))
    assert document["run"]["provider"] == "fake"
    assert document["run"]["mode"] == "single_pass"
    assert document["run"]["model"] == "fake-1"
    assert len(document["insights"]) == 1
    assert len(provider.calls) == 1
    run_dirs = list((tmp_path / "call.prompt").glob("run_*"))
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "single_pass.json").exists()


def test_multi_pass_runs_four_passes_in_order(tmp_path, fixture_segments,
                                              meta, fixture_report):
    provider = FakeProvider(fixture_report)
    result = run_interpretation(fixture_segments, meta, tmp_path, "call",
                                provider, mode="multi_pass")
    assert result.problems == []
    markers = ["PASS A: OBSERVE", "PASS B: COMPETING", "PASS C: SCEPTICAL",
               "PASS D: WRITE UP"]
    assert len(provider.calls) == 4
    for call, marker in zip(provider.calls, markers):
        assert marker in call["user"]
    # B and C receive the earlier passes' JSON in their slots.
    assert '"ob1"' in provider.calls[1]["user"]
    assert '"cl1"' in provider.calls[2]["user"]
    assert "{{" not in provider.calls[3]["user"]
    document = json.loads(result.insights_path.read_text(encoding="utf-8"))
    assert document["run"]["mode"] == "multi_pass"
    run_dir = next((tmp_path / "call.prompt").glob("run_*"))
    for name in ("pass_a", "pass_b", "pass_c", "pass_d"):
        assert (run_dir / (name + ".json")).exists()


def test_schema_failure_retries_once_quoting_the_error(tmp_path,
                                                       fixture_segments,
                                                       meta, fixture_report):
    provider = FakeProvider(fixture_report, fail_first=True)
    result = run_interpretation(fixture_segments, meta, tmp_path, "call",
                                provider)
    assert result.problems == []
    assert len(provider.calls) == 2
    assert "failed validation" in provider.calls[1]["user"]
    run_dir = next((tmp_path / "call.prompt").glob("run_*"))
    assert (run_dir / "single_pass_retry.json").exists()


def test_remote_providers_are_refused(tmp_path, fixture_segments, meta):
    class Remote:
        id = "cloud"
        egress = "remote"

    with pytest.raises(RunError):
        run_interpretation(fixture_segments, meta, tmp_path, "call",
                           Remote())


def test_provider_from_settings():
    assert provider_from_settings({"provider": "manual"}) is None
    provider = provider_from_settings(
        {"provider": "openai_compat",
         "provider_base_url": "http://127.0.0.1:9999/v1",
         "provider_model": "m"})
    assert provider.model == "m"
    with pytest.raises(RunError):
        provider_from_settings({"provider": "mystery"})


# -- the transport ----------------------------------------------------------

def test_openai_compat_refuses_non_loopback():
    with pytest.raises(EgressError):
        OpenAICompatProvider("http://192.168.0.5:8080/v1")


def test_openai_compat_parses_replies():
    def opener(url, payload):
        assert url.endswith("/chat/completions")
        assert payload["messages"][0]["role"] == "system"
        assert payload["response_format"]["type"] == "json_schema"
        return {"choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
                "model": "served-model"}

    provider = OpenAICompatProvider("http://127.0.0.1:8080/v1", model="m",
                                    opener=opener)
    completion = provider.complete(system="s", user="u",
                                   json_schema={"title": "t"})
    assert completion.text == '{"ok": true}'
    assert completion.tokens_in == 12
    assert completion.model == "served-model"


def test_openai_compat_falls_back_to_plain_json():
    calls = []

    def opener(url, payload):
        calls.append(payload)
        if "response_format" in payload:
            raise urllib.error.HTTPError(url, 400, "no response_format",
                                         {}, None)
        return {"choices": [{"message": {"content": "{}"}}]}

    provider = OpenAICompatProvider("http://127.0.0.1:8080/v1",
                                    opener=opener)
    completion = provider.complete(system="s", user="u",
                                   json_schema={"title": "t"})
    assert completion.text == "{}"
    assert len(calls) == 2
    assert "response_format" not in calls[1]
