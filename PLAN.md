# Sprachweg — Language Learning Progress Tracker
### Implementation Plan (v1: German, A1 → C1)

> This document is a complete build spec. It is written to be handed to an implementing
> engineer/model. Everything needed — goals, hour targets, data model, routes, UI, design
> tokens, algorithms, milestones and acceptance criteria — is here. Where a decision was
> made, the reasoning is given so it isn't re-litigated.

---

## 0. TL;DR

- **What:** A personal, single-user Flask web app to plan and log language-study hours,
  visualise progress toward CEFR levels, and keep motivation high with streaks and a
  GitHub-style activity heatmap.
- **v1 scope:** German only in the UI, but the **data model is multi-language from day one**.
- **Target:** ~**1,200 total hours** from zero to C1 for a Persian speaker who knows English
  (see §2 for the derivation and per-level breakdown).
- **Stack:** Python 3.12+, `uv`, Flask, Flask-SQLAlchemy + SQLite, Flask-Migrate, Jinja2,
  HTMX (for snappy partial updates), a small amount of vanilla JS, hand-written CSS with
  design tokens, server-rendered SVG for the heatmap and progress rings. No SPA, no build step.

---

## 1. Goals & non-goals

### Goals
1. Log study sessions (date, activity type, minutes, optional note) in ≤ 3 taps/clicks.
2. Create a **weekly study plan** (e.g. "Mon: 30 min vocab + 45 min reading") and tick each
   planned item as done / partial / skipped each day.
3. Show **one main progress bar to C1** and **one progress bar per level** (A1, A2, B1, B2, C1).
4. Show a **365-day activity heatmap**.
5. Show **streak stats**: current streak, longest streak, total active days, and more (§6.4).
6. Show a **projected C1 date** based on recent pace (strong motivator).
7. Responsive (phone first: logging mostly happens on a phone), fast, beautiful, light + dark.
8. Ready for more languages later with no schema change.

### Non-goals (v1)
- Multi-user accounts / social features (a single optional password gate is enough, §9).
- Spaced-repetition flashcards (use Anki etc.; this app *tracks time*, it doesn't teach).
- Native mobile app (a PWA manifest is a stretch goal, §12).

---

## 2. How many hours does A1 → C1 take? (research + chosen targets)

### 2.1 Sources

| Source | What it says | Notes |
|---|---|---|
| **Goethe-Institut** (course guidance) | Cumulative *Unterrichtseinheiten* (UE, 45 min each): A1 60–150, A2 150–260, B1 260–490, B2 450–600, C1 600–750 | Classroom time only. 750 UE ≈ **560 clock hours** of instruction. Goethe explicitly expects additional self-study on top. |
| **US Foreign Service Institute (FSI)** | German = Category II, **~30 weeks / ~750 class hours** to "Professional Working Proficiency" (ILR 3 ≈ B2+/C1) | Intensive, small classes, plus ~2–3 h/day homework → real total is well above 750. For English speakers. |
| **Cambridge / ALTE "guided learning hours"** (for English, widely used as a CEFR rule of thumb) | A2 ~180–200, B1 ~350–400, B2 ~500–600, C1 ~700–800 (cumulative, guided) | Guided hours ≈ ½ to ⅓ of total effort for independent learners. |

### 2.2 Adjustments for this learner (Persian native, knows English)
- **English helps a lot (-):** German and English are both West Germanic. Huge shared
  vocabulary (Haus/house, Wasser/water, trinken/drink), similar modal verbs, and the
  Latin script. Most published estimates *already assume* an English speaker, so this
  puts the learner at the baseline, not below it.
- **Persian helps a little (-):** Indo-European, so concepts like grammatical person,
  verb-final clauses (Persian is SOV; German subordinate clauses are verb-final!) feel
  natural. Persian speakers often find German word order *easier* than English
  speakers do.
- **Hurdles (+):** Grammatical gender (der/die/das) and the case system (4 cases, adjective
  endings) don't exist in Persian or English and are the #1 time sink. Umlauts and
  vowel length need some pronunciation work.
- **Self-study, not classroom (+):** Solo learners need more total hours than guided
  classroom hours because nobody structures or corrects the work.

**Net:** use the total-effort (self-study + any classes) numbers a bit above the
Goethe/FSI classroom figures.

### 2.3 Chosen targets (seed data, editable in Settings)

| Level | Hours for this level | Cumulative | Typical duration at 1.5 h/day |
|---|---:|---:|---:|
| **A1** | 120 h | 120 h | ~2.7 months |
| **A2** | 160 h | 280 h | ~3.5 months |
| **B1** | 240 h | 520 h | ~5.3 months |
| **B2** | 300 h | 820 h | ~6.7 months |
| **C1** | 380 h | **1,200 h** | ~8.4 months |
| **Total** | | **1,200 h** | **~2.2 years at 1.5 h/day** (~1.6 years at 2 h/day) |

These are *targets*, not guarantees. The app must make them **editable per language**
(Settings → Levels). Show a small "ⓘ How these were estimated" link on the dashboard
that opens a short modal with §2.1 in plain language.

### 2.4 Recommended skill mix per level (seed data for plan suggestions)

Percent of each level's hours. Early levels are vocab/grammar heavy; later levels shift
to input (reading/listening) and output (speaking/writing).

| Activity | A1 | A2 | B1 | B2 | C1 |
|---|---:|---:|---:|---:|---:|
| Vocabulary | 25% | 20% | 15% | 12% | 10% |
| Grammar | 25% | 20% | 15% | 10% | 8% |
| Listening | 15% | 18% | 20% | 22% | 22% |
| Reading | 10% | 15% | 20% | 22% | 22% |
| Speaking | 15% | 15% | 15% | 17% | 18% |
| Writing | 10% | 12% | 15% | 17% | 20% |

→ e.g. A1 = 30 h vocab, 30 h grammar, 18 h listening, 12 h reading, 18 h speaking, 12 h writing.

Used for: (a) per-skill mini-bars inside each level card, (b) a "Suggest a weekly plan"
button that pre-fills the plan builder from the current level's mix and a chosen
hours/week.

---

## 3. Tech stack & project setup

### 3.1 Choices (with reasons)

| Concern | Choice | Why |
|---|---|---|
| Package/env manager | **uv** | User requirement. |
| Web framework | **Flask 3.x** (app factory + blueprints) | User preference. |
| DB | **SQLite** via **Flask-SQLAlchemy 3.x** (SQLAlchemy 2.0 style) | Single user, zero ops, easy backup (one file). |
| Migrations | **Flask-Migrate** (Alembic) | Schema will grow (more languages, features). |
| Forms / CSRF | **Flask-WTF** | CSRF protection + validation. |
| Interactivity | **HTMX** (from `cdn.jsdelivr.net` or vendored in `static/vendor/`) | Tick plan items, quick-log, update the heatmap without page reloads and without an SPA. **Vendor it** so the app works offline. |
| Charts | **Server-rendered SVG** (heatmap, progress rings, bars) + **Chart.js** (vendored) only for the weekly-hours trend chart | SVG from Jinja is fast, themeable via CSS variables, no JS needed. |
| CSS | Hand-written, `static/css/app.css`, CSS custom-property design tokens | No build step; full control; dark mode via tokens. |
| Fonts | **Inter** (UI) + **Fraunces** or **Instrument Serif** (big display numbers/headings) via Google Fonts, with system fallbacks | Friendly and polished. |
| Icons | **Lucide** SVG icons, inlined via a Jinja macro | Crisp, consistent. |
| Tests | **pytest** + `pytest-flask`-style fixtures, **freezegun** (or `time-machine`) for date logic | Streak logic *must* be tested with frozen dates. |
| Lint/format | **ruff** (lint + format) | Fast, one tool. |

### 3.2 Setup commands

```bash
uv init --app --name sprachweg --python 3.12
uv add flask flask-sqlalchemy flask-migrate flask-wtf python-dotenv
uv add --dev pytest time-machine ruff
# run
uv run flask --app sprachweg run --debug
# migrations
uv run flask --app sprachweg db init
uv run flask --app sprachweg db migrate -m "initial"
uv run flask --app sprachweg db upgrade
# seed (custom CLI command, §8)
uv run flask --app sprachweg seed
```

### 3.3 Project layout

```
language-learning-progress/
├── pyproject.toml
├── uv.lock
├── .python-version
├── .env.example              # SECRET_KEY, APP_PASSWORD (optional), DATABASE_URL, TZ
├── .gitignore                # .venv, instance/, *.sqlite, __pycache__, .env
├── README.md
├── PLAN.md                   # this file
├── migrations/
├── instance/                 # sprachweg.sqlite lives here (gitignored)
├── src/sprachweg/
│   ├── __init__.py           # create_app()
│   ├── config.py
│   ├── extensions.py         # db, migrate, csrf
│   ├── models.py
│   ├── seed.py               # CEFR levels, activity types, default targets (§2)
│   ├── cli.py                # `flask seed`, `flask export`, `flask import`
│   ├── services/
│   │   ├── progress.py       # hours→level allocation, per-skill progress, ETA
│   │   ├── streaks.py        # current/longest streak, active days
│   │   ├── heatmap.py        # 53×7 grid + intensity buckets
│   │   ├── plans.py          # expand weekly template → daily plan items
│   │   └── stats.py          # weekly totals, averages, adherence
│   ├── blueprints/
│   │   ├── dashboard.py      # /
│   │   ├── log.py            # /log, /sessions/*
│   │   ├── plan.py           # /plan, /today
│   │   ├── stats.py          # /stats
│   │   └── settings.py       # /settings, /languages
│   ├── templates/
│   │   ├── base.html
│   │   ├── macros/ (ui.html, icons.html, charts.html)
│   │   ├── dashboard.html
│   │   ├── today.html
│   │   ├── plan/ (index.html, edit.html)
│   │   ├── log/ (index.html, form.html)
│   │   ├── stats.html
│   │   ├── settings.html
│   │   └── partials/ (plan_item.html, quick_log.html, heatmap.html, streak_card.html, toast.html)
│   └── static/
│       ├── css/app.css
│       ├── js/app.js         # theme toggle, tooltips, confetti, keyboard shortcuts
│       ├── vendor/ (htmx.min.js, chart.umd.min.js)
│       └── img/ (favicon.svg, flags/de.svg)
└── tests/
    ├── conftest.py
    ├── test_streaks.py
    ├── test_progress.py
    ├── test_heatmap.py
    ├── test_plans.py
    └── test_routes.py
```

Use the `src/` layout; set `[tool.uv] package = true` / a build backend so
`uv run flask --app sprachweg` resolves the package.

---

## 4. Domain concepts

- **Language:** e.g. German (`de`). Has a flag/emoji, a color accent, and its own level targets.
- **Level:** CEFR level (A1…C2) *for a language*, with `target_hours` and an order.
  C2 is seeded but **hidden** by default (user's goal is C1; the "goal level" is a
  per-language setting).
- **Activity type:** Vocabulary, Grammar, Reading, Listening, Speaking, Writing
  (seeded, global, user can add more like "Tutor/Class", "Anki", "Podcast").
  Each has an icon and a fixed color slot (§7.3).
- **Study session (log entry):** the atomic fact. `date`, `language`, `activity`,
  `minutes`, optional `note`, optional `resource` (e.g. "Nicos Weg Ep. 12"),
  optional link to the plan item it fulfilled.
- **Plan (weekly template):** per language, a set of recurring items:
  `weekday` + `activity` + `planned_minutes` (+ optional title). Only **one active plan per
  language**; old plans are archived (keeps history honest).
- **Plan item (daily instance):** a concrete item for a date, generated from the template
  (lazily, see §6.5). Status: `pending | done | partial | skipped`.
  Marking **done** creates a linked Study session for the planned minutes (editable);
  **partial** asks for actual minutes; **skipped** creates nothing.
- **Ad-hoc sessions** (not from the plan) are always allowed and count toward everything.

---

## 5. Data model (SQLAlchemy 2.0)

All timestamps UTC; **all "study dates" stored as a plain `DATE` in the user's local
timezone** (setting `timezone`, default `Europe/Berlin` — ask user; could be `Asia/Tehran`).
Never derive the study date from a UTC timestamp — a session at 00:30 local must count for
the local day.

```text
language
  id PK
  code            str(8) unique      "de"
  name            str(64)            "German"
  native_name     str(64)            "Deutsch"
  flag_emoji      str(8)             "🇩🇪"
  accent_color    str(9)             "#…" (optional per-language accent)
  goal_level_id   FK level.id NULL   → C1
  is_active       bool default True
  created_at      datetime

level
  id PK
  language_id     FK language.id
  code            str(4)             "A1".."C2"
  name            str(64)            "Beginner"
  sort_order      int
  target_hours    numeric(6,1)       hours for THIS level (not cumulative)
  UNIQUE(language_id, code)

activity_type
  id PK
  key             str(32) unique     "vocab"
  name            str(64)            "Vocabulary"
  icon            str(32)            lucide icon name ("book-a")
  color_slot      int                1..8 (maps to CSS var --series-N)
  sort_order      int
  is_archived     bool

level_skill_target        -- §2.4 mix, optional override per level
  id PK
  level_id        FK level.id
  activity_type_id FK activity_type.id
  percent         numeric(5,2)
  UNIQUE(level_id, activity_type_id)

study_session
  id PK
  language_id     FK language.id  (indexed)
  activity_type_id FK activity_type.id
  study_date      date (indexed)
  minutes         int  CHECK(minutes > 0 AND minutes <= 960)
  note            text NULL
  resource        str(200) NULL
  plan_item_id    FK plan_item.id NULL UNIQUE  (one session per plan item)
  created_at, updated_at datetime
  INDEX(language_id, study_date)

study_plan
  id PK
  language_id     FK language.id
  name            str(100)           "Summer intensive"
  weekly_goal_minutes int NULL        (derived sum, cached; or computed)
  starts_on       date
  ends_on         date NULL
  is_active       bool               (partial unique: one active per language)
  created_at

plan_template_item
  id PK
  plan_id         FK study_plan.id
  weekday         int  0=Mon..6=Sun
  activity_type_id FK activity_type.id
  planned_minutes int
  title           str(120) NULL      "Nicos Weg episode"
  sort_order      int

plan_item
  id PK
  plan_id         FK study_plan.id
  template_item_id FK plan_template_item.id NULL  (NULL = one-off item added for a day)
  date            date
  activity_type_id FK activity_type.id
  planned_minutes int
  title           str(120) NULL
  status          enum(pending, done, partial, skipped) default pending
  UNIQUE(template_item_id, date)
  INDEX(plan_id, date)

setting                     -- simple key/value
  key   str PK   e.g. timezone, streak_min_minutes, week_start, theme, daily_goal_minutes
  value str

milestone_event            -- for celebrations & a history timeline
  id PK
  language_id FK
  kind        str   "level_hours_reached" | "streak" | "hours_total" | "exam_passed"
  ref         str   "A1" | "30" | "100"
  achieved_on date
  seen        bool  (drives one-time celebration toast/confetti)
```

**Why store per-level (not cumulative) hours:** editing one level's target doesn't
require updating the others.

**Exam marker (optional but nice):** Settings → Levels → "I passed the Goethe A2 exam on …"
creates a `milestone_event(kind="exam_passed")`, shown with a ✓ badge on the level card.
It does **not** alter hour-based progress (hours stay the honest metric).

---

## 6. Core logic (put in `services/`, pure functions, fully unit-tested)

### 6.1 Total progress
```
total_minutes(language) = SUM(study_session.minutes)
goal_minutes = SUM(level.target_hours*60 for levels up to and including goal level)
total_pct = min(100, total_minutes / goal_minutes * 100)
```

### 6.2 Level progress — "fill in order" allocation
Hours pour into levels **sequentially** like water into stacked glasses:
```
remaining = total_minutes
for level in levels ordered by sort_order (up to goal):
    cap = level.target_hours * 60
    filled = min(remaining, cap); remaining -= filled
    level_pct = filled / cap
    status = "done" if filled == cap else ("current" if filled > 0 or first-unfilled else "locked")
```
- Exactly one level is **current** (the first not-full one).
- Overflow beyond the goal is shown as "+N h beyond C1" (don't cap the total count, only the bar).
- This is simple and honest; don't try to infer level from activity content.

### 6.3 Per-skill progress within a level
For the current level, show per-activity mini-bars: minutes logged *while that level was
current* vs `level.target_hours * percent`. Implementation: walk sessions in
chronological order with the same fill algorithm, attributing each session's minutes
to the level being filled at that moment (split a session across a boundary proportionally).
Cache the result in memory per request; for a single user this is fast enough
(thousands of rows). If it becomes slow, add a `level_id` column populated on write.

### 6.4 Streaks & consistency stats
Settings: `streak_min_minutes` (default **10**). A day is **active** if the language's
(or all languages', toggle) total minutes that day ≥ threshold.

- **Current streak:** count consecutive active days ending **today**; if today is not
  yet active, end at **yesterday** (the streak is "alive, at risk" until midnight —
  show a flame with a pulsing "Study today to keep it" state).
- **Longest streak:** max run of consecutive active days over all history (+ its date range).
- **Total active days**, **active days this month / % of days**.
- **Weekly streak:** consecutive ISO weeks meeting the plan's weekly goal (gentler metric
  that survives a sick day — great for motivation).
- **Average per active day**, **average per calendar day (last 30d)**.
- **Best day** (most minutes), **best week**.
- **Plan adherence:** `done + 0.5*partial` / planned items, last 7 / 30 days.

Algorithm: one query `SELECT study_date, SUM(minutes) GROUP BY study_date`, build a set of
active dates, then a linear scan. Must handle: gaps, today-empty, future dates (reject on
input), timezone (use local "today" from settings).

**Test cases (required):** empty DB; single day today; single day yesterday; streak broken
two days ago; streak spanning month/year boundary; day below threshold breaks the
streak; multiple sessions on one day summed; longest ≠ current; DST change week.

### 6.5 Plan expansion (lazy)
When a page needs plan items for date range `[a, b]`:
1. For each date in range ≥ `plan.starts_on` (and ≤ `ends_on` if set), and **≤ today + 7**:
2. For each template item with matching weekday, `INSERT … ON CONFLICT DO NOTHING`
   (`UNIQUE(template_item_id, date)`).
- **Never** create items for dates before the plan's start date.
- Editing the template affects only **future** pending items: delete future `pending`
  items for that template item, regenerate. Past items are history — never rewritten.
- Past `pending` items render as "missed" (computed, not stored), which keeps adherence honest.

### 6.6 Projection / ETA
```
pace_min_per_day = minutes in last 28 days / 28   (fallback: all-time avg if < 28 days of history)
remaining = goal_minutes - total_minutes
eta_date = today + ceil(remaining / pace)   (hide if pace == 0)
```
Show for C1 and for the current level: "At your 4-week pace (1 h 12 m/day), you'll
reach **B1 on 14 Mar 2027** and **C1 on 9 Nov 2028**." Also a "what-if" mini slider on
the stats page: "If I study X min/day → C1 on …" (pure client-side JS, no request).

### 6.7 Heatmap
- 53 columns (weeks) × 7 rows (days), last 365 days ending today, weeks start **Monday**
  (setting). Month labels above, Mon/Wed/Fri labels left.
- Intensity buckets (minutes): `0`, `1–14`, `15–29`, `30–59`, `60–119`, `≥120` → levels 0–5.
  Also render the **daily goal** marker: cells where the day met `daily_goal_minutes`
  get no extra decoration beyond their bucket (keep it clean).
- Returns a list of weeks → days → `{date, minutes, level, is_future, is_today}`; Jinja
  macro renders SVG `<rect>`s with `rx=2`, a 3px gap, `data-date`, `data-minutes`,
  `aria-label="Mon 3 Mar 2026: 45 minutes"`.
- Year selector (`← 2025 | 2026 →`) and a "Last 12 months" default.
- Click a cell → HTMX loads that day's sessions/plan items into a side panel (drawer on mobile).

---

## 7. UI / UX design

### 7.1 Design principles
1. **Progress first.** The first thing seen is "how far am I" (C1 bar + current level) and
   "am I on track today" (streak + today's plan).
2. **Logging must be frictionless.** A floating "+ Log" button everywhere; quick-log sheet
   with activity chips, minute presets (15 / 30 / 45 / 60 / custom), date defaults to today.
3. **Celebrate, don't nag.** Micro-animations and confetti on milestones; no guilt copy.
4. **Honest numbers.** Real hours, never inflated. Missed plan items shown neutrally.
5. **Calm, warm aesthetic.** Soft neutral surfaces, one confident accent, generous spacing,
   big serif numerals for hero stats.

### 7.2 Design tokens (`app.css`)
Define on `:root`, redefine for dark under
`@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {…} }` **and**
`:root[data-theme="dark"] {…}` (theme toggle must win both ways). `body` gets an explicit
background.

```css
:root {
  color-scheme: light;
  /* surfaces */
  --bg:          #f7f6f3;
  --surface-1:   #fcfcfb;   /* cards */
  --surface-2:   #f0efec;   /* inset / track of progress bars */
  --border:      #e4e2dc;
  /* text */
  --text-primary:   #0b0b0b;
  --text-secondary: #52514e;
  --text-muted:     #8a8983;
  /* brand accent (buttons, current-level highlight, focus ring) */
  --accent:      #2a78d6;
  --accent-ink:  #ffffff;
  /* streak flame (reserved: only for streak UI) */
  --flame:       #eb6834;
  /* status (reserved: never used as series colors) */
  --good: #1f8a4c; --warning: #b77900; --critical: #d03b3b;
  /* categorical series = activity types, fixed order, never cycled */
  --series-1: #2a78d6; /* Vocabulary  – blue    */
  --series-2: #eb6834; /* Grammar     – orange  */
  --series-3: #1baf7a; /* Listening   – aqua    */
  --series-4: #eda100; /* Reading     – yellow  */
  --series-5: #e87ba4; /* Speaking    – magenta */
  --series-6: #008300; /* Writing     – green   */
  --series-7: #4a3aa7; /* custom #1   – violet  */
  --series-8: #e34948; /* custom #2   – red     */
  /* heatmap: single-hue sequential ramp (blue), 0 = empty track */
  --heat-0: var(--surface-2);
  --heat-1: #cde2fb; --heat-2: #9ec5f4; --heat-3: #5598e7;
  --heat-4: #256abf; --heat-5: #104281;
  /* shape & motion */
  --radius-sm: 6px; --radius-md: 12px; --radius-lg: 20px;
  --shadow-card: 0 1px 2px rgb(0 0 0 / .04), 0 4px 16px rgb(0 0 0 / .04);
  --ease: cubic-bezier(.2,.8,.2,1);
  --font-ui: "Inter", system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-display: "Fraunces", Georgia, serif;
}
/* dark */
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #121211; --surface-1: #1a1a19; --surface-2: #262624; --border: #33332f;
  --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #8e8d85;
  --accent: #3987e5;
  --flame: #d95926;
  --series-1:#3987e5; --series-2:#d95926; --series-3:#199e70; --series-4:#c98500;
  --series-5:#d55181; --series-6:#008300; --series-7:#9085e9; --series-8:#e66767;
  --heat-1:#104281; --heat-2:#1c5cab; --heat-3:#2a78d6; --heat-4:#5598e7; --heat-5:#9ec5f4;
}
/* + identical block inside the prefers-color-scheme media query */
```
Notes for the implementer:
- The categorical order above is a pre-validated CVD-safe order (adjacent pairs); keep
  the order. Activity colors follow the **activity**, never its rank.
- In dark mode the heatmap ramp **inverts** (bright = more), so high activity still "pops".
- Text is never colored with a series color — labels use text tokens; a colored dot/icon
  beside the label carries identity. Colors are never the only signal: every activity also has an icon + name.
- Yellow/aqua/magenta are low-contrast on light surfaces → always pair with a visible label.

### 7.3 Layout & navigation
- **Desktop (≥ 1024px):** left sidebar (logo, language switcher with flag, nav: Dashboard,
  Today, Plan, Log, Stats, Settings), content max-width 1200px, 12-col grid.
- **Tablet (640–1023px):** collapsible sidebar → top bar.
- **Phone (< 640px):** bottom tab bar (Home, Today, **+** (center FAB), Stats, More),
  16px side gutters, cards stack to 1 column, **no horizontal page scroll**. The heatmap
  scrolls horizontally *inside its own card* and is auto-scrolled to today on load.
- Touch targets ≥ 44px. Visible focus rings (`outline: 2px solid var(--accent); outline-offset: 2px`).
- Respect `prefers-reduced-motion` (disable count-ups, confetti, bar animations).

### 7.4 Pages

#### Dashboard `/`
Top to bottom (mobile order; desktop uses a 2-column grid where noted):
1. **Greeting row:** "Guten Abend, Matin 👋" + date + language pill (🇩🇪 German ▾).
2. **Hero card — Road to C1** (full width):
   - Big serif number: **`312.5 h`** / 1,200 h · **26%**.
   - One thick (16px) rounded progress bar, **segmented into 5 level segments**
     proportional to their target hours (A1 | A2 | B1 | B2 | C1) with 2px gaps; filled
     portion in `--accent`, level boundaries labelled under the bar. A small marker
     "You are here".
   - Sub-line: "At your 4-week pace, C1 by **Nov 2028**" + "ⓘ how estimated".
3. **Stat tiles row** (4 tiles, 2×2 on phone): 🔥 Current streak (days) ·
   🏆 Longest streak · ⏱ This week (h, vs last week ▲/▼ %) · ✅ Plan adherence (7d %).
   Current-streak tile: flame icon animates when today is already active; shows
   "at risk" state (outline flame + "Study today to keep your 23-day streak") otherwise.
4. **Level cards** (horizontal scroll-snap row on phone; 5-column grid on desktop):
   each card = level code big (A1), name ("Anfänger"), hours `118 / 120 h`,
   a **progress ring** (SVG, stroke-dasharray) and status chip: ✓ Done / ● Current / 🔒 Locked.
   Current card is elevated with accent border. Tapping a card expands per-skill
   mini-bars (six thin bars with activity icon + `12.5 / 30 h`).
5. **Today's plan** card (left col on desktop): checklist of today's plan items with
   activity icon, title, planned minutes, and three actions: ✓ Done, ◐ Partial (minutes
   input pops inline), ✕ Skip. HTMX swaps the row; completing all items triggers a small
   celebration. Link "Edit plan".
6. **Activity heatmap** card (right col on desktop; full width below on phone), legend
   "Less ▢▢▢▢▢ More", totals "214 active days in the last year".
7. **Recent sessions** (last 5) with inline edit/delete.

#### Today `/today`
Focused, phone-optimized view: today's plan checklist + quick-log + "today so far: 45 min
of 90 min daily goal" ring. Date nav ← → to fill in past days.

#### Plan `/plan`
- **Weekly builder:** 7 columns (Mon–Sun; stacked day accordions on phone). Each day has
  item chips (activity color dot + name + minutes). Add item: activity select, minutes,
  optional title. Drag to reorder/move between days (SortableJS vendored, optional; buttons
  as fallback). Live totals per day and per week, plus a stacked bar showing the
  week's split by activity vs the **recommended mix** for the current level (§2.4).
- **"Suggest a plan"** button: input "days per week" + "minutes per day" → pre-fills
  the builder using the current level's skill mix, rounding to 15-min blocks. User edits then saves.
- **Plan history:** archived plans with date ranges and adherence %.

#### Log `/log`
- Filterable table/list of all sessions (date range, activity, language), paginated,
  grouped by day with day totals. Edit / delete (delete with undo toast, 5s).
- **Add session form** (also as modal/bottom-sheet from the FAB): date (default today,
  no future dates), activity (chip radio group with icons), minutes (preset chips +
  number input + optional `h:mm` parsing like "1:15"), resource, note.
- Keyboard shortcut `n` opens the quick-log on desktop.
- CSV export button.

#### Stats `/stats`
- **Weekly hours** bar chart (last 12/26/52 weeks), **stacked by activity** with 2px gaps,
  legend + tooltips, planned-goal as a dashed reference line (single y-axis).
- **Activity split** — horizontal bars "all time" vs "recommended mix" (don't use a pie).
- **Streak history** — timeline of past streaks ≥ 3 days.
- **Heatmap with year selector.**
- **What-if calculator:** slider min/day → C1 & next-level dates.
- **Milestones timeline:** "A1 hours reached – 12 Jan 2027", "100-day streak", "500 h".
- Every chart has a "View as table" toggle (accessibility).

#### Settings `/settings`
- Timezone, week start (Mon/Sun), streak threshold minutes, daily goal minutes, theme
  (system/light/dark), display name.
- **Languages:** add language (name, code, flag), set goal level, archive.
- **Levels:** edit target hours per level (with "reset to recommended"), record exam passed.
- **Activity types:** add/rename/archive, pick icon + color slot.
- **Data:** export JSON/CSV, import JSON, download SQLite backup.

### 7.5 Motivation features (the "delight" layer)
- **Count-up animation** of hero numbers on page load (respect reduced motion).
- **Confetti** (tiny inline JS, ~2 KB, or `canvas-confetti` vendored) on: level hours
  reached, streak milestones (7, 14, 30, 50, 100, 200, 365), every 100 total hours,
  completing all of today's plan. Triggered once via `milestone_event.seen = False`.
- **Toasts** after logging: "+30 min Listening · 🔥 24-day streak · 4.2 h to A2".
- **"Next milestone"** chip on the dashboard: "7.5 h until A2 🎯".
- **Level-up screen:** full-width card "🎉 A1 complete! 120 hours of German." with date, shareable (screenshot-friendly).
- German micro-copy touches (optional toggle): "Weiter so!", "Super gemacht!", "Los geht's!".

### 7.6 Empty & edge states
- No sessions yet: hero shows 0 h with an illustration and a big "Log your first session" CTA.
- No plan: Today card shows "No plan yet — **Suggest a plan** in 30 seconds".
- Streak 0: "Start a streak today".
- Goal already exceeded: bar full + "+42 h beyond C1 — time to set C2?".

---

## 8. Routes (blueprints)

| Method | Path | Purpose | Returns |
|---|---|---|---|
| GET | `/` | Dashboard (current language from session cookie, default first active) | page |
| GET | `/lang/<code>` | Switch current language | redirect |
| GET | `/today?date=YYYY-MM-DD` | Today view | page |
| POST | `/plan-items/<id>/status` | Set done/partial/skipped (+minutes) | HTMX partial (row + OOB swaps for stats/streak tile) |
| GET | `/plan` | Weekly builder (active plan) | page |
| POST | `/plan` | Create plan | redirect |
| POST | `/plan/<id>/items` | Add template item | partial |
| PATCH/POST | `/plan/items/<id>` | Edit / move template item | partial |
| DELETE/POST | `/plan/items/<id>/delete` | Remove template item | partial |
| POST | `/plan/suggest` | Generate suggested template (not saved) | partial |
| POST | `/plan/<id>/activate`, `/plan/<id>/archive` | Lifecycle | redirect |
| GET | `/log` | Session list (filters via query) | page |
| GET | `/sessions/new` | Form (modal partial if `HX-Request`) | page/partial |
| POST | `/sessions` | Create | redirect or partial + toast (HX-Trigger) |
| GET/POST | `/sessions/<id>/edit` | Edit | page/partial |
| POST | `/sessions/<id>/delete` | Delete (soft for 5s undo optional) | partial |
| GET | `/day/<date>` | Day drawer: sessions + plan items | partial |
| GET | `/heatmap?year=` | Heatmap partial | partial |
| GET | `/stats` | Stats page | page |
| GET | `/api/stats/weekly?weeks=26` | JSON for Chart.js | JSON |
| GET/POST | `/settings` (+ sub-sections) | Settings | page |
| GET | `/export.csv`, `/export.json` | Export | file |
| POST | `/import` | Import JSON | redirect |
| GET/POST | `/login`, `/logout` | Only if `APP_PASSWORD` set | page |

HTMX conventions: return partials when `HX-Request` header present; use `hx-swap-oob`
to refresh the streak tile, hero bar and heatmap cell after a log/tick, and `HX-Trigger`
headers to fire toasts / confetti events handled in `app.js`. All forms work without JS
(progressive enhancement).

### CLI commands (`cli.py`)
- `flask seed` — idempotent: creates German (`de`, 🇩🇪), levels A1–C2 with §2.3 targets
  (C2 = 500 h, hidden since goal = C1), activity types §2.4 order, skill mix, default settings.
- `flask seed-demo --days 200` — random realistic sessions for UI development (dev only).
- `flask export --out backup.json` / `flask import backup.json`.

---

## 9. Security & ops
- `SECRET_KEY` from `.env`; CSRF on all POSTs (Flask-WTF; HTMX sends the token via
  `hx-headers` on `<body>`).
- Optional single password (`APP_PASSWORD` env, hashed compare) for when it's deployed
  publicly; session cookie `HttpOnly`, `SameSite=Lax`, `Secure` in prod.
- Validate: minutes 1–960, date not in future and not before 2000-01-01, enums.
- Deployment (later): any small VPS / Fly.io / Railway / PythonAnywhere with a
  persistent volume for SQLite; run with `gunicorn` (Linux) or `waitress` (Windows):
  `uv add waitress` → `uv run waitress-serve --call sprachweg:create_app`.
- Backups: the SQLite file + JSON export button.

---

## 10. Testing strategy
- **Unit (services):** streaks (all cases in §6.4), level allocation (0 h, exact boundary,
  overflow beyond goal, edited targets), per-skill split across a boundary, heatmap grid
  shape (always 53×7, correct weekday alignment, week-start setting), plan expansion
  (no past generation, idempotency, template edit only affects future pending), ETA
  (zero pace → hidden).
- **Route tests:** create/edit/delete session; tick plan item creates exactly one session;
  un-tick (done → pending) deletes the linked session; CSRF enforced; future date rejected.
- Freeze time with `time-machine` in every date-dependent test.
- `uv run pytest -q` and `uv run ruff check . && uv run ruff format --check .` must pass.

---

## 11. Implementation milestones (build in this order)

| # | Milestone | Done when |
|---|---|---|
| M1 | **Skeleton** — uv project, app factory, config, extensions, base layout, design tokens, light/dark toggle, nav (sidebar + bottom bar) | `uv run flask run` shows an empty styled dashboard on desktop and phone widths |
| M2 | **Models + migrations + seed** | `flask db upgrade && flask seed` creates German + levels + activities; seed is idempotent |
| M3 | **Logging** — add/edit/delete sessions, log list, quick-log modal/FAB, validation | Sessions persist; list groups by day with totals |
| M4 | **Progress** — services/progress.py, hero C1 bar (segmented), level cards with rings, per-skill mini-bars, ETA | Numbers match unit tests; boundary cases correct |
| M5 | **Streaks & stat tiles** — services/streaks.py + tests, dashboard tiles, at-risk state | All §6.4 test cases pass |
| M6 | **Heatmap** — service + SVG macro, tooltips, day drawer, year selector | Renders 365 days, today highlighted, scrolls to today on phone |
| M7 | **Plans** — weekly builder, lazy expansion, Today view, done/partial/skip with linked sessions, suggest-a-plan | Ticking updates hero/streak/heatmap via OOB swaps without reload |
| M8 | **Stats page** — weekly stacked chart, split vs recommended, streak history, what-if slider, tables | Charts have legends, tooltips, table views, work in dark mode |
| M9 | **Delight** — count-ups, confetti + milestone events, toasts, empty states, German micro-copy | Milestones fire exactly once |
| M10 | **Settings, export/import, optional password, README** | Round-trip export→import reproduces identical stats |

Each milestone ends with tests green, ruff clean, and a manual check at 375px, 768px and 1280px, both themes.

---

## 12. Future (post-v1, keep the design open for these)
- Second language (e.g. Spanish/French): add via Settings; everything is already keyed
  by `language_id`. Dashboard gets an "All languages" overview (per-language rows, combined heatmap).
- Per-language hour targets for other languages (FSI categories: Spanish/French ≈ Cat I,
  shorter; Japanese/Arabic ≈ Cat IV, much longer).
- PWA (manifest + service worker) for home-screen install and offline quick-log.
- Timer mode (start/stop stopwatch that creates a session).
- Resource library (books, podcasts, courses) with hours per resource.
- Reminders (browser notifications / email) if the streak is at risk.
- Vocabulary count tracking (known words) as a second quantitative metric.

---

## 13. Acceptance checklist (v1)
- [ ] `uv sync && uv run flask --app sprachweg db upgrade && uv run flask --app sprachweg seed && uv run flask --app sprachweg run` works on a clean clone (Windows + Linux).
- [ ] Dashboard shows: segmented C1 bar with %, 5 level cards with correct statuses, 4 stat tiles, today's plan, heatmap, recent sessions.
- [ ] Log a session in ≤ 3 interactions from any page on a phone.
- [ ] Weekly plan can be created, suggested, edited; items can be marked done/partial/skipped; done creates a linked session.
- [ ] Current & longest streak correct across the test matrix; "at risk" state shown when today isn't active yet.
- [ ] Heatmap: 365 days, 6 intensity levels, tooltips, click → day details.
- [ ] Projection shown for next level and C1.
- [ ] Responsive at 375 / 768 / 1280 px with no horizontal page scroll; light & dark themes; reduced-motion respected; keyboard navigable; charts have table views.
- [ ] Level targets and all thresholds editable in Settings.
- [ ] Data export/import works.
- [ ] Tests + ruff pass.
