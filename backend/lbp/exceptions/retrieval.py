"""Precedent retrieval (the 'R' in RAG) over historically resolved exceptions.

Local: lexical/shape similarity over the precedents table, which is enough to surface
"we fixed 'Ca' -> 'CA' 412 times". AWS: OpenSearchPrecedentIndex stores an embedding
(Bedrock Titan) of the masked exception context and runs k-NN; same return shape.
"""
from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher

from sqlalchemy import func, select

from ..store import db


def _shape(v: str) -> str:
    return re.sub(r"\d", "9", re.sub(r"[A-Za-z]", "A", v or ""))


class SqlPrecedentIndex:
    def add(self, conn, rule_id, field, source_id, original, corrected, context, actor):
        conn.execute(db.precedents.insert().values(rule_id=rule_id, field=field, source_id=source_id,
                                                   original_value=None if original is None else str(original),
                                                   corrected_value=None if corrected is None else str(corrected),
                                                   context=context or {}, resolved_by=actor))

    def search(self, rule_id: str, field: str, original, k: int = 3) -> list[dict]:
        orig = "" if original is None else str(original)
        with db.get_engine().connect() as c:
            rows = c.execute(
                select(db.precedents.c.original_value, db.precedents.c.corrected_value, func.count().label("n"))
                .where(db.precedents.c.field == field)
                .group_by(db.precedents.c.original_value, db.precedents.c.corrected_value)
                .order_by(func.count().desc()).limit(500)
            ).all()
        scored = []
        for o, corr, n in rows:
            o = o or ""
            sim = 1.0 if o == orig else 0.6 * (_shape(o) == _shape(orig)) + 0.4 * SequenceMatcher(None, o, orig).ratio()
            scored.append({"original": o, "corrected": corr, "count": n, "similarity": round(sim, 3)})
        scored.sort(key=lambda x: (-x["similarity"], -x["count"]))
        return scored[:k]


class OpenSearchPrecedentIndex:  # pragma: no cover - requires AWS
    def __init__(self, endpoint: str, index: str = "exception-precedents"):
        from opensearchpy import OpenSearch  # type: ignore

        self.client, self.index = OpenSearch(hosts=[endpoint]), index

    def _embed(self, text: str) -> list[float]:
        import json

        import boto3

        br = boto3.client("bedrock-runtime")
        out = br.invoke_model(modelId="amazon.titan-embed-text-v2:0", body=json.dumps({"inputText": text}))
        return json.loads(out["body"].read())["embedding"]

    def add(self, conn, rule_id, field, source_id, original, corrected, context, actor):
        text = f"{rule_id} {field} {original}"
        self.client.index(self.index, body={"rule_id": rule_id, "field": field, "original": original, "corrected": corrected,
                                             "vector": self._embed(text)})

    def search(self, rule_id, field, original, k=3):
        q = {"size": k, "query": {"knn": {"vector": {"vector": self._embed(f"{rule_id} {field} {original}"), "k": k}}}}
        hits = self.client.search(index=self.index, body=q)["hits"]["hits"]
        return [{"original": h["_source"]["original"], "corrected": h["_source"]["corrected"], "count": 1,
                 "similarity": round(h["_score"], 3)} for h in hits]


def consensus(precedents: list[dict]) -> tuple[str | None, float]:
    """If exact-match precedents agree, return (value, strength)."""
    exact = [p for p in precedents if p["similarity"] == 1.0]
    if not exact:
        return None, 0.0
    c = Counter()
    for p in exact:
        c[p["corrected"]] += p["count"]
    val, n = c.most_common(1)[0]
    total = sum(c.values())
    return val, (n / total) * min(1.0, n / 3)


_index = SqlPrecedentIndex()


def get_index():
    return _index
