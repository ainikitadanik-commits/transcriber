import plistlib
import re
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_product_versions_are_synchronized(self):
        with (ROOT / "pyproject.toml").open("rb") as pyproject_file:
            version = tomllib.load(pyproject_file)["project"]["version"]

        with (ROOT / "packaging/app/Info.plist").open("rb") as plist_file:
            info = plistlib.load(plist_file)

        package_init = (ROOT / "src/transcriber/__init__.py").read_text()
        build_script = (ROOT / "scripts/build_app_bundle.sh").read_text()
        component_ledger = (
            ROOT / "packaging/Лицензии/Ведомость компонентов.md"
        ).read_text()
        changelog = (ROOT / "CHANGELOG.md").read_text()

        package_version = re.search(
            r'^__version__ = "([^"]+)"$',
            package_init,
            re.MULTILINE,
        )
        self.assertIsNotNone(package_version)
        self.assertEqual(package_version.group(1), version)
        self.assertEqual(info["CFBundleShortVersionString"], version)
        self.assertIn(f'VERSION="{version}"', build_script)
        self.assertIn(f"Версия поставки: {version}.", component_ledger)
        self.assertIn(f"## {version} ", changelog)

    def test_app_has_stable_identity_and_privacy_descriptions(self):
        with (ROOT / "packaging/app/Info.plist").open("rb") as plist_file:
            info = plistlib.load(plist_file)

        self.assertEqual(
            info["CFBundleIdentifier"],
            "com.ainikitadanik.transcriber",
        )
        self.assertEqual(info["CFBundleExecutable"], "Transcriber")
        self.assertEqual(info["CFBundleShortVersionString"], "0.2.0")
        self.assertIn("локальной транскрибации", info["NSMicrophoneUsageDescription"])
        self.assertIn("локальной транскрибации", info["NSAudioCaptureUsageDescription"])

    def test_audio_input_entitlement_is_enabled(self):
        with (
            ROOT / "packaging/app/Transcriber.entitlements"
        ).open("rb") as plist_file:
            entitlements = plistlib.load(plist_file)

        self.assertTrue(entitlements["com.apple.security.device.audio-input"])

    def test_product_build_uses_lgpl_ffmpeg(self):
        build_script = (ROOT / "scripts/build_app_bundle.sh").read_text()
        ffmpeg_script = (ROOT / "scripts/build_ffmpeg_lgpl.sh").read_text()

        self.assertIn("build_ffmpeg_lgpl.sh", build_script)
        self.assertNotIn("imageio_ffmpeg", build_script)
        self.assertIn("--disable-network", ffmpeg_script)
        self.assertIn("--disable-everything", ffmpeg_script)
        self.assertIn("--enable-protocol=file,pipe", ffmpeg_script)
        self.assertIn("--enable-muxer=wav,pcm_s16le", ffmpeg_script)
        configure_section = ffmpeg_script.split("/usr/bin/make", 1)[0]
        self.assertNotIn("--enable-gpl", configure_section)

    def test_component_ledger_mentions_full_license_collection(self):
        ledger = (ROOT / "packaging/Лицензии/Ведомость компонентов.md").read_text()

        self.assertIn("FFmpeg", ledger)
        self.assertIn("LGPL-2.1-or-later", ledger)
        self.assertIn("Python packages", ledger)


if __name__ == "__main__":
    unittest.main()
