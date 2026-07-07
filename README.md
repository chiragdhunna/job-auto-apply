# job-auto-apply

A **local-first job discovery & recommendation engine**. It finds openings across
the web, scores every one against *your* resume with an LLM, ranks the best
matches first, and hands you a JD-tailored resume PDF on one click — **you** do
the actual applying, it does everything else and tracks what you've applied to.

Everything runs on your own machine. Your data never leaves it.

```
  ATS APIs (Greenhouse/Lever/Ashby)──┐
  Web boards (Remotive, RemoteOK,    │    ┌─────────┐   ┌──────────────┐
  Arbeitnow, The Muse, Adzuna) ──────┼───▶│  Jobs   │──▶│ LLM Scoring  │
  LinkedIn / Indeed (browser,        │    │ (SQLite)│   │ (fit 0-100)  │
  discovery only) ───────────────────┘    └─────────┘   └──────┬───────┘
                                                               ▼
   ┌───────────────────────────  ⭐ Recommended (dashboard)  ──────────────┐
   │  best-fit jobs first · link to the posting · one-click tailored      │
   │  resume PDF · “Mark applied” tracking · you click Apply yourself     │
   └──────────────────────────────────────────────────────────────────────┘
```

---

## Table of contents

- [Features](#features)
- [Tech stack](#tech-stack)
- [Quick start](#quick-start)
- [LLM setup: Gemini vs Ollama](#llm-setup-gemini-vs-ollama)
- [Configuration](#configuration)
- [Your resume prompt & data](#your-resume-prompt--data)
- [Running it](#running-it)
- [The dashboard](#the-dashboard)
- [How the pipeline works](#how-the-pipeline-works)
- [Data model](#data-model)
- [Responsible use & anti-detection](#responsible-use--anti-detection)
- [Troubleshooting](#troubleshooting)
- [Project structure](#project-structure)

---

## Features

- **Web-wide discovery** — Greenhouse/Lever/Ashby public APIs, plus Remotive,
  RemoteOK, Arbeitnow (with a visa-sponsorship flag), The Muse, and optional
  Adzuna (strong UK/India coverage). LinkedIn/Indeed discovery via your own
  logged-in browser session — discovery only, nothing is submitted.
- **LLM fit scoring** — every role scored 0–100 against your resume with
  reasoning, matched skills, and gaps. High scorers become ⭐ **Recommended**.
- **Recommended-first dashboard** — best-fit jobs at the top, direct link to
  every posting, filter by score/source/status, search titles and companies.
- **One-click tailored resume** — generates LaTeX tailored to the JD and hands
  you the compiled PDF (with validate/repair passes and a guaranteed fallback
  to your base resume). Bring your own tailoring prompt.
- **Applied tracking** — tick "Mark applied" when you've submitted; the Applied
  page keeps your history. Undo supported.
- **Grounded application answers** — generate answers to common questions from
  your real resume data, ready to paste into forms.
- **Provider-agnostic LLM** — Google Gemini primary with automatic fallback to a
  local **Ollama** model; run 100% offline if you prefer.
- **Scheduled** — an in-process APScheduler loop discovers + scores on your
  interval, so the Recommended list is always fresh.

## Tech stack

Python 3.11+ · FastAPI · SQLAlchemy + SQLite · Playwright · Streamlit ·
APScheduler · Google Gemini / Ollama · LaTeX (tectonic or pdflatex).

---

## Quick start

```bash
# 1. Clone + enter
git clone https://github.com/chiragdhunna/job-auto-apply.git
cd job-auto-apply

# 2. Create a virtualenv and install deps
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. (Optional) Playwright browser — only needed for LinkedIn/Indeed discovery
python -m playwright install chromium

# 4. Configure
cp .env.example .env         # then edit .env
#   - set GEMINI_API_KEY, OR leave blank to use local Ollama (see below)
#   - fill LinkedIn/Indeed creds only if you'll use those platforms
$EDITOR config/keywords.yaml           # target roles, locations, companies
$EDITOR config/base_resume_data.json   # your structured resume

# 5. (For PDF resumes) install a LaTeX engine — tectonic is the easiest:
#   macOS:  brew install tectonic
#   Linux:  see https://tectonic-typesetting.github.io/  (single binary)

# 6. Run everything (backend + scheduler + dashboard)
./run.sh
```

Then open the dashboard at **http://localhost:8501** and the API docs at
**http://localhost:8000/docs**.

> First time using LinkedIn/Indeed automation? Log in once manually so the session
> persists — see [Running it](#running-it).

---

## LLM setup: Gemini vs Ollama

Every LLM call (scoring, resume tailoring, answers) goes through one client
(`backend/llm/client.py`) that picks a provider based on `LLM_PROVIDER`:

| `LLM_PROVIDER` | Behaviour |
|----------------|-----------|
| `auto` (default) | Use **Gemini** if `GEMINI_API_KEY` is set; otherwise **Ollama**. If a Gemini call fails (rate limit / network / bad key), automatically fall back to Ollama and log it. |
| `gemini` | Force Gemini (errors if no key; no fallback). |
| `ollama` | Force local Ollama. |

**Gemini (recommended for quality/speed):** get a free key at
<https://aistudio.google.com/app/apikey> and set `GEMINI_API_KEY` in `.env`.

**Ollama (fully local, no key):** install from <https://ollama.com>, then pull a
model **before the first run**:

```bash
ollama pull llama3.1:8b     # good default for a laptop without a big GPU
```

Leave `GEMINI_API_KEY` blank and everything routes through Ollama automatically.

Model choice by hardware (set `OLLAMA_MODEL` in `.env`):

| Your GPU/VRAM | Suggested model | Notes |
|---------------|-----------------|-------|
| No/low VRAM (laptop) | `llama3.1:8b` | Balanced quality/speed. Default. |
| 12 GB+ VRAM | `qwen2.5:14b` or `mistral-nemo` | Stronger at strict-JSON tasks like scoring. |

Local models are slower per call and slightly less reliable at strict JSON than
Gemini, so scoring/tailoring take longer and may occasionally retry — the
`format: "json"` constraint in `ollama_provider.py` handles most of it.

**Check it's working:** the dashboard **Settings** page (and `GET /settings/llm-status`)
shows the active provider and whether Ollama is reachable. You can also hit
`GET /debug/llm-check`, which sends a trivial prompt through the active provider.

---

## Configuration

### `.env` (secrets & providers)

| Variable | Purpose |
|----------|---------|
| `GEMINI_API_KEY` | Gemini key; blank = use Ollama. |
| `LLM_PROVIDER` | `auto` / `gemini` / `ollama`. |
| `GEMINI_MODEL` | Default `gemini-2.0-flash`. |
| `OLLAMA_HOST` / `OLLAMA_MODEL` | Local Ollama endpoint + model. |
| `LINKEDIN_EMAIL` / `LINKEDIN_PASSWORD` | Only for reference; login is manual. |
| `INDEED_EMAIL` / `INDEED_PASSWORD` | Only for reference; login is manual. |
| `INDEED_DOMAIN` | e.g. `https://uk.indeed.com` for your region. |
| `DB_PATH` | SQLite path (default `./data/jobs.db`). |
| `BROWSER_PROFILE_DIR` | Persistent Chrome profile (holds your session — **never commit**). |
| `MAX_APPLICATIONS_PER_RUN` | Cap per platform per run (default 10). |
| `AUTOMATION_DRY_RUN` | `true` = fill forms but never click final submit. |

### `config/keywords.yaml` (job search)

Target roles, locations, excluded companies, salary floor, score threshold,
platform toggles, run interval, and the **ATS company slugs** to pull from:

```yaml
ats_companies:
  greenhouse: ["stripe", "gitlab", "databricks"]   # the {company} in the API URL
  lever: ["leverdemo", "plaid"]
  ashby: ["ramp", "notion", "openai"]
  workday: []                                        # advanced, see below
```

`score_threshold`, the platform toggles, and `run_interval_minutes` can be edited
live from the dashboard Settings page (stored in the `settings` table, which
overrides the YAML defaults). Roles/locations/companies live in the YAML.

> **Workday** has no single public API — each employer exposes a tenant-specific
> CxS endpoint. To scrape one, add objects under `ats_companies.workday`:
> ```yaml
> workday:
>   - name: "Some Company"
>     cxs_url: "https://company.wd1.myworkdayjobs.com/wday/cxs/company/External/jobs"
>     site_url: "https://company.wd1.myworkdayjobs.com/en-US/External"
> ```

---

## Your resume prompt & data

- **`config/base_resume_data.json`** — your structured resume (skills, experience,
  education, links, preferences). Used by the scorer, resume tailor, and answer
  generator. Replace the placeholder values with your real data.
- **`backend/resume_tailor/prompts.py`** — paste your own battle-tested LaTeX
  resume-tailoring prompt at the clearly marked
  `# PASTE OWNER'S LATEX PROMPT HERE`. Keep the `{job_description}` and
  `{base_resume_data}` placeholders (substituted verbatim, so your LaTeX braces
  are safe). A sensible default prompt is used until you paste yours.

---

## Running it

**Everything at once:**

```bash
./run.sh        # backend + scheduler + dashboard, Ctrl-C stops all
```

**Individually** (handy while developing):

```bash
uvicorn backend.main:app --reload --port 8000     # API
python -m scheduler.runner                        # scheduler loop
python -m scheduler.runner --once                 # one pipeline cycle then exit
streamlit run dashboard/app.py                     # dashboard
```

**First-time browser login (LinkedIn / Indeed).** We never automate the login form
(that's the biggest "new device" flag). Log in once into the persistent profile:

```bash
python -m automation.linkedin_apply --login
python -m automation.indeed_apply --login
```

A browser opens; sign in, then press Enter in the terminal to save the session.
Future runs reuse it.

**Windows (Git Bash / MINGW64) notes:**

- `./run.sh` works as-is — it auto-detects the Windows venv layout
  (`.venv/Scripts/activate`).
- For the `--login` commands: Git Bash's mintty terminal often doesn't give
  Python an interactive stdin, so "press Enter" may not register. Either run
  them with winpty (`winpty python -m automation.linkedin_apply --login`) or
  just **close the browser window when you're done logging in** — the session
  is saved either way.
- LaTeX: install [MiKTeX](https://miktex.org). Compile your base resume once
  manually (`pdflatex config/base_resume.tex`) so MiKTeX installs any missing
  packages up front instead of stalling a scheduled run.

**Docker (API + dashboard only):**

```bash
docker compose up --build        # backend :8000, dashboard :8501
```

Browser automation and the scheduler run on the host (they need a real,
non-headless browser + your session), so keep the LinkedIn/Indeed toggles off for
container runs.

---

## The dashboard

- **Home** — pipeline stats, active LLM provider, one-click *Discover* / *Score*.
- **⭐ Recommended** — the main page: best-fit jobs first with score, reasoning,
  matched skills & gaps; link to the posting; **Tailored resume** (LLM) and
  **Quick resume** (instant base PDF) with download; **Mark applied** / Undo /
  Skip.
- **Applied** — everything you've marked as applied, filterable by platform,
  status, and date.
- **Settings** — score threshold, discovery-source toggles, run interval; live
  LLM/Ollama status.
- **Resume Versions** — view (LaTeX) and download every generated resume per job.

The dashboard talks to the backend over HTTP, so it controls exactly the same API
the scheduler uses.

---

## How the pipeline works

Each scheduler cycle (every `run_interval_minutes`) runs, respecting your
source toggles:

1. **Scrape** the enabled ATS boards (Greenhouse/Lever/Ashby) → new `jobs`.
2. **Scrape web boards** — Remotive, RemoteOK, Arbeitnow, The Muse (+ Adzuna
   with keys). All deduped against what's already known.
3. **Discover on LinkedIn / Indeed** (if toggled and logged in) — browser
   search + read, store only. Nothing is submitted.
4. **Score** every `new` job with the LLM → `fit_score`, reasoning, matched
   skills, gaps. Jobs at/above your threshold are flagged ⭐ **Recommended**.

Then it's your turn, on the **⭐ Recommended** page: open the posting, click
**Tailored resume** (LLM, tailored to that JD) or **Quick resume** (instant,
your base resume), apply on the company's site, and hit **Mark applied**.

Every cycle logs a summary (found / new / scored / recommended) to the console
and `logs/scheduler.log`.

Job statuses: `new → scored → (⭐ recommended)` then `applied` (marked by you)
or `skipped`.

---

## Data model

SQLite (via SQLAlchemy):

- **jobs** — `source, external_id, title, company, location, url, description_raw,
  salary_range, discovered_at, fit_score, score_details_json, status`.
- **applications** — `job_id, resume_version_id, submitted_at, status,
  platform_response_notes, custom_answers_json`.
- **resume_versions** — `job_id, tex_content, pdf_path, generated_at`.
- **settings** — `key, value` (JSON) for runtime overrides (threshold, toggles,
  interval).

---

## Responsible use

This tool researches **your** job search on **your** accounts:

- The primary discovery paths (ATS + web board public APIs) are ordinary API
  reads — the lowest-risk way to gather postings.
- LinkedIn/Indeed **discovery** uses your own logged-in browser session with
  human-like pacing. It only reads postings; still, automating those sites can
  conflict with their Terms — keep the toggles off if that concerns you.
- **Never commit secrets.** `.env`, `data/`, `logs/`, and the browser profile are
  git-ignored — the profile holds your live session cookies.

### Legacy auto-apply modules

The original auto-submission code (`automation/ats_apply.py`, plus the Easy
Apply / Indeed Apply flows) still lives in the repo but is **no longer wired
into the scheduler** — the pipeline never submits anything. If you ever want to
experiment with it manually, the stealth measures (persistent non-headless
profile, randomised delays, per-run caps, `AUTOMATION_DRY_RUN`) all still apply,
as do the ToS risks.

---

## Troubleshooting

- **"Ollama not reachable"** — start it (`ollama serve`) and `ollama pull` a model,
  or set `GEMINI_API_KEY`. Check the Settings page status.
- **"Ollama timed out after Ns" during resume generation** — writing a full LaTeX
  resume is a long generation and can take several minutes on CPU-only machines
  (scoring is much shorter, so it may work while resume generation times out).
  Raise `OLLAMA_TIMEOUT` in `.env` (default 600s), use a faster model, or set
  `GEMINI_API_KEY` — Gemini generates a resume in seconds. When the LLM is down
  or timing out, the application batch stops early and the remaining jobs stay
  `queued` so they're retried automatically next cycle.
- **Generated LaTeX is garbage / "Missing \begin{document}"** — two usual causes:
  1. *Ollama context truncation*: the tailoring prompt (instructions + base
     resume + JD) is ~5-6k tokens, larger than Ollama's default ~4k window, and
     Ollama silently drops the start of over-long prompts. `OLLAMA_NUM_CTX`
     (default 16384) fixes this.
  2. *Small-model reliability*: local 8B models sometimes emit broken documents
     anyway. The engine now validates structure, runs up to
     `RESUME_REPAIR_ATTEMPTS` LLM repair passes, and finally compiles the
     untailored `config/base_resume.tex` as a fallback so a valid PDF is always
     attached. Gemini rarely needs any of this.
- **"pdflatex timed out" (even on your own base resume)** — almost always
  MiKTeX blocking on its "install missing package?" GUI dialog, which a
  background process can't answer. The compiler is now invoked with
  `--enable-installer` on MiKTeX so packages install automatically, and
  `LATEX_COMPILE_TIMEOUT` (default 300s) allows for the downloads. Best
  practice: compile once manually (`pdflatex config/base_resume.tex`) or set
  "Always install missing packages" in the MiKTeX Console, so all packages are
  present before scheduled runs.
- **Want applications flowing NOW, without LLM resume roulette?** — set
  `RESUME_MODE=base_only` in `.env`: every application attaches your compiled
  `config/base_resume.tex` (no LLM tailoring calls at all). Scoring still runs
  normally. Switch back to `auto` when you're on Gemini or a stronger local model.
- **Resume generated but "not compiled"** — install `tectonic` or `pdflatex`. The
  `.tex` is always saved; only the PDF needs a compiler.
- **LinkedIn/Indeed "Not logged in"** — run the `--login` command for that platform
  once (see [Running it](#running-it)).
- **An apply flow stops mid-way** — the site's DOM likely changed; check
  `logs/automation.log`, update the selector lists in the relevant
  `automation/*_apply.py`. Affected jobs are marked `needs_review`.
- **Scores look off** — tune `score_threshold`, improve `base_resume_data.json`, or
  switch to a stronger model (Gemini, or a larger Ollama model).

---

## Project structure

```
backend/        FastAPI app, config, DB, LLM layer, scrapers, scoring,
                resume tailoring, answer generation, routers
automation/     Playwright stealth config + ATS/LinkedIn/Indeed appliers
dashboard/      Streamlit multi-page dashboard + API client
scheduler/      APScheduler pipeline loop
config/         keywords.yaml + base_resume_data.json
run.sh          one-command local launcher
docker-compose.yml / Dockerfile   optional API + dashboard containers
```

---

*Built incrementally, one working phase per commit. This is a personal-use tool —
use it thoughtfully.*
