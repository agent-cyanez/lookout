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


if __name__ == "__main__":
    unittest.main()
