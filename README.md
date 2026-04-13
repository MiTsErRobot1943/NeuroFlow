# NeuroFlow

NeuroFlow supports both:

- **Web mode**: Flask/Gunicorn for browser or Docker deployment.
- **Desktop mode**: embedded desktop app with `pywebview` on top of the same Flask backend.

The app now uses an app-factory pattern (`src/app_factory.py`) so startup initialization is explicit per runtime mode.

## Project Layout

- `src/` application code
- `src/assets/templates/` HTML/CSS/JS templates and static files
- `src/assets/schema.sql` SQLite schema
- `scripts/runtime/` canonical Python runtime entrypoints
- `docs/` project documentation and setup notes

Root-level launchers like `run_web.py` and `run_desktop.py` are kept as compatibility wrappers.

## Runtime Modes

- `dev`: local development defaults.
- `web`: container/server deployment defaults.
- `desktop`: local desktop app with per-user app data storage.

Mode selection is controlled by `NEUROFLOW_MODE` (or launcher scripts).

## Local Setup (PowerShell)

Run these from the repo root (`NeuroFlow`):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python db_setup.py --create-user your_username
```

## Run Locally

Web mode (dev defaults):

```powershell
python run_web.py --mode dev
```

Desktop mode:

```powershell
python run_desktop.py
```

Desktop backend smoke check (no GUI window):

```powershell
python run_desktop.py --no-window
```

## Smoke Tests

```powershell
python smoke_auth_test.py
python smoke_desktop_startup_test.py
```

Optional explicit-host runs:

```powershell
python run_web.py --mode dev --host 127.0.0.1 --port 5000
python run_desktop.py --host 127.0.0.1
```

## Docker Compose

This project runs with Docker Compose using Flask, Ollama (`mistral`), Nginx, local SQLite auth storage, and a separate PostgreSQL + pgvector analytics database.

```powershell
docker compose up --build
```

After startup:

- App URL: `http://localhost`
- Ollama endpoint in-network: `http://ollama:11434`
- SQLite DB file inside containers: `/data/neuroflow.db`
- Analytics DB endpoint in-network: `analytics-db:5432`

Stop services:

```powershell
docker compose down
```

Remove volumes too:

```powershell
docker compose down -v
```

## Windows Packaging (PyInstaller)

Use the helper script to build a desktop executable:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

Default build excludes the optional Ollama client to keep desktop packaging lightweight.

To bundle the Ollama Python client in the executable build:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1 -IncludeOllama
```

Build output is written to `dist\NeuroFlowDesktop\`.

The packaged desktop app now resolves bundled `src/assets/templates/` and `src/assets/schema.sql` assets at runtime,
and stores user data in `%APPDATA%\NeuroFlow\neuroflow.db` by default (unless `NEUROFLOW_DB_PATH` is set).

### AI Privacy Note

- Using a local Ollama runtime is the most private AI mode because prompts stay on your machine.
- If you point the app to a remote model endpoint, prompts may be processed outside your device.
- Web search is only performed after explicit approval in chat.

### Local AI Hardware Preflight

Desktop startup now runs a local-model readiness check and logs a warning when the machine is below the recommended baseline:

- CPU: 4+ logical cores
- RAM: 8+ GB
- Free disk: 10+ GB

You can disable this check (not recommended) with:

```powershell
$env:NEUROFLOW_CHECK_LOCAL_AI_HARDWARE = "0"
python run_desktop.py
```

### Voice Input and Output

The dashboard includes browser-native speech-to-text and text-to-speech controls for the task form and chatbot panels.

- Click **🎤 Dictate** on the task title field to fill in a task by voice.
- Click **🎤 Speak** in a chatbot panel to dictate a message and send it automatically.
- When a task or chatbot message is created from voice input, NeuroFlow can speak back the result.

Voice support depends on the browser/webview exposing the Web Speech APIs. If those APIs are unavailable, the buttons are disabled and typed input still works.

## Deadline Planning

- Manual task creation supports an optional calendar deadline (`due_date`).
- Predefined project templates support an optional project target deadline and automatically spread task due dates toward that target.
- Custom project configuration also accepts a target deadline and applies planned due dates to generated tasks.

