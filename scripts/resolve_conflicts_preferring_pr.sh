#!/usr/bin/env bash
# Resolve conflicts by preferring the PR branch, run backend smoke tests, and optionally push.
#
# This script mirrors the manual recovery steps documented in the repo docs. It can be run from
# any environment (including Colab) to refresh the repo, merge the latest "main" into the most
# recent feature branch, and ensure the backend still boots.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/englishpodcasteasy-glitch/videorobot.git}"
WORKDIR="${WORKDIR:-/content/videorobot}"
MAIN_BRANCH="${MAIN_BRANCH:-main}"
PR_BRANCH_PATTERN="${PR_BRANCH_PATTERN:-origin/(codex/|feat/|fix/|renderer|colab|security)}"
PYTHON_BIN="${PYTHON_BIN:-python}"
SKIP_PUSH="${SKIP_PUSH:-1}"

log() {
  printf '[%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

clone_or_refresh_repo() {
  if [[ ! -d "${WORKDIR}/.git" ]]; then
    log "Cloning repository ${REPO_URL} -> ${WORKDIR}"
    rm -rf "${WORKDIR}"
    git clone "${REPO_URL}" "${WORKDIR}"
  else
    log "Using existing repository at ${WORKDIR}"
  fi

  cd "${WORKDIR}"
  log "Fetching latest refs"
  git fetch --all --prune
}

select_pr_branch() {
  local branch
  branch=$(git for-each-ref --sort=-committerdate --format='%(refname:short)' refs/remotes/origin \
    | grep -E "${PR_BRANCH_PATTERN}" \
    | head -n 1 \
    | sed 's#^origin/##') || true

  if [[ -z "${branch}" ]]; then
    log "ERROR: Could not detect a PR branch (pattern: ${PR_BRANCH_PATTERN})."
    log "Set PR_BRANCH manually: PR_BRANCH=<branch> ${0}"
    exit 1
  fi

  PR_BRANCH="${PR_BRANCH:-$branch}"
  log "Using PR branch: ${PR_BRANCH}"
}

checkout_and_merge() {
  git checkout -B "${PR_BRANCH}" "origin/${PR_BRANCH}"
  log "Merging ${MAIN_BRANCH} into ${PR_BRANCH} (preferring PR changes)"
  git merge -s recursive -X ours "origin/${MAIN_BRANCH}" -m "chore: resolve conflicts preferring PR (ours) vs main" || true
  if git ls-files -u | grep . >/dev/null 2>&1; then
    log "WARNING: Merge left manual conflicts; keeping PR versions for affected files"
    git checkout --ours backend/main.py backend/renderer.py backend/renderer_service.py backend/requirements.txt \
      colab_runner.ipynb README.md REPORT.md docs/api_contract_frontend.json docs/api_harmony_report.json 2>/dev/null || true
    git add backend/main.py backend/renderer.py backend/renderer_service.py backend/requirements.txt \
      colab_runner.ipynb README.md REPORT.md docs/api_contract_frontend.json docs/api_harmony_report.json 2>/dev/null || true
  fi
}

ensure_backend_package() {
  touch backend/__init__.py
}

run_dependency_check() {
  log "Upgrading pip"
  "${PYTHON_BIN}" -m pip install -q --upgrade pip
  log "Installing backend requirements (best effort)"
  "${PYTHON_BIN}" -m pip install -q -r backend/requirements.txt || true
}

run_smoke_tests() {
  log "Running compileall smoke test"
  "${PYTHON_BIN}" -m compileall backend >/dev/null

  log "Booting backend for health check"
  BACKEND_PORT="${BACKEND_PORT:-8000}" "${PYTHON_BIN}" - <<'PY'
import os
import subprocess
import sys
import time
from urllib.request import urlopen

port = os.environ.get('BACKEND_PORT', '8000')
base = f"http://127.0.0.1:{port}"
process = subprocess.Popen([sys.executable, '-m', 'backend.main'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    healthy = False
    for _ in range(60):
        time.sleep(1)
        try:
            with urlopen(base + '/healthz', timeout=2) as response:
                if response.status == 200:
                    healthy = True
                    break
        except Exception:
            continue
    if not healthy:
        raise SystemExit('Backend did not become healthy in time')
finally:
    process.terminate()
PY
}

commit_and_push() {
  if [[ -n "$(git status --porcelain)" ]]; then
    log "Committing merge artifacts"
    git add -A
    git commit -m "fix: resolve conflicts preferring PR; ensure backend package; smoke ok"
  else
    log "No changes detected after merge"
  fi

  if [[ "${SKIP_PUSH}" == "0" ]]; then
    log "Pushing branch ${PR_BRANCH}"
    git push -u origin "${PR_BRANCH}"
  else
    log "Skipping push (SKIP_PUSH=${SKIP_PUSH})"
  fi
}

clone_or_refresh_repo
select_pr_branch
checkout_and_merge
ensure_backend_package
run_dependency_check
run_smoke_tests
commit_and_push

log "✅ Conflicts resolved on '${PR_BRANCH}'."
log "Open the PR in GitHub and complete the merge when ready."
