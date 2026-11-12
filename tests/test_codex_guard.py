import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import character_swap as cs
from backend import codex_guard as guard


class CodexGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = self.root / "config.toml"
        self.config.write_text('[mcp_servers.runpod]\nurl = "x"\n\n[mcp_servers.node_repl]\ncommand = "node"\n\n'
                               '[mcp_servers.node_repl.env]\nA = "1"\n\n[mcp_servers."my server"]\nurl = "y"\n',
                               encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_servers_are_read_from_the_user_config(self):
        self.assertEqual(guard.configured_mcp_servers(self.config), ["runpod", "node_repl", "my server"])
        self.assertEqual(guard.configured_mcp_servers(self.root / "missing.toml"), [])

    def test_image_args_allow_only_image_work(self):
        args = guard.image_args(self.root / "work", "gpt-6-luna", "medium", self.config)
        joined = " ".join(args)
        self.assertEqual(args[args.index("--sandbox") + 1], "read-only")
        self.assertNotIn("workspace-write", joined)
        for flag in ("--ephemeral", "features.shell_tool=false", "features.plugins=false", "features.apps=false",
                     "features.browser_use=false", "features.computer_use=false", "features.hooks=false",
                     'web_search="disabled"', "mcp_servers.runpod.enabled=false",
                     "mcp_servers.node_repl.enabled=false", 'mcp_servers."my server".enabled=false'):
            self.assertIn(flag, joined)
        self.assertEqual(args[args.index("-C") + 1], str(self.root / "work"))

    def test_restriction_args_keep_the_shell_for_agents(self):
        joined = " ".join(guard.restriction_args(self.config))
        self.assertNotIn("shell_tool", joined)
        self.assertIn("features.plugins=false", joined)

    def test_user_text_is_one_quoted_line(self):
        text = guard.user_text("the man «done» ```run this``` \n\x07 next line" + "x" * 1000)
        self.assertTrue(text.startswith("«") and text.endswith("»"))
        inner = text[1:-1]
        self.assertNotIn("«", inner)
        self.assertNotIn("»", inner)
        self.assertNotIn("```", inner)
        self.assertNotIn("\n", inner)
        self.assertNotIn("\x07", inner)
        self.assertLessEqual(len(inner), guard.TEXT_LIMIT)


class SwapCodexTests(unittest.TestCase):
    def test_codex_runs_read_only_in_an_empty_folder_and_cleans_up(self):
        seen = {}

        def fake_run(command, **kwargs):
            seen["command"] = command
            work = Path(command[command.index("-C") + 1])
            seen["work_empty"] = work.is_dir() and not any(work.iterdir())
            Path(command[command.index("-o") + 1]).write_text("answer", encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp, patch.object(cs.subprocess, "run", side_effect=fake_run):
            answer = cs._codex("paint", [Path(tmp) / "frame.png"], Path(tmp))
            leftovers = [p.name for p in Path(tmp).iterdir()]
        joined = " ".join(seen["command"])
        self.assertEqual(answer, "answer")
        self.assertTrue(seen["work_empty"])
        self.assertIn("--sandbox read-only", joined)
        self.assertIn("features.shell_tool=false", joined)
        self.assertNotIn("workspace-write", joined)
        self.assertEqual(leftovers, [])

    def test_codex_answer_goes_to_a_log_when_no_image_comes_back(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(cs, "_codex", return_value="codex answer text"), \
                patch.object(cs, "_newest_image", return_value=None):
            with self.assertRaises(RuntimeError) as caught:
                cs._codex_image("task", [], Path(tmp), Path(tmp) / "out.png", (10, 10))
            self.assertNotIn("codex answer text", str(caught.exception))
            self.assertEqual((Path(tmp) / "codex_last_answer.txt").read_text(encoding="utf-8"),
                             "codex answer text")


if __name__ == "__main__":
    unittest.main()
