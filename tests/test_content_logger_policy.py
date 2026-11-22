import ast
import unittest
from pathlib import Path


class ContentLoggerPolicyTests(unittest.TestCase):
    def test_content_store_uses_only_astrbot_api_logger(self):
        module_path = Path(__file__).resolve().parents[1] / "infra" / "content.py"
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        logger_imports = [
            (node.module, alias.name, alias.asname)
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
            if alias.name == "logger"
        ]
        logging_imports = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
            if alias.name == "logging" or alias.name.startswith("logging.")
        ]
        self.assertEqual(logger_imports, [("astrbot.api", "logger", None)])
        self.assertEqual(logging_imports, [])


if __name__ == "__main__":
    unittest.main()
