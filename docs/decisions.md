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

*Not yet made.*

**Why:**

---

## Pending entries

Decisions identified but not yet written up:

- **Timezone offset on `published_at`** — every stored article is exactly 12 hours
  behind reality; the cause is still undetermined (API clock, a deliberate free-tier
  delay, or `pubDate` meaning something other than publication time). Options range
  from correcting on write, to switching incremental logic to `created_at`, to
  documenting and leaving it.
- **`text` vs `timestamp` for `published_at`** — currently stored as text, taken
  verbatim from the API.
- **Client-side incremental filtering** — the free-tier endpoint has no date
  parameter, so filtering happens in Python after fetching.
- **Local scheduling limits** — the DAG is set to `@daily` but has never fired, since
  Airflow only runs while Docker Desktop is open.
- **Sentiment scored on title only**, not article body.
- **Airflow + Docker for a project this size** — orchestration chosen over a simpler
  scheduled script.
