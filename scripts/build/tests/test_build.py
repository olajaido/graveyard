"""Tests of the build scripts. Standard library only: python3 -m unittest discover scripts/build/tests"""

import hashlib
import io
import json
import stat
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_lambda_zip  # noqa: E402
import build_syft_layer  # noqa: E402
from zipping import FILE_MODE, write_zip  # noqa: E402


def tarball(member: str = "syft", content: bytes = b"\x7fELF-fake") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(member)
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


class BuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_zip_is_reproducible_sorted_and_fixed_time(self) -> None:
        entries = {"b.py": (b"2", FILE_MODE), "a/x.py": (b"1", FILE_MODE)}
        first = write_zip(entries, self.tmp / "one.zip")
        second = write_zip(dict(reversed(list(entries.items()))), self.tmp / "two" / "two.zip")
        self.assertEqual(first, second)
        with zipfile.ZipFile(self.tmp / "one.zip") as archive:
            self.assertEqual(archive.namelist(), ["a/x.py", "b.py"])
            self.assertEqual({i.date_time for i in archive.infolist()}, {(2026, 1, 1, 0, 0, 0)})

    def test_code_files_skip_tests_fakes_and_pycache(self) -> None:
        for name in ("core/a.py", "core/tests/t.py", "scan/fakes.py", "scan/store.py",
                     "core/__pycache__/a.pyc", "core/w.yaml"):
            path = self.tmp / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x")
        names = [n for n, _ in build_lambda_zip.code_files(self.tmp)]
        self.assertEqual(names, ["core/a.py", "core/w.yaml", "scan/store.py"])

    def test_layer_builds_with_an_executable_binary(self) -> None:
        data = tarball()
        digest = hashlib.sha256(data).hexdigest()
        one = build_syft_layer.build_layer(data, digest, self.tmp / "a.zip")
        two = build_syft_layer.build_layer(data, digest, self.tmp / "b.zip")
        self.assertEqual(one, two)
        with zipfile.ZipFile(self.tmp / "a.zip") as archive:
            info = archive.getinfo("bin/syft")
            self.assertEqual(stat.S_IMODE(info.external_attr >> 16), 0o755)
            self.assertEqual(archive.read("bin/syft"), b"\x7fELF-fake")

    def test_a_wrong_hash_fails_and_writes_nothing(self) -> None:
        with self.assertRaises(build_syft_layer.PinMismatch):
            build_syft_layer.build_layer(tarball(), "0" * 64, self.tmp / "x.zip")
        self.assertFalse((self.tmp / "x.zip").exists())

    def test_the_pin_file_is_well_formed(self) -> None:
        pin = build_syft_layer.load_pin()
        self.assertEqual(pin["version"], "1.56.0")
        self.assertEqual(len(pin["sha256"]), 64)
        self.assertTrue(pin["url"].startswith("https://github.com/anchore/syft/releases/download/v1.56.0/"))
        self.assertNotIn("latest", json.dumps(pin).lower())

    def test_a_pin_with_another_host_is_refused(self) -> None:
        bad = self.tmp / "pin.json"
        bad.write_text(json.dumps({"version": "1", "url": "https://evil.example/syft.tar.gz", "sha256": "0" * 64}))
        with self.assertRaises(ValueError):
            build_syft_layer.load_pin(bad)


if __name__ == "__main__":
    unittest.main()
