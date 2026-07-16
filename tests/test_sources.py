import unittest

import sources


class FakeHerdrSource(sources.HerdrSource):
    def _json(self, args, timeout=15):
        if args[:2] == ["pane", "list"]:
            return {
                "panes": [
                    {
                        "pane_id": "w1:p1",
                        "workspace_id": "w1",
                        "cwd": "/projects/api",
                        "focused": True,
                        "agent": "claude",
                        "agent_status": "idle",
                    },
                    {
                        "pane_id": "w1:p2",
                        "workspace_id": "w1",
                        "cwd": "/projects/api",
                        "focused": False,
                        "agent": "codex",
                        "agent_status": "working",
                    },
                    {
                        "pane_id": "w1:p3",
                        "workspace_id": "w1",
                        "cwd": "/projects/api",
                        "focused": False,
                        "agent_status": "unknown",
                    },
                ]
            }
        if args[:2] == ["workspace", "list"]:
            return {
                "workspaces": [
                    {
                        "workspace_id": "w1",
                        "number": 1,
                        "label": "api",
                        "focused": True,
                    }
                ]
            }
        raise AssertionError(f"unexpected Herdr command: {args}")


class HerdrSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = FakeHerdrSource()

    def test_all_panes_include_agents_and_plain_terminals(self):
        panes = self.source.list_panes(claude_only=False)

        self.assertEqual([p["pane_id"] for p in panes], ["w1:p1", "w1:p2", "w1:p3"])
        self.assertEqual([p["agent"] for p in panes], ["claude", "codex", ""])

    def test_claude_filter_remains_available_for_legacy_clients(self):
        panes = self.source.list_panes(claude_only=True)

        self.assertEqual([p["pane_id"] for p in panes], ["w1:p1"])

    def test_native_status_applies_to_every_recognized_agent(self):
        panes = self.source.list_panes(claude_only=False)

        self.assertEqual(self.source.session_status(panes[0]), "idle")
        self.assertEqual(self.source.session_status(panes[1]), "working")
        self.assertEqual(self.source.session_status(panes[2]), "other")

    def test_non_claude_agent_uses_agent_name_as_label(self):
        codex = self.source.list_panes(claude_only=False)[1]

        self.assertEqual(self.source.session_label(codex), "codex")


if __name__ == "__main__":
    unittest.main()
