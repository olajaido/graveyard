# Spec: infra-edge (LEAN)
> **Status:** REVISION 3 (25 Nov 2026): the maintainer's review decisions R1 to R13 are applied (`design.md` §1). Security headers come from CloudFront Functions, not a response headers policy; the web ACL exists in prod only; the prod apply role is explicitly denied dev records. T1 to T13.1 are done (bootstrap applied by the maintainer on 25 Nov 2026); the next step is the maintainer's T13.2 (set `ROUTE53_ZONE_ID`, then merge). Design in `design.md`, tasks in `tasks.md`.
> **Goal:** host the web app and the API on `lastrites.dev`. Prod: site `https://lastrites.dev` (`www` redirects to it), API `https://api.lastrites.dev`. Dev: site `https://dev.lastrites.dev`, API `https://api.dev.lastrites.dev`.
> **Source of truth:** `docs/PRD.md` §10.1 to §10.3 (CloudFront, WAF, static site), §12 (cost), §13 (T7 cost exhaustion), `tech.md`, `security.md`, `terraform.md` (S3, CloudFront and WAF section), `web/README.md` "Host contract", specs `infra-foundation` (names, tags, roles, INF-REG, INF-SHARED, INF-TEST), `scan-backend` (API, SB-API-9 CORS), `ui-core` (UI-CORS-1).
> **Out of scope:** creating or importing the hosted zone; WAF and CloudFront access logs (H12, H16); a CloudFront function or Lambda@Edge for anything but clean URLs and the www redirect; custom error pages beyond `404.html`; the Rites GitHub App (`github-app-pull-requests`); Route 53 health checks and DNSSEC (H19).
> **Lean rules (maintainer):** normal tests only (`terraform test` with mocks, guards, checkov, tflint, python unit tests); the agent never runs `terraform init` against a backend, `terraform plan/apply`, or the `aws` CLI, and never reads `~/.aws` or `AWS_*` variables (`scripts/ci/local-checks.sh` only); every real apply and every AWS console or CLI step is a MANUAL task for the maintainer; a permission the roles lack is listed, never worked around.

## Glossary for this spec

| Term | Meaning |
|------|---------|
| **Zone** | The existing public Route 53 hosted zone for `lastrites.dev`, made by hand. This spec manages records in it and nothing else. |
| **Site host** | `lastrites.dev` in prod, `dev.lastrites.dev` in dev. |
| **API host** | `api.<site host>`. |
| **Site distribution** | The CloudFront distribution that serves the S3 site bucket. |
| **API distribution** | The CloudFront distribution whose origin is the HTTP API `$default` stage. |
| **Edge ACL** | The WAFv2 web ACL (scope CLOUDFRONT, us-east-1) of one env, attached to both of its distributions. Prod only by default (EDGE-WAF-4). |
| **Edge alerts topic** | The SNS topic in us-east-1 that the two distribution alarms notify (design R1). |
| **Headers function** | A CloudFront Function on the `viewer-response` event that sets security response headers. |

---

## 1. DNS and certificates

| ID | Requirement |
|----|-------------|
| EDGE-DNS-1 | THE system SHALL manage only records in the zone. It SHALL NOT create, import or read the zone: no `aws_route53_zone` resource, no `data "aws_route53_zone"`, no `terraform import` for it. The zone ID SHALL be the variable `route53_zone_id` of the env roots and of the bootstrap root, supplied at run time (GitHub repository variable `ROUTE53_ZONE_ID` in CI, git-ignored tfvars locally). Modules SHALL receive it as an input and declare no data source (INF-POL-1). |
| EDGE-DNS-2 | THE hostnames SHALL be built in the env roots from one variable `domain_name` (default `lastrites.dev`) and the env: site host = `domain_name` in prod and `<env>.<domain_name>` otherwise; API host = `api.<site host>`; prod also has `www.<domain_name>`. The two roots SHALL stay identical except for the env name (INF-LAY-4), so this is a `local` with the same text in both. |
| EDGE-DNS-3 | EVERY hostname that serves traffic SHALL have an alias `A` and an alias `AAAA` record to its CloudFront distribution. The system SHALL create no other record type except the ACM validation `CNAME` records. |
| EDGE-CERT-1 | EACH env SHALL have one ACM certificate in us-east-1 whose names are exactly that env's hostnames (EDGE-DNS-2), validated by DNS with records created in the zone. The distributions SHALL wait for the issued certificate. The certificate SHALL have `create_before_destroy`. |
| EDGE-CERT-2 | THE env roots SHALL declare a provider alias `aws.us_east_1` with the same `allowed_account_ids` and `default_tags` as the default provider. Modules that need it (`edge-cert`, `edge-waf`, `edge-alarms`) receive it as their one default provider through an explicit `providers = {}` map; no module declares `configuration_aliases` (a module with one cannot be validated on its own) and none inherits it implicitly. |

## 2. Site distribution

| ID | Requirement |
|----|-------------|
| EDGE-SITE-1 | THE site bucket SHALL be named `graveyard-<env>-site-<random suffix>` and have: all four Block Public Access settings; `BucketOwnerEnforced`; versioning; default encryption (SSE-S3, design R6); a lifecycle rule that expires noncurrent versions after a configurable number of days (default 30) and aborts incomplete multipart uploads after 7 days; a bucket policy that denies non-TLS requests and allows `s3:GetObject` only to the CloudFront service principal when `AWS:SourceArn` equals this env's site distribution; no ACL, no website configuration, `force_destroy = false`. |
| EDGE-SITE-2 | THE site distribution SHALL read the bucket through an origin access control (SigV4, always). It SHALL redirect HTTP to HTTPS, allow only `GET` and `HEAD`, use TLS 1.2 or later (`TLSv1.2_2021`) with SNI only, enable HTTP/2, HTTP/3 and IPv6, compress responses, use the default root object `index.html`, and be attached to the Edge ACL when the env has one (EDGE-WAF-1). |
| EDGE-SITE-3 | A CloudFront Function on the `viewer-request` event of the site distribution SHALL: map an extensionless path to its `.html` file (`/scan` to `/scan.html`, `/scan/` to `/scan.html`, `/` to `/index.html`) and leave any path whose last segment has an extension unchanged (web README host contract, point 2); and, in prod only, answer a request for `www.<domain_name>` with `301` to `https://<domain_name>` with the same path and query string. |
| EDGE-SITE-4 | THE site distribution SHALL have custom error responses that turn an S3 `403` and `404` into `/404.html` with response code `404` and an error caching TTL of 10 seconds. THE API distribution SHALL NOT have custom error responses (EDGE-API-2). |

## 3. API distribution

| ID | Requirement |
|----|-------------|
| EDGE-API-1 | THE API distribution SHALL have the HTTP API's `$default` stage host as its only origin (HTTPS only, TLS 1.2, no origin path), allow all methods (`GET`, `HEAD`, `OPTIONS`, `PUT`, `POST`, `PATCH`, `DELETE`), accept only HTTPS from viewers, use the AWS-managed `CachingDisabled` cache policy, and use the AWS-managed `AllViewerExceptHostHeader` origin request policy, so query strings, cookies and viewer headers (including `Origin` and `Authorization`) reach the API and the `Host` header does not. It SHALL be attached to the Edge ACL when the env has one, and use the same certificate and TLS settings as EDGE-SITE-2. |
| EDGE-API-2 | THE API distribution SHALL NOT have custom error responses, a viewer-request function, or a response headers policy. Its only function is the headers function of EDGE-HDR-3, which adds headers and changes no status code, body or other header, so every API status code and body (RFC 9457 problem documents included) reaches the browser unchanged. |
| EDGE-API-3 | `design.md` SHALL state why there are two distributions: custom error responses apply to a whole distribution, and a WAF web ACL cannot be attached to an HTTP API directly. |

## 4. Headers and caching

| ID | Requirement |
|----|-------------|
| EDGE-HDR-1 | THE site distribution SHALL have a headers function on `viewer-response` that sets, replacing any origin value: `Strict-Transport-Security: max-age=63072000; includeSubDomains`; `Content-Security-Policy` as EDGE-HDR-2; `X-Content-Type-Options: nosniff`; `Referrer-Policy: strict-origin-when-cross-origin`. `frame-ancestors 'none'` in the CSP covers framing, so there is no `X-Frame-Options`. There SHALL be no response headers policy anywhere in this spec. |
| EDGE-HDR-2 | THE CSP SHALL be `default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self' https://<API host>; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; upgrade-insecure-requests`. `'unsafe-inline'` is allowed in `script-src` only because the Next.js static export writes three inline scripts into every HTML file (design §7.2); there SHALL be no inline style at all (no `style-src-attr` exception: the export has no `style="…"` attribute and no `<style>` element, and `npm run check:build` fails if one appears), no `'unsafe-eval'`, no wildcard and no origin other than the API host. The string SHALL be built from the API host input, never typed twice. |
| EDGE-HDR-3 | THE API distribution SHALL have a headers function on `viewer-response` that sets only `Strict-Transport-Security: max-age=63072000; includeSubDomains` and `X-Content-Type-Options: nosniff`. |
| EDGE-HDR-4 | CloudFront does not invoke a viewer-response function when the origin returns status 400 or higher (CloudFront developer guide, edge function restrictions). So the 404 page, S3 errors and API error responses are **not** given these headers. This is accepted and recorded (H20); no test or smoke check SHALL assume the headers on an error response. |
| EDGE-CACHE-1 | THE deploy SHALL upload every object under `/_next/static/` with `Cache-Control: public, max-age=31536000, immutable` and every other object with `Cache-Control: no-cache`. THE site distribution SHALL use the AWS-managed `CachingOptimized` cache policy, which honours these values. |

## 5. WAF

| ID | Requirement |
|----|-------------|
| EDGE-WAF-1 | WHEN an env has the Edge ACL (EDGE-WAF-4), it SHALL be one web ACL, scope `CLOUDFRONT`, in us-east-1, default action allow, named `graveyard-<env>-edge`, attached to both distributions of that env. Its rules SHALL be, in this order: `AWSManagedRulesAmazonIpReputationList`, the rate rule of EDGE-WAF-2, `AWSManagedRulesCommonRuleSet`, `AWSManagedRulesKnownBadInputsRuleSet`. The managed groups SHALL use `override_action { none {} }` (their own actions apply). |
| EDGE-WAF-2 | THE rate-based rule SHALL count requests per source IP over a 300-second window and block the IP above a limit (variable, default 20) with response code 429. It SHALL count only requests that match both `POST` and the URI path exactly `/v1/scans`. Justification: design §9.2. |
| EDGE-WAF-3 | THE web ACL and every rule SHALL have CloudWatch metrics and sampled requests enabled. The web ACL SHALL have no logging configuration (H12). |
| EDGE-WAF-4 | THE Edge ACL SHALL exist in prod and SHALL NOT exist in dev by default. The root variable `enable_waf` (bool, default `null`, same text in both roots) overrides that: `null` means prod only, `true` turns it on in dev. Without the ACL the dev API is protected only by API Gateway stage throttling. "WAF on dev" is optional, not required. |
| EDGE-COST-1 | THE price class of both distributions SHALL be a variable with default `PriceClass_100`. `design.md` §9.3 SHALL state the WAF fixed cost against the budget. |

## 6. CORS

| ID | Requirement |
|----|-------------|
| EDGE-CORS-1 | `cors_allowed_origins` of the prod root SHALL default to `["https://lastrites.dev"]`; of the dev root to `["https://dev.lastrites.dev", "http://localhost:5173"]`. A root test SHALL fail if the first entry differs from `https://<site host>`. No wildcard (scan-backend SB-API-9, ui-core UI-CORS-1). |

## 7. Observability

| ID | Requirement |
|----|-------------|
| EDGE-OBS-1 | EACH distribution SHALL have a CloudWatch alarm on its 5xx error rate: `AWS/CloudFront` `5xxErrorRate` (average, 5 minutes) above 2 percent, evaluated only when the distribution had at least 10 requests in the same period (otherwise the alarm value is 0). Missing data SHALL not breach. Names: `graveyard-<env>-cdn-site-5xx` and `graveyard-<env>-cdn-api-5xx`. |
| EDGE-OBS-2 | CloudFront publishes its metrics in us-east-1 only, so the alarms live in us-east-1. A CloudWatch alarm notifies only an SNS topic in its own region, so the alarms SHALL notify the Edge alerts topic `graveyard-<env>-edge-alerts` in us-east-1, with no subscription in Terraform (the maintainer subscribes by hand, as for the eu-west-2 topic). This replaces "the existing SNS topic" (design R1). |

## 8. Web deploy

| ID | Requirement |
|----|-------------|
| EDGE-DEP-1 | `deploy.yml` SHALL, for each env, build `web/` in a job with no AWS credentials and no environment, with `NEXT_PUBLIC_API_URL` set to that env's API URL (`https://<API host>`), run `npm run check:build`, and pass `out/` to the deploy job as a workflow artifact. |
| EDGE-DEP-2 | THE deploy job of an env SHALL be the existing `apply-<env>` job (same GitHub environment, same role, same approval: prod still waits for its required reviewer). After the Terraform apply step, or in place of it when the env's plan had no changes, it SHALL: read the bucket name and distribution ID from `terraform output` of that env's root; sync the artifact to the bucket in this order: hashed assets with the EDGE-CACHE-1 immutable header (no delete), then every other file with `no-cache` and `--delete`; create one CloudFront invalidation for the non-hashed paths; then delete removed hashed assets; then run the smoke checks of EDGE-DEP-4. |
| EDGE-DEP-3 | THE deploy SHALL run when the web app changed or when an env's plan has changes. A change under `web/` alone SHALL reach `deploy.yml`, which today it does not (design §11.1). A failed or cancelled `web` or `plan-*` job SHALL stop the deploy. A failed web build SHALL NOT stop an infrastructure apply: the apply step runs and the job then fails because the artifact is missing. |
| EDGE-DEP-4 | AFTER the sync the job SHALL check, with `curl` and retries, that `https://<site host>/` answers 200, `/scan` answers 200, an unknown path answers 404 with the 404 page, and the response carries the HSTS and CSP headers. A failed check fails the job. |
| EDGE-DEP-5 | No step that runs project code (`npm ci`, `npm run build`) SHALL run in a job that holds AWS credentials. The artifact SHALL contain only `out/`. |

## 9. IAM and region (bootstrap root, applied by the maintainer)

| ID | Requirement |
|----|-------------|
| EDGE-IAM-1 | THE bootstrap root SHALL extend the plan role and both apply roles with exactly the permissions of design §12, as one new managed policy per apply role (`graveyard-<env>-apply-edge-extra`) and one for the plan role (`graveyard-plan-read-edge-extra`), plus the listed additions to existing action lists and the guard change of EDGE-IAM-4. THE design SHALL hold the audit table of every API call per new resource type (design §13) and `tasks.md` SHALL check each row against the policy JSON. |
| EDGE-IAM-2 | **Exception E12.** `route53:ChangeResourceRecordSets` on the exact zone ARN only, with `ForAllValues` conditions on the record names of this env's hostnames (and `_*.<site host>` for the ACM validation records), the record types `A`, `AAAA`, `CNAME`, and the actions `CREATE`, `UPSERT`, `DELETE`, with `Null` checks that the three keys are present. Also `route53:GetHostedZone` and `route53:ListResourceRecordSets` on the zone ARN and `route53:GetChange` on `change/*`. Reason: Route 53 supports no tag condition and the zone has no Graveyard name (INF-SHARED-1), so no name or tag scoping is possible. |
| EDGE-IAM-3 | THE prod apply role SHALL be explicitly denied `route53:ChangeResourceRecordSets` when any normalized record name of the request matches `*dev.<domain_name>` (`ForAnyValue:StringLike` on `route53:ChangeResourceRecordSetsNormalizedRecordNames`), so prod can never change a dev record, including dev's ACM validation records. The deny sits in the prod apply guard policy; the dev guard has no such statement. A test SHALL assert the exact statement and that no Allow of the prod role is wider than its own names. |
| EDGE-IAM-4 | **Exception E11 (region).** In the plan guard and both apply guards only, the region deny SHALL also let these actions run in us-east-1: the four Route 53 actions of EDGE-IAM-2; `cloudwatch:PutMetricAlarm`, `DeleteAlarms`, `DescribeAlarms`, `TagResource`, `UntagResource`, `ListTagsForResource`; and the SNS topic actions already used for the eu-west-2 topic. Their Allow statements are scoped to `graveyard-<env>-*` alarm and topic ARNs in us-east-1. ACM, WAFv2 and CloudFront in us-east-1 are already allowed by INF-REG-2. Everything else outside eu-west-2 stays denied. THE workload boundaries SHALL NOT change (byte for byte). |
| EDGE-IAM-5 | THE apply roles SHALL get object-level `s3:PutObject`, `s3:DeleteObject` and `s3:AbortMultipartUpload` on `arn:<p>:s3:::graveyard-<env>-site-*/*` only. They SHALL get no cache-policy or origin-request-policy permission (the AWS-managed policies are used by ID, EDGE-SITE-2, EDGE-API-1). |
| EDGE-IAM-6 | EVERY managed policy of a CI role SHALL stay at most 6,144 characters and every role at most 10 attached managed policies (INF-TEST-2); each apply role has 7 today and 8 after this change. The current sizes and the margin are in design §12.5. |
| EDGE-IAM-7 | THE statements that carry `Resource = "*"` or a generated ID SHALL stay on the fixed lists of `shared_account.tftest.hcl`, updated by this spec: E12 joins the exception list with its zone ARN; the new `star_reads` entries are metadata `Get` and `List` actions only. No response-headers-policy action is allowed anywhere. |
| EDGE-IAM-8 | `infra-foundation` SHALL be amended (A5): INF-APPLY-2 adds Route 53; INF-SHARED-4 lists E11 and E12; INF-REG-2 lists the E11 actions; INF-SHARED-3 is unchanged (creating cache and response-headers policies stays forbidden). |

## 10. Tags and names

| ID | Requirement |
|----|-------------|
| EDGE-TAG-1 | BOTH AWS providers (default and `us_east_1`) SHALL set the PRD §14.1 `default_tags` (INF-TAG-1). Every named resource SHALL start with `graveyard-<env>-` (INF-NAME-1). The design SHALL list the resources that cannot carry tags (INF-TAG-3): origin access control and Route 53 records. |
| EDGE-TAG-2 | THE zone is tagged `Project=graveyard` by the maintainer (EDGE-MAN-1). No policy relies on that tag: Route 53 has no tag condition. |

## 11. Verification

| ID | Requirement |
|----|-------------|
| EDGE-TEST-1 | EACH new module (`edge-cert`, `edge-waf`, `edge-site`, `edge-api`, `edge-alarms`) SHALL have `terraform test` files that run offline with `mock_provider` and assert the requirements of sections 1 to 7 that apply to it, against the real resource arguments and policy JSON built in `locals`. |
| EDGE-TEST-2 | BOTH env roots SHALL have a plan test with mocked providers (including the aliased one) that checks: the derived hostnames, that both distributions get the same web ACL ARN and that the certificate ARN reaches both, that the CSP in the site headers function names the API host, EDGE-CORS-1, and that dev has no web ACL while prod has one on both distributions. |
| EDGE-TEST-3 | THE three CloudFront Functions (site viewer-request, site headers, API headers) SHALL have Node tests (`node --test`) that load the real template files: clean URLs, the www redirect with a query string and no redirect in a non-prod build; the headers set, replacing an origin value, and every other header left alone. A drift test SHALL assert the site and API headers templates are identical files. |
| EDGE-TEST-4 | `github-oidc` tests SHALL cover EDGE-IAM-1 to EDGE-IAM-8: the E11 guard statements on the three guards and none on the boundaries; E12 exactly; no response-headers-policy action anywhere; the prod deny of EDGE-IAM-3 exactly and absent from the dev guard; the object-level S3 statement; the sizes; the exception and `*` lists. |
| EDGE-TEST-5 | Python tests and guards SHALL be updated: env roots (alias provider, new variables, CORS defaults, no resources); a guard that fails on any `aws_route53_zone` resource or data source; a guard that fails on an `aws_cloudfront_distribution` without a `web_acl_id` argument (its value is null when the env has no ACL); workflow rules for the new jobs; the CI matrices list every new module. |
| EDGE-TEST-6 | checkov and tflint SHALL pass. Each checkov skip is an inline comment with a reason (INF-CI-4). |

## 12. Manual tasks (maintainer)

| ID | Requirement |
|----|-------------|
| EDGE-MAN-1 | Tag the hosted zone `Project=graveyard` (console). |
| EDGE-MAN-2 | Apply the bootstrap root: add `route53_zone_id` to the git-ignored tfvars, plan, run Access Analyzer (V9) on the new and changed policies, apply (`docs/runbooks/terraform-bootstrap.md`). |
| EDGE-MAN-3 | Set the GitHub repository variable `ROUTE53_ZONE_ID`. |
| EDGE-MAN-4 | After the first dev deploy: subscribe an email address to `graveyard-dev-edge-alerts` in us-east-1 and confirm it (and the same for prod after its deploy). |
| EDGE-MAN-5 | After each first deploy: run the checks of `docs/runbooks/edge.md` (headers, redirects, CSP console check, WAF sampled requests). |

---

## Belongs elsewhere

| Item | Belongs in | Why not here |
|------|------------|--------------|
| WAF logging, CloudFront standard logging | H12, H16 of the security review | Both need log-delivery or resource-policy permissions that INF-SHARED-3 forbids; each needs its own exception. |
| Closing the direct `execute-api` URL | H13 | The API distribution calls that URL, so it cannot be disabled; see design R8. |
| Hash-based CSP without `'unsafe-inline'` | H14 | Needs a post-build step in `web/` that feeds per-page hashes to the headers function. |
| Security headers on error responses (404 page, API 4xx and 5xx) | H20 | CloudFront does not run viewer-response functions for origin errors (EDGE-HDR-4). |
| WAF on dev | optional (EDGE-WAF-4) | Decided prod only. |
| CAA records, DNSSEC | H19 | The CI roles may not change those record types by design. |
| WAF `BlockedRequests` alarm (steering "informational") | `observability` | Not requested here. |
