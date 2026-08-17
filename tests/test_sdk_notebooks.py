from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest


NOTEBOOK_DIRECTORY = Path(__file__).parents[1] / "examples" / "notebooks"
REQUIRED_HEADINGS = (
    "## Goal",
    "## Setup",
    "## Steps",
    "## Checks",
    "## Next steps",
)


class SDKNotebookTests(unittest.TestCase):
    def test_two_notebooks_are_valid_and_code_cells_compile(self) -> None:
        paths = sorted(NOTEBOOK_DIRECTORY.glob("*.ipynb"))
        self.assertEqual(
            [path.name for path in paths],
            ["01_owner_encrypt.ipynb", "02_compute_encrypted.ipynb"],
        )
        for path in paths:
            with self.subTest(path=path.name):
                notebook = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(notebook["nbformat"], 4)
                markdown = "\n".join(
                    "".join(cell["source"])
                    for cell in notebook["cells"]
                    if cell["cell_type"] == "markdown"
                )
                for heading in REQUIRED_HEADINGS:
                    self.assertIn(heading, markdown)
                for index, cell in enumerate(notebook["cells"]):
                    if cell["cell_type"] == "code":
                        ast.parse(
                            "".join(cell["source"]),
                            filename=f"{path}:cell-{index}",
                        )

    def test_compute_notebook_uses_only_sdk_workspace_api(self) -> None:
        path = NOTEBOOK_DIRECTORY / "02_compute_encrypted.ipynb"
        notebook = json.loads(path.read_text(encoding="utf-8"))
        code = "\n".join(
            "".join(cell["source"])
            for cell in notebook["cells"]
            if cell["cell_type"] == "code"
        )
        self.assertIn("HESession.open_workspace", code)
        self.assertIn("compute.sum", code)
        self.assertIn("compute.mean", code)
        self.assertIn("compute.variance", code)
        self.assertNotIn("/v1/evaluate", code)
        self.assertNotIn("urllib", code)
        self.assertNotIn("requests", code)
        self.assertNotIn("openfhe", code)


if __name__ == "__main__":
    unittest.main()
