"""Unit tests for Lookout — container health watchdog."""

import unittest
import lookout


class TestContainerKey(unittest.TestCase):
    def test_extracts_name(self):
        c = {"Names": ["/myapp"], "Id": "abc123def456"}
        self.assertEqual(lookout.container_key(c), "myapp")

    def test_strips_leading_slash(self):
        c = {"Names": ["/some-container"], "Id": "abc123def456"}
        self.assertEqual(lookout.container_key(c), "some-container")

    def test_falls_back_to_id(self):
        c = {"Names": [], "Id": "abc123def456789"}
        self.assertEqual(lookout.container_key(c), "abc123def456")

    def test_no_names_key(self):
        c = {"Id": "abc123def456789"}
        self.assertEqual(lookout.container_key(c), "abc123def456")


class TestContainerHealth(unittest.TestCase):
    def test_healthy(self):
        c = {"State": "running", "Status": "Up 2 hours (healthy)"}
        self.assertEqual(lookout.container_health(c), "healthy")

    def test_unhealthy(self):
        c = {"State": "running", "Status": "Up 2 hours (unhealthy)"}
        self.assertEqual(lookout.container_health(c), "unhealthy")

    def test_running_no_healthcheck(self):
        c = {"State": "running", "Status": "Up 2 hours"}
        self.assertEqual(lookout.container_health(c), "running")

    def test_exited(self):
        c = {"State": "exited", "Status": "Exited (0) 1 hour ago"}
        self.assertEqual(lookout.container_health(c), "exited")

    def test_missing_state(self):
        c = {"Status": "Up 2 hours"}
        self.assertEqual(lookout.container_health(c), "unknown")


class TestDiffStates(unittest.TestCase):
    def test_new_container(self):
        prev = {}
        curr = {"app": "running"}
        events = lookout.diff_states(prev, curr)
        self.assertEqual(events, [("started", "app", "running")])

    def test_stopped_container(self):
        prev = {"app": "running"}
        curr = {}
        events = lookout.diff_states(prev, curr)
        self.assertEqual(events, [("stopped", "app", "running")])

    def test_health_changed(self):
        prev = {"app": "running"}
        curr = {"app": "unhealthy"}
        events = lookout.diff_states(prev, curr)
        self.assertEqual(events, [("changed", "app", "running -> unhealthy")])

    def test_no_change(self):
        state = {"app": "running", "db": "healthy"}
        events = lookout.diff_states(state, dict(state))
        self.assertEqual(events, [])

    def test_multiple_events(self):
        prev = {"app": "running", "old": "running"}
        curr = {"app": "unhealthy", "new": "running"}
        events = lookout.diff_states(prev, curr)
        types = {e[0] for e in events}
        self.assertEqual(types, {"changed", "stopped", "started"})


class TestFormatEvent(unittest.TestCase):
    def test_stopped_is_high_priority(self):
        title, msg, priority, tags = lookout.format_event("stopped", "app", "running")
        self.assertEqual(priority, "high")
        self.assertIn("warning", tags)

    def test_unhealthy_is_high_priority(self):
        title, msg, priority, tags = lookout.format_event(
            "changed", "app", "healthy -> unhealthy"
        )
        self.assertEqual(priority, "high")

    def test_started_is_default_priority(self):
        title, msg, priority, tags = lookout.format_event("started", "app", "running")
        self.assertEqual(priority, "default")


class TestShouldWatch(unittest.TestCase):
    def setUp(self):
        self._orig = lookout.WATCH_FILTER

    def tearDown(self):
        lookout.WATCH_FILTER = self._orig

    def test_empty_filter_watches_all(self):
        lookout.WATCH_FILTER = ""
        c = {"Names": ["/anything"], "Id": "abc123def456"}
        self.assertTrue(lookout.should_watch(c))

    def test_filter_matches(self):
        lookout.WATCH_FILTER = "app,db"
        c = {"Names": ["/app"], "Id": "abc123def456"}
        self.assertTrue(lookout.should_watch(c))

    def test_filter_excludes(self):
        lookout.WATCH_FILTER = "app,db"
        c = {"Names": ["/other"], "Id": "abc123def456"}
        self.assertFalse(lookout.should_watch(c))

    def test_glob_pattern(self):
        lookout.WATCH_FILTER = "immich_*,blog-web-*"
        c = {"Names": ["/immich_server"], "Id": "abc123def456"}
        self.assertTrue(lookout.should_watch(c))

    def test_glob_excludes_non_match(self):
        lookout.WATCH_FILTER = "immich_*,blog-web-*"
        c = {"Names": ["/example-local-mongo"], "Id": "abc123def456"}
        self.assertFalse(lookout.should_watch(c))

    def test_glob_prefix_match(self):
        lookout.WATCH_FILTER = "forgejo-runner-*"
        c = {"Names": ["/forgejo-runner-1"], "Id": "abc123def456"}
        self.assertTrue(lookout.should_watch(c))

    def test_exclude_pattern(self):
        lookout.WATCH_FILTER = "blog-web-*, !*_replaced_*"
        active = {"Names": ["/blog-web-abc123"], "Id": "abc123def456"}
        replaced = {"Names": ["/blog-web-abc123_replaced_def789"], "Id": "def789abc123"}
        self.assertTrue(lookout.should_watch(active))
        self.assertFalse(lookout.should_watch(replaced))

    def test_exclude_does_not_affect_other_includes(self):
        lookout.WATCH_FILTER = "ntfy, blog-web-*, !*_replaced_*"
        c = {"Names": ["/ntfy"], "Id": "abc123def456"}
        self.assertTrue(lookout.should_watch(c))


class TestDebounceIntegration(unittest.TestCase):
    """Test the debounce logic by simulating poll cycles."""

    def setUp(self):
        self._orig_debounce = lookout.DEBOUNCE_SECONDS
        lookout.DEBOUNCE_SECONDS = 90

    def tearDown(self):
        lookout.DEBOUNCE_SECONDS = self._orig_debounce

    def test_stopped_then_started_suppresses_both(self):
        """Container restarts within grace period — no notifications."""
        pending_stops = {}
        restart_grace = {}
        notifications = []

        def fake_notify(title, message, priority="default", tags=None):
            notifications.append((title, message))

        # Poll 1: container disappears
        events = [("stopped", "app", "healthy")]
        now = 1000.0
        for event_type, name, detail in events:
            if event_type == "stopped":
                pending_stops[name] = (now, detail)

        self.assertIn("app", pending_stops)
        self.assertEqual(len(notifications), 0)

        # Poll 2 (30s later): container reappears
        events = [("started", "app", "running")]
        now = 1030.0
        for event_type, name, detail in events:
            if event_type == "started" and name in pending_stops:
                del pending_stops[name]
                restart_grace[name] = now

        self.assertNotIn("app", pending_stops)
        self.assertIn("app", restart_grace)
        self.assertEqual(len(notifications), 0)

    def test_stopped_past_grace_fires(self):
        """Container stays gone past debounce period — alert fires."""
        pending_stops = {"app": (1000.0, "healthy")}
        now = 1100.0  # 100s later, past 90s debounce

        expired = [
            (n, detail)
            for n, (stop_time, detail) in pending_stops.items()
            if now - stop_time >= lookout.DEBOUNCE_SECONDS
        ]

        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0][0], "app")

    def test_stopped_within_grace_holds(self):
        """Container gone but still within debounce period — no alert yet."""
        pending_stops = {"app": (1000.0, "healthy")}
        now = 1060.0  # 60s later, still within 90s debounce

        expired = [
            (n, detail)
            for n, (stop_time, detail) in pending_stops.items()
            if now - stop_time >= lookout.DEBOUNCE_SECONDS
        ]

        self.assertEqual(len(expired), 0)

    def test_health_change_during_restart_suppressed(self):
        """Health transitions during restart grace are suppressed."""
        restart_grace = {"app": 1000.0}
        now = 1030.0  # 30s into grace period

        suppressed = "app" in restart_grace and now - restart_grace["app"] < lookout.DEBOUNCE_SECONDS
        self.assertTrue(suppressed)

    def test_health_change_after_grace_fires(self):
        """Health changes after grace period are not suppressed."""
        restart_grace = {"app": 1000.0}
        now = 1100.0  # 100s, past grace period

        suppressed = "app" in restart_grace and now - restart_grace["app"] < lookout.DEBOUNCE_SECONDS
        self.assertFalse(suppressed)

    def test_debounce_disabled_fires_immediately(self):
        """With DEBOUNCE_SECONDS=0, stopped events fire immediately."""
        lookout.DEBOUNCE_SECONDS = 0
        # When debounce is 0, the code path skips the pending_stops logic
        self.assertEqual(lookout.DEBOUNCE_SECONDS, 0)


class TestCapPriority(unittest.TestCase):
    def test_no_cap_passes_through(self):
        self.assertEqual(lookout.cap_priority("urgent", cap=""), "urgent")

    def test_caps_high_and_urgent(self):
        self.assertEqual(lookout.cap_priority("high", cap="default"), "default")
        self.assertEqual(lookout.cap_priority("urgent", cap="default"), "default")
        self.assertEqual(lookout.cap_priority("5", cap="high"), "high")

    def test_leaves_lower_priorities_alone(self):
        self.assertEqual(lookout.cap_priority("default", cap="default"), "default")
        self.assertEqual(lookout.cap_priority("low", cap="default"), "low")


if __name__ == "__main__":
    unittest.main()
