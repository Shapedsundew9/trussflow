"""Feature-extractor agent: vision text -> intermediate features.

Features are the capability layer that sits between the root Vision and atomic
Requirements (see ``docs/design/memgraph-schema.md``). There is no dedicated
prompt file for this agent, so the instructions are built inline and the source
text is appended behind the ``===FEATURES_FROM===`` marker the stub recognizes.
"""

from __future__ import annotations

from trussflow.agents.common import format_feature_id, parse_json, validate
from trussflow.config import get_logger
from trussflow.llm.base import LLMProvider
from trussflow.llm.stub import FEATURES_MARKER
from trussflow.models import Feature

logger = get_logger("agents.feature_extractor")

_SCHEMA = "feature_extraction"

_INSTRUCTIONS = (
    "You are a feature analyst. Read the source document and identify the "
    "intermediate capabilities (features) that group the project's "
    "requirements. Each feature is a milestone-level capability, not an atomic "
    "requirement.\n\n"
    "## Output Contract\n"
    "Return ONLY a JSON object of the form "
    '{"features": [{"name", "description"}]}.'
)


class FeatureExtractorAgent:
    """Derives the feature layer from a source document."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def build_prompt(self, source_text: str) -> str:
        return f"{_INSTRUCTIONS}\n\n{FEATURES_MARKER}\n{source_text}\n"

    def run(self, source_text: str) -> list[Feature]:
        prompt = self.build_prompt(source_text)
        response = self._provider.complete(prompt, json_mode=True)
        payload = parse_json(response.text)
        validate(payload, _SCHEMA)

        features = [
            Feature(
                id=format_feature_id(index),
                name=item["name"],
                description=item["description"],
            )
            for index, item in enumerate(payload["features"], start=1)  # type: ignore[index]
        ]
        logger.info("Feature extractor produced %d feature(s)", len(features))
        return features
