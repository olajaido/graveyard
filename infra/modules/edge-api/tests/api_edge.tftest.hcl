# Offline tests for edge-api (EDGE-API-1 to EDGE-API-3, EDGE-HDR-3). Defaults describe prod.
mock_provider "aws" {}
override_resource {
  target          = aws_cloudfront_distribution.api
  override_during = plan
  values = {
    id             = "E4EXAMPLE67890"
    arn            = "arn:aws:cloudfront::123456789012:distribution/E4EXAMPLE67890"
    domain_name    = "d222222abcdef8.cloudfront.net"
    hosted_zone_id = "Z2FDTNDATAQYW2"
  }
}
override_resource {
  target          = aws_cloudfront_function.viewer_response
  override_during = plan
  values          = { arn = "arn:aws:cloudfront::123456789012:function/graveyard-prod-api-headers" }
}
variables {
  name_prefix     = "graveyard-prod"
  api_host        = "api.lastrites.dev"
  api_endpoint    = "https://abc123.execute-api.eu-west-2.amazonaws.com"
  certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"
  web_acl_arn     = "arn:aws:wafv2:us-east-1:123456789012:global/webacl/graveyard-prod-edge/11111111-1111-1111-1111-111111111111"
  zone_id         = "Z0123456789ABCDEFGHIJ"
}
run "the_only_origin_is_the_http_api_default_stage_over_https" {
  command = plan
  assert {
    condition     = length(aws_cloudfront_distribution.api.origin) == 1 && one(aws_cloudfront_distribution.api.origin).domain_name == "abc123.execute-api.eu-west-2.amazonaws.com"
    error_message = "One origin: the execute-api host, without the scheme."
  }
  assert {
    condition     = (one(aws_cloudfront_distribution.api.origin).origin_path == null || one(aws_cloudfront_distribution.api.origin).origin_path == "") && one(one(aws_cloudfront_distribution.api.origin).custom_origin_config).origin_protocol_policy == "https-only" && one(one(aws_cloudfront_distribution.api.origin).custom_origin_config).origin_ssl_protocols == toset(["TLSv1.2"])
    error_message = "No origin path (the $default stage has no prefix); HTTPS only to the origin with TLS 1.2."
  }
}
run "all_methods_no_caching_viewer_headers_but_not_host_and_https_only" {
  command = plan
  assert {
    condition = (
      one(aws_cloudfront_distribution.api.default_cache_behavior).allowed_methods == toset(["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]) &&
      one(aws_cloudfront_distribution.api.default_cache_behavior).viewer_protocol_policy == "https-only" &&
      one(aws_cloudfront_distribution.api.default_cache_behavior).cache_policy_id == "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" &&
      one(aws_cloudfront_distribution.api.default_cache_behavior).origin_request_policy_id == "b689b0a8-53d0-40ab-baf2-68738e2966ac"
    )
    error_message = "All seven methods, HTTPS only, CachingDisabled, AllViewerExceptHostHeader."
  }
}
run "api_errors_pass_through_unchanged" {
  command = plan
  assert {
    condition     = length(aws_cloudfront_distribution.api.custom_error_response) == 0
    error_message = "The API distribution must have no custom error responses (EDGE-API-2)."
  }
  assert {
    condition     = length(one(aws_cloudfront_distribution.api.default_cache_behavior).function_association) == 1 && one(one(aws_cloudfront_distribution.api.default_cache_behavior).function_association).event_type == "viewer-response"
    error_message = "The only function is the headers function on viewer-response; no viewer-request function."
  }
  assert {
    condition     = one(aws_cloudfront_distribution.api.default_cache_behavior).response_headers_policy_id == null || one(aws_cloudfront_distribution.api.default_cache_behavior).response_headers_policy_id == ""
    error_message = "No response headers policy (decision R2)."
  }
}
run "the_headers_function_sets_hsts_and_nosniff_only" {
  command = plan
  assert {
    condition     = strcontains(aws_cloudfront_function.viewer_response.code, jsonencode({ "strict-transport-security" = "max-age=63072000; includeSubDomains", "x-content-type-options" = "nosniff" }))
    error_message = "HSTS (2 years, includeSubDomains) and nosniff, nothing else."
  }
  assert {
    condition     = aws_cloudfront_function.viewer_response.name == "graveyard-prod-api-headers" && aws_cloudfront_function.viewer_response.runtime == "cloudfront-js-2.0" && aws_cloudfront_function.viewer_response.publish
    error_message = "Named graveyard-<env>-api-headers, JavaScript 2.0, published."
  }
}
run "the_alias_certificate_acl_and_tls_are_set" {
  command = plan
  assert {
    condition     = aws_cloudfront_distribution.api.aliases == toset(["api.lastrites.dev"]) && aws_cloudfront_distribution.api.web_acl_id == "arn:aws:wafv2:us-east-1:123456789012:global/webacl/graveyard-prod-edge/11111111-1111-1111-1111-111111111111"
    error_message = "One alias and the Edge ACL."
  }
  assert {
    condition     = one(aws_cloudfront_distribution.api.viewer_certificate).minimum_protocol_version == "TLSv1.2_2021" && one(aws_cloudfront_distribution.api.viewer_certificate).ssl_support_method == "sni-only"
    error_message = "SNI only, TLS 1.2 or later."
  }
  assert {
    condition     = aws_cloudfront_distribution.api.http_version == "http2and3" && aws_cloudfront_distribution.api.is_ipv6_enabled && aws_cloudfront_distribution.api.price_class == "PriceClass_100"
    error_message = "HTTP/2 and 3, IPv6, PriceClass_100."
  }
}
run "dev_has_no_web_acl" {
  command = plan
  variables {
    name_prefix = "graveyard-dev"
    api_host    = "api.dev.lastrites.dev"
    web_acl_arn = null
  }
  assert {
    condition     = aws_cloudfront_distribution.api.web_acl_id == null && aws_cloudfront_distribution.api.aliases == toset(["api.dev.lastrites.dev"])
    error_message = "Without an ACL the distribution has no web_acl_id (R7)."
  }
}
run "the_api_host_has_alias_a_and_aaaa_records_and_nothing_else" {
  command = plan
  assert {
    condition     = toset(keys(aws_route53_record.alias)) == toset(["A", "AAAA"]) && alltrue([for k, r in aws_route53_record.alias : r.name == "api.lastrites.dev" && r.zone_id == "Z0123456789ABCDEFGHIJ" && one(r.alias).name == "d222222abcdef8.cloudfront.net"])
    error_message = "A and AAAA alias records for the API host."
  }
  assert {
    condition     = output.api_url == "https://api.lastrites.dev" && output.distribution_id == "E4EXAMPLE67890"
    error_message = "The outputs are the public URL and the distribution ID."
  }
}
run "an_endpoint_with_a_path_is_rejected" {
  command = plan
  variables {
    api_endpoint = "https://abc123.execute-api.eu-west-2.amazonaws.com/v1"
  }
  expect_failures = [var.api_endpoint]
}
