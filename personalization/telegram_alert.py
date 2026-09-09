from __future__ import annotations

import argparse
import html
import os
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd


def telegram_api(token: str, method: str, payload: dict[str, str]) -> dict:
    body = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        import json
        return json.load(response)


def format_job(row: pd.Series, index: int) -> str:
    title = html.escape(str(row.get("title") or "Untitled"))
    company = html.escape(str(row.get("company_name") or row.get("company") or "Unknown"))
    location = html.escape(str(row.get("location") or row.get("city") or "Location not listed"))
    site = html.escape(str(row.get("site") or "Job board"))
    score = float(row.get("match_score") or 0)
    url = html.escape(str(row.get("job_url") or ""), quote=True)
    skills = row.get("matched_skills") or ""
    if isinstance(skills, str):
        skill_text = skills.replace("[", "").replace("]", "").replace("'", "")
    else:
        skill_text = str(skills)
    reason = html.escape(str(row.get("match_reason") or "")[:220])
    lines = [
        f"<b>{index}. {title}</b>",
        f"{company} · {location} · {site}",
        f"<b>Match: {score:.0f}/100</b>",
    ]
    if skill_text:
        lines.append(f"Skills: {html.escape(skill_text[:180])}")
    if reason:
        lines.append(html.escape(reason))
    if url:
        lines.append(f'<a href="{url}">Open job posting</a>')
    return "\n".join(lines)


def load_seen(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Send top personalized JobSpy jobs to Telegram")
    parser.add_argument("csv", default="out/ranked_jobs.csv", nargs="?")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--seen-file", default="out/telegram_seen.txt")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not args.dry_run and (not token or not chat_id):
        raise SystemExit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")

    df = pd.read_csv(args.csv)
    if df.empty:
        print("No ranked jobs to alert")
        return 0

    seen_path = Path(args.seen_file)
    seen = load_seen(seen_path)
    id_col = "job_url" if "job_url" in df.columns else None
    if id_col is None:
        df["_alert_id"] = df.apply(lambda r: f"{r.get('site','')}|{r.get('title','')}|{r.get('company_name',r.get('company',''))}|{r.get('location','')}", axis=1)
        id_col = "_alert_id"

    fresh = df[~df[id_col].fillna("").astype(str).isin(seen)].copy()
    fresh = fresh.sort_values("match_score", ascending=False).head(args.top)
    if fresh.empty:
        print("No new personalized jobs above the configured threshold")
        return 0

    blocks = [format_job(row, i) for i, (_, row) in enumerate(fresh.iterrows(), 1)]
    message = "<b>🎯 Personalized JobSpy Alerts</b>\n\n" + "\n\n".join(blocks)
    message = message[:4000]

    if args.dry_run:
        print(message)
    else:
        telegram_api(token, "sendMessage", {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        })
        print(f"Telegram alert sent for {len(fresh)} jobs")

    seen_path.parent.mkdir(parents=True, exist_ok=True)
    with seen_path.open("a", encoding="utf-8") as handle:
        for value in fresh[id_col].fillna("").astype(str):
            if value and value not in seen:
                handle.write(value + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
