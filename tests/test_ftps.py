import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")
NODE = shutil.which("node")
CURL = shutil.which("curl.exe") or shutil.which("curl")
DESTINATION = "ftp://ftp.c9ry3m6by.service.one/webroots/r1058768/"
IMAGE_STATE_URL = DESTINATION + ".kk67-image-state.json"


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def image_state(images, complete=True):
    return json.dumps(
        {
            "version": 1,
            "complete": complete,
            "images": {
                path: hashlib.sha256(contents).hexdigest()
                for path, contents in images.items()
            },
        }
    )


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
        self.command_log = self.root.joinpath("commands.jsonl")
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
                "KK67_FTPS_TEST_COMMAND_LOG": str(self.command_log),
                "KK67_FTPS_TEST_PROMPT_LOG": str(self.prompt_log),
                "KK67_FTPS_TEST_ALLOW_PROMPT": "0",
                "KK67_FTPS_TEST_FORBID_NODE": "0",
                "KK67_FTPS_TEST_PREFLIGHT_EXIT": "0",
                "KK67_FTPS_TEST_UPLOAD_EXIT": "0",
                "KK67_FTPS_TEST_IMAGE_STATE": "",
                "KK67_FTPS_TEST_STATE_READ_EXIT": "0",
                "KK67_FTPS_TEST_STATE_WRITE_EXIT": "0",
                "KK67_FTPS_TEST_STATE_COMMIT_EXIT": "0",
                "KK67_FTPS_TEST_FAIL_UPLOAD_SUFFIX": "",
                "KK67_FTPS_TEST_PASSWORD": self.password,
                "KK67_FTPS_TEST_USERNAME": "ftp-user",
                "NO_COLOR": "1",
                "TERM": "dumb",
            }
        )
        env.update(overrides)
        harness = r"""
function Invoke-TestCurl {
    $call = @{
        arguments = @($args)
        config = (@($input) -join "`n")
    }
    $stateUpload = $args -contains '--upload-file' -and
        $args[-1].EndsWith('/.kk67-image-state.json')
    if ($stateUpload) {
        $call.imageState = Get-Content -Raw -LiteralPath $args[
            [Array]::IndexOf($args, '--upload-file') + 1
        ]
    }
    $call | ConvertTo-Json -Compress |
        Add-Content -LiteralPath $env:KK67_FTPS_TEST_CURL_LOG -WhatIf:$false -Confirm:$false
    if ($args -contains '--list-only') {
        $global:LASTEXITCODE = [int] $env:KK67_FTPS_TEST_PREFLIGHT_EXIT
    }
    elseif ($args -contains '--output') {
        $global:LASTEXITCODE = [int] $env:KK67_FTPS_TEST_STATE_READ_EXIT
        if ($global:LASTEXITCODE -eq 0) {
            if ([string]::IsNullOrEmpty($env:KK67_FTPS_TEST_IMAGE_STATE)) {
                $global:LASTEXITCODE = 78
            }
            else {
                Set-Content -LiteralPath $args[[Array]::IndexOf($args, '--output') + 1] `
                    -Value $env:KK67_FTPS_TEST_IMAGE_STATE -NoNewline -WhatIf:$false -Confirm:$false
            }
        }
    }
    elseif ($stateUpload) {
        $state = ConvertFrom-Json $call.imageState
        $global:LASTEXITCODE = if ($state.complete) {
            [int] $env:KK67_FTPS_TEST_STATE_COMMIT_EXIT
        } else {
            [int] $env:KK67_FTPS_TEST_STATE_WRITE_EXIT
        }
    }
    elseif ($env:KK67_FTPS_TEST_FAIL_UPLOAD_SUFFIX -and
        $args[-1].EndsWith($env:KK67_FTPS_TEST_FAIL_UPLOAD_SUFFIX)) {
        $global:LASTEXITCODE = 25
    }
    else {
        $global:LASTEXITCODE = [int] $env:KK67_FTPS_TEST_UPLOAD_EXIT
    }
}
function Get-Command {
    [CmdletBinding()]
    param(
        [string] $Name,
        [System.Management.Automation.CommandTypes] $CommandType
    )
    if ($Name -in @('curl', 'curl.exe')) {
        @{ name = $Name; commandType = [string] $CommandType } |
            ConvertTo-Json -Compress |
            Add-Content -LiteralPath $env:KK67_FTPS_TEST_COMMAND_LOG -WhatIf:$false -Confirm:$false
        if ($Name -ne 'curl' -or $CommandType -ne 'Application') {
            throw 'The uploader must select one portable native curl application.'
        }
        return Microsoft.PowerShell.Core\Get-Command Invoke-TestCurl -CommandType Function
    }
    return Microsoft.PowerShell.Core\Get-Command @PSBoundParameters
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

    def add_image(self, relative_path, contents=b"photo"):
        path = self.source.joinpath(*relative_path.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)

    def build_uploads(self):
        return [
            call for call in self.calls()
            if "--upload-file" in call["arguments"]
            and call["arguments"][-1] != IMAGE_STATE_URL
        ]

    def uploaded_image_states(self):
        return [
            json.loads(call["imageState"])
            for call in self.calls() if "imageState" in call
        ]

    def test_resolves_native_curl_without_a_windows_suffix(self):
        self.assert_success(self.invoke())
        lookups = [
            json.loads(line)
            for line in self.command_log.read_text(encoding="utf-8-sig").splitlines()
        ]
        self.assertEqual(lookups, [{"name": "curl", "commandType": "Application"}])

    def test_image_mode_without_images_does_not_read_or_write_state(self):
        self.assert_success(
            self.invoke("-SkipUnchangedImages", KK67_FTPS_TEST_STATE_READ_EXIT="56")
        )
        self.assertEqual(len(self.calls()), 5)
        self.assertEqual(self.uploaded_image_states(), [])
        self.assertFalse(any("--output" in call["arguments"] for call in self.calls()))

    def test_unchanged_images_are_skipped_but_php_entry_point_is_uploaded_last(self):
        images = {"photos/old.JPG": b"photo", "assets/logo-hash.svg": b"<svg/>"}
        for path, contents in images.items():
            self.add_image(path, contents)
        self.assert_success(
            self.invoke("-SkipUnchangedImages", KK67_FTPS_TEST_IMAGE_STATE=image_state(images))
        )
        self.assertEqual(len(self.calls()), 6)
        self.assertEqual(len(self.build_uploads()), 4)
        self.assertEqual(self.calls()[-1]["arguments"][-1], DESTINATION + "index.php")
        self.assertEqual(self.uploaded_image_states(), [])

    def test_new_and_same_size_changed_images_upload_and_commit_before_index(self):
        previous = {"photos/same.jpg": b"original", "photos/change.jpg": b"oldphoto"}
        current = {
            "photos/same.jpg": b"original",
            "photos/change.jpg": b"newphoto",
            "assets/new # [photo].avif": b"new",
        }
        for path, contents in current.items():
            self.add_image(path, contents)
        self.assert_success(
            self.invoke("-SkipUnchangedImages", KK67_FTPS_TEST_IMAGE_STATE=image_state(previous))
        )
        urls = [call["arguments"][-1] for call in self.build_uploads()]
        self.assertEqual(len(urls), 6)
        self.assertNotIn(DESTINATION + "photos/same.jpg", urls)
        self.assertIn(DESTINATION + "photos/change.jpg", urls)
        self.assertIn(DESTINATION + "assets/new%20%23%20%5Bphoto%5D.avif", urls)
        self.assertEqual(urls[-1], DESTINATION + "index.php")
        self.assertEqual(self.calls()[2]["arguments"][-1], IMAGE_STATE_URL)
        self.assertEqual(self.calls()[-2]["arguments"][-1], IMAGE_STATE_URL)
        self.assertEqual(
            [state["complete"] for state in self.uploaded_image_states()], [False, True]
        )
        self.assertEqual(self.uploaded_image_states()[-1], json.loads(image_state(current)))
        for call in self.calls():
            if "imageState" in call:
                arguments = call["arguments"]
                self.assertFalse(Path(arguments[arguments.index("--upload-file") + 1]).exists())
                self.assertNotIn(self.password, call["imageState"])

    def test_missing_or_invalid_image_state_is_reported_and_rebuilt(self):
        images = {"photos/photo.jpg": b"photo"}
        self.add_image("photos/photo.jpg")
        for saved in (
            "",
            image_state(images, complete=False),
            "{interrupted",
            "null",
            '{"version":2,"complete":true,"images":{}}',
            '{"version":1,"complete":true,"images":{"photo.jpg":"invalid"}}',
        ):
            with self.subTest(state=saved[:60]):
                self.curl_log.unlink(missing_ok=True)
                result = self.invoke("-SkipUnchangedImages", KK67_FTPS_TEST_IMAGE_STATE=saved)
                self.assert_success(result)
                self.assertEqual(len(self.build_uploads()), 5)
                self.assertEqual(self.uploaded_image_states()[-1], json.loads(image_state(images)))
                self.assertIn("WARNING" if saved else "Image state not found", result.stdout)

    def test_image_state_read_or_invalidation_failure_prevents_all_file_writes(self):
        self.add_image("photos/photo.jpg")
        for setting in ("KK67_FTPS_TEST_STATE_READ_EXIT", "KK67_FTPS_TEST_STATE_WRITE_EXIT"):
            with self.subTest(setting=setting):
                self.curl_log.unlink(missing_ok=True)
                result = self.invoke("-SkipUnchangedImages", **{setting: "56"})
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.build_uploads(), [])
                self.assertNotIn("Upload complete", result.stdout)

    def test_failed_image_upload_leaves_incomplete_state_and_retries_all_images(self):
        images = {"photos/a.jpg": b"first", "photos/b.jpg": b"second"}
        for path, contents in images.items():
            self.add_image(path, contents)
        result = self.invoke(
            "-SkipUnchangedImages", KK67_FTPS_TEST_FAIL_UPLOAD_SUFFIX="/b.jpg"
        )
        self.assertNotEqual(result.returncode, 0)
        states = self.uploaded_image_states()
        self.assertEqual([state["complete"] for state in states], [False])
        self.assertNotEqual(self.calls()[-1]["arguments"][-1], DESTINATION + "index.php")
        self.curl_log.unlink()
        self.assert_success(
            self.invoke("-SkipUnchangedImages", KK67_FTPS_TEST_IMAGE_STATE=json.dumps(states[-1]))
        )
        self.assertEqual(len(self.build_uploads()), 6)
        self.assertTrue(self.uploaded_image_states()[-1]["complete"])

    def test_image_state_commit_failure_prevents_entry_point_publication(self):
        self.add_image("photos/photo.jpg")
        result = self.invoke("-SkipUnchangedImages", KK67_FTPS_TEST_STATE_COMMIT_EXIT="25")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(
            any(call["arguments"][-1] == DESTINATION + "index.php" for call in self.build_uploads())
        )
        self.assertNotIn("Upload complete", result.stdout)

    def test_full_image_refresh_ignores_the_old_baseline(self):
        self.add_image("photos/photo.jpg")
        self.assert_success(self.invoke(KK67_FTPS_TEST_STATE_READ_EXIT="56"))
        self.assertEqual(len(self.build_uploads()), 5)
        self.assertEqual(
            [state["complete"] for state in self.uploaded_image_states()], [False, True]
        )
        self.assertFalse(any("--output" in call["arguments"] for call in self.calls()))

    def test_image_preview_never_reads_state_or_credentials(self):
        self.add_image("photos/photo.jpg")
        self.env_file.write_text("FTP_USERNAME=incomplete\n", encoding="utf-8")
        self.assert_success(
            self.invoke("-SkipUnchangedImages -WhatIf", credential=False)
        )
        self.assertEqual(self.calls(), [])
        self.assertFalse(self.prompt_log.exists())

    def test_real_duplicate_curl_lookup_uses_first_client_and_downloads_image_state(self):
        self.add_image("photos/photo.jpg")
        stub = self.root.joinpath("curl_stub.py")
        stub.write_text(
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "arguments = sys.argv[2:]\n"
            "if '--output' in arguments:\n"
            "    Path(arguments[arguments.index('--output') + 1]).write_text(\n"
            "        os.environ['KK67_FTPS_TEST_IMAGE_STATE'], encoding='utf-8')\n"
            "with open(os.environ['KK67_FTPS_TEST_CURL_LOG'], 'a', encoding='utf-8') as log:\n"
            "    log.write(json.dumps({'client': sys.argv[1], 'arguments': arguments,\n"
            "        'config': sys.stdin.read()}) + '\\n')\n",
            encoding="utf-8",
        )
        executables = []
        for name in ("first", "second"):
            directory = self.root.resolve().joinpath(f"curl {name}")
            directory.mkdir()
            if os.name == "nt":
                executable = directory.joinpath("curl.cmd")
                command = f'@echo off\n"{sys.executable}" "{stub}" {name} %*\n'
            else:
                executable = directory.joinpath("curl")
                command = (
                    f"#!/bin/sh\nexec {shlex.quote(sys.executable)} "
                    f'{shlex.quote(str(stub))} {name} "$@"\n'
                )
            executable.write_text(command, encoding="utf-8")
            executable.chmod(0o755)
            executables.append(executable)
        env = os.environ.copy()
        env.update({
            "PATH": os.pathsep.join(str(path.parent) for path in executables),
            "KK67_FTPS_TEST_CURL_LOG": str(self.curl_log),
            "KK67_FTPS_TEST_PASSWORD": self.password,
            "KK67_FTPS_TEST_IMAGE_STATE": image_state({"photos/photo.jpg": b"photo"}),
            "NO_COLOR": "1",
            "TERM": "dumb",
        })
        command = f"""
$ErrorActionPreference = 'Stop'
$candidates = @(Get-Command curl -CommandType Application -ErrorAction Stop)
if ($candidates.Count -ne 2 -or
    $candidates[0].Source -ne {ps_quote(executables[0])} -or
    $candidates[1].Source -ne {ps_quote(executables[1])}) {{
    throw 'Expected two isolated native curl clients.'
}}
$password = ConvertTo-SecureString $env:KK67_FTPS_TEST_PASSWORD -AsPlainText -Force
$credential = [PSCredential]::new('ftp-user', $password)
Import-Module {ps_quote(self.module)} -Force
Send-FtpsDirectory -SourcePath {ps_quote(self.source)} -FtpHost 'ftp.c9ry3m6by.service.one' `
    -RemotePath 'webroots/r1058768' -PublishLast 'index.php' -SkipUnchangedImages `
    -Credential $credential -Confirm:$false
"""
        result = subprocess.run(
            [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=self.root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assert_success(result)
        calls = self.calls()
        self.assertEqual(len(calls), 6)
        self.assertEqual({call["client"] for call in calls}, {"first"})
        self.assertIn("--output", calls[1]["arguments"])
        self.assertFalse(any(call["arguments"][-1].endswith("/photo.jpg") for call in calls))
        self.assertEqual(calls[-1]["arguments"][-1], DESTINATION + "index.php")
        for call in calls:
            self.assertEqual(call["arguments"][:3], ["--disable", "--config", "-"])
            self.assertTrue(call["config"].startswith('user = "ftp-user:'))
            self.assertNotIn(self.password, " ".join(call["arguments"]))

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
        self.assertIn("Upload complete: 4 files; 0 unchanged images skipped.", result.stdout)
        self.assertIn("No remote files were deleted.", result.stdout)

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
        self.assertRegex(result.stderr, r"Deployment\s+stopped;\s+uploaded\s+files\s+are\s+not\s+rolled\s+back")
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

    def test_directory_link_in_source_prevents_upload(self):
        outside = self.root.joinpath("outside package")
        outside.mkdir()
        outside.joinpath("private.txt").write_text("fixture", encoding="utf-8")
        link = self.source.joinpath("linked directory")
        if os.name == "nt":
            result = subprocess.run(
                [
                    PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                    f"New-Item -ItemType Junction -Path {ps_quote(link)} "
                    f"-Target {ps_quote(outside)} -ErrorAction Stop | Out-Null",
                ],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            link.symlink_to(outside, target_is_directory=True)
        try:
            result = self.invoke(credential=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symbolic links or junctions", result.stderr)
            self.assertEqual(self.calls(), [])
        finally:
            if os.name == "nt":
                link.rmdir()
            else:
                link.unlink()

    @unittest.skipUnless(CURL, "Native curl is required for option validation")
    def test_real_curl_accepts_the_options_without_connecting(self):
        self.add_image("photos/photo.jpg")
        self.assert_success(self.invoke("-SkipUnchangedImages"))
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
                self.assertRegex(native.stdout, r"(?m)^Protocols: .*\bftp\b")
                self.assertRegex(native.stdout, r"(?m)^Protocols: .*\bftps\b")
                self.assertNotIn(self.password, native.stdout + native.stderr)


if __name__ == "__main__":
    unittest.main()
