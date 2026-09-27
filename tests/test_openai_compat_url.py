"""Fix list #11: a base URL without /v1 posts to the server root.

LM Studio answers such a request with HTTP 200 and a non-completion body,
which reached the user as a schema error. The provider now adds /v1 to a
URL that has no path, says so, and names the likely cause when a reply is
not a chat completion. Kept apart from test_runner.py so it runs without
PySide6 (test_runner imports a GUI test module for its fixtures).
"""

import pytest

from revolv.interpret.providers.base import ProviderError
from revolv.interpret.providers.openai_compat import (
    OpenAICompatProvider, missing_prefix_hint, normalise_base_url)


@pytest.mark.parametrize("given, expected", [
    ("http://127.0.0.1:1234", "http://127.0.0.1:1234/v1"),
    ("http://127.0.0.1:1234/", "http://127.0.0.1:1234/v1"),
    ("  http://localhost:11434  ", "http://localhost:11434/v1"),
])
def test_url_with_no_path_gets_v1(given, expected):
    fixed, note = normalise_base_url(given)
    assert fixed == expected
    assert note and "/v1" in note


@pytest.mark.parametrize("given, expected", [
    ("http://127.0.0.1:1234/v1", "http://127.0.0.1:1234/v1"),
    ("http://127.0.0.1:1234/v1/", "http://127.0.0.1:1234/v1"),
    ("http://127.0.0.1:8080/api", "http://127.0.0.1:8080/api"),
])
def test_url_with_a_path_is_left_alone(given, expected):
    fixed, note = normalise_base_url(given)
    assert fixed == expected
    assert note == ""


def test_empty_url_stays_empty():
    assert normalise_base_url("") == ("", "")
    assert normalise_base_url(None) == ("", "")


def test_provider_posts_to_v1_when_the_path_was_missing():
    seen = []

    def opener(url, payload):
        seen.append(url)
        return {"choices": [{"message": {"content": "{}"}}]}

    provider = OpenAICompatProvider("http://127.0.0.1:1234", opener=opener)
    assert provider.base_url == "http://127.0.0.1:1234/v1"
    assert provider.note
    provider.complete(system="s", user="u")
    assert seen == ["http://127.0.0.1:1234/v1/chat/completions"]


def test_provider_keeps_an_explicit_v1_and_says_nothing():
    provider = OpenAICompatProvider("http://127.0.0.1:1234/v1/",
                                    opener=lambda url, payload: {})
    assert provider.base_url == "http://127.0.0.1:1234/v1"
    assert provider.note == ""


def test_non_completion_reply_names_the_url_and_the_v1_hint():
    """A custom path that is not /v1 and a root-style 200 answer: the error
    says where it asked and what local servers expect."""
    provider = OpenAICompatProvider(
        "http://127.0.0.1:1234/api", opener=lambda url, payload: {"ok": True})
    with pytest.raises(ProviderError) as caught:
        provider.complete(system="s", user="u")
    message = str(caught.value)
    assert "http://127.0.0.1:1234/api" in message
    assert "/v1" in message


def test_non_completion_reply_on_a_v1_url_has_no_v1_hint():
    provider = OpenAICompatProvider(
        "http://127.0.0.1:1234/v1", opener=lambda url, payload: {"nope": 1})
    with pytest.raises(ProviderError) as caught:
        provider.complete(system="s", user="u")
    assert "/v1" not in str(caught.value).replace("127.0.0.1:1234/v1", "")


def test_hint_wording():
    assert missing_prefix_hint("http://127.0.0.1:1234/v1") == ""
    assert "/v1" in missing_prefix_hint("http://127.0.0.1:1234/api")
