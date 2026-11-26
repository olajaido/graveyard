# Offline tests for edge-site (EDGE-SITE-1 to EDGE-SITE-4, EDGE-HDR-1, EDGE-HDR-2, EDGE-DNS-3). Defaults describe prod.
mock_provider "aws" {}
mock_provider "random" {}
override_resource {
  target          = random_id.suffix
  override_during = plan
  values          = { hex = "0a1b2c3d" }
}
override_resource {
  target          = aws_s3_bucket.site
  override_during = plan
  values = {
    id                          = "graveyard-prod-site-0a1b2c3d"
    arn                         = "arn:aws:s3:::graveyard-prod-site-0a1b2c3d"
    bucket_regional_domain_name = "graveyard-prod-site-0a1b2c3d.s3.eu-west-2.amazonaws.com"
  }
}
override_resource {
  target          = aws_cloudfront_distribution.site
  override_during = plan
  values = {
    id             = "E2EXAMPLE12345"
    arn            = "arn:aws:cloudfront::123456789012:distribution/E2EXAMPLE12345"
    domain_name    = "d111111abcdef8.cloudfront.net"
    hosted_zone_id = "Z2FDTNDATAQYW2"
  }
}
override_resource {
  target          = aws_cloudfront_origin_access_control.site
  override_during = plan
  values          = { id = "E3OACEXAMPLE" }
}
override_resource {
  target          = aws_cloudfront_function.viewer_request
  override_during = plan
  values          = { arn = "arn:aws:cloudfront::123456789012:function/graveyard-prod-site-request" }
}
override_resource {
  target          = aws_cloudfront_function.viewer_response
  override_during = plan
  values          = { arn = "arn:aws:cloudfront::123456789012:function/graveyard-prod-site-headers" }
}
variables {
  name_prefix     = "graveyard-prod"
  site_host       = "lastrites.dev"
  redirect_www    = true
  api_host        = "api.lastrites.dev"
  certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"
  web_acl_arn     = "arn:aws:wafv2:us-east-1:123456789012:global/webacl/graveyard-prod-edge/11111111-1111-1111-1111-111111111111"
  zone_id         = "Z0123456789ABCDEFGHIJ"
}
run "the_bucket_is_private_versioned_encrypted_and_owned_by_the_bucket_owner" {
  command = plan
  assert {
    condition     = aws_s3_bucket.site.bucket == "graveyard-prod-site-0a1b2c3d" && aws_s3_bucket.site.force_destroy == false
    error_message = "graveyard-<env>-site-<random suffix>, never force-destroyed."
  }
  assert {
    condition     = aws_s3_bucket_public_access_block.site.block_public_acls && aws_s3_bucket_public_access_block.site.block_public_policy && aws_s3_bucket_public_access_block.site.ignore_public_acls && aws_s3_bucket_public_access_block.site.restrict_public_buckets
    error_message = "All four Block Public Access settings must be on."
  }
  assert {
    condition     = one(aws_s3_bucket_ownership_controls.site.rule).object_ownership == "BucketOwnerEnforced" && one(aws_s3_bucket_versioning.site.versioning_configuration).status == "Enabled"
    error_message = "BucketOwnerEnforced and versioning on."
  }
  assert {
    condition     = one(one(aws_s3_bucket_server_side_encryption_configuration.site.rule).apply_server_side_encryption_by_default).sse_algorithm == "AES256"
    error_message = "SSE-S3 (decision R6)."
  }
}
run "the_lifecycle_expires_old_versions_and_aborts_old_uploads" {
  command = plan
  assert {
    condition     = one([for r in aws_s3_bucket_lifecycle_configuration.site.rule : one(r.noncurrent_version_expiration).noncurrent_days if r.id == "expire-noncurrent-versions"]) == 30
    error_message = "Noncurrent versions expire after 30 days by default."
  }
  assert {
    condition     = one([for r in aws_s3_bucket_lifecycle_configuration.site.rule : one(r.abort_incomplete_multipart_upload).days_after_initiation if r.id == "abort-incomplete-multipart-uploads"]) == 7
    error_message = "Incomplete multipart uploads are aborted after 7 days."
  }
  assert {
    condition     = alltrue([for r in aws_s3_bucket_lifecycle_configuration.site.rule : r.status == "Enabled"])
    error_message = "Every rule is enabled."
  }
}
run "the_bucket_policy_denies_plain_http_and_lets_only_this_distribution_read" {
  command = plan
  assert {
    condition = jsondecode(aws_s3_bucket_policy.site.policy).Statement == [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = ["arn:aws:s3:::graveyard-prod-site-0a1b2c3d", "arn:aws:s3:::graveyard-prod-site-0a1b2c3d/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
      {
        Sid       = "AllowSiteDistributionRead"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "arn:aws:s3:::graveyard-prod-site-0a1b2c3d/*"
        Condition = { StringEquals = { "AWS:SourceArn" = "arn:aws:cloudfront::123456789012:distribution/E2EXAMPLE12345" } }
      },
    ]
    error_message = "The bucket policy must be exactly the TLS deny and one read for this distribution."
  }
}
run "the_origin_access_control_signs_every_request" {
  command = plan
  assert {
    condition     = aws_cloudfront_origin_access_control.site.name == "graveyard-prod-site-oac" && aws_cloudfront_origin_access_control.site.origin_access_control_origin_type == "s3" && aws_cloudfront_origin_access_control.site.signing_behavior == "always" && aws_cloudfront_origin_access_control.site.signing_protocol == "sigv4"
    error_message = "OAC: s3, always, sigv4."
  }
}
run "the_distribution_settings_follow_the_requirements" {
  command = plan
  assert {
    condition     = aws_cloudfront_distribution.site.aliases == toset(["lastrites.dev", "www.lastrites.dev"]) && aws_cloudfront_distribution.site.default_root_object == "index.html"
    error_message = "Prod serves the apex and www; the root object is index.html."
  }
  assert {
    condition     = aws_cloudfront_distribution.site.http_version == "http2and3" && aws_cloudfront_distribution.site.is_ipv6_enabled && aws_cloudfront_distribution.site.price_class == "PriceClass_100"
    error_message = "HTTP/2 and 3, IPv6, PriceClass_100."
  }
  assert {
    condition = (
      one(aws_cloudfront_distribution.site.default_cache_behavior).viewer_protocol_policy == "redirect-to-https" &&
      one(aws_cloudfront_distribution.site.default_cache_behavior).allowed_methods == toset(["GET", "HEAD"]) &&
      one(aws_cloudfront_distribution.site.default_cache_behavior).compress == true &&
      one(aws_cloudfront_distribution.site.default_cache_behavior).cache_policy_id == "658327ea-f89d-4fab-a63d-7e88639e58f6"
    )
    error_message = "Redirect to HTTPS, GET and HEAD only, compressed, the managed CachingOptimized policy."
  }
  assert {
    condition = (
      one(aws_cloudfront_distribution.site.viewer_certificate).ssl_support_method == "sni-only" &&
      one(aws_cloudfront_distribution.site.viewer_certificate).minimum_protocol_version == "TLSv1.2_2021" &&
      one(aws_cloudfront_distribution.site.viewer_certificate).acm_certificate_arn == "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"
    )
    error_message = "SNI only, TLS 1.2 or later, the us-east-1 certificate."
  }
  assert {
    condition     = aws_cloudfront_distribution.site.web_acl_id == "arn:aws:wafv2:us-east-1:123456789012:global/webacl/graveyard-prod-edge/11111111-1111-1111-1111-111111111111"
    error_message = "The Edge ACL is attached."
  }
  assert {
    condition     = one(one(aws_cloudfront_distribution.site.restrictions).geo_restriction).restriction_type == "none" && length(aws_cloudfront_distribution.site.origin) == 1
    error_message = "No geo restriction and one origin."
  }
}
run "an_s3_403_or_404_shows_the_404_page_with_status_404" {
  command = plan
  assert {
    condition = {
      for e in aws_cloudfront_distribution.site.custom_error_response : e.error_code => "${e.response_code}|${e.response_page_path}|${e.error_caching_min_ttl}"
    } == { 403 = "404|/404.html|10", 404 = "404|/404.html|10" }
    error_message = "403 and 404 from S3 become /404.html with status 404 and a 10 second cache."
  }
}
run "the_two_functions_are_on_the_right_events" {
  command = plan
  assert {
    condition = {
      for f in one(aws_cloudfront_distribution.site.default_cache_behavior).function_association : f.event_type => f.function_arn
      } == {
      "viewer-request"  = "arn:aws:cloudfront::123456789012:function/graveyard-prod-site-request"
      "viewer-response" = "arn:aws:cloudfront::123456789012:function/graveyard-prod-site-headers"
    }
    error_message = "The clean-URL function is on viewer-request and the headers function on viewer-response."
  }
  assert {
    condition     = aws_cloudfront_function.viewer_request.runtime == "cloudfront-js-2.0" && aws_cloudfront_function.viewer_response.runtime == "cloudfront-js-2.0" && aws_cloudfront_function.viewer_request.publish && aws_cloudfront_function.viewer_response.publish
    error_message = "Both functions are JavaScript 2.0 and published."
  }
  assert {
    condition     = aws_cloudfront_function.viewer_request.name == "graveyard-prod-site-request" && aws_cloudfront_function.viewer_response.name == "graveyard-prod-site-headers"
    error_message = "Function names start with graveyard-<env>- (INF-NAME-1)."
  }
}
run "the_prod_function_redirects_www_and_the_dev_function_does_not" {
  command = plan
  assert {
    condition     = strcontains(aws_cloudfront_function.viewer_request.code, "var APEX = \"lastrites.dev\";") && strcontains(aws_cloudfront_function.viewer_request.code, "var REDIRECT_WWW = true;")
    error_message = "Prod: apex lastrites.dev, redirect on."
  }
}
run "the_dev_site_has_no_www_alias_no_redirect_and_no_web_acl" {
  command = plan
  variables {
    name_prefix  = "graveyard-dev"
    site_host    = "dev.lastrites.dev"
    redirect_www = false
    api_host     = "api.dev.lastrites.dev"
    web_acl_arn  = null
  }
  assert {
    condition     = aws_cloudfront_distribution.site.aliases == toset(["dev.lastrites.dev"]) && aws_cloudfront_distribution.site.web_acl_id == null
    error_message = "Dev serves one host and has no web ACL (R7)."
  }
  assert {
    condition     = strcontains(aws_cloudfront_function.viewer_request.code, "var APEX = \"dev.lastrites.dev\";") && strcontains(aws_cloudfront_function.viewer_request.code, "var REDIRECT_WWW = false;")
    error_message = "Dev: redirect off."
  }
  assert {
    condition     = toset(keys(aws_route53_record.alias)) == toset(["dev.lastrites.dev|A", "dev.lastrites.dev|AAAA"])
    error_message = "Dev has A and AAAA for its one host."
  }
}
run "the_headers_function_sets_exactly_the_four_site_headers" {
  command = plan
  assert {
    condition = strcontains(aws_cloudfront_function.viewer_response.code, jsonencode({
      "content-security-policy"   = output.csp
      "referrer-policy"           = "strict-origin-when-cross-origin"
      "strict-transport-security" = "max-age=63072000; includeSubDomains"
      "x-content-type-options"    = "nosniff"
    }))
    error_message = "The function holds HSTS (2 years, includeSubDomains), the CSP, nosniff and the referrer policy, and no other header."
  }
}
run "the_csp_is_exact_and_names_only_self_and_the_api_host" {
  command = plan
  assert {
    condition     = output.csp == "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self' https://api.lastrites.dev; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; upgrade-insecure-requests"
    error_message = "The CSP must be exactly the string of EDGE-HDR-2."
  }
  assert {
    condition     = !strcontains(output.csp, "unsafe-eval") && !strcontains(output.csp, "*") && !strcontains(output.csp, "http://")
    error_message = "No unsafe-eval, no wildcard, no plain http origin."
  }
}
run "the_dev_csp_names_the_dev_api_host" {
  command = plan
  variables {
    api_host = "api.dev.lastrites.dev"
  }
  assert {
    condition     = strcontains(output.csp, "connect-src 'self' https://api.dev.lastrites.dev;") && !strcontains(output.csp, "https://api.lastrites.dev")
    error_message = "The CSP is built from the API host input."
  }
}
run "every_host_has_an_alias_a_and_aaaa_record_to_the_distribution" {
  command = plan
  assert {
    condition     = toset(keys(aws_route53_record.alias)) == toset(["lastrites.dev|A", "lastrites.dev|AAAA", "www.lastrites.dev|A", "www.lastrites.dev|AAAA"])
    error_message = "A and AAAA for the apex and www in prod, and no other record."
  }
  assert {
    condition = alltrue([
      for k, r in aws_route53_record.alias : r.zone_id == "Z0123456789ABCDEFGHIJ" && one(r.alias).name == "d111111abcdef8.cloudfront.net" && one(r.alias).zone_id == "Z2FDTNDATAQYW2" && one(r.alias).evaluate_target_health == false
    ])
    error_message = "Alias records point at the site distribution in the given zone."
  }
}
run "the_outputs_are_the_bucket_and_the_distribution" {
  command = plan
  assert {
    condition     = output.bucket_name == "graveyard-prod-site-0a1b2c3d" && output.distribution_id == "E2EXAMPLE12345" && output.site_url == "https://lastrites.dev"
    error_message = "The deploy workflow reads the bucket name and the distribution ID."
  }
}
run "a_certificate_outside_us_east_1_is_rejected" {
  command = plan
  variables {
    certificate_arn = "arn:aws:acm:eu-west-2:123456789012:certificate/00000000-0000-0000-0000-000000000000"
  }
  expect_failures = [var.certificate_arn]
}
run "a_regional_web_acl_is_rejected" {
  command = plan
  variables {
    web_acl_arn = "arn:aws:wafv2:eu-west-2:123456789012:regional/webacl/x/1"
  }
  expect_failures = [var.web_acl_arn]
}
