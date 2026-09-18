from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from graders.lab1.static_achievements import detect


class Lab1StaticAchievementsTests(unittest.TestCase):
    def test_detects_explicit_algorithmic_choices(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "solution.py"
            source.write_text(
                "def has_unique_characters(data):\n return len(set(data.value)) == len(data.value)\n"
                "def prime_factorization(data):\n d=2\n\n while d*d <= data.value:\n  d += 1\n return ''\n"
                "def multiplicative_persistence(data):\n return 0 if data.value < 10 else multiplicative_persistence(data)\n"
                "def sum_prod(data):\n return np.einsum('pij,pjk->ik', data.matrices, data.vectors)\n"
                ,
                encoding="utf-8",
            )
            names = ["has_unique_characters", "prime_factorization", "multiplicative_persistence", "sum_prod"]
            selected = {name: (Path("solution.py"), 1) for name in names}
            identifiers = {item["achievement_id"] for item in detect(root, selected)}
            self.assertTrue({
                "assignment/lab-1/unexpected-set", "assignment/lab-1/work-smarter",
                "assignment/lab-1/understand-recursion", "assignment/lab-1/einstein",
            }.issubset(identifiers))


if __name__ == "__main__":
    unittest.main()
