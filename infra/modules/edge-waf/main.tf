# The Edge ACL of one env (spec infra-edge, EDGE-WAF-1 to EDGE-WAF-3): scope CLOUDFRONT, so the root passes the us-east-1 provider
# as this module's default provider. Prod only by default (R7): the root decides by count, so this module always makes one ACL.
locals {
  acl_name = "${var.name_prefix}-edge"
}
resource "aws_wafv2_web_acl" "this" {
  # checkov:skip=CKV2_AWS_31:No logging configuration by decision (EDGE-WAF-3): a destination needs log delivery or logs:PutResourcePolicy, which INF-SHARED-3 forbids to CI roles. Metrics and sampled requests are on. Tracked as H12.
  name        = local.acl_name
  description = "Edge ACL of ${var.name_prefix}: managed rule sets and a per-IP rate limit on POST /v1/scans."
  scope       = "CLOUDFRONT"
  default_action {
    allow {}
  }
  # The three AWS managed groups use their own actions (override_action none). The order of the rules is the order of evaluation:
  # known-bad IPs first, then the per-IP rate rule, then the two content rule sets.
  rule {
    name     = "ip-reputation"
    priority = 1
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesAmazonIpReputationList"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.acl_name}-ip-reputation"
      sampled_requests_enabled   = true
    }
  }
  rule {
    name     = "rate-post-scans"
    priority = 2
    action {
      block {
        custom_response {
          response_code = 429
        }
      }
    }
    statement {
      rate_based_statement {
        limit                 = var.scan_rate_limit
        evaluation_window_sec = var.scan_rate_window_seconds
        aggregate_key_type    = "IP"
        # Only POST /v1/scans counts. Any other request does not use up an IP's allowance.
        scope_down_statement {
          and_statement {
            statement {
              byte_match_statement {
                search_string         = "POST"
                positional_constraint = "EXACTLY"
                field_to_match {
                  method {}
                }
                text_transformation {
                  priority = 0
                  type     = "NONE"
                }
              }
            }
            statement {
              byte_match_statement {
                search_string         = "/v1/scans"
                positional_constraint = "EXACTLY"
                field_to_match {
                  uri_path {}
                }
                text_transformation {
                  priority = 0
                  type     = "NONE"
                }
              }
            }
          }
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.acl_name}-rate-post-scans"
      sampled_requests_enabled   = true
    }
  }
  rule {
    name     = "common"
    priority = 3
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.acl_name}-common"
      sampled_requests_enabled   = true
    }
  }
  rule {
    name     = "known-bad-inputs"
    priority = 4
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.acl_name}-known-bad-inputs"
      sampled_requests_enabled   = true
    }
  }
  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = local.acl_name
    sampled_requests_enabled   = true
  }
}
