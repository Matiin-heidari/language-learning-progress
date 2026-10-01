# Sprachweg 🇩🇪

A multi-user web app for tracking language-learning hours, built around one
question: *how close am I to German C1?*

Each account tracks its own study sessions by activity (vocab, grammar,
listening, reading, speaking, writing), sees progress toward each CEFR level
and the overall goal, and stays honest with a GitHub-style activity heatmap
and streaks. A public landing page explains the app to signed-out visitors;
signed-in users can view each other's progress by username and check a
leaderboard. Built multi-language from the start — every account gets German
by default, more languages can be added from Settings.

See [PLAN.md](PLAN.md) for the original single-user design spec (research
behind the hour targets, data model, algorithms, page-by-page UI spec) — most
of it still applies per-account; the multi-user/social layer was added on top.

## Stack

Python 3.12+ · [uv](https://docs.astral.sh/uv/) · Flask 3 · SQLAlchemy 2 /
Flask-SQLAlchemy · Flask-Migrate (Alembic) · Flask-Login (accounts/sessions) ·
Flask-WTF (CSRF) · Jinja2 · [htmx](https://htmx.org) (vendored) ·
[Chart.js](https://www.chartjs.org) (vendored, weekly chart only) ·
hand-written CSS with light/dark design tokens · server-rendered SVG for the
heatmap and progress rings. No frontend build step.

## Quickstart

```bash
uv sync                                          # install dependencies
cp .env.example .env                             # then edit as needed
uv run flask --app sprachweg db upgrade          # create the database
uv run flask --app sprachweg seed                # seed the global activity types
uv run flask --app sprachweg run --debug         # http://127.0.0.1:5000
```

Then open the app and use **Sign up** — each new account is automatically
seeded a German language with CEFR levels. (`flask create-user` does the same
thing from the CLI if you'd rather script it.)

Optional: `uv run flask --app sprachweg seed-demo --username <you> --days 200`
fills in realistic random sessions for the last N days on one account, handy
for trying out the UI.

### Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | dev key | Flask session signing — set a real value in production |
| `DATABASE_URL` | `sqlite:///instance/sprachweg.sqlite` | SQLAlchemy DB URI |
| `TIMEZONE` | `Europe/Berlin` | Fallback "today" before anyone's logged in; each account then uses its own timezone (Settings) |

There's no more single app-wide password — accounts are real now (username +
password, hashed with Werkzeug's `generate_password_hash`).

## Everyday commands

```bash
uv run flask --app sprachweg run --debug     # dev server, auto-reloads templates & code
uv run pytest                                # test suite
uv run ruff check .                          # lint
uv run ruff format .                         # format
uv run flask --app sprachweg db migrate -m "message"   # after changing models.py
uv run flask --app sprachweg db upgrade                # apply migrations

uv run flask --app sprachweg create-user --username alice --password secret123
uv run flask --app sprachweg export --username alice --out backup.json
uv run flask --app sprachweg import-data --username alice backup.json
```

To run in "production" locally on Windows (no `flask run` dev server):

```bash
uv run waitress-serve --host=127.0.0.1 --port=8000 --call sprachweg:create_app
```

### Migrating from the old single-user version

If you're upgrading a database created before multi-user accounts existed,
`flask db upgrade` adds the new tables/columns but leaves the old language and
sessions unowned. Claim them into a new account in one step:

```bash
uv run flask --app sprachweg claim-data --username matin --password <new-password>
```

This creates the account and re-points every pre-existing language/session at
it (or seeds a fresh German if there was nothing to claim).

## Project layout

```
src/sprachweg/
├── __init__.py          # create_app() factory, login manager wiring
├── config.py             # env-driven config classes
├── extensions.py         # db / migrate / csrf / login_manager singletons
├── models.py              # User + SQLAlchemy models, today_local()
├── seed.py                 # global activity types + per-user German/CEFR seeding
├── cli.py                   # flask seed / create-user / seed-demo / claim-data / export / import-data
├── services/                 # pure(ish) business logic, unit-tested
│   ├── progress.py            # level fill-in-order, per-skill split, ETA, mark-complete
│   ├── streaks.py              # current/longest streak, plan adherence
│   ├── heatmap.py               # 365-day grid builder
│   ├── plans.py                  # weekly template -> daily plan items
│   ├── stats.py                    # weekly/activity aggregates
│   ├── milestones.py                # celebration detection
│   ├── leaderboard.py                # cross-user rankings (today/week/streak)
│   └── context.py                    # current-language / activity-type helpers
├── blueprints/
│   ├── main.py                        # public landing page ("/")
│   ├── auth.py                         # signup / login / logout
│   ├── profile.py                       # /u/<username> + /leaderboard
│   └── dashboard / log / plan / stats / settings.py   # the app itself, login-gated
├── templates/                          # Jinja2, htmx partials in templates/partials/
└── static/                              # css/app.css, js/app.js, vendor/{htmx,chart.js}
tests/                                    # pytest, frozen-time streak/progress/plan tests
```

## What's implemented

- **Accounts**: signup/login/logout (Flask-Login, hashed passwords), a public
  landing page for signed-out visitors, per-account settings (timezone,
  week-start, streak threshold, daily goal, theme, display name, a
  public/private toggle).
- **Social**: `/u/<username>` shows another signed-in user's heatmap, streak
  and per-language progress (read-only, respects their public/private
  toggle); `/leaderboard` ranks accounts by today's minutes, this week's
  minutes, or current streak.
- Logging sessions (quick-log modal + full page form), edit/delete, CSV export.
- Weekly plan builder with a "suggest a plan" generator based on the current
  level's recommended skill mix, plus a "universal daily plan" mode (build
  one day's activities, apply them to every weekday you pick at once); daily
  checklist (done/partial/skipped) that creates/updates/removes a linked
  session automatically. Past plans can be archived, reactivated or deleted
  (deleting a plan keeps the logged sessions, just unlinks them).
- "I passed A1 ✓" on the current level's card logs catch-up sessions for the
  remaining hours (split across that level's skill mix) instead of requiring
  you to know the exact hours studied — the catch-up entries are ordinary,
  editable/deletable sessions, and are excluded from pace-style stats (see
  below) so they don't skew the numbers.
- Dashboard: segmented progress bar to the goal level, per-level cards with
  progress rings and per-skill mini-bars, streak/adherence stat tiles,
  today's plan, activity heatmap, recent sessions (editable/deletable).
- Streaks (current, longest, at-risk state, plan adherence) and a projected
  ETA to the next level and to the goal, based on 28-day pace. Backfilled
  "mark complete" minutes count as a streak-active day but are excluded from
  the weekly chart, activity split, this-week tile, pace/ETA and
  best-day/average stats, so one lump entry doesn't dwarf every real day.
- Stats page: stacked weekly-hours chart (Chart.js, with a table-view
  toggle), all-time activity split, a "what if I study X min/day" slider,
  milestones timeline, heatmap.
- Settings: account (display name, timezone, week-start, streak-threshold,
  daily-goal, theme, public-profile toggle, password change), per-level hour
  targets (editable, with an "exam passed" marker), activity types (global
  defaults + your own custom ones), languages, JSON/CSV export + JSON import
  (scoped to your own account).
- Light/dark theme (auto + manual toggle), responsive layout (sidebar on
  desktop, bottom tab bar + FAB on phone), toasts + confetti on milestones.
- 56 pytest tests covering streak edge cases (empty DB, at-risk vs broken,
  month/year/DST boundaries, backfill exclusion), level-fill/overflow/
  per-skill-split math, plan expansion rules, cross-account isolation (one
  user can't mutate another's plan), and the main routes (including CSRF
  enforcement and the signup/login flow).

## Known simplifications / good next steps

- After logging a session via the modal, the page does a soft
  `location.reload()` rather than an htmx out-of-band swap of just the hero
  bar/streak tiles/heatmap — simpler for v1, a bit less snappy.
- The "suggest a plan" minute rounding is naive (nearest 5/15 min per
  activity per day); fine for a first pass.
- The streak leaderboard recomputes `compute_streaks` per public user rather
  than a single SQL query — fine at personal/small-group scale, would need
  revisiting for many accounts.
- No automated browser/E2E tests (the suite is model/service/route-level);
  the UI was checked manually and with one-off Playwright scripts during
  development, not committed to the repo.
- No email verification or password-reset flow (there's no email sending
  configured yet) — if you forget a password, reset it with a DB script or a
  future `flask` CLI command.
- PWA/offline support, a timer/stopwatch mode, and a resource library are
  listed as post-v1 ideas in `PLAN.md` §12 but not built yet.
