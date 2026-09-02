"""Harness Capability Router — real project Work Unit -> eligible Harness Skill.

Design rules (WorkBuddy full-delivery-controller contract):

- The candidate pool is the CURRENT-SESSION Harness snapshot only. The Router never
  discovers skills by itself and never consults local directories or mock registries.
- No fixed task name maps to a skill. Matching is description/text overlap of the
  real Work Unit with the real candidate identity+description exposed by the Harness.
- A candidate is EXCLUDED (with a machine reason) when it is: not available /
  not callable, permission denied or unknown-denied, identity incomplete (missing
  name or description), unverified, or task-mismatched (no lexical overlap).
- Among remaining candidates the Router picks the minimal-sufficient best match
  (deterministic: highest overlap count, then earlier snapshot order).
- If nothing overlaps, the Router answers NO_ELIGIBLE_HARNESS_SKILL instead of
  force-selecting. Selecting is a decision artifact, never a runtime invocation;
  invocation is a separate, real Harness step.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from harness_skill_snapshot import HarnessSnapshot, SkillCandidate

# CJK bigrams and ascii words; no skill names live here.
# Generic query-side function words are stripped so that verbs like 执行/进行 do not
# cause false "task match" against generic descriptions (standard IR stopword use).
QUERY_STOP_BIGRAMS = {
    "执行", "进行", "完成", "确认", "需要", "确保", "用于", "适用", "使用", "支持",
    "提供", "可以", "能够", "帮助", "包括", "针对", "基于", "通过", "一次", "这个",
    "然后", "接着", "并且", "以及", "已经", "还要",
}


def _tokens(text: str) -> set[str]:
    low = text.lower()
    tokens: set[str] = set()
    for word in re.findall(r"[a-z0-9]+", low):
        if len(word) >= 2:
            tokens.add(word)
    # CJK character bigrams only (single chars are too noisy for matching)
    cjk = [ch for ch in low if "\u4e00" <= ch <= "\u9fff"]
    tokens.update("".join(pair) for pair in zip(cjk, cjk[1:]))
    return tokens


@dataclass(frozen=True)
class Exclusion:
    identity: str
    reason: str


@dataclass(frozen=True)
class RouterDecision:
    work_unit: str
    eligible: tuple[SkillCandidate, ...]
    exclusions: tuple[Exclusion, ...]
    ranked: tuple[tuple[SkillCandidate, int], ...]
    decision: str  # skill identity | "NO_ELIGIBLE_HARNESS_SKILL"
    reason: str = ""

    def as_json(self) -> dict[str, Any]:
        return {
            "work_unit": self.work_unit,
            "decision": self.decision,
            "reason": self.reason,
            "ranked": [
                {"identity": c.identity, "version": c.version,
                 "verified_callable": c.verified_callable, "overlap": score}
                for c, score in self.ranked
            ],
            "exclusions": [{"identity": e.identity, "reason": e.reason}
                           for e in self.exclusions],
        }


def _eligibility(c: SkillCandidate) -> Exclusion | None:
    if not c.available:
        return Exclusion(c.identity, "not_available_in_current_session")
    if not c.identity or not c.description:
        return Exclusion(c.identity, "identity_incomplete")
    # A candidate that the session has not really loaded/verified is excluded before
    # any permission claim is considered (verifiability precedes permission).
    if not c.verified_callable:
        return Exclusion(c.identity, "not_verified_callable_in_this_session")
    if c.permission == "denied":
        return Exclusion(c.identity, "permission_denied")
    if c.permission == "unknown":
        return Exclusion(c.identity, "permission_unknown")
    return None


def route(snapshot: HarnessSnapshot, work_unit_text: str) -> RouterDecision:
    raw_wu = _tokens(work_unit_text)
    wu_tokens = raw_wu - QUERY_STOP_BIGRAMS
    eligible: list[SkillCandidate] = []
    exclusions: list[Exclusion] = []
    for candidate in snapshot.skills:
        block = _eligibility(candidate)
        if block is not None:
            exclusions.append(block)
            continue
        candidate_tokens = _tokens(f"{candidate.identity} {candidate.description}")
        if not (wu_tokens & candidate_tokens):
            exclusions.append(Exclusion(candidate.identity, "task_mismatch_no_text_overlap"))
            continue
        eligible.append(candidate)

    ranked = sorted(
        ((c, len(wu_tokens & _tokens(f"{c.identity} {c.description}"))) for c in eligible),
        key=lambda pair: (-pair[1], pair[0].identity),
    )
    if not ranked:
        return RouterDecision(
            work_unit=work_unit_text,
            eligible=(),
            exclusions=tuple(exclusions),
            ranked=(),
            decision="NO_ELIGIBLE_HARNESS_SKILL",
            reason="no current-session Harness skill textually matches this Work Unit",
        )
    winner, score = ranked[0]
    return RouterDecision(
        work_unit=work_unit_text,
        eligible=tuple(eligible),
        exclusions=tuple(exclusions),
        ranked=tuple(ranked),
        decision=winner.identity,
        reason=f"best text overlap={score} among {len(eligible)} eligible candidate(s); "
               f"minimal-sufficient selection (deterministic)",
    )
