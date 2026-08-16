#!/usr/bin/env python3
"""Lookout — lightweight Docker container health watchdog with ntfy alerts."""

import fnmatch
import http.client
import json
import os
import signal
import socket
import sys
import time
import urllib.parse
import urllib.request


DOCKER_SOCKET = os.environ.get("DOCKER_HOST", "/var/run/docker.sock")
NTFY_URL = os.environ.get("NTFY_URL", "http://127.0.0.1:8888")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "lookout")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
WATCH_FILTER = os.environ.get("WATCH_FILTER", "")
WATCH_STOPPED = os.environ.get("WATCH_STOPPED", "false").lower() == "true"
NOTIFY_ON_START = os.environ.get("NOTIFY_ON_START", "false").lower() == "true"


class DockerClient:
    def __init__(self, socket_path):
        self._socket_path = socket_path

    def _request(self, method, path):
        conn = http.client.HTTPConnection("localhost")
        conn.connect = lambda: setattr(
            conn, "sock", self._make_socket()
        ) or None
        conn.sock = self._make_socket()
        conn.request(method, path)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        if resp.status != 200:
            raise RuntimeError(f"Docker API {resp.status}: {data.decode()[:200]}")
        return json.loads(data)

    def _make_socket(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self._socket_path)
        return sock

    def containers(self, all_containers=False):
        path = "/containers/json"
        if all_containers:
            path += "?all=true"
        return self._request("GET", path)


def notify(title, message, priority="default", tags=None):
    url = f"{NTFY_URL}/{NTFY_TOPIC}"
    headers = {
        "Title": title,
        "Priority": priority,
    }
    if tags:
        headers["Tags"] = ",".join(tags)
    req = urllib.request.Request(
        url,
        data=message.encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[ntfy error] {e}", file=sys.stderr)
        return False


def container_key(c):
    name = c["Names"][0].lstrip("/") if c.get("Names") else c["Id"][:12]
    return name


def container_health(c):
    state = c.get("State", "unknown")
    status = c.get("Status", "")
    if "(healthy)" in status:
        return "healthy"
    if "(unhealthy)" in status:
        return "unhealthy"
    return state


def should_watch(c):
    if not WATCH_FILTER:
        return True
    name = container_key(c)
    filters = [f.strip() for f in WATCH_FILTER.split(",")]
    return any(fnmatch.fnmatch(name, f) for f in filters)


def diff_states(prev, curr):
    events = []
    prev_keys = set(prev.keys())
    curr_keys = set(curr.keys())

    for name in curr_keys - prev_keys:
        events.append(("started", name, curr[name]))

    for name in prev_keys - curr_keys:
        events.append(("stopped", name, prev[name]))

    for name in prev_keys & curr_keys:
        old_health = prev[name]
        new_health = curr[name]
        if old_health != new_health:
            events.append(("changed", name, f"{old_health} -> {new_health}"))

    return events


def format_event(event_type, name, detail):
    if event_type == "started":
        return (
            f"Container started: {name}",
            f"{name} is now running ({detail})",
            "default",
            ["whale"],
        )
    elif event_type == "stopped":
        return (
            f"Container stopped: {name}",
            f"{name} is no longer running (was {detail})",
            "high",
            ["warning"],
        )
    elif event_type == "changed":
        priority = "high" if "unhealthy" in detail else "default"
        tags = ["red_circle"] if "unhealthy" in detail else ["green_circle"]
        return (
            f"Container health changed: {name}",
            f"{name}: {detail}",
            priority,
            tags,
        )
    return (name, str(detail), "default", [])


def snapshot(docker):
    containers = docker.containers(all_containers=WATCH_STOPPED)
    state = {}
    for c in containers:
        if should_watch(c):
            name = container_key(c)
            state[name] = container_health(c)
    return state


def main():
    print(f"Lookout starting — polling every {POLL_INTERVAL}s")
    print(f"  Docker: {DOCKER_SOCKET}")
    print(f"  ntfy:   {NTFY_URL}/{NTFY_TOPIC}")
    if WATCH_FILTER:
        print(f"  Filter: {WATCH_FILTER}")

    docker = DockerClient(DOCKER_SOCKET)

    prev_state = snapshot(docker)
    print(f"  Watching {len(prev_state)} containers")

    if NOTIFY_ON_START:
        names = ", ".join(sorted(prev_state.keys()))
        notify(
            "Lookout started",
            f"Watching {len(prev_state)} containers: {names}",
            tags=["eyes"],
        )

    running = True

    def handle_signal(signum, frame):
        nonlocal running
        print(f"\nReceived signal {signum}, shutting down")
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    while running:
        time.sleep(POLL_INTERVAL)
        if not running:
            break

        try:
            curr_state = snapshot(docker)
        except Exception as e:
            print(f"[error] Docker query failed: {e}", file=sys.stderr)
            notify(
                "Lookout error",
                f"Failed to query Docker: {e}",
                priority="high",
                tags=["warning"],
            )
            continue

        events = diff_states(prev_state, curr_state)
        for event_type, name, detail in events:
            title, message, priority, tags = format_event(event_type, name, detail)
            print(f"[event] {title}: {message}")
            notify(title, message, priority=priority, tags=tags)

        prev_state = curr_state


if __name__ == "__main__":
    main()
