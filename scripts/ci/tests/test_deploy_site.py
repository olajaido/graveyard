"""The deploy-site composite action (infra-edge T10.3; EDGE-DEP-2, EDGE-DEP-4, EDGE-DEP-5, EDGE-CACHE-1).
Static rules read the file. Execution tests run the actual `run:` scripts with fake `terraform`, `aws` and `curl`
executables, so the path list of the invalidation, the refusal of a bad bucket name and the live-site checks are seen
doing what the design says. Nothing here touches AWS or a network.
"""
from __future__ import annotations
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Dict, Optional
from helpers import PLACEHOLDER, REPO_ROOT  # noqa: F401  (helpers fixes sys.path)
import actions_text as a
import guards
from test_actions import Shims
ACTION = ".github/actions/deploy-site/action.yml"
TEXT = (REPO_ROOT / ACTION).read_text(encoding="utf-8")
STEPS = a.action_steps("deploy-site")
BASH = shutil.which("bash") is not None
GOOD_HEADERS = "\r\n".join([
    "strict-transport-security: max-age=63072000; includeSubDomains",
    "content-security-policy: default-src 'self'",
    "x-content-type-options: nosniff",
    "cache-control: no-cache",
])
IMMUTABLE = "cache-control: public,max-age=31536000,immutable"
class Static(unittest.TestCase):
    def test_the_action_is_pinned_and_runs_nothing_from_the_project(self) -> None:
        self.assertEqual(guards.check_action_pins({ACTION: TEXT}), [])
        self.assertIn("actions/download-artifact@", TEXT)
        for needle in ("npm ", "npx ", "pip ", "uv "):
            self.assertNotIn(needle, "".join(s.get("run", "") for s in STEPS), "no project code runs in the credentialed job (EDGE-DEP-5)")
    def test_the_artifact_rule_accepts_this_action_and_nothing_else(self) -> None:
        self.assertEqual(a.artifact_problems(ACTION, TEXT), [])
        self.assertTrue(a.artifact_problems(".github/workflows/ci.yml", "uses: actions/upload-artifact@" + "0" * 40 + "\n"))
        bad = "      - uses: actions/upload-artifact@" + "0" * 40 + " # v1\n        with:\n          name: plan\n          path: dev.tfplan\n"
        self.assertTrue(a.artifact_problems(".github/workflows/deploy.yml", bad))
    def test_no_run_block_interpolates_an_expression_and_every_variable_is_declared(self) -> None:
        builtin = {"HOME", "GITHUB_OUTPUT", "GITHUB_ENV", "GITHUB_STEP_SUMMARY", "PATH"}
        for s in STEPS:
            if "run" not in s:
                continue
            self.assertNotIn("${{", s["run"], s.get("name"))
            self.assertEqual(s.get("shell"), "bash", s.get("name"))
            local = set(re.findall(r"^\s*(?:local\s+)?([A-Za-z_][A-Za-z0-9_]*)=", s["run"], flags=re.M))
            for var in set(re.findall(r"\$\{?([A-Z][A-Z0-9_]+)", s["run"])):
                self.assertTrue(var in s.get("env", {}) or var in builtin or var in local, f"{s.get('name')}: ${var} is not declared in env")
    def test_the_apply_role_of_the_same_env_is_used(self) -> None:
        init = a.step_named(STEPS, "Initialise with the apply role")
        self.assertEqual(init["with"]["role"], "graveyard-ci/graveyard-${{ inputs.env }}-apply")
        self.assertEqual(init["with"]["with-backend"], "true")
        self.assertEqual(a.step_named(STEPS, "Download the build")["with"]["name"], "site-${{ inputs.env }}")
    def test_the_order_is_assets_then_pages_then_invalidation_then_old_assets_then_checks(self) -> None:
        names = [str(s.get("name")) for s in STEPS]
        order = [next(i for i, n in enumerate(names) if frag in n) for frag in (
            "Read the bucket", "Download the build", "Upload the hashed assets", "Upload every other file", "Invalidate", "Delete the hashed assets", "Check the live site")]
        self.assertEqual(order, sorted(order))
    def test_the_two_cache_control_values_and_the_delete_flags(self) -> None:
        assets = a.step_named(STEPS, "Upload the hashed assets")["run"]
        self.assertIn('--cache-control "public,max-age=31536000,immutable"', assets)
        self.assertNotIn("--delete", assets)
        pages = a.step_named(STEPS, "Upload every other file")["run"]
        self.assertIn('--exclude "_next/static/*"', pages)
        self.assertIn('--cache-control "no-cache"', pages)
        self.assertIn("--delete", pages)
        old = a.step_named(STEPS, "Delete the hashed assets")["run"]
        self.assertIn('"s3://$BUCKET/_next/static" --delete', old)
    def test_nothing_reads_objects_or_changes_the_bucket_itself(self) -> None:
        run = "".join(s.get("run", "") for s in STEPS)
        for forbidden in ("s3 cp", "s3 rm", "s3api", "get-object", "put-bucket", "rb "):
            self.assertNotIn(forbidden, run)
@unittest.skipUnless(BASH, "needs bash")
class Execution(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_ctx.cleanup)
        self.tmp = Path(self.tmp_ctx.name)
        self.shims = Shims(self.tmp)
        self.out = self.tmp / "out"
        self.out.write_text("")
        self.site = self.tmp / "site"
    def run_step(self, fragment: str, env: Dict[str, str]) -> subprocess.CompletedProcess:
        step = a.step_named(STEPS, fragment)
        full = {"PATH": f"{self.shims.bin}:{os.environ.get('PATH', '')}", "HOME": str(self.tmp), "GITHUB_OUTPUT": str(self.out), "CALLS": str(self.shims.log), **env}
        return subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", step["run"]], env=full, cwd=self.tmp, capture_output=True, text=True)
    def build_site(self, extra: Optional[Dict[str, str]] = None) -> None:
        files = {"index.html": "<html>", "404.html": "<html>", "scan.html": "<html>", "grave.html": "<html>", "scan.txt": "t", "__next.scan.txt": "t",
                 "_next/static/chunks/a1b2.js": "x", "_next/static/media/f.woff2": "x", "scan/__next.scan.txt": "t", **(extra or {})}
        for name, text in files.items():
            path = self.site / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    # ---- the target
    def terraform_prints(self, bucket: str = "graveyard-dev-site-0a1b2c3d", distribution: str = "E2EXAMPLE12345", url: str = "https://dev.lastrites.dev") -> None:
        self.shims.make("terraform", f'case "$*" in\n  *site_bucket_name) printf "%s" "{bucket}" ;;\n  *site_distribution_id) printf "%s" "{distribution}" ;;\n  *site_url) printf "%s" "{url}" ;;\nesac\n')
    def test_the_target_is_read_from_the_state_and_written_as_outputs(self) -> None:
        self.terraform_prints()
        done = self.run_step("Read the bucket", {"ENV_NAME": "dev"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.out.read_text().splitlines(), ["bucket=graveyard-dev-site-0a1b2c3d", "distribution=E2EXAMPLE12345", "site-url=https://dev.lastrites.dev"])
    def test_the_target_is_refused_when_it_is_not_this_envs_site(self) -> None:
        for kwargs in ({"bucket": "graveyard-prod-site-0a1b2c3d"}, {"bucket": "graveyard-dev-artefacts-0a1b2c3d"}, {"bucket": "graveyard-dev-site-0a1b2c3d; rm"}, {"distribution": "not-an-id"}, {"url": "http://dev.lastrites.dev"}):
            self.out.write_text("")
            self.terraform_prints(**kwargs)
            done = self.run_step("Read the bucket", {"ENV_NAME": "dev"})
            self.assertNotEqual(done.returncode, 0, kwargs)
            self.assertEqual(self.out.read_text(), "", kwargs)
    # ---- the download
    def test_a_download_that_is_not_a_finished_site_is_refused(self) -> None:
        self.build_site()
        self.assertEqual(self.run_step("Check that the download", {"SITE_DIR": str(self.site)}).returncode, 0)
        (self.site / "404.html").unlink()
        self.assertNotEqual(self.run_step("Check that the download", {"SITE_DIR": str(self.site)}).returncode, 0)
        self.build_site()
        (self.site / "mockServiceWorker.js").write_text("// mock")
        self.assertNotEqual(self.run_step("Check that the download", {"SITE_DIR": str(self.site)}).returncode, 0)
    # ---- the uploads
    def test_the_sync_commands_are_run_as_designed(self) -> None:
        self.shims.make("aws", 'printf "%s\\n" "$*" >> "$CALLS"\n')
        self.build_site()
        env = {"SITE_DIR": str(self.site), "BUCKET": "graveyard-dev-site-0a1b2c3d"}
        for fragment in ("Upload the hashed assets", "Upload every other file", "Delete the hashed assets"):
            self.assertEqual(self.run_step(fragment, env).returncode, 0, fragment)
        calls = self.shims.calls()
        self.assertEqual(calls[0], f"s3 sync {self.site}/_next/static s3://graveyard-dev-site-0a1b2c3d/_next/static --cache-control public,max-age=31536000,immutable --only-show-errors")
        self.assertEqual(calls[1], f"s3 sync {self.site} s3://graveyard-dev-site-0a1b2c3d --exclude _next/static/* --cache-control no-cache --delete --only-show-errors")
        self.assertEqual(calls[2], f"s3 sync {self.site}/_next/static s3://graveyard-dev-site-0a1b2c3d/_next/static --delete --only-show-errors")
    # ---- the invalidation
    def invalidated_paths(self) -> list:
        self.shims.make("aws", 'printf "%s\\n" "$*" >> "$CALLS"\necho I123\n')
        done = self.run_step("Invalidate", {"SITE_DIR": str(self.site), "DISTRIBUTION": "E2EXAMPLE12345"})
        self.assertEqual(done.returncode, 0, done.stderr)
        call = self.shims.calls()[-1]
        self.assertTrue(call.startswith("cloudfront create-invalidation --distribution-id E2EXAMPLE12345 --paths "), call)
        return call.split(" --paths ")[1].split(" --query")[0].split(" ")
    def test_the_invalidation_lists_every_page_and_clean_url_and_no_hashed_asset(self) -> None:
        self.build_site()
        paths = self.invalidated_paths()
        self.assertEqual(sorted(paths), sorted(["/", "/index.html", "/404.html", "/404", "/scan.html", "/scan", "/grave.html", "/grave", "/scan.txt", "/__next.scan.txt", "/scan/__next.scan.txt"]))
        self.assertFalse([p for p in paths if p.startswith("/_next/static")])
    def test_a_site_with_more_than_50_paths_is_invalidated_as_a_whole(self) -> None:
        self.build_site({f"page{i}.html": "<html>" for i in range(60)})
        self.assertEqual(self.invalidated_paths(), ["/*"])
    # ---- the live site
    def curl_shim(self, headers: str = GOOD_HEADERS, asset_headers: str = IMMUTABLE, missing_status: int = 404, www_status: int = 301) -> None:
        self.shims.make("curl", f'''args=("$@")
url="${{args[$#-1]}}"
hdr=""; out=/dev/null; wo=""
for ((i = 0; i < $#; i++)); do
  case "${{args[$i]}}" in
    --dump-header) hdr="${{args[$((i + 1))]}}" ;;
    --output) out="${{args[$((i + 1))]}}" ;;
    --write-out) wo="${{args[$((i + 1))]}}" ;;
  esac
done
printf "%s\\n" "$url" >> "$CALLS"
status=200; body="<html>ok</html>"; h='{headers}'
case "$url" in
  */_next/static/*) h='{asset_headers}' ;;
  */graveyard-smoke-missing-page) status={missing_status}; body="<html>404</html>" ;;
  https://www.*) status={www_status} ;;
esac
if [ -n "$hdr" ]; then printf 'HTTP/2 %s\\r\\n%s\\r\\n' "$status" "$h" > "$hdr"; fi
if [ "$out" != /dev/null ]; then printf "%s" "$body" > "$out"; fi
if [ -n "$wo" ]; then printf "%s" "$status"; fi
''')
    def live(self, env_name: str = "dev", url: str = "https://dev.lastrites.dev") -> subprocess.CompletedProcess:
        self.build_site()
        return self.run_step("Check the live site", {"ENV_NAME": env_name, "SITE_URL": url, "SITE_DIR": str(self.site), "WORK_DIR": str(self.tmp)})
    def test_a_correct_live_site_passes_and_the_asset_checked_is_a_hashed_script(self) -> None:
        self.curl_shim()
        done = self.live()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("https://dev.lastrites.dev/_next/static/chunks/a1b2.js", self.shims.calls())
        self.assertFalse([c for c in self.shims.calls() if "www." in c], "dev has no www redirect")
    def test_each_wrong_header_or_status_fails_the_check(self) -> None:
        cases = {
            "no hsts": dict(headers=GOOD_HEADERS.replace("strict-transport-security: max-age=63072000; includeSubDomains\r\n", "")),
            "short hsts": dict(headers=GOOD_HEADERS.replace("63072000", "300")),
            "no csp": dict(headers=GOOD_HEADERS.replace("content-security-policy: default-src 'self'\r\n", "")),
            "no nosniff": dict(headers=GOOD_HEADERS.replace("x-content-type-options: nosniff\r\n", "")),
            "pages cached": dict(headers=GOOD_HEADERS.replace("cache-control: no-cache", "cache-control: max-age=600")),
            "assets not immutable": dict(asset_headers="cache-control: no-cache"),
            "unknown path is 200": dict(missing_status=200),
        }
        for name, kwargs in cases.items():
            self.curl_shim(**kwargs)
            self.assertNotEqual(self.live().returncode, 0, name)
    def test_prod_also_checks_the_www_redirect(self) -> None:
        self.curl_shim()
        done = self.live("prod", "https://lastrites.dev")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("https://www.lastrites.dev/scan", self.shims.calls())
        self.curl_shim(www_status=200)
        self.assertNotEqual(self.live("prod", "https://lastrites.dev").returncode, 0)
if __name__ == "__main__":
    unittest.main()
