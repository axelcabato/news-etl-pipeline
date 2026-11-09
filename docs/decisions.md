# Design Decisions

A record of the choices behind this project and the reasoning for them. Bug fixes
live in the git history; this file covers decisions where a real alternative existed.

Each entry states the problem, the options available, what was chosen, and why.

---

## 1. Dependency pinning strategy

**Status:** open — decision not yet made

### Problem

Unpinned dependencies have broken this project three times:

1. **July 2026** — `newsdataapi` was unpinned. A rebuild installed a newer version
   in which `latest_api()` no longer accepted the `from_date` argument. Every ETL
   run failed with a `TypeError`.
2. **14 Sep 2026** — `dashboard/requirements.txt` pinned `streamlit==1.31.0` but
   left `plotly` unpinned, so a rebuild installed Plotly 7.0.0. Streamlit renders
   figures using a plotly.js bundled in its own frontend, and the two-year gap
   between the figure spec and the renderer caused the log-level pie chart to draw
   equal slices (50/50) instead of the real 83/17 distribution.
3. **19 Oct 2026** — `pyarrow`, a *transitive* dependency pulled in by Streamlit and
   listed nowhere in `requirements.txt`, resolved to a version requiring NumPy 2.0.
   Streamlit 1.31.0 constrains NumPy to `<2`. The container entered a crash loop with
   `ImportError: pyarrow requires NumPy 2.0 or newer, found 1.26.4`.

The third incident is the important one. By then all four *direct* dependencies were
pinned, and the build still broke — because the tree beneath them kept moving. The
same `requirements.txt` produced a working image two weeks earlier only because
Docker had cached the pip layer; once that cache expired, pip resolved differently.

### Options

**A. Pin direct dependencies only** (current approach)

- Small, readable file — five lines
- Does not prevent transitive drift; incident 3 happened under this approach
- Each new break is fixed reactively by adding another pin

**B. Lock the full tree** (`pip freeze > requirements.txt`)

- Builds become genuinely reproducible — every version fixed
- File grows to ~45 packages, most never chosen deliberately
- Security updates require regenerating the lock rather than arriving automatically
- Standard practice in production systems

**C. Use a dependency manager with a lockfile** (Poetry, pip-tools, uv)

- Separates "what I asked for" from "what was resolved" — two files, both explicit
- Industry standard on newer projects
- Adds a tool and a workflow to learn

### Decision

**C — generate a lock file with `uv`.** Keep the five chosen packages in
`requirements.in`, and generate the full pinned list with:

```bash
uv pip compile requirements.in -o requirements.txt \
    --python-version 3.12 --python-platform linux
```

The platform flags matter: resolution must target the container's Linux image rather
than the Windows host. The Dockerfile is unchanged — the generated file is an
ordinary pip requirements file, so the image still runs `pip install -r
requirements.txt`. `uv` is a local tool, run when dependencies change, and never
enters the build.

**Status of implementation:** decided 7 Nov 2026, not yet implemented. The project
remains on approach A until the lock file is generated and a rebuild is verified.

**Why:** C is low-cost and low-effort to implement, and its benefits are within
reach regardless of how significant they turn out to be. It locks everything the way
B does, but keeps the five packages actually chosen in a separate file, so the
intent behind the dependency list stays visible instead of being buried among the
forty-odd packages that came along with them. The extra cost over B is installing
one tool and learning one command — and it is a command that gets reused every time
a dependency changes, rather than hand-editing a long generated file.

Rejected A because it is the option that accepts recurring breakage: each incident
gets patched reactively after it has already cost a working session, and incident 3
happened under A with every direct dependency already pinned. Rejected Poetry
because restructuring the project around `pyproject.toml` is days of work for the
same lock file.

---

## 2. Handling the 12-hour gap between publication and ingestion

**Status:** decided

### Problem

Every article in the database shows a gap of 12.00–12.02 hours between `created_at`
and `published_at`, uniform across every batch since July 2026 and across every time
of day, including a scheduled run that executed at `00:00:02` UTC.

The cause was investigated on 27 Oct 2026 and traced to **NewsData.io's free tier,
which delays article access by 12 hours**. The newest article the free plan will
serve is one published roughly 12 hours earlier, so `pubDate` tracks request time
minus 12 hours. A raw API record confirmed this: requested at `22:43:40` UTC, it
reported `pubDate: 10:43:00` — exactly 12 hours earlier, matching to the minute —
alongside a `fetched_at` crawler timestamp of `15:00:48` sitting independently
between publication and delivery.

The key point: **the delay affects which articles are received, not the accuracy of
their timestamps.** `published_at` is correct. Nothing is corrupted.

This also explains an anomaly noticed earlier — all ten articles in a batch claim
publication times within about five seconds of each other. They sit at the boundary
of the delayed window rather than having been published simultaneously.

### Options

**A. Document the delay; change no code**

- `published_at` stays accurate
- The gap remains visible to anyone reading the data

**B. Surface the constraint in the dashboard**

- A viewer seeing 12-hour-old articles understands why
- Small addition, no data change

**C. Shift stored values forward by 12 hours, and document the shift**

- Timestamps would appear current
- The shifted value describes nothing real — not publication time, not ingestion time
- Breaks silently if the plan tier changes and the delay disappears
- Replaces a correct value with an inferred one

**D. Store the API's `fetched_at` field as an additional column**

- Enables measuring the full latency chain: published → crawled → ingested
- A column this project would never query

### Decision

**A and B.** Keep `published_at` exactly as the API reports it, and note the
free-tier delay where a reader would otherwise be confused by it.

**Why:** The data is already correct, so there is nothing to fix. Shifting the values
would mean taking an accurate timestamp and making it wrong just so a number on a
dashboard looked fresher, and it would break silently if the plan tier ever changed.
Disclosure costs nothing and keeps the data honest.

---

## 3. Grouping the ingestion chart by `created_at` rather than `published_at`

**Status:** decided

### Problem

The "Daily Article Ingestion" chart groups articles by `published_at` — when the news
outlet published the story — while its title claims to show ingestion. Because the
free tier delays content by 12 hours (see entry 2), any pipeline run between 00:00
and 12:00 UTC produces articles whose `published_at` falls on the previous calendar
day, splitting a single run across two dates on the chart.

### Options

**A. Group by `published_at`** — describes the source material: when the news was
published.

**B. Group by `created_at`** — describes the pipeline: when a run executed and how
much it moved.

### Decision

**B — group by `created_at`.** The existing title, "Daily Article Ingestion", becomes
accurate as a result and needs no change.

**Why:** A pipeline is a series of steps that extracts data from a source and lands it
in storage, transforming it along the way. When the pipeline fires, it ingests the
source data and does everything else. So grouping by ingestion date feels more
accurate to what this project is: it shows viewers the metric around the project's
focus, rather than a metric about something that isn't — the per-article publication
date. That holds regardless of the free-tier delay; even if publication dates were
real-time, the chart would still be measuring a property of the source material
rather than the behaviour of the system built around it.

---

## Pending entries

Decisions identified but not yet written up:

- **`text` vs `timestamp` for `published_at`** — currently stored as text, taken
  verbatim from the API.
- **Client-side incremental filtering** — the free-tier endpoint has no date
  parameter, so filtering happens in Python after fetching.
- **Local scheduling limits** — the DAG is set to `@daily` but has never fired, since
  Airflow only runs while Docker Desktop is open.
- **Sentiment scored on title only**, not article body.
- **Airflow + Docker for a project this size** — orchestration chosen over a simpler
  scheduled script.
