# The API distribution of one env (spec infra-edge, EDGE-API-1 to EDGE-API-3). Why a second distribution: custom error responses
# apply to a whole distribution, and the API must pass every error through unchanged, while the site turns S3 errors into a 404
# page; and a WAF web ACL cannot be attached to an HTTP API directly, so CloudFront is how the ACL reaches it.
locals {
  # AWS-managed policies, by ID (R11).
  cache_policy_caching_disabled            = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
  origin_request_policy_all_viewer_no_host = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
  # EDGE-HDR-3. The function does not run for origin errors of 400 or higher (EDGE-HDR-4).
  headers = {
    "strict-transport-security" = "max-age=63072000; includeSubDomains"
    "x-content-type-options"    = "nosniff"
  }
  origin_domain = trimprefix(var.api_endpoint, "https://")
}
resource "aws_cloudfront_function" "viewer_response" {
  name    = "${var.name_prefix}-api-headers"
  runtime = "cloudfront-js-2.0"
  comment = "HSTS and nosniff on API responses. Adds headers only."
  publish = true
  code    = templatefile("${path.module}/functions/viewer-response.js.tftpl", { headers_json = jsonencode(local.headers) })
}
resource "aws_cloudfront_distribution" "api" {
  # checkov:skip=CKV_AWS_305:An API has no root document: / is not a route, and a default root object would rewrite requests to it.
  # checkov:skip=CKV_AWS_86:No CloudFront access logging (H16): it needs an S3 bucket with ACL logging and a log-delivery grant.
  # checkov:skip=CKV_AWS_310:One origin: the HTTP API.
  # checkov:skip=CKV_AWS_374:No geo restriction: the API is public worldwide.
  # checkov:skip=CKV2_AWS_32:Headers come from a viewer-response function, not a response headers policy (decision R2).
  # checkov:skip=CKV_AWS_68:The web ACL is attached through web_acl_id in prod and absent in dev by decision R7.
  # checkov:skip=CKV2_AWS_47:The web ACL (with KnownBadInputs, which covers Log4j) is created by edge-waf in prod only (R7).
  enabled         = true
  is_ipv6_enabled = true
  http_version    = "http2and3"
  comment         = "${var.name_prefix} API"
  price_class     = var.price_class
  aliases         = [var.api_host]
  web_acl_id      = var.web_acl_arn
  origin {
    domain_name = local.origin_domain
    origin_id   = "http-api"
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }
  default_cache_behavior {
    target_origin_id = "http-api"
    # Not redirect-to-https: a redirect would turn a POST into a GET.
    viewer_protocol_policy   = "https-only"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    compress                 = false
    cache_policy_id          = local.cache_policy_caching_disabled
    origin_request_policy_id = local.origin_request_policy_all_viewer_no_host
    function_association {
      event_type   = "viewer-response"
      function_arn = aws_cloudfront_function.viewer_response.arn
    }
  }
  # No custom_error_response on purpose (EDGE-API-2): every API status code and body reaches the browser unchanged.
  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }
  viewer_certificate {
    acm_certificate_arn      = var.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}
resource "aws_route53_record" "alias" {
  for_each = toset(["A", "AAAA"])
  zone_id  = var.zone_id
  name     = var.api_host
  type     = each.key
  alias {
    name                   = aws_cloudfront_distribution.api.domain_name
    zone_id                = aws_cloudfront_distribution.api.hosted_zone_id
    evaluate_target_health = false
  }
}
