# Runbook: the edge (lastrites.dev)
Spec: `.kiro/specs/infra-edge/` (requirements `EDGE-*`, design). This runbook is for the first deploys, the checks after them, and what to do when something is off. Nothing here needs an AWS access key: CI deploys, and you use the console and `curl`.

## 1. What exists

| | dev | prod |
|---|---|---|
| Site | `https://dev.lastrites.dev` | `https://lastrites.dev` (`www` answers 301 to it) |
| API | `https://api.dev.lastrites.dev` | `https://api.lastrites.dev` |
| Web ACL (WAF) | none (optional: `enable_waf = true`) | `graveyard-prod-edge`: IP reputation, a per-IP rate limit on `POST /v1/scans` (20 per 5 minutes, then 429), Common, KnownBadInputs |
| Certificate | one ACM certificate in us-east-1 per env, DNS-validated in the hosted zone | same |
| Alarms | `graveyard-dev-cdn-site-5xx`, `graveyard-dev-cdn-api-5xx` in us-east-1, topic `graveyard-dev-edge-alerts` | the same with `prod` |
| Site bucket | `graveyard-dev-site-<random>`, private, versioned, reached through an origin access control only | `graveyard-prod-site-<random>` |

The hosted zone is yours: Terraform writes `A`, `AAAA` and ACM validation `CNAME` records into it and nothing else. It never creates, imports or reads the zone.

## 2. Before the first deploy
1. The bootstrap root is applied with the edge permissions (`terraform-bootstrap.md`, section 15). Done on 25 Nov 2026.
2. The repository variable `ROUTE53_ZONE_ID` is set (`github-environments.md`, section 1).
3. The `prod` environment still has you as required reviewer.

## 3. The first deploy
1. Merge to `main`. CI plans dev and prod, applies dev, then waits for your approval of prod. The same approval covers the prod apply and the prod site upload.
2. Expect in dev: the certificate takes a few minutes to validate; the two distributions take 5 to 15 minutes to deploy; then the site is uploaded and checked by the workflow itself (headers, `/scan`, a 404, the immutable asset header).
3. Do the checks in section 4 on dev before you approve prod.
4. Approve prod. In prod the workflow also checks that `www` answers 301.
5. In the console, region **us-east-1**, SNS: subscribe your email to `graveyard-dev-edge-alerts`, confirm the mail, and do the same for `graveyard-prod-edge-alerts`. (They are in us-east-1 because CloudFront publishes its metrics only there.)

## 4. Checks after a first deploy (tell the agent the result)
Replace the host for prod. `-sI` shows headers only.
1. Pages: open `https://dev.lastrites.dev/`, `/scan` and `/grave`; `/nope` shows the 404 page. Reload `/scan?id=x`: it still loads (clean URLs).
2. Headers on a 200:
   ```sh
   curl -sI https://dev.lastrites.dev/ | grep -iE '^(strict-transport|content-security|x-content-type|referrer-policy|cache-control)'
   ```
   Expect HSTS `max-age=63072000; includeSubDomains`, the CSP of EDGE-HDR-2, `nosniff`, `strict-origin-when-cross-origin` and `cache-control: no-cache`.
   On `curl -sI https://dev.lastrites.dev/nope` the security headers are **expected to be missing**: CloudFront does not run the headers function for an origin error (EDGE-HDR-4, H20). Report what you see.
3. Browser console on `/`, `/scan` and `/grave`: **no Content-Security-Policy violation**. This is the one check that proves the CSP (design 7.2). If something is blocked, copy the console line; do not loosen the policy by hand.
4. A scan started from the page reaches `https://api.dev.lastrites.dev` with no CORS error. `curl -si https://api.dev.lastrites.dev/v1/scans/not-an-id` returns the API's own problem document and status, not an HTML page.
5. Prod only, the `www` redirect with a query string (R13):
   ```sh
   curl -sI 'https://www.lastrites.dev/scan?id=a%20b' | grep -i '^location'
   ```
   Expect `location: https://lastrites.dev/scan?id=a%20b` (the same bytes, not `a%2520b`).
6. Prod only (dev has no web ACL): the WAF console in us-east-1 shows sampled requests for `graveyard-prod-edge`; 25 quick `POST https://api.lastrites.dev/v1/scans` calls from one address start returning 429. Use a short script and an empty body, and expect 400s before the 429s.
7. Cache: a hashed asset has `cache-control: public,max-age=31536000,immutable` and the second request shows `x-cache: Hit from cloudfront`; `/` has `cache-control: no-cache`.
8. CloudWatch, us-east-1, Alarms: the two alarms are `OK` or `Insufficient data`, not in an error state.

## 5. If a deploy fails
| Where | Likely cause | What to do |
|---|---|---|
| plan job, `AccessDenied` on a Route 53, CloudFront, WAF or ACM read | a plan-role permission is missing | Copy the action and the resource (no account ID). It is a new request to the bootstrap root; do not widen anything by hand. |
| apply job, `AccessDenied` | an apply-role permission is missing, or the unverified items of design 2.3 | Same. Design section 13 lists every call that was checked; a failure outside that list is new. |
| apply job, certificate stays `PENDING_VALIDATION` | a validation record is missing or wrong | Console, Route 53, the zone: there must be one `CNAME` per hostname, name and value as ACM shows them. Terraform fails after about 75 minutes; re-run the failed jobs. |
| apply job, "alias already in use" on a distribution | an old distribution or another account's still holds the hostname | Console, CloudFront: find the distribution that lists the hostname and remove the alias. Do not delete it unless it is yours. |
| apply job, a Route 53 `ChangeResourceRecordSets` denied | the record name or type is outside what the role may change | Expected for any name not listed in A5-3 of `infra-foundation`; tell the agent. The prod role can never change a name ending in `dev.lastrites.dev`. |
| site job, a smoke check fails right after the apply | CloudFront or DNS was still settling | Re-run the failed jobs once. If the same check fails again, it is a real failure: see section 4. |
| `deploy-site` step fails on `terraform output` | the apply did not finish creating the bucket | Re-run the failed jobs after the apply succeeded. |

## 6. Routine
- **Publish only the web app again:** re-run the failed or the last `deploy` job from the Actions tab, or push any change under `web/`. The build runs without credentials, the upload is incremental.
- **Roll back the site:** revert the commit on `main`. CI rebuilds the old site and uploads it. The bucket is versioned, so a bad upload can also be undone in the console (S3, the bucket, Show versions, delete the newer versions) followed by an invalidation of `/*` in CloudFront.
- **Turn the web ACL on in dev:** set `enable_waf = true` in `infra/envs/dev/terraform.tfvars` locally or add the variable in CI; it creates `graveyard-dev-edge` (about USD 9 a month).
- **Change the rate limit:** `scan_rate_limit` (variable of the env roots, 10 or more).
- **Destroy:** CloudFront must disable a distribution before deleting it (15 minutes or more), and the site bucket (`force_destroy = false`) must be emptied, including old versions, first.

## 7. Open items (security review)
H12 to H20 in `terraform-bootstrap.md`, section 13: WAF logging, the open `execute-api` URL, tightening `script-src`, review of E11 and E12, CloudFront logs, WAF rule tuning, a dedicated site-deploy role, CAA and DNSSEC, headers on error responses.
Unverified until the first deploy (design 2.3): whether CreateWebACL needs rights on managed rule sets, whether CloudFront checks the web ACL, certificate or function with the caller's rights, the region of Route 53 calls, that a CloudWatch alarm cannot notify a topic in another region, the encoding of query-string values in CloudFront Functions, and whether the 404 page gets the headers function.
