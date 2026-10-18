from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT.joinpath(".github", "workflows", "deploy.yml").read_text(
    encoding="utf-8"
)
VALIDATE = WORKFLOW.split("\n  validate:\n", 1)[1].split("\n  deploy:\n", 1)[0]
DEPLOY = WORKFLOW.split("\n  deploy:\n", 1)[1]


def step(job, name):
    return job.split(f"      - name: {name}\n", 1)[1].split(
        "\n      - name: ", 1
    )[0]


class DeploymentWorkflowTests(unittest.TestCase):
    def test_only_default_branch_pushes_and_pull_requests_trigger_checks(self):
        events = WORKFLOW.split("\non:\n", 1)[1].split("\npermissions:\n", 1)[0]
        self.assertEqual(
            events.strip(),
            "push:\n    branches: [main]\n  pull_request:\n    branches: [main]",
        )
        self.assertNotIn("pull_request_target", WORKFLOW)
        self.assertNotIn("workflow_dispatch", WORKFLOW)

    def test_deployment_requires_a_default_branch_push(self):
        guard = re.search(r"^    if: (.+)$", DEPLOY, re.MULTILINE).group(1)
        self.assertEqual(
            guard,
            "${{ github.event_name == 'push' && "
            "github.ref == format('refs/heads/{0}', github.event.repository.default_branch) }}",
        )
        self.assertNotIn("github.ref_protected", WORKFLOW)
        self.assertIn("    needs: validate\n", DEPLOY)
        self.assertNotIn("continue-on-error", WORKFLOW)

    def test_running_production_uploads_are_serialized_and_not_cancelled(self):
        self.assertIn(
            "    concurrency:\n"
            "      group: backend-php-production\n"
            "      cancel-in-progress: false\n",
            DEPLOY,
        )
        self.assertNotIn("cancel-in-progress: true", WORKFLOW)
        self.assertNotIn("concurrency:", VALIDATE)

    def test_pull_request_checks_have_no_ftp_credentials(self):
        self.assertNotIn("secrets.", VALIDATE)
        self.assertNotIn("FTP_USERNAME", VALIDATE)
        self.assertNotIn("FTP_PASSWORD", VALIDATE)
        self.assertIn("run: .\\scripts\\upload-backend-php.ps1 -WhatIf", VALIDATE)

    def test_credentials_are_scoped_only_to_the_guarded_publish_step(self):
        publish = step(DEPLOY, "Publish packaged PHP backend")
        before_publish = DEPLOY.split(
            "      - name: Publish packaged PHP backend\n", 1
        )[0]
        self.assertNotIn("secrets.", before_publish)
        self.assertEqual(WORKFLOW.count("${{ secrets."), 2)
        self.assertIn("FTP_USERNAME: ${{ secrets.FTP_USERNAME }}", publish)
        self.assertIn("FTP_PASSWORD: ${{ secrets.FTP_PASSWORD }}", publish)
        self.assertIn("[PSCredential]::new($env:FTP_USERNAME, $password)", publish)
        self.assertIn("-Credential $credential -Confirm:$false", publish)

    def test_each_job_checks_out_only_this_repository(self):
        self.assertIn("permissions:\n  contents: read\n", WORKFLOW)
        self.assertEqual(WORKFLOW.count("uses: actions/checkout@"), 2)
        for job in (VALIDATE, DEPLOY):
            app = step(job, "Check out PHP application")
            self.assertEqual(job.count("uses: actions/checkout@"), 1)
            self.assertIn("ref: ${{ github.sha }}", app)
            self.assertIn("persist-credentials: false", app)
            self.assertIn("submodules: false", app)
            self.assertNotIn("repository:", job)
            self.assertNotIn("path:", app)
        self.assertNotRegex(
            WORKFLOW,
            r"(?i)controller|kk67-docker|git\s+clone|gh\s+repo\s+clone|"
            r"Invoke-WebRequest|Invoke-RestMethod|DownloadFile",
        )

    def test_deployment_scripts_and_tests_are_owned_by_this_repository(self):
        for relative in (
            ("scripts", "upload-backend-php.ps1"),
            ("scripts", "ftps.psm1"),
            ("tests", "test_upload_backend_php.py"),
            ("tests", "test_ftps.py"),
        ):
            self.assertTrue(ROOT.joinpath(*relative).is_file(), relative)
        self.assertIn(
            "python -m unittest discover -s .\\tests -p 'test_*.py' -v", VALIDATE
        )
        self.assertIn("run: .\\scripts\\upload-backend-php.ps1 -WhatIf", VALIDATE)
        self.assertIn(".\\scripts\\upload-backend-php.ps1 -Credential", DEPLOY)

    def test_actions_are_pinned_and_php_matches_the_docker_baseline(self):
        actions = re.findall(r"^\s+uses: ([^@\s]+)@(\S+)", WORKFLOW, re.MULTILINE)
        self.assertEqual(len(actions), 5)
        for action, pin in actions:
            self.assertIn(
                action,
                ("actions/checkout", "shivammathur/setup-php", "actions/setup-node"),
            )
            self.assertRegex(pin, r"^[0-9a-f]{40}$")
        for job in (VALIDATE, DEPLOY):
            self.assertIn("runs-on: windows-latest", job)
            php = step(job, "Set up PHP")
            self.assertIn("php-version: '8.3'", php)
            self.assertIn("coverage: none", php)
            self.assertIn("tools: none", php)
        node = step(VALIDATE, "Set up Node for credential parser tests")
        self.assertIn("node-version: '24'", node)


if __name__ == "__main__":
    unittest.main()
