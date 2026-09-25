"""Any OpenAI-compatible endpoint — loopback only in Phase 1 (PR-1).

Structured output uses `response_format` with a JSON Schema where the server
supports it; a server that rejects that falls back to plain JSON, and the
runner's validation-plus-one-retry covers the difference. HTTP goes through
`urllib.request` from the standard library on purpose: `requests` is only in
the environment as a transitive dependency of the model stack, and the fewer
layers between here and the socket, the easier the no-egress promise is to
audit.
"""

import json
import time
import urllib.error
import urllib.request

from ...netguard import assert_loopback
from .base import Completion, ProviderError

DEFAULT_TIMEOUT_SECONDS = 900.0


class OpenAICompatProvider:
    id = "openai_compat"
    egress = "loopback"

    def __init__(self, base_url, model="", api_key="",
                 timeout=DEFAULT_TIMEOUT_SECONDS, opener=None):
        assert_loopback(base_url)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        # Injectable for tests; the default goes to the local server.
        self._open = opener or self._http_post

    def _http_post(self, url, payload):
        assert_loopback(url)
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     **({"Authorization": "Bearer " + self.api_key}
                        if self.api_key else {})},
            method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout) as reply:
            return json.loads(reply.read().decode("utf-8"))

    def complete(self, *, system, user, json_schema=None, temperature=0.3,
                 seed=None, max_tokens=6000) -> Completion:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if seed is not None:
            payload["seed"] = seed
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": json_schema.get("title", "reply"),
                                "schema": json_schema},
            }

        url = self.base_url + "/chat/completions"
        started = time.time()
        try:
            data = self._open(url, payload)
        except urllib.error.HTTPError as error:
            if json_schema is not None and error.code in (400, 404, 422):
                # The server does not speak response_format; plain JSON plus
                # validation downstream covers it.
                payload.pop("response_format", None)
                try:
                    data = self._open(url, payload)
                except Exception as second:
                    raise ProviderError(
                        "The local model endpoint refused the request: "
                        "{0}".format(second)) from second
            else:
                raise ProviderError(
                    "The local model endpoint refused the request: "
                    "HTTP {0}".format(error.code)) from error
        except Exception as error:
            raise ProviderError(
                "Could not reach the local model endpoint at {0}: {1}. "
                "Start it first (tools/start_local_llm.ps1).".format(
                    self.base_url, error)) from error

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(
                "The endpoint's reply had no message content.") from error
        usage = data.get("usage") or {}
        return Completion(
            text=text or "",
            tokens_in=usage.get("prompt_tokens"),
            tokens_out=usage.get("completion_tokens"),
            seconds=round(time.time() - started, 2),
            model=data.get("model") or self.model,
            provider=self.id,
            raw=data,
        )
