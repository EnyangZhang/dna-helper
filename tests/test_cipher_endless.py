import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CipherEndlessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pipeline = json.loads(
            (ROOT / "assets/resource/base/pipeline/RewardConfirm.json").read_text(
                encoding="utf-8"
            )
        )
        cls.task = json.loads(
            (ROOT / "assets/resource/tasks/CipherEndlessBoost.json").read_text(
                encoding="utf-8"
            )
        )

    def test_again_button_stops_cipher_endless_from_every_wait_phase(self) -> None:
        stop_node = self.pipeline["CipherEndlessAgainDetected"]
        self.assertEqual(stop_node["recognition"]["type"], "TemplateMatch")
        self.assertEqual(
            stop_node["recognition"]["param"]["template"],
            "RewardConfirm/expel_again.png",
        )
        self.assertEqual(stop_node["action"]["type"], "StopTask")

        for node_name in (
            "RewardConfirmEntry",
            "RewardConfirmFirstPageClick3Finalize",
            "RewardConfirmContinueChallengeClick3Finalize",
            "RewardConfirmWaitContinue",
            "RewardConfirmWaitThird",
        ):
            with self.subTest(node=node_name):
                self.assertEqual(
                    self.pipeline[node_name]["next"][0],
                    "CipherEndlessAgainDetected",
                )

    def test_expel_entry_keeps_its_existing_outside_monitor(self) -> None:
        mode = self.task["option"]["CipherMode"]
        expel = next(case for case in mode["cases"] if case["name"] == "Expel")
        self.assertEqual(
            expel["pipeline_override"]["RewardConfirmEntry"]["next"],
            ["CipherExpelEntryMonitor"],
        )


if __name__ == "__main__":
    unittest.main()
