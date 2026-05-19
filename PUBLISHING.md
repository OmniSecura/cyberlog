# Publishing cyberlog — one-time setup + release runbook

This document is the complete step-by-step you (Bartosz) will follow to ship
`cyberlog` to PyPI. Keep it in the repo so future-you doesn't have to figure
it out again.

---

## 0. Pre-flight check (one minute)

Before anything else, confirm the package is in a publishable state:

```bash
cd cyberlog
python -m venv .venv && source .venv/Scripts/activate   # Windows
pip install -e ".[dev]"
pytest -q                                               # → 24 passed
python -m build                                         # → dist/cyberlog-0.1.0-py3-none-any.whl
twine check dist/*                                      # → PASSED
```

If anything fails — fix it locally first, don't push.

---

## 1. Deploy the log-service publicly

The library defaults to `https://logs.omnisecura.pl/api/v1`. That URL has to
work before users can `pip install cyberlog`.

### 1a. DNS

In your domain provider's panel add an **A record** (or **AAAA** for IPv6):

```
logs.omnisecura.pl   A   <IP of the server running CyberCore>
```

Same IP as `omnisecura.pl`. Wait a few minutes for propagation.
Verify: `dig +short logs.omnisecura.pl` should return your server's IP.

### 1b. Deploy CyberCore in production mode

On the server:

```bash
cd /path/to/CyberCore
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

`docker-compose.prod.yml` already hides `log` and `log-consumer` from the
host — they're only reachable through Caddy.

Caddy reads `Caddyfile`, sees the new `logs.omnisecura.pl` block, and
automatically requests a Let's Encrypt certificate the first time it serves
the subdomain. No extra config needed.

### 1c. Smoke test

```bash
curl https://logs.omnisecura.pl/health
# → {"status":"ok","database":"reachable"}

curl https://logs.omnisecura.pl/api/v1/auth/validate
# → {"detail":"Missing API key…"}   ← 401, but you reached the right service

curl -X POST https://logs.omnisecura.pl/api/v1/api-keys \
     -H "X-Org-Id: anything"
# → 404 Not found                    ← good, dashboard endpoints are hidden
```

If those three lines look right, the SDK can talk to your server.

---

## 2. Create the GitHub repo

1. On github.com create a new **public** (or private) repo named **`cyberlog`**
   under the `OmniSecura` org.
2. From your local `C:\Users\Bartosz\Desktop\cyberlog` directory:

```bash
git init                                  # if not already
git add .
git commit -m "Initial release"
git branch -M main
git remote add origin git@github.com:OmniSecura/cyberlog.git
git push -u origin main
```

CI (`.github/workflows/ci.yml`) starts immediately and runs the test matrix
on Python 3.9–3.13. Wait for the green check.

---

## 3. Register the project on PyPI

1. Sign in at https://pypi.org (create an account if you don't have one).
2. Go to **Your projects → Publishing → Add a new pending publisher**.
3. Fill in:
   - **PyPI Project Name:** `cyberlog`
   - **Owner:** `OmniSecura`
   - **Repository name:** `cyberlog`
   - **Workflow filename:** `publish.yml`
   - **Environment name:** `pypi`
4. Save.

This is **PyPI Trusted Publishing** — your GitHub Actions workflow can now
publish without any token, using OpenID Connect. Nothing in repo secrets.

### 3a. Tell GitHub the environment exists

On GitHub: **Settings → Environments → New environment → `pypi`**.
No reviewers, no secrets — the environment exists purely so the workflow
can reference it (`environment: name: pypi`).

---

## 4. First release

```bash
# Make sure main is clean and tests are green.
git status
git pull --rebase

# Tag it.
git tag -a v0.1.0 -m "v0.1.0 — initial release"
git push origin v0.1.0
```

That push triggers `.github/workflows/publish.yml` which:

1. Builds sdist + wheel
2. Smoke-imports the wheel
3. Uploads to PyPI via OIDC

Watch the run in the Actions tab. ~1 minute end to end.

When it finishes:

```bash
pip install cyberlog
python -c "from cyberlog import CyberLogCore; print(CyberLogCore.__doc__[:60])"
```

🎉

---

## 5. Subsequent releases

Cadence: bump version, tag, push. PyPI is immutable per-version, so you
can't overwrite — every bump needs a new version number.

```bash
# 1. Bump the version
#    Edit cyberlog/_version.py:  __version__ = "0.2.0"

# 2. Update the changelog
#    Edit CHANGELOG.md, move [Unreleased] to [0.2.0] - YYYY-MM-DD

# 3. Commit + push
git add cyberlog/_version.py CHANGELOG.md
git commit -m "Release 0.2.0"
git push

# 4. Tag + push tag (workflow fires)
git tag -a v0.2.0 -m "v0.2.0"
git push origin v0.2.0
```

Use **SemVer**:
- patch (`0.1.0` → `0.1.1`) for bugfixes
- minor (`0.1.x` → `0.2.0`) for new features that are backward-compatible
- major (`0.x.y` → `1.0.0`) when you break the public API

---

## 6. Yanking a bad release

If you publish a broken version, you can't delete it from PyPI but you can
**yank** it — new installs skip it, existing pins keep working:

```
https://pypi.org/manage/project/cyberlog/release/0.2.0/
→ Options → Yank release
```

Then publish a fixed version (`0.2.1`) and write a note in the changelog.

---

## 7. Troubleshooting

| Symptom | Fix |
|---------|-----|
| Workflow fails at "Publish to PyPI" with "Trusted publisher not found" | The pending-publisher form on PyPI doesn't match repo / workflow filename / environment exactly. Re-check step 3. |
| `pip install cyberlog` returns `0.1.0` long after you released `0.2.0` | PyPI propagates within seconds, but pip's own caches and mirrors can lag. Try `pip install --no-cache-dir cyberlog`. |
| `httpx.ConnectError: [Errno 11001] getaddrinfo failed` from a user | They have no internet, or they're behind a corporate proxy that blocks `logs.omnisecura.pl`. Suggest they set `CYBERLOG_API_URL` to their own mirror or pass `validate_on_init=False`. |
| Server-side: log-consumer eats memory | Queue is filling up because consumer can't keep up. Scale by running another `log-consumer` replica — they're stateless. |
