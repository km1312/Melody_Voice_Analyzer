"""The manual provider: the human is the transport.

It cannot complete anything itself — the prompts are already on disk in the
prompt pack, and the reply arrives through the Import box or
`python -m revolv.interpret import`. Existing as a provider keeps the
settings model honest (`provider: manual` is the default) and gives the
runner one uniform refusal instead of a special case.
"""

from .base import Completion, ProviderError


class ManualProvider:
    id = "manual"
    egress = "none"

    def complete(self, *, system, user, json_schema=None, temperature=0.3,
                 seed=None, max_tokens=6000) -> Completion:
        raise ProviderError(
            "The manual provider sends nothing anywhere. Paste the prompts "
            "from the .prompt folder into your model and import its reply "
            "(the Import box, or `python -m revolv.interpret import`).")
