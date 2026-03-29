# Analytics Database Access for Desktop Version

## Overview

The desktop version of NeuroFlow now has access to the analytics database. This document explains how it works and how to configure it.

## What Changed

### 1. **Configuration Layer (`src/config.py`)**
   - Added `analytics_database_url` field to `RuntimeConfig` dataclass
   - Updated `load_runtime_config()` to read and return `ANALYTICS_DATABASE_URL` from environment variables

### 2. **Application Factory (`src/app_factory.py`)**
   - Updated Flask config initialization to use `analytics_database_url` from runtime config
   - Changed `initialize_analytics_database()` call to use the config value instead of environment variable directly

### 3. **Desktop Launcher (`src/desktop_launcher.py`)**
   - Added `_configure_analytics_for_desktop()` function that:
     - Sets up a PostgreSQL connection string for the local analytics database
     - Supports configurable host, port, credentials, and database name via environment variables
     - Uses sensible defaults that match the Docker Compose configuration
   - Modified `start_desktop_backend()` to call analytics configuration before creating the Flask app

## Configuration

### Default Configuration

By default, the desktop version will attempt to connect to:
- **Host:** `localhost`
- **Port:** `5432`
- **User:** `neuroflow`
- **Password:** `neuroflow`
- **Database:** `neuroflow_analytics`

This matches the analytics database in the Docker Compose setup.

### Custom Configuration

You can override any of these settings using environment variables before running the desktop app:

```powershell
# Set custom credentials
$env:NEUROFLOW_ANALYTICS_USER = "myuser"
$env:NEUROFLOW_ANALYTICS_PASSWORD = "mypassword"
$env:NEUROFLOW_ANALYTICS_HOST = "192.168.1.100"
$env:NEUROFLOW_ANALYTICS_PORT = "5433"
$env:NEUROFLOW_ANALYTICS_DB = "custom_analytics"

# Or set the full connection string directly (overrides all above)
$env:ANALYTICS_DATABASE_URL = "postgresql://user:password@host:5432/dbname"

# Then run the desktop app
python run_desktop.py
```

### Disabling Analytics

If you want to run the desktop version without analytics, either:
1. Don't have PostgreSQL running on the expected host/port
2. Set an invalid `ANALYTICS_DATABASE_URL`

The application will log a warning but continue to work normally with analytics disabled.

## How It Works

1. When the desktop backend starts, `_configure_analytics_for_desktop()` is called
2. If `ANALYTICS_DATABASE_URL` is not already set, it builds one from individual environment variables
3. The URL is set in the process environment before creating the Flask app
4. The Flask app reads this URL during initialization via `load_runtime_config()`
5. The analytics database schema is created if it doesn't exist
6. Events are tracked to the database as the app runs

## Usage Examples

### Scenario 1: Local PostgreSQL (default)
```powershell
# Assumes PostgreSQL is running on localhost:5432 with default credentials
python run_desktop.py
```

### Scenario 2: Remote PostgreSQL Server
```powershell
$env:NEUROFLOW_ANALYTICS_HOST = "analytics.company.com"
$env:NEUROFLOW_ANALYTICS_USER = "prod_user"
$env:NEUROFLOW_ANALYTICS_PASSWORD = "prod_password"
python run_desktop.py
```

### Scenario 3: Docker-based Analytics (from Docker Desktop)
```powershell
# Connect to a PostgreSQL running in Docker on the local machine
$env:NEUROFLOW_ANALYTICS_HOST = "host.docker.internal"
python run_desktop.py
```

### Scenario 4: Analytics Disabled
```powershell
# Force analytics to be disabled
$env:ANALYTICS_DATABASE_URL = "postgresql://invalid:invalid@127.0.0.1:9999/fake"
python run_desktop.py
```

## Database Requirements

The desktop analytics feature requires:
- **PostgreSQL 12+** (tested with pgvector/pgvector:pg16)
- **psycopg2-binary** Python package (already in requirements.txt)
- The `analytics_events` table (created automatically on first run)

## Graceful Fallback

If the PostgreSQL database is unavailable or misconfigured:
- The application will log a warning during startup
- Analytics tracking will be silently skipped
- The application will continue to function normally
- All other features remain available

## Checking Logs

To verify analytics configuration is working, check the startup logs:

```
Desktop analytics configured: localhost:5432/neuroflow_analytics
```

If analytics is disabled, you'll see:

```
Analytics DB initialization skipped: [error details]
```

## Integration with Docker Compose

When running the full Docker stack via `docker-compose up`, the Flask web service already has analytics enabled. The desktop version now brings parity to the local development experience.

Both modes now use the same analytics database and event taxonomy, allowing you to:
- Track user actions across web and desktop
- Build unified dashboards and reports
- Test analytics features in both environments

