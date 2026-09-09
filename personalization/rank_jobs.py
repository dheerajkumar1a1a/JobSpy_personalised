from __future__ import annotations

import argparse
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

WORD_RE = re.compile(r"[a-z0-9+#.]+", re.I)


def norm(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip().lower()


def contains(text: str, term: str) -> bool:
    text = norm(text)
    term = norm(term)
    if not term:
        return False
    return term in text


def parse_date(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        ts = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.to_pydatetime()
    except Exception:
        return None


@dataclass
class RankedJob:
    score: float
    title_match: float
    skill_match: float
    domain_match: float
    location_match: float
    freshness: float
    matched_skills: list[str]
    matched_targets: list[str]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_score": round(self.score, 1),
            "title_match": round(self.title_match, 1),
            "skill_match": round(self.skill_match, 1),
            "domain_match": round(self.domain_match, 1),
            "location_match": round(self.location_match, 1),
            "freshness": round(self.freshness, 1),
            "matched_skills": self.matched_skills,
            "matched_targets": self.matched_targets,
            "match_reason": self.reason,
        }


def _all_text(row: pd.Series) -> str:
    fields = [
        row.get("title"),
        row.get("description"),
        row.get("skills"),
        row.get("job_function"),
        row.get("company_industry"),
    ]
    return " ".join(norm(v) for v in fields if norm(v))


def _location_text(row: pd.Series) -> str:
    return " ".join(norm(row.get(k)) for k in ("location", "city", "state", "country") if norm(row.get(k)))


def rank_row(row: pd.Series, profile: dict[str, Any], now: datetime | None = None) -> RankedJob:
    now = now or datetime.now(timezone.utc)
    title = norm(row.get("title"))
    text = _all_text(row)
    loc = _location_text(row)

    scoring = profile.get("scoring", {}) or {}
    title_weight = float(scoring.get("title_weight", 35))
    skill_weight = float(scoring.get("skill_weight", 40))
    domain_weight = float(scoring.get("domain_weight", 10))
    location_weight = float(scoring.get("location_weight", 10))
    freshness_weight = float(scoring.get("freshness_weight", 5))

    targets = profile.get("target_titles", {}) or {}
    primary_targets = [norm(x) for x in targets.get("primary", []) if norm(x)]
    secondary_targets = [norm(x) for x in targets.get("secondary", []) if norm(x)]

    exact_primary = [t for t in primary_targets if contains(title, t)]
    exact_secondary = [t for t in secondary_targets if contains(title, t)]
    if exact_primary:
        title_match = title_weight
    elif exact_secondary:
        title_match = title_weight * 0.78
    else:
        title_match = 0.0

    skills = profile.get("skills", {}) or {}
    matched_skills = [term for term in skills if contains(text, term)]
    # A posting matching roughly six high-weight skills is considered saturated;
    # this prevents a 20-skill profile from making every good posting look weak.
    matched_skill_weight = sum(float(skills[t]) for t in matched_skills)
    skill_match = skill_weight * min(1.0, matched_skill_weight / 6.0)

    matched_domains = [d for d in (profile.get("project_terms") or []) if contains(text, d)]
    domain_match = domain_weight * min(1.0, len(matched_domains) / 3.0)

    preferred_locations = [norm(x) for x in (profile.get("locations", {}) or {}).get("preferred", []) if norm(x)]
    remote_ok = bool((profile.get("work_preferences", {}) or {}).get("remote_ok", True))
    location_hit = any(contains(loc, p) for p in preferred_locations)
    remote_hit = remote_ok and any(k in loc for k in ("remote", "work from home", "wfh"))
    location_match = location_weight if (location_hit or remote_hit) else 0.0

    posted = parse_date(row.get("date_posted"))
    if posted:
        age_days = max(0.0, (now - posted).total_seconds() / 86400.0)
        freshness = freshness_weight * max(0.0, 1.0 - min(age_days / 14.0, 1.0))
    else:
        freshness = freshness_weight * 0.25

    raw_score = title_match + skill_match + domain_match + location_match + freshness

    exclusions = [norm(x) for x in profile.get("exclude_title_patterns", []) if norm(x)]
    negative_terms = [norm(x) for x in profile.get("exclude_terms", []) if norm(x)]
    title_excluded = [x for x in exclusions if contains(title, x)]
    text_excluded = [x for x in negative_terms if contains(text, x)]
    if title_excluded:
        raw_score *= 0.25
    if text_excluded:
        raw_score *= 0.35

    score = max(0.0, min(100.0, raw_score))

    matched_targets = exact_primary or exact_secondary
    parts = []
    if matched_targets:
        parts.append("target title: " + ", ".join(matched_targets[:2]))
    if matched_skills:
        parts.append("skills: " + ", ".join(matched_skills[:5]))
    if location_hit or remote_hit:
        parts.append("preferred location")
    if title_excluded:
        parts.append("title exclusion penalty")
    if text_excluded:
        parts.append("negative-term penalty")
    reason = "; ".join(parts) if parts else "limited evidence of profile fit"

    return RankedJob(
        score=score,
        title_match=title_match,
        skill_match=skill_match,
        domain_match=domain_match,
        location_match=location_match,
        freshness=freshness,
        matched_skills=matched_skills,
        matched_targets=matched_targets,
        reason=reason,
    )


def rank_dataframe(df: pd.DataFrame, profile: dict[str, Any]) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy()
    ranked = [rank_row(row, profile).to_dict() for _, row in out.iterrows()]
    rank_df = pd.DataFrame(ranked)
    for col in rank_df.columns:
        out[col] = rank_df[col]
    minimum = float((profile.get("scoring", {}) or {}).get("minimum_alert_score", 72))
    out = out[out["match_score"] >= minimum].sort_values("match_score", ascending=False).reset_index(drop=True)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Rank a JobSpy CSV against a personal profile")
    parser.add_argument("csv", help="Input CSV produced by JobSpy")
    parser.add_argument("--profile", default="personalization/profile.yaml")
    parser.add_argument("--output", default="out/ranked_jobs.csv")
    args = parser.parse_args()

    profile = yaml.safe_load(Path(args.profile).read_text(encoding="utf-8")) or {}
    df = pd.read_csv(args.csv)
    ranked = rank_dataframe(df, profile)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    ranked.to_csv(args.output, index=False)
    print(f"{len(ranked)} relevant jobs written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
