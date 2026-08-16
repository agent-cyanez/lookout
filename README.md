# Lookout

A lightweight Docker container health watchdog that sends [ntfy](https://ntfy.sh) notifications when containers start, stop, or change health status.

**Zero dependencies.** Single Python file. Talks to the Docker socket directly using only the standard library.

## Quick Start

```bash
# Run directly
NTFY_URL=http://localhost:8080 NTFY_TOPIC=docker python3 lookout.py

# Or with Docker
docker run -d \
  --name lookout \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -e NTFY_URL=http://ntfy:8080 \
  -e NTFY_TOPIC=docker \
  ghcr.io/agent-cyanez/lookout
```

## What It Does

Lookout polls the Docker daemon and detects:
- **Container stopped** — a running container disappears (high priority alert)
- **Container started** — a new container appears
- **Health changed** — a container transitions between healthy/unhealthy (unhealthy = high priority)

Notifications go to any [ntfy](https://ntfy.sh) server — self-hosted or ntfy.sh.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DOCKER_HOST` | `/var/run/docker.sock` | Path to Docker socket |
| `NTFY_URL` | `http://127.0.0.1:8888` | ntfy server URL |
| `NTFY_TOPIC` | `lookout` | ntfy topic to publish to |
| `POLL_INTERVAL` | `30` | Seconds between checks |
| `WATCH_FILTER` | _(empty = all)_ | Comma-separated container names to watch |
| `WATCH_STOPPED` | `false` | Include stopped containers in monitoring |
| `NOTIFY_ON_START` | `false` | Send a summary notification on startup |

## Docker Compose

```yaml
services:
  lookout:
    image: ghcr.io/agent-cyanez/lookout
    container_name: lookout
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - NTFY_URL=http://ntfy:8080
      - NTFY_TOPIC=docker
```

## Resource Usage

- **Memory:** ~8 MB
- **CPU:** Negligible (one HTTP request per poll)
- **Image size:** ~25 MB (python:alpine)
- **Dependencies:** None (stdlib only)

## License

MIT
