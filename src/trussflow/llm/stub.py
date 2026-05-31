"""Deterministic, offline LLM stub.

The stub lets the full pipeline run without any API key or network access. It is
*not* an AI: it applies simple, deterministic heuristics so tests and demos are
reproducible. The real agents embed machine-readable marker blocks in their
prompts (``===SOURCE===`` / ``===REQUIREMENTS_JSON===``) which this provider
parses to decide what to emit.
"""

from __future__ import annotations

import json
import re

from trussflow.llm.base import LLMResponse

SOURCE_MARKER = "===SOURCE==="
REQUIREMENTS_MARKER = "===REQUIREMENTS_JSON==="
FEATURES_MARKER = "===FEATURES_FROM==="
WORKPACKAGE_MARKER = "===WORKPACKAGE_REQS==="
DERIVE_MARKER = "===DERIVE_PARENT==="

# Words that signal an existing normative/imperative statement.
_IMPERATIVE_RE = re.compile(r"\b(shall|must|will|should|require[ds]?)\b", re.IGNORECASE)
# Vague terms the analyst prompt explicitly forbids.
_VAGUE_TERMS = (
    "easy",
    "sufficient",
    "robust",
    "user-friendly",
    "as appropriate",
    "and/or",
    "etc",
    "quickly",
    "minimize",
    "maximize",
    "fast",
    "simple",
)
_HIGH_CONCERN_HINTS = ("secur", "privacy", "safety", "compliance", "user experience")


class StubProvider:
    """Heuristic provider used for offline runs and tests."""

    name = "stub"

    def complete(self, prompt: str, *, json_mode: bool = False) -> LLMResponse:
        del json_mode  # The stub always returns JSON; arg kept for protocol parity.
        if DERIVE_MARKER in prompt:
            payload = self._derive(prompt)
        elif FEATURES_MARKER in prompt:
            payload = self._features(prompt)
        elif WORKPACKAGE_MARKER in prompt:
            payload = self._work_packages(prompt)
        elif REQUIREMENTS_MARKER in prompt:
            payload = self._grade(prompt)
        elif SOURCE_MARKER in prompt:
            payload = self._extract(prompt)
        else:
            payload = {"requirements": []}
        return LLMResponse(text=json.dumps(payload), provider=self.name, raw=payload)

    # -- extraction --------------------------------------------------------
    def _extract(self, prompt: str) -> dict:
        source = prompt.split(SOURCE_MARKER, 1)[1]
        sentences = self._split_sentences(source)
        requirements: list[dict] = []
        for sentence in sentences:
            if len(sentence) < 25:
                continue
            text = self._to_shall(sentence)
            concern = (
                "High"
                if any(h in sentence.lower() for h in _HIGH_CONCERN_HINTS)
                else "Low"
            )
            requirements.append(
                {
                    "text": text,
                    "rationale": f'Derived from source statement: "{sentence.strip()}".',
                    "type": "Product",
                    "user_concern": concern,
                }
            )
        return {"requirements": requirements}

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        # Strip markdown headings/bullets, then split on sentence boundaries.
        cleaned = re.sub(r"(?m)^[#>*\-\s]+", " ", text)
        parts = re.split(r"(?<=[.!?])\s+", cleaned)
        return [p.strip() for p in parts if p.strip()]

    @staticmethod
    def _to_shall(sentence: str) -> str:
        sentence = sentence.strip().rstrip(".")
        if _IMPERATIVE_RE.search(sentence):
            normalized = _IMPERATIVE_RE.sub("shall", sentence, count=1)
            return normalized[0].upper() + normalized[1:] + "."
        return f"The system shall {sentence[0].lower() + sentence[1:]}."

    # -- grading -----------------------------------------------------------
    def _grade(self, prompt: str) -> dict:
        block = prompt.split(REQUIREMENTS_MARKER, 1)[1].strip()
        try:
            requirements = json.loads(block)
        except json.JSONDecodeError:
            return {"grades": []}

        grades = []
        for req in requirements:
            text = str(req.get("text", ""))
            lower = text.lower()
            findings = []
            score = 1.0

            has_shall = " shall " in f" {lower} "
            if not has_shall:
                score -= 0.3
                findings.append(
                    {
                        "issue": "Statement does not use the normative term SHALL.",
                        "rule": "Use SHALL for requirements.",
                        "suggested_fix": "Rephrase the statement using 'shall'.",
                        "severity": "high",
                    }
                )

            vague = [t for t in _VAGUE_TERMS if t in lower]
            if vague:
                score -= 0.2
                findings.append(
                    {
                        "issue": f"Contains vague/unverifiable term(s): {', '.join(vague)}.",
                        "rule": "Avoid vague or unverifiable terms.",
                        "suggested_fix": "Replace vague terms with measurable criteria.",
                        "severity": "medium",
                    }
                )

            # Atomicity: a single thought, no conjunction joining clauses.
            is_atomic = " and " not in lower and ";" not in text
            if not is_atomic:
                score -= 0.2
                findings.append(
                    {
                        "issue": "Statement may express more than one thought.",
                        "rule": "Write one thought per requirement.",
                        "suggested_fix": "Split compound clauses into separate requirements.",
                        "severity": "medium",
                    }
                )

            is_verifiable = has_shall and not vague
            score = max(0.0, round(score, 2))
            grades.append(
                {
                    "quality_score": score,
                    "is_atomic": is_atomic,
                    "is_verifiable": is_verifiable,
                    "findings": findings,
                }
            )
        return {"grades": grades}

    # -- feature extraction ------------------------------------------------
    def _features(self, prompt: str) -> dict:
        source = prompt.split(FEATURES_MARKER, 1)[1]
        # Derive features from Markdown H2 headings; fall back to a default set.
        headings = re.findall(r"(?m)^##\s+(.+?)\s*$", source)
        seen: set[str] = set()
        features: list[dict] = []
        for heading in headings:
            name = heading.strip()
            key = name.lower()
            if not name or key in seen:
                continue
            seen.add(key)
            features.append(
                {
                    "name": name,
                    "description": f"Capability area derived from the '{name}' section.",
                }
            )
        if not features:
            features.append(
                {
                    "name": "Core Capability",
                    "description": "Default feature grouping the project's requirements.",
                }
            )
        return {"features": features}

    # -- work package generation ------------------------------------------
    def _work_packages(self, prompt: str) -> dict:
        block = prompt.split(WORKPACKAGE_MARKER, 1)[1].strip()
        try:
            requirements = json.loads(block)
        except json.JSONDecodeError:
            return {"work_packages": []}

        work_packages = []
        for req in requirements:
            req_id = str(req.get("id", ""))
            if not req_id:
                continue
            concern = str(req.get("user_concern", "High"))
            scope = "AI_Autonomous" if concern == "Low" else "Human"
            text = str(req.get("text", "")).strip()
            work_packages.append(
                {
                    "requirement_id": req_id,
                    "summary": f"Implement {req_id}: {text}",
                    "scope": scope,
                }
            )
        return {"work_packages": work_packages}

    # -- requirement derivation -------------------------------------------
    def _derive(self, prompt: str) -> dict:
        block = prompt.split(DERIVE_MARKER, 1)[1].strip()
        try:
            spec = json.loads(block)
        except json.JSONDecodeError:
            return {"requirements": []}

        parent_text = str(spec.get("parent_text", "")).strip().rstrip(".")
        target_type = str(spec.get("target_type", "System"))
        concern = str(spec.get("user_concern", "Low"))
        # Restate the parent intent at the target decomposition level. With a
        # real LLM this expands into multiple detailed children; the stub emits
        # one clearly-derived placeholder so the plumbing is exercised offline.
        core = parent_text
        if core.lower().startswith("the system shall "):
            core = core[len("the system shall ") :]
        text = f"The {target_type.lower()} shall {core}."
        return {
            "requirements": [
                {
                    "text": text,
                    "rationale": f"{target_type}-level decomposition of parent requirement.",
                    "type": target_type,
                    "user_concern": concern,
                }
            ]
        }
