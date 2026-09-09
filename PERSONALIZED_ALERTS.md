# Personalized Job Alerts

This repository keeps the upstream JobSpy scraper and adds a separate personal-ranking/Telegram layer under `personalization/`.

## What it does

1. Searches JobSpy across LinkedIn, Naukri, Indeed, Glassdoor, Google, ZipRecruiter, Bayt and BDJobs.
2. Searches multiple role families that fit the current profile: data science, data analytics, ML, computer vision, AI/automation, research/analytics and Python.
3. Searches preferred Indian metros plus Remote India.
4. Deduplicates postings by `job_url`.
5. Scores each job 0–100 using weighted title, skills, domain/project evidence, location and freshness signals.
6. Applies negative penalties for senior/staff/lead/manager roles, internships and unrelated functions.
7. Sends only new jobs above the profile's alert threshold to Telegram.
8. Stores the sent-posting keys in a GitHub Actions cache so scheduled runs avoid repeatedly alerting on the same postings.

## Personal profile

`personalization/profile.yaml` is the configuration source. The current seed uses public project evidence already visible in the account context; it intentionally leaves years of experience, education and seniority out of the score rather than inventing them.

For exact resume-driven ranking, update `profile.yaml` from the real resume and keep the project evidence that is actually supported by the resume.

## Telegram setup

Create a bot with `@BotFather` using `/newbot` and send the bot at least one message from the destination chat.

Add these GitHub Actions repository secrets:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Optional:

- `JOBSPY_PROXIES` — comma-separated proxies. This is especially useful for LinkedIn because some boards rate-limit aggressively.

## Run locally

```bash
pip install -e .
python personalization/run_alerts.py
python personalization/telegram_alert.py out/ranked_jobs.csv --top 10 --dry-run
```

The dry-run prints the Telegram message without sending it.

## GitHub Actions

The workflow is `.github/workflows/personalized-job-alerts.yml` and runs daily at 06:30 IST (01:00 UTC). It can also be started manually from the Actions tab.

## Important distinction

This layer does **not** submit applications. It discovers, scores, deduplicates and alerts. Application submission should remain a separate, human-approved step.
