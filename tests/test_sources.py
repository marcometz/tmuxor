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
                        "tab_id": "w1:t2",
                        "cwd": "/projects/api",
                        "focused": True,
                        "agent": "claude",
                        "agent_status": "idle",
                    },
                    {
                        "pane_id": "w1:p2",
                        "workspace_id": "w1",
                        "tab_id": "w1:t1",
                        "cwd": "/projects/api",
                        "focused": False,
                        "agent": "codex",
                        "agent_status": "working",
                    },
                    {
                        "pane_id": "w1:p3",
                        "workspace_id": "w1",
                        "tab_id": "w1:t1",
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
        if args[:2] == ["tab", "list"]:
            return {
                "tabs": [
                    {
                        "tab_id": "w1:t1",
                        "workspace_id": "w1",
                        "number": 1,
                        "label": "shells",
                        "pane_count": 2,
                        "focused": False,
                    },
                    {
                        "tab_id": "w1:t2",
                        "workspace_id": "w1",
                        "number": 2,
                        "label": "coding-session",
                        "pane_count": 1,
                        "focused": True,
                    },
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

    def test_space_tab_and_pane_hierarchy_is_preserved(self):
        panes = self.source.list_panes(claude_only=False)

        self.assertEqual(panes[0]["window_name"], "api")
        self.assertEqual(panes[0]["tab_id"], "w1:t2")
        self.assertEqual(panes[0]["tab_name"], "coding-session")
        self.assertEqual(panes[0]["tab_index"], 2)
        self.assertEqual(panes[1]["tab_name"], "shells")
        self.assertEqual(panes[1]["pane_index"], 0)
        self.assertEqual(panes[2]["pane_index"], 1)

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

    def test_herdr_uses_live_terminal_as_authoritative_view(self):
        self.assertTrue(self.source.live_terminal_view)


if __name__ == "__main__":
    unittest.main()
