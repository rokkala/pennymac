"""Pluggable LLM access used by mapping re-ranking, rule authoring (English -> DSL) and
exception correction proposals.

LBP_AI_PROVIDER = heuristic (default, no model calls) | bedrock | anthropic

Every caller has a deterministic fallback, so a model outage degrades quality, never
availability. PII is never sent: callers pass profiles, rule text and masked context only.
"""
from __future__ import annotations

import json
import logging
import os
import re

from .config import get_settings

log = logging.getLogger(__name__)


class LLMClient:
    name = "heuristic"

    def complete_json(self, system: str, user: str, max_tokens: int = 2000) -> dict | list | None:
        return None

    @staticmethod
    def _extract_json(text: str):
        m = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
        body = m.group(1) if m else text
        start = min([i for i in (body.find("{"), body.find("[")) if i >= 0], default=-1)
        if start < 0:
            return None
        try:
            return json.loads(body[start:])
        except json.JSONDecodeError:
            end = max(body.rfind("}"), body.rfind("]"))
            try:
                return json.loads(body[start:end + 1])
            except json.JSONDecodeError:
                return None


class BedrockClient(LLMClient):
    name = "bedrock"

    def __init__(self):
        import boto3

        s = get_settings()
        self.model_id = s.bedrock_model_id
        self.client = boto3.client("bedrock-runtime", region_name=s.aws_region)

    def complete_json(self, system, user, max_tokens=2000):
        try:
            resp = self.client.converse(
                modelId=self.model_id,
                system=[{"text": system}],
                messages=[{"role": "user", "content": [{"text": user}]}],
                inferenceConfig={"maxTokens": max_tokens, "temperature": 0},
            )
            text = "".join(b.get("text", "") for b in resp["output"]["message"]["content"])
            return self._extract_json(text)
        except Exception as e:  # noqa: BLE001 - fall back on any provider error
            log.warning("bedrock call failed: %s", e)
            return None


class AnthropicClient(LLMClient):
    name = "anthropic"

    def __init__(self):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = get_settings().anthropic_model

    def complete_json(self, system, user, max_tokens=2000):
        if not self.api_key:
            return None
        import httpx

        try:
            r = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": self.model, "max_tokens": max_tokens, "temperature": 0, "system": system,
                      "messages": [{"role": "user", "content": user}]},
                timeout=60,
            )
            r.raise_for_status()
            text = "".join(b.get("text", "") for b in r.json().get("content", []))
            return self._extract_json(text)
        except Exception as e:  # noqa: BLE001
            log.warning("anthropic call failed: %s", e)
            return None


_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _client
    if _client is None:
        p = get_settings().ai_provider
        try:
            _client = BedrockClient() if p == "bedrock" else AnthropicClient() if p == "anthropic" else LLMClient()
        except Exception as e:  # noqa: BLE001
            log.warning("AI provider %s unavailable (%s); using heuristic", p, e)
            _client = LLMClient()
    return _client


class LLMMappingReranker:
    """Asks the model to choose among the heuristic top-K for each column."""

    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.name = llm.name

    def rerank(self, scored, profile):
        if self.llm.name == "heuristic":
            return None
        payload = [
            {"source": c["name"], "type": c.get("inferred_type"), "pattern": (c.get("top_patterns") or [[None]])[0][0],
             "pii": c.get("pii_type"), "candidates": [t.name for _, t in cands]}
            for c, cands in scored
        ]
        system = ("You map mortgage loan tape columns to a servicing system schema. For each source column pick the best "
                  "candidate or null. Respond with JSON: [{\"source\":..., \"target\":..., \"confidence\":0-1, \"reason\":...}]")
        result = self.llm.complete_json(system, json.dumps(payload))
        if not isinstance(result, list):
            return None
        picks = {r.get("source"): r for r in result if isinstance(r, dict)}
        out = []
        for c, cands in scored:
            pick = picks.get(c["name"])
            if pick and pick.get("target"):
                new = []
                for (score, sig), t in cands:
                    if t.name == pick["target"]:
                        llm_conf = float(pick.get("confidence", 0.8))
                        score = round(min(0.99, 0.5 * score + 0.5 * llm_conf + 0.05), 3)
                        sig = {**sig, "llm": pick.get("reason", "")[:160]}
                    new.append(((score, sig), t))
                cands = sorted(new, key=lambda x: -x[0][0])
            out.append((c, cands))
        return out
