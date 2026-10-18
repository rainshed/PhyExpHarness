import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from src.exporting.validate import relocate


class ExportValidationTests(unittest.TestCase):
    def test_changed_archive_is_rejected_before_installation(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);archive=root/'harness.zip';archive.write_bytes(b'changed')
            with patch('src.exporting.validate.subprocess.run') as command:
                with self.assertRaisesRegex(ValueError,'archive changed'):
                    relocate({'archive':str(archive),'archiveSha256':'0'*64},root/'relocated')
                command.assert_not_called()

    def test_traversal_and_symlinks_are_rejected_before_extraction(self):
        for name,mode in [('harness/../../outside',0),('/outside',0),('harness/link',0o120777)]:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as root:
                root=Path(root);archive=root/'harness.zip'
                with zipfile.ZipFile(archive,'w') as z:
                    info=zipfile.ZipInfo(name);info.external_attr=mode<<16;z.writestr(info,'/outside')
                record={'archive':str(archive),'archiveSha256':hashlib.sha256(archive.read_bytes()).hexdigest()}
                with patch('src.exporting.validate.subprocess.run') as command:
                    with self.assertRaisesRegex(ValueError,'Unsafe archive'):
                        relocate(record,root/'relocated')
                    command.assert_not_called()
                self.assertEqual(list((root/'relocated').iterdir()),[])
