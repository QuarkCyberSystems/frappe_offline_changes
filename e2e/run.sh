#!/usr/bin/env bash
# The browser test of the review screen, on a development site that is being served:
#
#   apps/frappe_offline_changes/e2e/run.sh [site]
#
# Needs a Python with Playwright and Chromium (pip install playwright; playwright install chromium): the
# bench's own by default, or the one named in E2E_PYTHON.
set -euo pipefail

SITE="${1:-${SITE:-}}"
BENCH="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$BENCH"
if [ -z "$SITE" ]; then
	echo "Name the site: e2e/run.sh <site>" >&2
	exit 2
fi

T="frappe_offline_changes.tests.e2e"
trap 'bench --site "$SITE" execute "$T.cleanup" >/dev/null' EXIT
bench --site "$SITE" execute "$T.prepare" | tail -n 1 | "${E2E_PYTHON:-env/bin/python}" apps/frappe_offline_changes/e2e/review.py
bench --site "$SITE" execute "$T.check"
echo "The site holds what the reviewer chose"
