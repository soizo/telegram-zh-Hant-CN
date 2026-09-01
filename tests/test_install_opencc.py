import unittest
from pathlib import Path


class InstallerTests(unittest.TestCase):
    def test_release_workflow_installs_official_opencc_wheel(self) -> None:
        workflow = (
            Path(__file__).parents[1] / ".github/workflows/release.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "python -m pip install --only-binary=:all: opencc==1.4.2",
            workflow,
        )
        self.assertNotIn("scripts/install_opencc.py", workflow)
        self.assertNotIn("apt-get install --yes opencc", workflow)


if __name__ == "__main__":
    unittest.main()
