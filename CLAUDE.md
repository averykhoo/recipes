# Recipes repo

Markdown recipes published as a Jekyll site on GitHub Pages:
https://averykhoo.github.io/recipes

## Environment

- **Python**: always use the `recipes` conda env:
  `C:\Users\avery\anaconda3\envs\recipes\python.exe`. Never the system Python.
- **Tests**: `"C:\Users\avery\anaconda3\envs\recipes\python.exe" -m pytest -q` from the repo root.
- **Shells**: PowerShell and Git Bash are both available. Pick one per command and use
  its syntax. They can't run each other's code: no `$env:X` or `Get-ChildItem` in Bash, no
  heredocs, `&&`, or `/c/...` paths in PowerShell 5.1. Don't pass a script written for one
  to the other.

## After every push to `master`: CI babysitting loop

A push to `master` runs `.github/workflows/deploy.yml`. Its jobs are `test` (pytest), then
`build` (Jekyll build, service worker, built-site checks), then `deploy` (GitHub Pages).
After each push, run this loop with subagents and don't stop until it ends:

1. **Watch CI with a Haiku agent** (`model: haiku`). Give it the pushed commit SHA. It
   polls the Actions REST API until that commit's run finishes:
   ```bash
   API=https://api.github.com/repos/averykhoo/recipes
   curl -s "$API/actions/runs?branch=master&per_page=5"   # match head_sha; status, conclusion
   curl -s "$API/actions/runs/<run_id>/jobs"              # per-job and per-step conclusions
   curl -s -L -H "Authorization: Bearer $GH_TOKEN" "$API/actions/jobs/<job_id>/logs"
   ```
   The logs endpoint needs a token. Use the read-only token from the user's global
   CLAUDE.md, passed through the environment. **Never write the token into this repo.**
   Have it report back:
   - **Success**: the run's ID and URL.
   - **Failure**: the failing job and step, plus the relevant log excerpt (the error and
     about 50 lines around it). Not the whole log, and not its own diagnosis.

2. **On failure, fix with a bigger agent** (default/Opus model). Give it the Haiku agent's
   report and the commit SHA. It finds the root cause, fixes it, runs the test suite in the
   `recipes` env, commits, and pushes. Then go back to step 1 for the new commit. Keep
   repeating until CI is green. Never skip, disable, or `continue-on-error` a test to get
   green. If the same failure comes back after two fix attempts, stop and report to the
   user with the logs.

3. **When CI is green, smoke-test the live site with another agent.** Have it wait a few
   minutes first, because Pages and its CDN take time to serve a new deploy. Then check
   https://averykhoo.github.io/recipes:
   - The index page and `sw.js` return 200, and `sw.js` has no leftover
     `__BUILD_ID__` / `__SHELL_ASSETS__` / `__PAGES__` placeholders.
   - `static/3d-moon-widget.html` returns 200.
   - Every recipe the push added, renamed, or edited is served at its new URL and shows its
     new content. For example, `recipes/confectionery/meemas-sherry-trifle.html` is the page
     for `recipes/confectionery/meemas-sherry-trifle.md`. `in-progress/` and
     `curated-untested/` map to the same paths.
   - A couple of unrelated recipe pages still return 200.

   If a page is stale or missing, retry once after a few more minutes before calling it
   a failure. Report pass/fail with the URLs checked. A real failure goes back into
   step 2.
