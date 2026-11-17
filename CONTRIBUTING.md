# Contributing to Offline Changes

## Branches

`develop` is where work happens, `version-16` is the release branch. Open pull requests against `develop`, one concern per pull request.

## Commits

[Conventional Commits](https://www.conventionalcommits.org): `type: summary`, with the type one of `feat fix perf refactor docs test style build ci chore revert`. The summary says what changes, the body says why. Formatting-only changes go in their own `style:` commit, listed in `.git-blame-ignore-revs`.

## Before you commit

```bash
pre-commit run --all-files
bench --site $SITE run-tests --app frappe_offline_changes
```

## Code

- The app depends on Frappe alone. What it needs to know about another app's DocTypes it asks through the hooks in `frappe_offline_changes/utils/extensions.py`; it never imports another app.
- DocTypes are changed in the Desk on a developer-mode site, which writes the JSON and the controller's typed field block. No migration patches.
- A rule on what becomes of a change belongs in `offline_changes/processing.py`, with a test in `tests/test_changes.py` for the situation it covers.
- Values are SQL parameters. User-facing strings are translatable (`_()`, `__()`). Comments say why.
- Synthetic data only, in tests, fixtures, issues and screenshots.
