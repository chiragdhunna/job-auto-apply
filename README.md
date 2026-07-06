# job-auto-apply

A fully automated, **local-first** job application system. It discovers roles, scores
them against your resume with an LLM, generates a JD-tailored resume + application
answers, and (optionally) submits applications for you — all controllable from a
Streamlit dashboard and driven on a schedule.

Everything runs on your own machine. Your credentials, browser session, and data
never leave it.

```
                ┌──────────────┐
   ATS APIs ───▶│   Scrapers   │────┐
 LinkedIn/Indeed│ (Greenhouse, │    │
   (browser)    │ Lever, Ashby)│    ▼
                └──────────────┘  ┌─────────┐   ┌──────────────┐   ┌───────────────┐
                                  │  Jobs   │──▶│ LLM Scoring  │──▶│  Resume +     │
                                  │ (SQLite)│   │ (fit 0-100)  │   │  Answers gen  │
                                  └─────────┘   └──────────────┘   └───────┬───────┘
                                       ▲                                    │
                                       │                                    ▼
   ┌───────────┐   ┌───────────┐   ┌───┴────────┐              ┌────────────────────┐
   │ Streamlit │──▶│  FastAPI  │──▶│ APScheduler│─────────────▶│  Browser automation │
   │ dashboard │   │  backend  │   │   loop     │   auto-submit│ (Playwright, stealth)│
   └───────────┘   └───────────┘   └────────────┘              └────────────────────┘
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

- **Multi-source discovery** — Greenhouse, Lever and Ashby via their public JSON
  APIs (lowest detection risk), plus browser-driven LinkedIn and Indeed.
- **LLM fit scoring** — every role is scored 0–100 against your resume with
  reasoning, matched skills, and gaps. Only jobs above your threshold get queued.
- **JD-tailored resumes** — generates LaTeX tailored to each posting and compiles
  it to PDF (via `tectonic`/`pdflatex`). Bring your own tailoring prompt.
- **Grounded application answers** — answers common (and form-specific) questions
  using only facts from your resume data.
- **Automated submission** — fills and submits Greenhouse/Lever forms, LinkedIn
  Easy Apply, and Indeed Apply with human-like typing, randomised delays, and
  per-run caps.
- **Provider-agnostic LLM** — Google Gemini primary with automatic fallback to a
  local **Ollama** model; run 100% offline if you prefer.
- **Dashboard control** — review the queue, approve/skip jobs, edit thresholds and
  platform toggles, browse applications, and download tailored resumes.
- **Scheduled** — an in-process APScheduler loop runs the whole pipeline on your
  interval, respecting the toggles/threshold you set in the dashboard.

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

# 3. Install the Playwright browser (for LinkedIn/Indeed automation)
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

**Docker (API + dashboard only):**

```bash
docker compose up --build        # backend :8000, dashboard :8501
```

Browser automation and the scheduler run on the host (they need a real,
non-headless browser + your session), so keep the LinkedIn/Indeed toggles off for
container runs.

---

## The dashboard

- **Home** — pipeline stats, active LLM provider, and one-click *Scrape* / *Score*.
- **Live Queue** — new/scored/queued jobs with fit scores and reasoning; per-job
  **Approve / Skip / Score / Resume / Answers** actions.
- **Applied** — history of submitted/attempted applications, filterable by
  platform, status, and date.
- **Settings** — edit score threshold, platform toggles, and run interval; see the
  live LLM/Ollama status; trigger manual scrape/score.
- **Resume Versions** — generate, view (LaTeX), and download tailored resumes per job.

The dashboard talks to the backend over HTTP, so it controls exactly the same API
the scheduler uses.

---

## How the pipeline works

Each scheduler cycle (every `run_interval_minutes`) runs, respecting your toggles
and threshold:

1. **Scrape** the enabled ATS boards → new `jobs` (deduped).
2. **Score** every `new` job with the LLM → `fit_score` + reasoning; jobs ≥ the
   threshold become `queued`.
3. **Apply**:
   - **Greenhouse/Lever** — fill the public form, upload the tailored resume,
     answer questions, submit.
   - **LinkedIn / Indeed** — search (Easy-Apply/Indeed-Apply filtered), read + score
     each posting in-session, then run the multi-step apply flow for queued jobs.
   Resume tailoring + answer generation happen just before each submission.

Every cycle logs a summary (found / scored / queued / submitted / failed) to the
console and `logs/scheduler.log`; every browser action is logged to
`logs/automation.log`.

Job statuses: `new → scored → queued → applied` (or `skipped` / `failed` /
`needs_review`). Anything the automation can't complete confidently is left as
`needs_review` for you.

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

## Responsible use & anti-detection

This tool automates **your** job search on **your** accounts. Please use it
responsibly:

- **Terms of Service.** Automating LinkedIn and Indeed may violate their Terms and
  can lead to restrictions or bans on your account. You accept that risk. The ATS
  public APIs (Greenhouse/Lever/Ashby) are the safest, lowest-risk path — prefer
  them. Consider keeping LinkedIn/Indeed toggles off unless you understand the risk.
- **Start in dry-run.** Set `AUTOMATION_DRY_RUN=true` to fill forms without
  submitting, verify the results in the dashboard, then switch it off.
- **Keep caps low.** `MAX_APPLICATIONS_PER_RUN` defaults to 10; go lower while you
  build trust in the flow. Review `needs_review` items rather than blindly trusting.
- **Never commit secrets.** `.env`, `data/`, `logs/`, and the browser profile are
  git-ignored — the profile holds your live session cookies.

Built-in anti-detection measures: non-headless persistent browser context (real
profile), randomised delays between every action, character-by-character typing
with jitter, mouse movement before clicks, `navigator.webdriver` masking, and
per-run application caps. Selectors for LinkedIn/Indeed/ATS DOMs change often —
`logs/automation.log` is your friend when a flow breaks.

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
- **Fallback base resume fails to compile** — your `config/base_resume.tex` may
  use packages MiKTeX hasn't installed yet. Compile it once manually
  (`pdflatex config/base_resume.tex`) and let MiKTeX install missing packages,
  or enable "always install missing packages" in the MiKTeX Console.
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
