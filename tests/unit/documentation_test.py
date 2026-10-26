import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('check_docs', Path(__file__).resolve().parents[2] / 'scripts/check-docs.py')
docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(docs)


class DocumentationTests(unittest.TestCase):
    def run_check(self, pages):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in pages.items():
                file = root / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(content)
            return docs.check(root, [Path(p) for p in pages])

    def test_moved_page_and_anchor_fail_independently(self):
        errors = self.run_check({'docs/README.md': '[old](old.md)\n[new](new.md#gone)', 'docs/new.md': '# Current'})
        self.assertEqual(len(errors), 2)
        self.assertIn('missing or outside', errors[0])
        self.assertIn('missing heading', errors[1])

    def test_unicode_duplicate_headings_and_escaped_paths(self):
        self.assertEqual(self.run_check({'docs/README.md': '[x](guide%20one.md#当前规则)\n[y](<guide one.md#当前规则-1>)',
                                       'docs/guide one.md': '# 当前：规则\n# 当前：规则'}), [])

    def test_examples_and_external_urls_are_not_local_links(self):
        self.assertEqual(self.run_check({'docs/README.md': '# Guide\n```md\n[example](absent.md)\n```\n'
                                        '`[inline](absent.md)`\n<!-- [hidden](absent.md) -->\n[web](https://example.org/no.md#x)'}), [])

    def test_archive_is_not_a_current_rule_source(self):
        errors = self.run_check({'docs/README.md': '[old](archive/old.md)', 'docs/archive/old.md': '# Historical'})
        self.assertEqual(len(errors), 1)
        self.assertIn('archived page', errors[0])

    def test_archive_index_does_not_make_current_pages_discoverable(self):
        errors = self.run_check({'docs/README.md': '[history](archive/README.md)',
                                'docs/archive/README.md': '[current](../lost.md)', 'docs/lost.md': '# Lost'})
        self.assertEqual(len(errors), 1)
        self.assertIn('unreachable', errors[0])

    def test_fragments_references_and_repository_escape(self):
        errors = self.run_check({'docs/README.md': '# Here\n[self](#here)\n[ref]: #here\n[bad](../../outside.md)'})
        self.assertEqual(len(errors), 1)
        self.assertIn('outside repository', errors[0])
