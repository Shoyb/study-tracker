# Contributing

Thanks for helping improve Study Tracker. Keep changes focused and preserve the local-first data model.

## Set up

Use Python 3.12 or newer from the project directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m pip install -r requirements-dev.txt
```

Set `STUDY_TRACKER_HOME` to a temporary folder while developing so experiments do not touch your normal database.

## Before submitting a change

```powershell
ruff check .
pytest -q
```

Add tests for new business rules and preserve existing user data. Do not edit an applied SQL migration; add the next numbered migration. Keep SQL in `db/`, UI code in `ui/`, and use the injected clock for timestamps and tests. Do not add a runtime dependency without first discussing it.

For a bug report, include the app version, operating system, steps to reproduce, and relevant log output. Remove personal study notes and other private data before sharing logs or database files.
