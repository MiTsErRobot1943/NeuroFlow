# Quick Start: Desktop Analytics

Run desktop mode with analytics enabled using a local PostgreSQL endpoint.

## Default behavior

When `python run_desktop.py` starts, desktop mode now sets `ANALYTICS_DATABASE_URL` automatically (unless already provided):

`postgresql://neuroflow:neuroflow@localhost:5432/neuroflow_analytics`

If PostgreSQL is unavailable, startup continues and analytics is skipped.

## Try it

```powershell
python run_desktop.py --no-window
```

## Optional overrides

```powershell
$env:NEUROFLOW_ANALYTICS_HOST = "localhost"
$env:NEUROFLOW_ANALYTICS_PORT = "5432"
$env:NEUROFLOW_ANALYTICS_USER = "neuroflow"
$env:NEUROFLOW_ANALYTICS_PASSWORD = "neuroflow"
$env:NEUROFLOW_ANALYTICS_DB = "neuroflow_analytics"
python run_desktop.py
```

## Full URL override

```powershell
$env:ANALYTICS_DATABASE_URL = "postgresql://user:pass@host:5432/dbname"
python run_desktop.py
```

