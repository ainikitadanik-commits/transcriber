import plistlib
import re
import subprocess
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
        self.assertIn(
            "--enable-filter=aresample,aformat,pan,ebur128,highpass,loudnorm",
            ffmpeg_script,
        )
        self.assertIn("--enable-muxer=wav,pcm_s16le,null", ffmpeg_script)
        self.assertIn("audit_ffmpeg.sh", ffmpeg_script)
        self.assertIn("audit_macho.sh", ffmpeg_script)
        self.assertIn("MACOSX_DEPLOYMENT_TARGET", ffmpeg_script)
        configure_section = ffmpeg_script.split("/usr/bin/make", 1)[0]
        self.assertNotIn("--enable-gpl", configure_section)

    def test_component_ledger_mentions_full_license_collection(self):
        ledger = (ROOT / "packaging/Лицензии/Ведомость компонентов.md").read_text()

        self.assertIn("FFmpeg", ledger)
        self.assertIn("LGPL-2.1-or-later", ledger)
        self.assertIn("Python packages", ledger)
        self.assertIn("PYTHON-PACKAGE-INVENTORY.tsv", ledger)

        docx_license = (
            ROOT / "packaging/Лицензии/Python packages/python-docx/LICENSE"
        ).read_text()
        transformers_license = (
            ROOT / "packaging/Лицензии/Python packages/transformers/LICENSE"
        ).read_text()
        self.assertIn("MIT License", docx_license)
        self.assertIn("Apache License", transformers_license)
        self.assertIn("Version 2.0", transformers_license)

    def test_product_build_runs_fail_fast_release_audits(self):
        build_script = (ROOT / "scripts/build_app_bundle.sh").read_text()

        self.assertIn('RELEASE_BUILD:-0', build_script)
        self.assertIn("Developer ID Application", build_script)
        self.assertIn("audit_ffmpeg.sh", build_script)
        self.assertIn("audit_licenses.sh", build_script)
        self.assertIn("audit_macho.sh", build_script)
        self.assertIn("MACHO-INVENTORY.tsv", build_script)
        self.assertIn("sign_app_bundle.sh", build_script)
        self.assertIn("audit_signatures.sh", build_script)
        self.assertIn("--copy-metadata python-docx", build_script)
        self.assertIn("--copy-metadata transformers", build_script)
        self.assertIn("requirements-release.lock", build_script)
        self.assertIn("audit_release_dependencies.sh", build_script)
        self.assertIn("prepare_release_environment.sh", build_script)
        self.assertIn("DEPENDENCY-INVENTORY.txt", build_script)
        self.assertNotIn('codesign "${SIGN_ARGS[@]}" --deep', build_script)

    def test_release_lock_is_exact_and_excludes_local_editable_repo(self):
        lock = (ROOT / "packaging/requirements-release.lock").read_text()
        requirements = [
            line
            for line in lock.splitlines()
            if line and not line.startswith("#")
        ]

        self.assertNotIn("-e ", lock)
        self.assertNotIn("file://", lock)
        self.assertNotIn("local-gigaam-transcriber", lock)
        self.assertIn("# python-version: 3.12.10", lock)
        self.assertIn("Flask==3.1.3", requirements)
        self.assertIn("python-docx==1.2.0", requirements)
        self.assertIn("transformers==5.13.1", requirements)
        self.assertIn("pyinstaller==6.15.0", requirements)
        self.assertIn(
            "gigaam @ git+https://github.com/salute-developers/GigaAM.git"
            "@559d88d6b72541412743929f633a6ae7c9950b85",
            requirements,
        )

        exact_pin = re.compile(r"^[A-Za-z0-9._-]+==\S+$")
        vcs_pin = re.compile(
            r"^[A-Za-z0-9._-]+ @ git\+https://.+@[0-9a-f]{40}$"
        )
        for requirement in requirements:
            self.assertTrue(
                exact_pin.fullmatch(requirement)
                or vcs_pin.fullmatch(requirement),
                requirement,
            )

    def test_python_toolchain_is_user_local_and_verified(self):
        script = (ROOT / "scripts/prepare_python_toolchain.sh").read_text()

        self.assertIn('VERSION="3.12.10"', script)
        self.assertIn("python-$VERSION-macos11.pkg", script)
        self.assertIn("8373e58da4ea146b3eb1c1f9834f19a3", script)
        self.assertIn("pkgutil --check-signature", script)
        self.assertIn("install_name_tool", script)
        self.assertIn("audit_macho.sh", script)
        self.assertNotIn("sudo", script)

    def test_bottom_up_signer_does_not_use_deep_for_signing(self):
        signer = (ROOT / "scripts/sign_app_bundle.sh").read_text()

        self.assertIn("Mach-O", signer)
        self.assertIn("--options runtime", signer)
        self.assertIn("--timestamp", signer)
        self.assertIn("--entitlements", signer)
        self.assertIn("not a release candidate", signer)
        self.assertNotIn('"${SIGN_ARGS[@]}" --deep', signer)
        self.assertIn("codesign --verify --deep --strict", signer)

    def test_macho_audit_requires_arm64_and_macos_15_or_earlier(self):
        audit = (ROOT / "scripts/audit_macho.sh").read_text()

        self.assertIn('/usr/bin/lipo -archs', audit)
        self.assertIn("xcrun vtool -show-build", audit)
        self.assertIn('ARCHITECTURES" != "arm64', audit)
        self.assertIn("version_is_at_most", audit)
        self.assertIn("MACHO-INVENTORY.tsv", audit)

    def test_product_dmg_is_developer_id_only_and_verifiable(self):
        dmg_script = (ROOT / "scripts/build_product_dmg.sh").read_text()
        installer = (ROOT / "scripts/install_product_app.command").read_text()

        self.assertIn("Authority=Developer ID Application:", dmg_script)
        self.assertIn('if [[ -z "$NOTARY_PROFILE" ]]', dmg_script)
        self.assertNotIn("not-requested", dmg_script)
        self.assertIn("notarytool submit", dmg_script)
        self.assertIn("stapler staple", dmg_script)
        self.assertIn("stapler validate", dmg_script)
        self.assertIn('--sign "$SIGN_IDENTITY"', dmg_script)
        self.assertIn("--type open", dmg_script)
        self.assertIn("context:primary-signature", dmg_script)
        self.assertIn("hdiutil verify", dmg_script)
        self.assertIn("spctl --assess", dmg_script)
        self.assertIn("shasum -a 256", dmg_script)
        self.assertIn("manifest.txt", dmg_script)
        self.assertIn("КАК УСТАНОВИТЬ.txt", dmg_script)
        self.assertIn('audit_signatures.sh" "$APP" 1', dmg_script)
        self.assertIn("DEPENDENCY-INVENTORY.txt", dmg_script)
        self.assertIn("dependency_lock_sha256", dmg_script)
        self.assertNotIn("--noqtn", dmg_script)
        self.assertIn("$HOME/Applications", installer)
        self.assertIn("Транскрибатор.previous.app", installer)
        self.assertIn("Authority=Developer ID Application:", installer)
        self.assertIn("spctl --assess --type execute", installer)
        self.assertIn("Gatekeeper не подтвердил", installer)
        self.assertNotIn("sudo", installer)
        self.assertNotIn("com.apple.quarantine", installer)
        self.assertNotIn("--noqtn", installer)

    def test_release_shell_scripts_parse_as_zsh(self):
        scripts = [
            "audit_ffmpeg.sh",
            "audit_macho.sh",
            "audit_licenses.sh",
            "audit_signatures.sh",
            "audit_release_dependencies.sh",
            "sign_app_bundle.sh",
            "prepare_release_environment.sh",
            "build_product_dmg.sh",
            "install_product_app.command",
            "rollback_product_app.command",
            "build_ffmpeg_lgpl.sh",
            "build_app_bundle.sh",
        ]

        for script in scripts:
            with self.subTest(script=script):
                subprocess.run(
                    ["/bin/zsh", "-n", str(ROOT / "scripts" / script)],
                    check=True,
                )


if __name__ == "__main__":
    unittest.main()
