#!/usr/bin/env bash
# Prove this repo is still deployable to a fresh, offline box — WITHOUT cutting a
# 1.4 GB bundle to find out.
#
# `make bundle` takes minutes and a gigabyte of disk, so it is not something anyone runs
# per change. This is: it checks the properties that, when they break, silently make the
# bundle wrong. Run it whenever docker-compose.yml, the Dockerfile or deploy/ moves.
#
# WHAT IT CHECKS, AND WHY EACH ONE HAS ALREADY BITTEN
#
#   1. Every image compose needs is PROJECT-NAME INDEPENDENT.
#      Compose names a built image `<project>-<service>` by default. The bundle ships
#      images BY NAME, so a target box installing under any other project name looks for
#      an image the tarball does not contain. Found on 2026-08-28 by rehearsing an
#      install under `-ProjectName jd-bank-verify`; fixed with explicit `image:` keys.
#      The check is dependency-free on purpose: ask compose for its image list twice
#      under two different project names and require the answers to be identical.
#
#   2. Nothing in the runtime path builds from a remote base at deploy time.
#      `install.ps1` passes `--no-build --pull never`, so an image that is not in the
#      bundle is a hard failure on the target, not a silent pull. That only holds if
#      compose can enumerate its images at all.
#
#   3. The deploy kit is actually present and syntactically valid.
#      A bundle script that does not parse is discovered at the worst possible moment.
#
# It does NOT verify the CONTENTS of a bundle — MANIFEST.txt and install.ps1's row-count
# verification do that, on the target, where it matters.

set -euo pipefail

cd "$(dirname "$0")/.."

fail=0
ok()   { printf '  [ok]   %s\n' "$1"; }
bad()  { printf '  [FAIL] %s\n' "$1"; fail=1; }
step() { printf '\n=== %s ===\n' "$1"; }

step 'Compose can enumerate its images'
if ! images_default="$(docker compose --project-name jd-bank config --images 2>/dev/null | sort -u)"; then
    bad 'docker compose config --images failed — the compose file does not resolve.'
    exit 1
fi
if [ -z "$images_default" ]; then
    bad 'compose reported NO images at all.'
    exit 1
fi
# `grep -c .` counts NON-EMPTY LINES; `wc -l` counts newlines and so reported 4 for the
# 5 images, because the last line carries no trailing newline.
ok "$(printf '%s\n' "$images_default" | grep -c .) image(s) required:"
printf '%s\n' "$images_default" | sed 's/^/           /'

step 'Image names do not depend on the compose project name'
# The whole check: a DIFFERENT project name must produce the SAME list. If a service
# leaves its image name to compose's default, this diff is where it shows up.
images_other="$(docker compose --project-name jd-bank-offline-check config --images 2>/dev/null | sort -u)"
if [ "$images_default" = "$images_other" ]; then
    ok 'identical under a second project name — the bundle is portable'
else
    bad 'image names CHANGE with the project name. A bundle cut here will not install'
    printf '     under a different project name. Add an explicit `image:` to each service\n'
    printf '     that has a `build:`.\n'
    printf '     only-under-jd-bank:\n'
    comm -23 <(printf '%s\n' "$images_default") <(printf '%s\n' "$images_other") | sed 's/^/           /'
    printf '     only-under-the-other-name:\n'
    comm -13 <(printf '%s\n' "$images_default") <(printf '%s\n' "$images_other") | sed 's/^/           /'
fi

step 'The deploy kit is present'
for f in deploy/bundle.ps1 deploy/install.ps1 deploy/README.md; do
    if [ -f "$f" ]; then ok "$f"; else bad "missing $f"; fi
done

step 'The build context excludes churning caches'
if [ -f core/.dockerignore ]; then
    ok 'core/.dockerignore present'
    # tests/ and alembic/ MUST reach the image: gates runs the suite inside it (ADR-006)
    # and migrations run from the api container.
    for keep in 'tests' 'alembic'; do
        if grep -qE "^/?${keep}/?$" core/.dockerignore; then
            bad "core/.dockerignore excludes ${keep}/ — that breaks 'make gates' or migrations"
        fi
    done
else
    bad 'core/.dockerignore missing — every lint/test run will bust the image layer cache'
fi

step 'Result'
if [ "$fail" -ne 0 ]; then
    printf '  DEPLOY-CHECK FAILED — this repo is not currently safe to bundle.\n\n'
    exit 1
fi
printf '  ✅ DEPLOY-CHECK GREEN — a bundle cut from this repo will install on a fresh box.\n'
printf '     Cut it with:  make bundle\n\n'
