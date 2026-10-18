import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")
NODE = shutil.which("node")
CURL = shutil.which("curl.exe") or shutil.which("curl")
DESTINATION = "ftp://ftp.c9ry3m6by.service.one/webroots/r1058768/"


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def curl_escape(value):
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\v", "\\v")
    )


@unittest.skipUnless(
    shutil.which("git") and ROOT.joinpath(".git").exists(),
    "A Git checkout is required for credential-file ignore checks",
)
class SecretFileIgnoreTests(unittest.TestCase):
    def test_local_credentials_and_editor_backups_are_ignored(self):
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--stdin", "-z"],
            input="\0".join(
                (".env", ".env.local", ".env~", "..env.un~", ".env.example", "")
            ),
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            set(result.stdout.rstrip("\0").split("\0")),
            {".env", ".env.local", ".env~", "..env.un~"},
        )


@unittest.skipUnless(PWSH, "PowerShell 7 is required for real-module FTPS tests")
class FtpsTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(dir=ROOT, prefix=".ftps-test-")
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name).joinpath("app with spaces")
        self.module = self.root.joinpath("scripts", "ftps.psm1")
        self.module.parent.mkdir(parents=True)
        shutil.copyfile(ROOT.joinpath("scripts", "ftps.psm1"), self.module)
        self.source = self.root.joinpath("package")
        for relative in (
            "index.php",
            "loader.php",
            "assets/space # [name].txt",
            ".well-known/example.txt",
        ):
            path = self.source.joinpath(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture", encoding="utf-8")
        self.env_file = self.root.joinpath(".env")
        self.external_env = Path(self.workspace.name).joinpath(
            "external credentials.env"
        )
        self.curl_log = self.root.joinpath("curl.jsonl")
        self.prompt_log = self.root.joinpath("prompt.txt")
        self.password = 'pass "quoted" \\ : $value & end'

    def invoke(
        self,
        arguments="",
        credential=True,
        source=None,
        ftp_host="ftp.c9ry3m6by.service.one",
        remote_path="webroots/r1058768",
        publish_last="index.php",
        **overrides,
    ):
        env = os.environ.copy()
        env.update(
            {
                "KK67_FTPS_TEST_CURL_LOG": str(self.curl_log),
                "KK67_FTPS_TEST_PROMPT_LOG": str(self.prompt_log),
                "KK67_FTPS_TEST_ALLOW_PROMPT": "0",
                "KK67_FTPS_TEST_FORBID_NODE": "0",
                "KK67_FTPS_TEST_PREFLIGHT_EXIT": "0",
                "KK67_FTPS_TEST_UPLOAD_EXIT": "0",
                "KK67_FTPS_TEST_PASSWORD": self.password,
                "KK67_FTPS_TEST_USERNAME": "ftp-user",
                "NO_COLOR": "1",
                "TERM": "dumb",
            }
        )
        env.update(overrides)
        harness = r"""
function curl.exe {
    @{
        arguments = @($args)
        config = (@($input) -join "`n")
    } | ConvertTo-Json -Compress |
        Add-Content -LiteralPath $env:KK67_FTPS_TEST_CURL_LOG -WhatIf:$false -Confirm:$false
    $global:LASTEXITCODE = if ($args -contains '--list-only') {
        [int] $env:KK67_FTPS_TEST_PREFLIGHT_EXIT
    } else {
        [int] $env:KK67_FTPS_TEST_UPLOAD_EXIT
    }
}
function Get-Credential {
    if ($env:KK67_FTPS_TEST_ALLOW_PROMPT -ne '1') {
        throw 'Unexpected interactive credential prompt.'
    }
    Set-Content -LiteralPath $env:KK67_FTPS_TEST_PROMPT_LOG -Value 'prompted' -WhatIf:$false -Confirm:$false
    return $global:KK67FtpsCredential
}
if ($env:KK67_FTPS_TEST_FORBID_NODE -eq '1') {
    function global:node { throw 'The saved credential parser must not run.' }
}
$password = ConvertTo-SecureString $env:KK67_FTPS_TEST_PASSWORD -AsPlainText -Force
$credential = [PSCredential]::new($env:KK67_FTPS_TEST_USERNAME, $password)
$global:KK67FtpsCredential = $credential
"""
        command = (
            f"\nImport-Module {ps_quote(self.module)} -Force\n"
            f"Send-FtpsDirectory -SourcePath {ps_quote(source or self.source)} "
            f"-FtpHost {ps_quote(ftp_host)} -RemotePath {ps_quote(remote_path)} "
            "-Confirm:$false "
        )
        if publish_last is not None:
            command += f"-PublishLast {ps_quote(publish_last)} "
        if credential:
            command += "-Credential $credential "
        return subprocess.run(
            [
                PWSH,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                harness + command + arguments,
            ],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )

    def calls(self):
        if not self.curl_log.exists():
            return []
        return [
            json.loads(line)
            for line in self.curl_log.read_text(encoding="utf-8-sig").splitlines()
        ]

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(self.password, result.stdout + result.stderr)

    def test_required_tls_stdin_credentials_preflight_encoding_and_entry_point_last(self):
        self.password += "\r\n\t\v"
        result = self.invoke()
        self.assert_success(result)
        calls = self.calls()
        self.assertEqual(len(calls), 5)
        self.assertIn("--list-only", calls[0]["arguments"])
        self.assertNotIn("--ftp-create-dirs", calls[0]["arguments"])
        self.assertEqual(calls[0]["arguments"][-1], DESTINATION)
        self.assertEqual(calls[-1]["arguments"][-1], DESTINATION + "index.php")
        self.assertEqual(
            {call["arguments"][-1] for call in calls[1:]},
            {
                DESTINATION + "index.php",
                DESTINATION + "loader.php",
                DESTINATION + "assets/space%20%23%20%5Bname%5D.txt",
                DESTINATION + ".well-known/example.txt",
            },
        )
        for call in calls:
            arguments = call["arguments"]
            self.assertEqual(arguments[:3], ["--disable", "--config", "-"])
            self.assertIn("--ssl-reqd", arguments)
            self.assertEqual(arguments[arguments.index("--proto") + 1], "=ftp")
            for forbidden in ("--insecure", "--quote", "--request", "--user"):
                self.assertNotIn(forbidden, arguments)
            self.assertNotIn("ftp-user", " ".join(arguments))
            self.assertNotIn(self.password, " ".join(arguments))
            self.assertEqual(
                call["config"], f'user = "ftp-user:{curl_escape(self.password)}"'
            )
        for call in calls[1:]:
            arguments = call["arguments"]
            self.assertIn("--ftp-create-dirs", arguments)
            source = Path(arguments[arguments.index("--upload-file") + 1])
            self.assertTrue(source.resolve().is_relative_to(self.source.resolve()))
        self.assertIn("Upload complete: 4 files. No remote files were deleted.", result.stdout)

    @unittest.skipUnless(NODE, "Node.js 20.12+ is required for dotenv parser tests")
    def test_default_app_file_uses_real_dotenv_parser_without_exporting_other_keys(self):
        self.password += " # = \u00f8"
        self.env_file.write_text(
            "IGNORED=1\nexport FTP_USERNAME='saved-user'\n"
            f"FTP_PASSWORD='{self.password}' # outside the value\n"
            "NODE_OPTIONS='--require=does-not-exist'\n",
            encoding="utf-8",
        )
        result = self.invoke(credential=False)
        self.assert_success(result)
        self.assertEqual(len(self.calls()), 5)
        for call in self.calls():
            self.assertEqual(
                call["config"], f'user = "saved-user:{curl_escape(self.password)}"'
            )
        self.assertFalse(self.prompt_log.exists())

    @unittest.skipUnless(NODE, "Node.js 20.12+ is required for dotenv parser tests")
    def test_explicit_external_file_overrides_the_default_without_copying_it(self):
        self.env_file.write_text("FTP_USERNAME=incomplete-default\n", encoding="utf-8")
        self.external_env.write_text(
            f"FTP_USERNAME=external-user\nFTP_PASSWORD='{self.password}'\n",
            encoding="utf-8",
        )
        original = self.env_file.read_bytes()
        result = self.invoke(
            f"-EnvFilePath {ps_quote(self.external_env)}", credential=False
        )
        self.assert_success(result)
        self.assertEqual(self.env_file.read_bytes(), original)
        self.assertEqual(len(self.calls()), 5)
        for call in self.calls():
            self.assertEqual(
                call["config"], f'user = "external-user:{curl_escape(self.password)}"'
            )
        self.assertFalse(self.prompt_log.exists())

    def test_explicit_credential_skips_even_an_incomplete_or_missing_selected_file(self):
        self.env_file.write_text("FTP_USERNAME=incomplete-default\n", encoding="utf-8")
        for exists in (True, False):
            with self.subTest(exists=exists):
                self.curl_log.unlink(missing_ok=True)
                if exists:
                    self.external_env.write_text(
                        "FTP_PASSWORD=incomplete-external\n", encoding="utf-8"
                    )
                else:
                    self.external_env.unlink()
                result = self.invoke(
                    f"-EnvFilePath {ps_quote(self.external_env)}",
                    KK67_FTPS_TEST_FORBID_NODE="1",
                )
                self.assert_success(result)
                self.assertEqual(len(self.calls()), 5)
                for call in self.calls():
                    self.assertTrue(call["config"].startswith('user = "ftp-user:'))
                self.assertFalse(self.prompt_log.exists())

    @unittest.skipUnless(NODE, "Node.js 20.12+ is required for dotenv parser tests")
    def test_partial_credentials_fail_without_prompt_or_connection_for_either_file(self):
        for path in (self.env_file, self.external_env):
            for contents in ("FTP_USERNAME=only-user\n", "FTP_PASSWORD=only-password\n"):
                with self.subTest(file=path.name, key=contents.split("=")[0]):
                    path.write_text(contents, encoding="utf-8")
                    arguments = (
                        f"-EnvFilePath {ps_quote(path)}" if path == self.external_env else ""
                    )
                    result = self.invoke(arguments, credential=False)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("Set both FTP_USERNAME and FTP_PASSWORD", result.stderr)
                    self.assertIn(path.name.split()[-1], result.stderr)
                    self.assertEqual(self.calls(), [])
                    self.assertFalse(self.prompt_log.exists())

    def test_explicit_missing_file_fails_instead_of_using_default_or_prompt(self):
        self.env_file.write_text(
            "FTP_USERNAME=default-user\nFTP_PASSWORD=default-password\n",
            encoding="utf-8",
        )
        result = self.invoke(
            f"-EnvFilePath {ps_quote(self.external_env)}",
            credential=False,
            KK67_FTPS_TEST_FORBID_NODE="1",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FTP credential file not found", result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertFalse(self.prompt_log.exists())

    def test_whatif_never_reads_files_prompts_or_connects_even_with_missing_override(self):
        self.env_file.write_text("FTP_USERNAME=incomplete\n", encoding="utf-8")
        for arguments in ("", f"-EnvFilePath {ps_quote(self.external_env)}"):
            with self.subTest(arguments=arguments):
                result = self.invoke(
                    "-WhatIf " + arguments,
                    credential=False,
                    KK67_FTPS_TEST_FORBID_NODE="1",
                )
                self.assert_success(result)
                self.assertIn(DESTINATION, result.stdout)
                self.assertNotIn("Upload complete", result.stdout)
                self.assertEqual(self.calls(), [])
                self.assertFalse(self.prompt_log.exists())

    @unittest.skipUnless(NODE, "Node.js 20.12+ is required for dotenv parser tests")
    def test_absent_default_file_or_empty_pair_keeps_the_secure_prompt(self):
        for contents in (None, "IGNORED=1\n", "FTP_USERNAME=''\nFTP_PASSWORD=''\n"):
            with self.subTest(contents=contents):
                self.curl_log.unlink(missing_ok=True)
                self.prompt_log.unlink(missing_ok=True)
                if contents is None:
                    self.env_file.unlink(missing_ok=True)
                else:
                    self.env_file.write_text(contents, encoding="utf-8")
                result = self.invoke(credential=False, KK67_FTPS_TEST_ALLOW_PROMPT="1")
                self.assert_success(result)
                self.assertTrue(self.prompt_log.exists())
                self.assertEqual(len(self.calls()), 5)

    def test_failed_preflight_does_not_upload_or_create_directories(self):
        result = self.invoke(KK67_FTPS_TEST_PREFLIGHT_EXIT="67")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FTP login or destination check failed", result.stderr)
        self.assertEqual(len(self.calls()), 1)
        self.assertNotIn("--ftp-create-dirs", self.calls()[0]["arguments"])
        self.assertNotIn("Upload complete", result.stdout)
        self.assertNotIn(self.password, result.stdout + result.stderr)

    def test_failed_dependency_upload_stops_before_the_entry_point(self):
        result = self.invoke(KK67_FTPS_TEST_UPLOAD_EXIT="25")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Deployment stopped; uploaded files are not rolled back", result.stderr)
        self.assertEqual(len(self.calls()), 2)
        self.assertNotEqual(self.calls()[-1]["arguments"][-1], DESTINATION + "index.php")
        self.assertNotIn("Upload complete", result.stdout)
        self.assertNotIn(self.password, result.stdout + result.stderr)

    def test_invalid_destinations_are_rejected_before_credentials_or_connection(self):
        for overrides, message in (
            ({"remote_path": "../wrong"}, "RemotePath must be"),
            ({"remote_path": "site//root"}, "RemotePath must be"),
            ({"ftp_host": "ftp://wrong/path"}, "FtpHost must be"),
        ):
            with self.subTest(overrides=overrides):
                result = self.invoke(credential=False, **overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertEqual(self.calls(), [])
                self.assertFalse(self.prompt_log.exists())

    def test_remote_directory_is_trimmed_and_encoded(self):
        result = self.invoke(remote_path=" /site name/root/ ")
        self.assert_success(result)
        self.assertEqual(
            self.calls()[0]["arguments"][-1],
            "ftp://ftp.c9ry3m6by.service.one/site%20name/root/",
        )

    def test_invalid_or_missing_entry_point_and_empty_source_fail_without_connection(self):
        for publish_last in ("../index.php", "folder/index.php", "missing.php"):
            with self.subTest(publish_last=publish_last):
                result = self.invoke(credential=False, publish_last=publish_last)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("PublishLast", result.stderr)
                self.assertEqual(self.calls(), [])
        empty = self.root.joinpath("empty")
        empty.mkdir()
        result = self.invoke(credential=False, source=empty, publish_last=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("contains no files", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_invalid_credential_username_fails_before_connection(self):
        result = self.invoke(KK67_FTPS_TEST_USERNAME="user:invalid")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("without colons or newlines", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_symbolic_link_in_source_prevents_upload(self):
        try:
            self.source.joinpath("linked.txt").symlink_to(
                self.source.joinpath("loader.php")
            )
        except OSError as error:
            self.skipTest(f"Creating symbolic links is unavailable: {error}")
        result = self.invoke(credential=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symbolic links or junctions", result.stderr)
        self.assertEqual(self.calls(), [])

    @unittest.skipUnless(os.name == "nt", "NTFS junctions are Windows-specific")
    def test_junction_in_source_prevents_upload(self):
        outside = self.root.joinpath("outside package")
        outside.mkdir()
        outside.joinpath("private.txt").write_text("fixture", encoding="utf-8")
        link = self.source.joinpath("linked directory")
        result = subprocess.run(
            [
                PWSH,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"New-Item -ItemType Junction -Path {ps_quote(link)} "
                f"-Target {ps_quote(outside)} -ErrorAction Stop | Out-Null",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        try:
            result = self.invoke(credential=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symbolic links or junctions", result.stderr)
            self.assertEqual(self.calls(), [])
        finally:
            link.rmdir()

    @unittest.skipUnless(CURL, "Native curl is required for option validation")
    def test_real_curl_accepts_the_options_without_connecting(self):
        self.assert_success(self.invoke())
        for call in self.calls():
            with self.subTest(operation=call["arguments"][-1]):
                native = subprocess.run(
                    [CURL, *call["arguments"], "--version"],
                    input=call["config"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(native.returncode, 0, native.stderr)
                self.assertTrue(native.stdout.startswith("curl "))
                self.assertNotIn(self.password, native.stdout + native.stderr)


if __name__ == "__main__":
    unittest.main()
