# NeuroFlow Docker Setup

This project runs with Docker Compose using Flask, Ollama (with `mistral`), Nginx, and a shared SQLite volume.

## Services

- `nginx`: Public web server exposed on port `80`
- `flask`: Python app served by Gunicorn
- `ollama`: Local LLM runtime
- `ollama-pull`: One-time job that pulls the `mistral` model
- `sqlite`: Utility container with shared database volume

All services run on the same Docker network (`neuroflow_net`).

## Quick Start

```bash
docker compose up --build
```

After startup:

- App URL: `http://localhost`
- Ollama endpoint in the network: `http://ollama:11434`
- SQLite DB file location inside containers: `/data/neuroflow.db`

## Local Auth Database Setup

The login system uses SQLite with parameterized SQL queries (`?` placeholders) to prevent SQL injection, and Jinja auto-escaping + CSP headers to reduce XSS risk.

Initialize the schema and create your first user:

```bash
python db_setup.py --create-user your_username
```

Then start the app and log in at `/login`.

## Stop

```bash
docker compose down
```

To remove volumes too:

```bash
docker compose down -v
```

