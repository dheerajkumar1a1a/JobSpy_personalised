from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd
import yaml

from jobspy import scrape_jobs
from personalization.rank_jobs import rank_dataframe
from personalization.telegram_alert import main as send_telegram


ROOT = Path(__file__).resolve().parents[1]


def load_profile(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def run_search(profile: dict) -> pd.DataFrame:
    jobspy = profile.get("jobspy", {}) or {}
    sites = list(jobspy.get("sites") or [
        "linkedin", "naukri", "indeed", "glassdoor",
        "google", "zip_recruiter", "bayt", "bdjobs",
    ])
    terms = list(jobspy.get("search_terms") or ["data scientist"])
    locations = list((profile.get("locations") or {}).get("preferred") or ["India"])
    results_wanted = int(jobspy.get("results_wanted", 12))
    hours_old = int(jobspy.get("hours_old", 168))
    country_indeed = str(jobspy.get("country_indeed", "India"))
    distance = int((profile.get("locations") or {}).get("radius_miles", 50))
    remote_ok = bool((profile.get("work_preferences") or {}).get("remote_ok", True))
    proxies_env = os.environ.get("JOBSPY_PROXIES", "").strip()
    proxies = [x.strip() for x in proxies_env.split(",") if x.strip()] or None

    frames: list[pd.DataFrame] = []
    for term in terms:
        for location in locations:
            kwargs = {
                "site_name": sites,
                "search_term": term,
                "location": location,
                "results_wanted": results_wanted,
                "hours_old": hours_old,
                "country_indeed": country_indeed,
                "distance": distance,
                "is_remote": remote_ok,
                "job_type": "fulltime",
                "linkedin_fetch_description": True,
                "verbose": 0,
            }
            if proxies:
                kwargs["proxies"] = proxies
            if "google" in sites:
                kwargs["google_search_term"] = f"{term} jobs near {location}"
            try:
                frame = scrape_jobs(**kwargs)
            except Exception as exc:
                print(f"WARN: JobSpy failed for {term!r} / {location!r}: {type(exc).__name__}: {exc}")
                continue
            if frame is not None and not frame.empty:
                frames.append(frame)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    url_col = df.get("job_url")
    if url_col is not None:
        df = df.drop_duplicates(subset=["job_url"], keep="first")
    else:
        df = df.drop_duplicates(subset=[c for c in ("site", "title", "company_name", "location") if c in df.columns])
    return df.reset_index(drop=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run personalized JobSpy search and Telegram alerts")
    parser.add_argument("--profile", default="personalization/profile.yaml")
    parser.add_argument("--raw-output", default="out/jobs_raw.csv")
    parser.add_argument("--ranked-output", default="out/ranked_jobs.csv")
    parser.add_argument("--alert", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    profile = load_profile(args.profile)
    raw = run_search(profile)
    Path(args.raw_output).parent.mkdir(parents=True, exist_ok=True)
    raw.to_csv(args.raw_output, index=False)
    print(f"Fetched {len(raw)} unique raw postings")

    if raw.empty:
        return 0

    ranked = rank_dataframe(raw, profile)
    ranked.to_csv(args.ranked_output, index=False)
    print(f"Retained {len(ranked)} relevant postings")

    if args.alert or args.dry_run:
        os.environ.setdefault("PYTHONPATH", str(ROOT))
        telegram_args = ["personalization/telegram_alert.py", args.ranked_output]
        if args.dry_run:
            telegram_args.append("--dry-run")
        import sys
        old_argv = sys.argv
        try:
            sys.argv = telegram_args
            return send_telegram()
        finally:
            sys.argv = old_argv
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
