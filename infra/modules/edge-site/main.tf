# The static site of one env (spec infra-edge): a private S3 bucket behind a CloudFront distribution with an origin access control,
# a viewer-request function (clean URLs, www redirect), a viewer-response function (security headers), custom 404, alias records.
locals {
  bucket_name = "${var.name_prefix}-site-${random_id.suffix.hex}"
  aliases     = concat([var.site_host], var.redirect_www ? ["www.${var.site_host}"] : [])
  # AWS-managed policies, by ID (R11): CachingOptimized honours the objects' Cache-Control between 1 second and 1 year.
  cache_policy_caching_optimized = "658327ea-f89d-4fab-a63d-7e88639e58f6"
  # EDGE-HDR-2. 'unsafe-inline' for scripts only: the Next.js export writes three inline scripts into every page (design 7.2).
  csp = join("; ", [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self'",
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self' https://${var.api_host}",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "upgrade-insecure-requests",
  ])
  # EDGE-HDR-1. Header names are lower-case, as CloudFront Functions require.
  headers = {
    "strict-transport-security" = "max-age=63072000; includeSubDomains"
    "content-security-policy"   = local.csp
    "x-content-type-options"    = "nosniff"
    "referrer-policy"           = "strict-origin-when-cross-origin"
  }
  bucket_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.site.arn, "${aws_s3_bucket.site.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
      {
        # Only this env's distribution, through the origin access control, may read objects.
        Sid       = "AllowSiteDistributionRead"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.site.arn}/*"
        Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.site.arn } }
      },
    ]
  })
}
resource "random_id" "suffix" {
  byte_length = 4
}
resource "aws_s3_bucket" "site" {
  # checkov:skip=CKV_AWS_18:No S3 access logging (H16); the content is public and CloudFront is the only reader.
  # checkov:skip=CKV_AWS_144:No cross-region replication: the site is rebuilt from the repository.
  # checkov:skip=CKV2_AWS_62:No event notifications are needed.
  # checkov:skip=CKV_AWS_145:SSE-S3, not KMS, by decision R6: the bucket holds only public files, and a CMK would need a key policy for the CloudFront principal.
  bucket        = local.bucket_name
  force_destroy = false
}
resource "aws_s3_bucket_public_access_block" "site" {
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_ownership_controls" "site" {
  bucket = aws_s3_bucket.site.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}
resource "aws_s3_bucket_versioning" "site" {
  bucket = aws_s3_bucket.site.id
  versioning_configuration {
    status = "Enabled"
  }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  bucket = aws_s3_bucket.site.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
resource "aws_s3_bucket_lifecycle_configuration" "site" {
  bucket = aws_s3_bucket.site.id
  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_expiry_days
    }
  }
  rule {
    id     = "remove-expired-delete-markers"
    status = "Enabled"
    filter {}
    expiration {
      expired_object_delete_marker = true
    }
  }
  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
  # The rules on noncurrent versions need versioning to be on first.
  depends_on = [aws_s3_bucket_versioning.site]
}
resource "aws_s3_bucket_policy" "site" {
  bucket     = aws_s3_bucket.site.id
  policy     = local.bucket_policy
  depends_on = [aws_s3_bucket_public_access_block.site]
}
resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${var.name_prefix}-site-oac"
  description                       = "Lets the ${var.name_prefix} site distribution read its private bucket."
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}
resource "aws_cloudfront_function" "viewer_request" {
  name    = "${var.name_prefix}-site-request"
  runtime = "cloudfront-js-2.0"
  comment = "Clean URLs and, in prod, the www redirect."
  publish = true
  code = templatefile("${path.module}/functions/viewer-request.js.tftpl", {
    apex_host    = var.site_host
    redirect_www = var.redirect_www
  })
}
resource "aws_cloudfront_function" "viewer_response" {
  name    = "${var.name_prefix}-site-headers"
  runtime = "cloudfront-js-2.0"
  comment = "Security response headers of the site."
  publish = true
  code    = templatefile("${path.module}/functions/viewer-response.js.tftpl", { headers_json = jsonencode(local.headers) })
}
resource "aws_cloudfront_distribution" "site" {
  # checkov:skip=CKV_AWS_86:No CloudFront access logging (H16): it needs an S3 bucket with ACL logging and a log-delivery grant.
  # checkov:skip=CKV_AWS_310:One origin: the site is static and the bucket is versioned, so there is nothing to fail over to.
  # checkov:skip=CKV_AWS_374:No geo restriction: the site is public worldwide.
  # checkov:skip=CKV2_AWS_32:Security headers come from a viewer-response function, not a response headers policy (decision R2: no permission to create one).
  # checkov:skip=CKV_AWS_68:The web ACL is attached through web_acl_id in prod and absent in dev by decision R7.
  # checkov:skip=CKV2_AWS_47:The web ACL (with KnownBadInputs, which covers Log4j) is created by edge-waf in prod only (R7).
  enabled             = true
  is_ipv6_enabled     = true
  http_version        = "http2and3"
  comment             = "${var.name_prefix} site"
  default_root_object = "index.html"
  price_class         = var.price_class
  aliases             = local.aliases
  web_acl_id          = var.web_acl_arn
  origin {
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_id                = "site-bucket"
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }
  default_cache_behavior {
    target_origin_id       = "site-bucket"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    cache_policy_id        = local.cache_policy_caching_optimized
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.viewer_request.arn
    }
    function_association {
      event_type   = "viewer-response"
      function_arn = aws_cloudfront_function.viewer_response.arn
    }
  }
  # EDGE-SITE-4: an S3 403 or 404 shows the 404 page with status 404. Site distribution only; the API distribution has none.
  custom_error_response {
    error_code            = 403
    response_code         = 404
    response_page_path    = "/404.html"
    error_caching_min_ttl = 10
  }
  custom_error_response {
    error_code            = 404
    response_code         = 404
    response_page_path    = "/404.html"
    error_caching_min_ttl = 10
  }
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
# Alias A and AAAA for every host of the site (EDGE-DNS-3).
resource "aws_route53_record" "alias" {
  for_each = { for p in setproduct(local.aliases, ["A", "AAAA"]) : "${p[0]}|${p[1]}" => { name = p[0], type = p[1] } }
  zone_id  = var.zone_id
  name     = each.value.name
  type     = each.value.type
  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}
