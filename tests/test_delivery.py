import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from finance_bot.delivery import project_root


class DeliveryTests(unittest.TestCase):
    def test_project_root_uses_workflow_override(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"FINANCE_BOT_ROOT": directory}
        ):
            self.assertEqual(project_root(), Path(directory).resolve())


if __name__ == "__main__":
    unittest.main()
