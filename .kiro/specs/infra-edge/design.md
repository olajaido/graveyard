# Design: infra-edge (LEAN)
> Requirements: `requirements.md` in this folder (IDs `EDGE-*`). Requirements win if the two differ.
## 0. Working rule
The agent runs only `scripts/ci/local-checks.sh` (fmt, `init -backend=false`, validate, test, tflint, checkov, actionlint, guards), python unit tests and `node --test`. It never runs `terraform plan/apply` or `init` with a backend, never calls the `aws` CLI, never reads `~/.aws` or `AWS_*`. Every apply and every console or CLI step is a MANUAL task. Facts below were read from public documentation and the provider source on 25 Nov 2026; items marked **unverified** are listed in §2.3.

## 1. Review decisions (taken 25 Nov 2026) and the finding they produced
| # | Decision | Effect on this spec |
|---|----------|---------------------|
| R1 | Approved: `graveyard-<env>-edge-alerts` SNS topic in us-east-1. E11's CloudWatch and SNS actions are allowed in us-east-1 only for `graveyard-<env>-*` alarm and topic ARNs. The subscription is a MANUAL task. | `edge-alarms` stays (§5.5); E11 (§12.1); T14.1. |
| R2 | **Security headers come from CloudFront Functions on `viewer-response`**, not from a response headers policy: a full set on the site, HSTS and nosniff on the API. **E13 is dropped**; no response-headers-policy permission is granted. | §5.3, §5.4, §7, §8.2; E-list ends at E12; INF-SHARED-3 is unchanged. |
| R3 | Approved: only Route 53 (and R1's actions) widen the region guard; the boundaries are not touched. | §12.1. |
| R4 | Approved, plus an explicit Deny on the prod apply role for `route53:ChangeResourceRecordSets` when any normalized record name matches `*dev.lastrites.dev`. | §12.2b; EDGE-IAM-3; test in T1.5. |
| R5 | `'unsafe-inline'` for `script-src` accepted for now. H14 stays and now means: post-build hashes fed to the headers function. The console and CI checks stay. **No `style-src-attr` exception (decision of 25 Nov 2026, after T9 found one `style="…"` attribute on the landing page): the attribute was moved into the CSS class `gy-cursed-shape`, and `npm run check:build` fails on any style attribute in `out/`.** | §7.2, H14. |
| R6 | Approved: SSE-S3 on the site bucket. | §5.3. |
| R7 | **WAF on prod only.** Dev has no web ACL; its API has stage throttling only. "WAF on dev" is optional, not required (`enable_waf`). | §5.2, §6, §9. |
| R8, R11, R12, R13 | Approved as proposed (execute-api bypass accepted, H13; no cache or origin-request policy permissions; deploy by the apply role, H18; query string copied as given, checked by hand). | unchanged |
| R9 | Approved. Each apply role has 7 managed policies today and gets 8; limit 10. The plan role goes from 7 to 8. A test asserts this. | §12.5. |
| R10 | Approved. | §11.1. |
**Finding F1 (found while applying R2).** CloudFront does not invoke a viewer-response function when the origin returns status 400 or higher ("HTTP status codes" in the edge function restrictions page, read 25 Nov 2026). So a headers function cannot add headers to: the site's `404.html` (it comes from a custom error response after an S3 403 or 404), and any API 4xx or 5xx. Successful responses (the pages, assets, API 2xx and 3xx) get the headers. Whether the custom error page also skips the function is not stated beyond that sentence (**unverified**, §2.3). Accepted risk: the 404 page is a static page with no data; HSTS is also preloaded for the whole `.dev` TLD; API error bodies are JSON. For `nosniff` on API errors the API itself would have to send the header (H20). EDGE-HDR-4 records this.
## 2. Facts
### 2.1 Checked
| Fact | Source (25 Nov 2026) |
|------|----------------------|
| Managed response headers policy `SecurityHeadersPolicy` has no CSP, HSTS `max-age=31536000` only, `X-Frame-Options: SAMEORIGIN` | CloudFront developer guide, managed response headers policies |
| CloudFront metrics, including the default `5xxErrorRate`, `Requests`, are published in us-east-1 | CloudFront developer guide, "View CloudFront and edge function metrics" |
| Route 53 supports no tag condition; `hostedzone` has no condition keys; `ChangeResourceRecordSets` supports `…NormalizedRecordNames`, `…RecordTypes`, `…Actions`; names are lowercase, no trailing dot, `_` and `-` allowed | Service Authorization Reference (Route 53) and Route 53 developer guide "Using IAM policy conditions" |
| `CreateDistribution`, `CreateFunction` support `aws:RequestTag`; `distribution` and `function` resources support `aws:ResourceTag`; the function ARN is `function/<name>`; `CreateOriginAccessControl` and `CreateResponseHeadersPolicy` have no resource type or condition key; `CreateDistributionWithTags` maps to `cloudfront:CreateDistribution` plus `cloudfront:TagResource` | Service Authorization Reference (CloudFront) |
| `aws_cloudfront_function` supports `tags` in provider 6.73.0 (so the existing `CreateCloudFrontFunctions` RequestTag condition works) | provider docs v6.73.0 |
| SDK calls per resource type (§13) | provider source v6.73.0, `internal/service/{cloudfront,wafv2,acm,route53,cloudwatch}` |
| Region guard already exempts ACM, WAFv2, CloudFront for us-east-1; Route 53 not | `infra/modules/github-oidc/main.tf` |
| CloudFront does not invoke viewer-response functions when the origin returns 400 or higher | CloudFront developer guide, restrictions on all edge functions ("HTTP status codes") |
| Current managed policy sizes (§12.5) | `terraform test` in a scratch copy of `github-oidc`, mocked provider, no credentials |
| The static export has three inline scripts per HTML file and no inline `<style>` or `style=` attribute | `web/out/*.html` (see §7.2) |
| The POST throttle of the stage is 2 requests per second, burst 5 | `infra/modules/api/variables.tf` |
### 2.2 Verified against the repo
Roots may not declare resources or data sources, and dev and prod must differ only in the env name (`test_env_roots.py`). Modules declare no data sources (INF-POL-1). Policies are `jsonencode` in `locals`.
### 2.3 Unverified (watch at the first apply, listed in the runbook)
1. Whether CreateWebACL needs rights on `managedruleset` ARNs for AWS-managed rule groups. The Service Authorization Reference lists the type as optional; common use suggests it is not needed.
2. Whether CloudFront checks `wafv2:GetWebACL` or ACM permissions with the caller's credentials when a distribution is created. The policies already allow `wafv2:GetWebACL`, `acm:DescribeCertificate` and `acm:ListCertificates`.
3. The reference maps `CreateDistribution` to `cloudfront:CreateConnectionGroup` and `cloudfront:GetVpcOrigin` as well. They matter only for multi-tenant distributions and VPC origins, which this spec does not use. Not granted.
4. That `aws:RequestedRegion` for Route 53 is `us-east-1` (the global-endpoint behaviour that CloudFront and ACM already show). If the first plan shows Route 53 denied in eu-west-2, E11 adds eu-west-2 to the list; it already does.
5. The CloudWatch to SNS same-region rule (R1).
6. The encoding of `querystring` values in CloudFront Functions (R13).
7. Whether the 404 page served by the custom error response gets the headers function (F1). Assumed not.

## 3. Files
```
infra/modules/edge-cert/      main.tf variables.tf outputs.tf versions.tf tests/      ACM certificate + validation records
infra/modules/edge-waf/       ...                                                      web ACL (CLOUDFRONT scope), prod only
infra/modules/edge-site/      ... functions/{viewer-request,viewer-response}.js.tftpl + tests/*.test.mjs   bucket, OAC, two functions, distribution, alias records
infra/modules/edge-api/       ... functions/viewer-response.js.tftpl                                   API distribution, headers function, alias records
infra/modules/edge-alarms/    ...                                                      us-east-1 topic and two alarms
infra/envs/{dev,prod}/        providers.tf (+alias) variables.tf locals.tf main.tf outputs.tf tests/root.tftest.hcl terraform.tfvars.example
infra/modules/github-oidc/    main.tf policies_actions.tf policies_apply_edge_extra.tf (new) policies_plan_read.tf variables.tf + tests
infra/bootstrap/              main.tf variables.tf terraform.tfvars.example
.github/workflows/            ci.yml deploy.yml
.github/actions/deploy-site/  action.yml (new)
.github/actions/terraform-plan/action.yml   (input route53-zone-id)
scripts/ci/                   guards.py tests/*  changed_paths.py (unchanged)
web/scripts/                  check-build.mjs and check-build.test.ts (inline script allow-list, T9)
docs/runbooks/edge.md (new)  terraform-bootstrap.md (H12 to H19, bootstrap steps)  github-environments.md
.kiro/steering/{structure,terraform}.md  infra/README.md  docs/PRD.md §14 module list
```
One module per resource family (`structure.md`): certificate, web ACL, site, API distribution, alarms. Each distribution module owns the alias records of its own hostnames, because the record needs the distribution.

## 4. Architecture
```
viewer ──https──► Route 53 alias (A, AAAA)
                     │
      ┌──────────────┴───────────────┐
      ▼                              ▼
site distribution               API distribution
  viewer-request fn: clean URLs,  viewer-response fn: HSTS, nosniff
    www→apex (prod)               no custom errors, no other fn
  viewer-response fn: HSTS, CSP,  CachingDisabled, all methods
    nosniff, Referrer-Policy      AllViewerExceptHostHeader
  custom errors 403/404→/404.html origin: <id>.execute-api.eu-west-2…/ ($default)
  OAC ► S3 graveyard-<env>-site-*
      └── Edge ACL (WAF, us-east-1): prod only ──┘
   cert: one ACM cert per env, us-east-1, covers all hostnames of the env
```
**Why two distributions (EDGE-API-3).** (1) Custom error responses are a setting of the whole distribution. The site needs 403 and 404 turned into the 404 page; the API must pass every error unchanged. One distribution cannot do both. (2) A WAF web ACL cannot be attached to an HTTP API (API Gateway supports WAF only on REST API stages), and the API still needs the WAF rate rule. Fronting it with CloudFront is how the web ACL reaches it, and it gives the API its own hostname and certificate too.

## 5. Modules
Inputs not listed here: `name_prefix` (`graveyard-<env>`), `env`. Every module declares `required_providers` with exact versions, a committed lock file with `linux_amd64`, `darwin_arm64`, `linux_arm64` hashes (INF-VER-2), and no data source.
### 5.1 `edge-cert`
Provider: one default provider, which the root sets to its us-east-1 provider (a module with `configuration_aliases` cannot be validated on its own, and Route 53 is global, so the records use the same provider). Inputs: `domain_names` (list, first is primary, validated as lower-case hostnames), `zone_id` (validated `^Z[A-Z0-9]+$`).
- `aws_acm_certificate.this`: `domain_name = domain_names[0]`, `subject_alternative_names = slice(…)`, `validation_method = "DNS"`, `key_algorithm = "RSA_2048"`, `lifecycle.create_before_destroy`.
- `aws_route53_record.validation` keyed by the known hostnames, not by the computed set: `for_each = toset(var.domain_names)`, values from `one([for o in cert.domain_validation_options : o if o.domain_name == each.key])`. `allow_overwrite = false`, ttl 60.
- `aws_acm_certificate_validation.this` on the record FQDNs.
Output: `certificate_arn` (from the validation resource, so consumers wait for issuance).
### 5.2 `edge-waf`
Provider: default, passed as `aws.us_east_1` by the root. The root calls it with `count = local.enable_waf ? 1 : 0` (prod only, R7), so the module itself has no switch. Inputs: `scan_rate_limit` (default 20, validated 10 to 2,000,000), `scan_rate_window_seconds` (default 300, validated one of 60, 120, 300, 600). Resource `aws_wafv2_web_acl.this`, scope `CLOUDFRONT`, name `${name_prefix}-edge`, rules per §9.1. Output `web_acl_arn`.
### 5.3 `edge-site`
Provider: default. Inputs: `site_host`, `redirect_www` (bool), `certificate_arn`, `web_acl_arn` (nullable: null in dev), `zone_id`, `api_host`, `price_class`, `noncurrent_expiry_days`. Additional provider: `random`.
Resources: `random_id.suffix` (4 bytes); `aws_s3_bucket.site` and the settings of EDGE-SITE-1 as separate resources (versioning, SSE-S3, public access block, ownership, lifecycle, policy); `aws_cloudfront_origin_access_control.site`; `aws_cloudfront_function.viewer_request` (`${name_prefix}-site-request`) and `aws_cloudfront_function.viewer_response` (`${name_prefix}-site-headers`), both `cloudfront-js-2.0`, `publish = true`, code from `templatefile`; `aws_cloudfront_distribution.site`; `aws_route53_record.alias` for A and AAAA over `[site_host] + (redirect_www ? [www] : [])`. No `aws_cloudfront_response_headers_policy` (R2). The bucket policy is `jsonencode` in `locals` and names the distribution ARN; the distribution depends on the bucket, not on its policy, so there is no cycle.
Distribution settings: one default cache behavior (no ordered behavior: `Cache-Control` comes from the objects, EDGE-CACHE-1), `cache_policy_id = 658327ea-f89d-4fab-a63d-7e88639e58f6` (CachingOptimized), one function association on `viewer-request` and one on `viewer-response`, `compress = true`, `viewer_protocol_policy = "redirect-to-https"`, `allowed_methods = ["GET","HEAD"]`. `custom_error_response` for 403 and 404. `web_acl_id = var.web_acl_arn`. `viewer_certificate { acm_certificate_arn, ssl_support_method = "sni-only", minimum_protocol_version = "TLSv1.2_2021" }`. `restrictions.geo_restriction.none`. `price_class` variable. No logging (H16).
Outputs: `bucket_name`, `bucket_arn`, `distribution_id`, `distribution_arn`, `distribution_domain_name`, `site_url`.
### 5.4 `edge-api`
Provider: default. Inputs: `api_host`, `api_endpoint` (the stage URL; the module strips `https://` with `trimprefix`), `certificate_arn`, `web_acl_arn` (nullable), `zone_id`, `price_class`. Resources: `aws_cloudfront_distribution.api` (origin `custom_origin_config { https_only, origin_ssl_protocols = ["TLSv1.2"] }`, no `origin_path`, behavior of EDGE-API-1: `cache_policy_id = 4135ea2d-6df8-44a3-9df3-4b5a84be39ad`, `origin_request_policy_id = b689b0a8-53d0-40ab-baf2-68738e2966ac`, `viewer_protocol_policy = "https-only"`, all seven methods, `compress = false`, `web_acl_id = var.web_acl_arn`, one `viewer-response` function association), `aws_cloudfront_function.viewer_response` (`${name_prefix}-api-headers`), A and AAAA alias records. Outputs: `distribution_id`, `distribution_arn`, `api_url` (`https://<api_host>`).
`https-only` (not redirect) because a redirect would turn a POST into a GET. The function only adds two headers (§8.2); it cannot change a status code or body, and it does not run for origin errors (F1), so error responses pass through exactly as the API sent them.
### 5.5 `edge-alarms`
Provider: default, passed as `aws.us_east_1`. Inputs: `site_distribution_id`, `api_distribution_id`, `error_rate_threshold` (default 2), `min_requests` (default 10). Resources: `aws_sns_topic.edge` named `${name_prefix}-edge-alerts` (checkov `CKV_AWS_26` skip with the same reason as the existing topic); two `aws_cloudwatch_metric_alarm` named `${name_prefix}-cdn-site-5xx` and `-cdn-api-5xx`. Each is a metric-math alarm: `rate = IF(requests >= min_requests, errors, 0)` where `errors` is `AWS/CloudFront` `5xxErrorRate` (Average, 300 s, dimensions `DistributionId` and `Region = "Global"`) and `requests` is `Requests` (Sum, 300 s). `comparison_operator = GreaterThanThreshold`, `evaluation_periods = 1`, `treat_missing_data = notBreaching`, `alarm_actions = [topic]`. Output `topic_arn`.

## 6. Env roots
`providers.tf` adds the alias:
```hcl
provider "aws" {
  alias               = "us_east_1"
  region              = "us-east-1"
  allowed_account_ids = var.allowed_account_ids
  default_tags { tags = local.tags }
}
```
`variables.tf` adds `domain_name` (default `lastrites.dev`, validated as a lower-case domain), `route53_zone_id` (no default), `enable_waf` (bool, default `null`, same in both roots), `price_class`, `scan_rate_limit`, and changes the default of `cors_allowed_origins` (EDGE-CORS-1; the existing roots test already exempts that block from the "only the env name differs" comparison, and T11 updates its asserted values). `locals.tf` adds, with identical text in both roots:
```hcl
site_host    = local.env == "prod" ? var.domain_name : "${local.env}.${var.domain_name}"
api_host     = "api.${local.site_host}"
redirect_www = local.env == "prod"
hostnames    = concat([local.site_host], local.redirect_www ? ["www.${var.domain_name}"] : [], [local.api_host])
enable_waf   = coalesce(var.enable_waf, local.env == "prod")
```
`main.tf` adds `module "edge_cert"`, `"edge_waf"` (with `count = local.enable_waf ? 1 : 0`), `"edge_site"`, `"edge_api"`, `"edge_alarms"` with explicit `providers`, `api_endpoint = module.api.api_url`, `web_acl_arn = one(module.edge_waf[*].web_acl_arn)` (null in dev). Both roots keep the same module calls (INF-LAY-4); only the count differs through the env. `outputs.tf` adds `site_url`, `api_public_url`, `site_bucket_name`, `site_distribution_id`, `api_distribution_id`, `edge_alerts_topic_arn`. The deploy reads `site_bucket_name` and `site_distribution_id`.
The bucket policy and the CSP both need values from later modules, so the order is: cert, waf, then site and api (which need the certificate and the web ACL), then alarms.

## 7. Headers
### 7.1 Headers functions (R2)
No response headers policy and no permission to manage one. Two `viewer-response` functions, one per distribution, from templates (§8.2) that take a map of header names and values built with `jsonencode` in the module's `locals`:
- Site (`${name_prefix}-site-headers`): `strict-transport-security = "max-age=63072000; includeSubDomains"`, `content-security-policy = local.csp`, `x-content-type-options = "nosniff"`, `referrer-policy = "strict-origin-when-cross-origin"`. `local.csp` is the string of EDGE-HDR-2 with `connect-src 'self' https://${var.api_host}`. No `preload`: `.dev` is already HSTS-preloaded as a whole TLD, and a preload entry cannot be removed quickly. No `X-Frame-Options`: `frame-ancestors 'none'` covers it.
- API (`${name_prefix}-api-headers`): `strict-transport-security` and `x-content-type-options` only.
The function sets each header unconditionally, so it replaces an origin value (same effect as `override = true`). It does not run for origin responses of 400 or higher (F1).
### 7.2 Does the export need inline scripts? Yes (checked); inline style? No
Every file in `web/out/*.html` has three `<script>` tags without `src`: the Turbopack chunk registry (`id="_R_"`), `self.__next_f=…push([0])` and the React Server Components payload `self.__next_f.push([1,…])`. They carry hydration data and change with page content and every build. Fonts are self-hosted (`/_next/static/media/*.woff2`) and nothing loads from another origin.
**One style attribute, removed (T9, 25 Nov 2026).** The first look at `web/out` was at a test build. A real production build had one server-rendered `style="…"` attribute: the `clip-path` and `drop-shadow` of the landing page's tombstone shape (`components/landing/example-strip.tsx`). Decision of the maintainer: no `style-src-attr` exception. The two properties now live in the class `.gy-cursed-shape` in `web/app/globals.css`, and the export has no style attribute and no `<style>` element. `npm run check:build` fails on any `<style>` element, any `style` attribute, any other inline script shape, any inline event handler and any `javascript:` URL, so the next such change fails CI and not a browser. Styles that React and Framer Motion set later through the DOM (`element.style`) are not governed by `style-src` and are not in the HTML.
- Nonces need a server per request: not possible on a static export.
- Hashes would have to be in the response header. The function code is fixed by Terraform, while the hashes change with every build: not possible without a post-build step (H14: the deploy computes the hashes per page and feeds them to the headers function, for example through a CloudFront KeyValueStore the function reads, which needs its own permissions and exception; then `'unsafe-inline'` is dropped from `script-src`).
- So the CSP keeps `'unsafe-inline'` for scripts only and is strict everywhere else: `style-src 'self'` with no exception, no `unsafe-eval`, `object-src 'none'`, `base-uri`, `form-action`, `frame-ancestors 'none'`, and `connect-src` limited to the API host. Residual risk: an HTML injection bug could run inline script. The app renders third-party text (package descriptions) through React, which escapes it.
- That the pages render correctly under this CSP is **not proven** until a browser runs it: EDGE-MAN-5 checks the console on dev.
### 7.3 Caching
Objects carry their own `Cache-Control` (set by `deploy-site`, §11.3). CachingOptimized has min TTL 1 s, default 24 h, max 1 year and honours the origin value inside that range: immutable assets get a year, `no-cache` objects get 1 s, plus the invalidation of §11.3. All files outside `/_next/static/` are `no-cache`, including the RSC `.txt` files and `404.html`.

## 8. Functions
### 8.1 Viewer-request function (site)
Template `functions/viewer-request.js.tftpl` (CloudFront Functions JS 2.0). `${apex_host}` and `${redirect_www}` are filled by `templatefile`, so the dev build contains no redirect.
```js
var APEX = "${apex_host}";
var REDIRECT_WWW = ${redirect_www};
function query(qs) {
  var parts = [];
  Object.keys(qs).forEach(function (k) {
    var item = qs[k];
    if (item.multiValue) { item.multiValue.forEach(function (m) { parts.push(k + "=" + m.value); }); }
    else { parts.push(k + "=" + item.value); }
  });
  return parts.length ? "?" + parts.join("&") : "";
}
function handler(event) {
  var request = event.request;
  var host = request.headers.host ? request.headers.host.value : "";
  if (REDIRECT_WWW && host === "www." + APEX) {
    return { statusCode: 301, statusDescription: "Moved Permanently",
      headers: { location: { value: "https://" + APEX + request.uri + query(request.querystring) } } };
  }
  var uri = request.uri;
  if (uri === "/") { uri = "/index.html"; }
  else if (uri.charAt(uri.length - 1) === "/") { uri = uri.slice(0, -1) + ".html"; }
  else if (uri.lastIndexOf(".") < uri.lastIndexOf("/")) { uri = uri + ".html"; }
  request.uri = uri;
  return request;
}
```
Cases tested (EDGE-TEST-3): `/` to `/index.html`; `/scan` to `/scan.html`; `/scan/` to `/scan.html`; `/_next/static/a.js` and `/scan.txt` and `/__next.scan.txt` unchanged; `/a.b/c` to `/a.b/c.html`; `/nope` to `/nope.html` (S3 answers 403, the error response shows `404.html` with 404); `www` with `?id=1&x=2` in prod redirects, in dev does not; apex in prod does not redirect. The `${redirect_www}` template value is the string `true` or `false`.

### 8.2 Headers function (site and API)
Template `functions/viewer-response.js.tftpl`, the same file in `edge-site` and `edge-api` (a Node test asserts the two files are identical). `${headers_json}` is `jsonencode` of the header map, so quotes in the CSP are escaped by Terraform and never typed by hand.
```js
var HEADERS = ${headers_json};
function handler(event) {
  var response = event.response;
  Object.keys(HEADERS).forEach(function (name) {
    response.headers[name] = { value: HEADERS[name] };
  });
  return response;
}
```
Cases tested: every configured header is present; an origin value for the same header is replaced; other headers (`content-type`, `cache-control`) and the status code are untouched; header names are lower-case (CloudFront requires it). The site CSP and the API map are asserted in the module tests from the rendered code.

## 9. WAF
### 9.1 Rules
Prod only (R7): the root creates the ACL when `enable_waf` is true, which defaults to prod. Dev has no ACL; `web_acl_id` is null on its two distributions. Setting `enable_waf = true` in dev gives it the same ACL, so "WAF on dev" is a variable and not a code change.
| Priority | Name | Statement | Action |
|----------|------|-----------|--------|
| 1 | `ip-reputation` | managed `AWSManagedRulesAmazonIpReputationList` (AWS) | group actions (`override_action none`) |
| 2 | `rate-post-scans` | rate-based, `aggregate_key_type = "IP"`, `limit`, `evaluation_window_sec`, scope-down `AND(method EXACTLY POST, uri_path EXACTLY /v1/scans)` | block, `custom_response { response_code = 429 }` |
| 3 | `common` | managed `AWSManagedRulesCommonRuleSet` | group actions |
| 4 | `known-bad-inputs` | managed `AWSManagedRulesKnownBadInputsRuleSet` | group actions |
`visibility_config` on the ACL and on each rule: `cloudwatch_metrics_enabled = true`, `sampled_requests_enabled = true`, metric names `${name_prefix}-edge`, `${name_prefix}-edge-<rule name>`. The ACL has no `logging` resource. The managed groups are pinned to their default (current) version, not a fixed version, so AWS updates apply; version pinning is H17.
### 9.2 Rate limit
Limit **20 requests per 300 s per IP** on `POST /v1/scans`. Reasoning: the stage allows 2 POST per second in total for all callers (`post_rate_limit`), so one IP at full speed could use the whole allowance and lock out everyone else; 20 per 5 minutes is about 0.07 per second. A person watches one scan at a time and a scan runs up to 5 minutes (scan-backend R7), so a human does not start 20 in 5 minutes; a script does. A group behind one NAT (a judging room) would need 20 scans in 5 minutes to be hit. The window is one of the four WAF allows. The limit and window are variables; WAF requires at least 10.
### 9.3 Cost
Fixed WAF cost, prod only: 1 ACL × (USD 5 + 4 rules × USD 1) ≈ USD 9 a month (about USD 18 if dev opts in), plus about USD 0.60 per million requests. CloudFront at demo traffic is inside the free tier or cents. Route 53 queries for the new records are cents. `PriceClass_100` avoids the most expensive edge regions. Against "≤ GBP 30 while live" the WAF is the main item; the cost budget (`infra-foundation`) alarms at 50, 80 and 100 percent.

## 10. Alarms
See §5.5. The 10-request floor stops one failed request at demo traffic from reading as 100 percent, the way the existing API alarm uses `requests > 0`. `5xxErrorRate` is a default CloudFront metric (no extra monitoring subscription). The alarm and the topic are in us-east-1 (R1, EDGE-OBS-2).

## 11. Web deploy
### 11.1 Trigger fix (R10, EDGE-DEP-3)
Today `ci.yml` job `deploy` needs `plan-dev` and `plan-prod`, which run only when `changes.outputs.infra == 'true'`, and runs only if a plan has changes. A `web/` change alone reaches neither. Change:
- `deploy.needs = [changes, web, plan-dev, plan-prod]`.
- `deploy.if = !cancelled() && push to main && (plan-dev.has_changes == 'true' || plan-prod.has_changes == 'true' || changes.web == 'true') && (changes.infra != 'true' || (plan-dev.result == success && plan-prod.result == success)) && web.result in (success, skipped)`. The second clause matters: a failed static check skips the plan jobs, and a skipped plan must not read as "nothing to apply" when the push also changed `web/`.
- New input `web_changed` (string) of `deploy.yml`, from `needs.changes.outputs.web`.
- Infra changes also redeploy the site: the API URL and the CSP come from the same commit. In `deploy.yml` both envs' jobs run when `has_changes == 'true'` **or** `web_changed == 'true'`.
`scripts/ci/tests/workflow_rules.py` and `test_ci_workflow.py` encode the old shape (exact inputs, needs, `if`); T10 updates them with the new shape.
### 11.2 Jobs in `deploy.yml`
- `build-web-dev`, `build-web-prod`: `permissions: contents: read`, no environment, no `id-token`. Steps: checkout `github.sha`; `actions/setup-node` (the SHA already used in `ci.yml`, `web/.node-version`); `npm ci`; `npm run build` with `NEXT_PUBLIC_API_URL: https://api.dev.lastrites.dev` (prod: `https://api.lastrites.dev`); `npm run check:build`; `actions/upload-artifact` (pinned by SHA) of `web/out`, name `site-<env>`, 7-day retention. The artifact is the public site; no secret is in it. The two API URLs are literals in the workflow; a python test checks them against `domain_name` and the host rule of §6, so they cannot drift.
- `build-web-<env>` runs when `inputs.<env>_has_changes == 'true' || inputs.web_changed == 'true'`.
- `apply-dev`: `needs: [build-web-dev]`, `if: !cancelled() && (inputs.dev_has_changes == 'true' || inputs.web_changed == 'true')`. `apply-prod`: `needs: [apply-dev, build-web-prod]`, same shape plus the existing rule on the dev result. The `if` does not require the build to have succeeded, so a broken web build cannot block an infrastructure apply.
- Steps of an apply job: checkout; **Apply** (`terraform-apply`) with `if: inputs.<env>_has_changes == 'true'`; **Deploy site** (`./.github/actions/deploy-site`) with `if: needs.build-web-<env>.result == 'success'`; a last step that fails the job when that result is anything else (the artifact is missing). Prod keeps `environment: prod`, so one approval covers apply and site.
### 11.3 Composite action `deploy-site`
Inputs: `env`, `account-id`, `aws-region`, `state-bucket`, `state-kms-key-id`. Steps:
1. `terraform-init` with the backend and the env's apply role (re-assumes the role, so credentials are fresh even after a long apply).
2. `terraform -chdir=infra/envs/$ENV output -raw site_bucket_name` and `site_distribution_id`; reject values that do not match `^graveyard-(dev|prod)-site-[a-z0-9]+$` and `^E[A-Z0-9]+$`, and a bucket whose env part differs from `$ENV`.
3. Download artifact `site-<env>` to `out/`.
4. `aws s3 sync out/_next/static "s3://$BUCKET/_next/static" --cache-control "public,max-age=31536000,immutable" --only-show-errors` (no delete).
5. `aws s3 sync out "s3://$BUCKET" --exclude "_next/static/*" --cache-control "no-cache" --delete --only-show-errors`.
6. Invalidation of the non-hashed paths: `/`, plus every file of `out/` outside `_next/static/` as `/<path>`, plus the clean URL of each `.html` file (`/scan`); if more than 50 paths, use `/*`. `aws cloudfront create-invalidation --paths …`.
7. `aws s3 sync out/_next/static "s3://$BUCKET/_next/static" --delete` removes assets the new build no longer has, after the new HTML is live.
8. Smoke checks of EDGE-DEP-4 (successful responses only, because the headers function does not run on origin errors, EDGE-HDR-4): `curl --fail --silent --show-error --retry 6 --retry-delay 10 --retry-all-errors` on `/`, `/scan`; status 404 and the 404 body on `/graveyard-smoke-missing`; headers `strict-transport-security` and `content-security-policy` present.
Uploading hashed assets first and deleting old ones last means a cached old page never points at a missing file. The apply role has `s3:ListBucket` already; object `PutObject`, `DeleteObject`, `AbortMultipartUpload` are added by EDGE-IAM-5. `aws s3 sync` makes no `GetObject` call.

## 12. IAM (bootstrap root)
### 12.1 Region guard, exception E11 (EDGE-IAM-4)
`main.tf` keeps `region_deny` as is (the boundaries use it). A new local `region_deny_ci` is `region_deny` with one list `region_us_east_1_actions` added to `NotAction` of `DenyOutsideRegion` and to `Action` of `DenyGlobalOutsideUsEast1`, so those actions are allowed in eu-west-2 and us-east-1 and nowhere else. `policies_apply_core.tf` (apply guard) and `policies_plan.tf` (plan guard) use `region_deny_ci`; `boundary.tf` does not change.
```
region_us_east_1_actions = [
  "route53:ChangeResourceRecordSets", "route53:GetChange", "route53:GetHostedZone", "route53:ListResourceRecordSets",
  <cw_write>, <cw_read>, "cloudwatch:DescribeAlarms",
  <sns_write>, <sns_read>,
]
```
Justification: Route 53 and the CloudFront alarm and topic live in us-east-1 (global endpoint, CloudFront metrics). Each action is still allowed only on the ARNs of §12.2 to §12.3. ACM, WAFv2 and CloudFront need no change. **Boundary size:** the boundary text is the same bytes as today (6,066 and 6,084), and a test asserts that none of these actions appears in a boundary and that its length is unchanged.
### 12.2 `graveyard-<env>-apply-edge-extra` (new managed policy)
| Sid | Actions | Resource | Condition |
|-----|---------|----------|-----------|
| `ExceptionE12` | `route53:ChangeResourceRecordSets` | `arn:<p>:route53:::hostedzone/<zone id>` | `ForAllValues:StringLike` `route53:ChangeResourceRecordSetsNormalizedRecordNames` in the names below; `ForAllValues:StringEquals` `…RecordTypes` in `A`, `AAAA`, `CNAME`; `ForAllValues:StringEquals` `…Actions` in `CREATE`, `UPSERT`, `DELETE`; `Null` `false` on all three keys (a request without them is not allowed) |
| `Route53Read` | `route53:GetHostedZone`, `route53:ListResourceRecordSets` | the zone ARN | |
| `Route53Change` | `route53:GetChange` | `arn:<p>:route53:::change/*` | |
| `SiteObjects` | `s3:PutObject`, `s3:DeleteObject`, `s3:AbortMultipartUpload` | `arn:<p>:s3:::graveyard-<env>-site-*/*` | |
| `EdgeAlarms` | `cw_write`, `cw_read` | `arn:<p>:cloudwatch:us-east-1:<a>:alarm:graveyard-<env>-*` | |
| `EdgeTopic` | `sns_write`, `sns_read` | `arn:<p>:sns:us-east-1:<a>:graveyard-<env>-*` | |
Record names, normalised (lower-case, no trailing dot): dev `dev.lastrites.dev`, `api.dev.lastrites.dev`, `_*.dev.lastrites.dev`; prod `lastrites.dev`, `www.lastrites.dev`, `api.lastrites.dev`, `_*.lastrites.dev`. They come from `edge_domain_name` and the host rule of §6 inside the module, so the roots and the policy use one rule; a test in each place checks the same strings.
New inputs of `github-oidc` and of the bootstrap root: `edge_domain_name` (default `lastrites.dev`) and `route53_zone_id` (required, validated `^Z[A-Z0-9]+$`, in git-ignored tfvars; not an account ID, so the guards allow it in code but the value stays out of the repo like the other run-time values).
### 12.2b Explicit deny on the prod apply role (R4, EDGE-IAM-3)
In `graveyard-prod-apply-guard` only:
```json
{ "Sid": "DenyProdChangingDevRecords", "Effect": "Deny",
  "Action": ["route53:ChangeResourceRecordSets"], "Resource": "*",
  "Condition": { "ForAnyValue:StringLike": {
    "route53:ChangeResourceRecordSetsNormalizedRecordNames": ["*dev.lastrites.dev"] } } }
```
The pattern is `*dev.<edge_domain_name>`. It matches `dev.lastrites.dev`, `api.dev.lastrites.dev` and dev's validation names `_<hash>.dev.lastrites.dev`. It cannot match a name prod needs: the apex, `www`, `api`, and `_<hash>.<prod host>` where the hash is hexadecimal and so never ends in `dev` (`v` is not a hex digit). `ForAnyValue` denies the whole request if any one of its changes touches a dev name. An explicit deny wins over every Allow. The dev guard gets no statement (dev's Allow already lists only dev names).
### 12.3 Additions to existing lists
- `star_reads.edge` (reads on `*`, metadata only): `cloudfront:ListOriginRequestPolicies`, `cloudfront:GetOriginRequestPolicy`. Not documented as required to attach a managed policy; cheap insurance for the first apply (remove if it proves unneeded).
- `res.alarm_us_east_1`, `res.topic_us_east_1` (new, §12.2). `gen.certificates` already has us-east-1, `res.waf` already has the CLOUDFRONT-scope ARNs, `res.cf_function` is name-scoped, `S3Buckets` already covers every bucket-level action on `graveyard-<env>-*`.
### 12.4 Residual risk of the exceptions
- **E12:** the roles can create, change and delete `A`, `AAAA` and `CNAME` records with those names in the zone, including by a bad Terraform change. Prod's allowed pattern `_*.lastrites.dev` also matches dev's validation CNAMEs (`_x.dev.lastrites.dev`) because the ACM validation names are `_<hash>.<hostname>` and cannot be listed in advance; the explicit deny of §12.2b closes that. A hand-made record with one of the allowed names and types would be overwritten by an `UPSERT`.
- **E11:** CloudWatch and SNS actions are allowed in us-east-1 for the CI roles; the Allow statements limit them to `graveyard-<env>-*` ARNs.
### 12.5 Sizes and counts
Measured after T1 (`terraform test` in a scratch copy, mocked provider, no credentials). Before is the measurement of 25 Nov 2026 before the change.
| Policy | Dev before | Dev after | Prod before | Prod after | Limit |
|--------|-----------|-----------|-------------|------------|-------|
| `apply-edge` | 5,645 | 5,720 | 5,664 | 5,739 | 6,144 (405 spare; only the two `star_reads` names were added) |
| `apply-guard` | 2,184 | 3,042 | 2,181 | 3,273 | 6,144 (E11; prod also holds the R4 deny) |
| `plan-guard` | 1,117 | 1,975 | same | same | 6,144 (E11) |
| `plan-read-edge` | 2,715 | 2,790 | same | same | 6,144 |
| boundary | 6,066 | 6,066 | 6,084 | 6,084 | 6,144, **unchanged** (a test pins both sizes) |
| new `apply-edge-extra` | | 1,503 | | 1,514 | 6,144 |
| new `plan-read-edge-extra` | | 658 | | same | 6,144 |
The largest policy is a boundary at 6,084 (60 spare); the largest CI-role policy is `apply-edge` at 5,739. Managed policies per role: each apply role 7 + 1 = **8** (compute, data, edge, guard, iam, ops, state, edge-extra), the plan role 7 + 1 = **8**; the quota is 10 (R9). `tests/edge.tftest.hcl` asserts 8, 8, 8 and every policy at most 6,144. Expected bootstrap plan: 6 to add (3 policies, 3 attachments), 6 to change (`apply-edge` and `apply-guard` in both envs, `plan-guard`, `plan-read-edge`), 0 to destroy.

## 13. Apply-permission audit
Calls come from the provider 6.73.0 source (`internal/service/*`, read 25 Nov 2026) and the Service Authorization Reference. "Apply" is the env apply role's identity policy, "Plan" the plan role's read policy. **New** marks a statement this spec adds. `region` is the `aws:RequestedRegion` of the call.
| Resource | Calls (create / read / update / delete) | Extra calls | Region | Apply | Plan |
|---|---|---|---|---|---|
| `random_id` | none | | | n/a | n/a |
| `aws_s3_bucket` and `_versioning`, `_server_side_encryption_configuration`, `_public_access_block`, `_ownership_controls`, `_lifecycle_configuration`, `_policy` | as the artefacts bucket of the scan-backend audit (CreateBucket, TagResource, the Put/Get of each setting, DeleteBucket) | | eu-west-2 | yes (`S3Buckets`, `graveyard-<env>-*`) | yes |
| objects of the site bucket | PutObject, DeleteObject, AbortMultipartUpload; ListBucket | by the workflow, not Terraform | eu-west-2 | **New** `SiteObjects`; `ListBucket` in `S3Buckets` | n/a |
| `aws_cloudfront_origin_access_control` | CreateOriginAccessControl; GetOriginAccessControl; UpdateOriginAccessControl; DeleteOriginAccessControl | ListOriginAccessControls | us-east-1 | yes (E6) | yes (`star_reads`) |
| `aws_cloudfront_function` (site request, site headers, API headers; three per prod env, two per dev) | CreateFunction (with tags); DescribeFunction, GetFunction, ListTagsForResource; UpdateFunction, PublishFunction, TagResource; DeleteFunction | TagResource on create (function ARN) | us-east-1 | yes (`CreateCloudFrontFunctions` RequestTag; `ManageCloudFrontFunctions` by name `graveyard-<env>-*`) | yes |
| `aws_cloudfront_distribution` | CreateDistributionWithTags (needs `CreateDistribution` and `TagResource`); GetDistribution, ListTagsForResource; UpdateDistribution (GetDistribution first), TagResource, UntagResource; UpdateDistribution to disable, then DeleteDistribution | web ACL, certificate, managed policy IDs referenced in the config (item 2 and 3 of §2.3) | us-east-1 | yes (`CreateDistributions` RequestTag, `TagNewDistributions`, `ManageDistributions` ResourceTag) | yes |
| invalidation (workflow) | CreateInvalidation; GetInvalidation | | us-east-1 | yes (`cf_dist_write`) | n/a |
| managed cache and origin request policies | referenced by ID | possibly Get on the policy | us-east-1 | **New** `star_reads` Get/List (insurance) | yes |
| `aws_cloudfront_distribution` (viewer-response association) | the function ARN is part of the distribution config; no extra call | CloudFront may check the function exists (`DescribeFunction`) | us-east-1 | yes (`ManageCloudFrontFunctions` read) | yes |
| `aws_wafv2_web_acl` (CLOUDFRONT, prod only) | CreateWebACL, TagResource; GetWebACL, ListTagsForResource; UpdateWebACL (lock token from GetWebACL); DeleteWebACL | managed rule groups (§2.3 item 1) | us-east-1 | yes (`Waf`, `global/webacl/graveyard-<env>-*/*`) | yes |
| `aws_acm_certificate` | RequestCertificate (with tags); DescribeCertificate, ListTagsForCertificate; UpdateCertificateOptions, AddTagsToCertificate, RemoveTagsFromCertificate; DeleteCertificate | AddTagsToCertificate on create | us-east-1 | yes (`AcmRequest`, `AcmTagNew`, `AcmManage`; ARN pattern includes us-east-1) | yes |
| `aws_acm_certificate_validation` | DescribeCertificate (polling) | | us-east-1 | yes | yes |
| `aws_route53_record` (validation and alias) | GetHostedZone, ChangeResourceRecordSets, GetChange (wait for INSYNC); ListResourceRecordSets; ChangeResourceRecordSets; ChangeResourceRecordSets (DELETE) | | us-east-1 | **New** `ExceptionE12`, `Route53Read`, `Route53Change` | **New** read |
| `aws_sns_topic` (us-east-1) | CreateTopic; GetTopicAttributes, ListTagsForResource; SetTopicAttributes, TagResource; DeleteTopic | | us-east-1 | **New** `EdgeTopic` | **New** |
| `aws_cloudwatch_metric_alarm` (us-east-1) | PutMetricAlarm; DescribeAlarms, ListTagsForResource; PutMetricAlarm, TagResource; DeleteAlarms | | us-east-1 | **New** `EdgeAlarms`; `DescribeAlarms` in `star_reads.ops` | **New** |
| provider | sts:GetCallerIdentity | | | always allowed | |
The region guard (E11) covers the Route 53, CloudWatch and SNS rows. The first deploy fails only on the **unverified** items of §2.3 and on anything this table missed; tasks T1 and T3 to T7 re-check each row against the policy JSON in a test.

## 14. Tests
- `github-oidc`: new `tests/edge.tftest.hcl` (E11 on the three guards and not on the boundary, the boundary text size unchanged and free of the new actions, E12 exactly, no response-headers-policy action anywhere, the prod deny exactly and absent from the dev guard, `SiteObjects`, us-east-1 ARNs, sizes ≤ 6,144 and 8 policies per role, `Route53Read` in the plan role); `shared_account.tftest.hcl` (exception list E1 to E12, `*` list, E12 not on `*`); every existing test's `variables {}` gets `route53_zone_id` and `edge_domain_name`.
- `edge-cert`: names, SAN list, validation method, `create_before_destroy`, record count equals names, no record for a name outside the list, output depends on validation.
- `edge-waf`: scope, name, default action, rule order and names, managed group names, `override_action none`, rate rule key, limit and window, scope-down (both statements), custom response 429, visibility on ACL and rules, no logging resource, variable validations reject a limit below 10.
- `edge-site`: bucket settings, bucket policy statements (TLS deny, one allow with `AWS:SourceArn`), lifecycle, OAC settings, function runtime and publish, rendered function code for prod (redirect on) and dev (off), the headers function rendered with the exact CSP string (API host inside, no `unsafe-eval`) and the other three headers, one function association on `viewer-request` and one on `viewer-response`, distribution settings (methods, protocol, TLS, price class, error responses, root object, `web_acl_id` equal to the input and null when the input is null, aliases, cache policy ID), alias records (A and AAAA per host).
- `edge-api`: origin host without scheme and no path, all methods, managed policy IDs, `https-only`, **no** custom error responses, no viewer-request association, exactly one viewer-response association (the API headers function: HSTS and nosniff only), no response headers policy, `web_acl_id`, aliases, records.
- `edge-alarms`: provider region, metric math, threshold, min requests, topic name, `alarm_actions`, `treat_missing_data`.
- Env roots `tests/root.tftest.hcl` (both): hostnames per env, certificate ARN on both distributions; prod: the same web ACL ARN on both distributions; dev: no web ACL, and with `enable_waf = true` it has one; the site headers function names `api_host`; CORS first entry equals the site host; outputs.
- `viewer-request.test.mjs` and `viewer-response.test.mjs`: §8 cases, run by `node --test` in a new CI job; the second also asserts the site and API templates are identical files.
- python (`scripts/ci/tests`): env roots (alias provider, `domain_name`, no resources), guards (no `aws_route53_zone`, every distribution sets `web_acl_id`), workflow rules (new jobs and inputs, build jobs hold no credentials and no `id-token`, API URL literals match the host rule, sync commands carry the two `Cache-Control` values and `--delete`), CI matrices contain the five modules.

## 15. Risks and the H-list
New items for `docs/runbooks/terraform-bootstrap.md` §13 (next free number after H11), all deferred to the ship-week security review:
| # | Item |
|---|------|
| H12 | WAF logging. Needs log delivery and `logs:PutResourcePolicy` or an S3 or Firehose destination; a new exception. Today only metrics and sampled requests. |
| H13 | The direct `execute-api` URL bypasses WAF and the CloudFront alias. Options: a custom origin header checked by the API (the secret would live in state), or a different origin type. |
| H14 | Remove `'unsafe-inline'` from `script-src` with per-page hashes computed after the build and fed to the headers function (§7.2). |
| H15 | Review E11 and E12 after the first month; check whether prod's `_*.lastrites.dev` pattern should become exact names after the certificate exists. |
| H16 | CloudFront standard logs (need an S3 bucket with ACL logging and a log-delivery grant). |
| H17 | WAF rule review from sampled requests after a week of traffic; pin managed rule group versions; consider Count mode for new rules. |
| H18 | Move site upload to a dedicated `graveyard-<env>-site-deploy` role. |
| H20 | Security headers on error responses: the 404 page and API 4xx and 5xx get none, because CloudFront skips viewer-response functions for origin errors (F1). For the API, have the API send `nosniff` itself; for the 404 page, check whether it is acceptable as is. |
| H19 | CAA records for `lastrites.dev` (allow only `amazon.com`) and DNSSEC, by hand; the CI roles cannot change those record types. |
Other risks: the first deploy of a certificate waits for DNS validation (minutes); CloudFront deletes take 15 minutes or more because the distribution must be disabled first; `terraform destroy` of the site bucket is blocked while it has objects (`force_destroy = false`, intended); the Edge ACL (prod) blocks by managed rules, so a false positive blocks real users until H17; dev has no ACL, so the WAF behaviour is first seen in prod, and the dev API has no per-IP limit.

## 16. Traceability
| Requirement | Design | Task |
|-------------|--------|------|
| EDGE-DNS-1..3 | §3, §5.1, §5.3, §5.4, §6 | T3, T5, T6, T8, T11 |
| EDGE-CERT-1..2 | §5.1, §6 | T3, T8 |
| EDGE-SITE-1..4 | §5.3, §8 | T5 |
| EDGE-API-1..3 | §4, §5.4 | T6 |
| EDGE-HDR-1..4, EDGE-CACHE-1 | §7, §8.2 | T5, T6, T9, T10 |
| EDGE-WAF-1..4, EDGE-COST-1 | §5.2, §6, §9 | T4, T8 |
| EDGE-CORS-1 | §6 | T8 |
| EDGE-OBS-1..2 | §5.5, §10 | T7 |
| EDGE-DEP-1..5 | §11 | T10 |
| EDGE-IAM-1..8 | §12, §13 | T0, T1 |
| EDGE-TAG-1..2 | §5, §6 | T8, T2 |
| EDGE-TEST-1..6 | §14 | T1, T3 to T11 |
| EDGE-MAN-1..5 | | T2, T13, T14 |
