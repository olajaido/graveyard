# Offline tests for edge-waf (EDGE-WAF-1 to EDGE-WAF-3).
mock_provider "aws" {}
variables {
  name_prefix = "graveyard-prod"
}
run "the_acl_has_the_right_scope_name_and_default_action" {
  command = plan
  assert {
    condition     = aws_wafv2_web_acl.this.scope == "CLOUDFRONT" && aws_wafv2_web_acl.this.name == "graveyard-prod-edge"
    error_message = "A CLOUDFRONT-scope ACL named <prefix>-edge."
  }
  assert {
    condition     = length(aws_wafv2_web_acl.this.default_action) == 1 && length(one(aws_wafv2_web_acl.this.default_action).allow) == 1 && length(one(aws_wafv2_web_acl.this.default_action).block) == 0
    error_message = "The default action is allow."
  }
}
run "the_rules_are_these_four_in_this_order" {
  command = plan
  assert {
    condition     = [for r in sort([for r in aws_wafv2_web_acl.this.rule : format("%02d:%s", r.priority, r.name)]) : r] == ["01:ip-reputation", "02:rate-post-scans", "03:common", "04:known-bad-inputs"]
    error_message = "Order: ip-reputation, rate-post-scans, common, known-bad-inputs."
  }
  assert {
    condition = {
      for r in aws_wafv2_web_acl.this.rule : r.name => one(one(r.statement).managed_rule_group_statement).name if length(one(r.statement).managed_rule_group_statement) == 1
      } == {
      "ip-reputation"    = "AWSManagedRulesAmazonIpReputationList"
      "common"           = "AWSManagedRulesCommonRuleSet"
      "known-bad-inputs" = "AWSManagedRulesKnownBadInputsRuleSet"
    }
    error_message = "The three managed groups must be IP reputation, Common and KnownBadInputs."
  }
  assert {
    condition = alltrue([
      for r in aws_wafv2_web_acl.this.rule : length(one(r.statement).managed_rule_group_statement) == 1 ? (
        one(one(r.statement).managed_rule_group_statement).vendor_name == "AWS" && length(one(r.override_action).none) == 1 && length(one(r.override_action).count) == 0
      ) : true
    ])
    error_message = "Managed groups are AWS's and use their own actions (override_action none)."
  }
}
run "the_rate_rule_counts_post_v1_scans_per_ip_and_blocks_with_429" {
  command = plan
  assert {
    condition = (
      one([for r in aws_wafv2_web_acl.this.rule : one(one(r.statement).rate_based_statement) if r.name == "rate-post-scans"]).limit == 20 &&
      one([for r in aws_wafv2_web_acl.this.rule : one(one(r.statement).rate_based_statement) if r.name == "rate-post-scans"]).evaluation_window_sec == 300 &&
      one([for r in aws_wafv2_web_acl.this.rule : one(one(r.statement).rate_based_statement) if r.name == "rate-post-scans"]).aggregate_key_type == "IP"
    )
    error_message = "20 requests per 300 seconds per IP."
  }
  assert {
    condition     = one([for r in aws_wafv2_web_acl.this.rule : one(one(one(r.action).block).custom_response).response_code if r.name == "rate-post-scans"]) == 429
    error_message = "A blocked IP gets 429."
  }
  assert {
    condition = (
      length(one(one([for r in aws_wafv2_web_acl.this.rule : one(one(r.statement).rate_based_statement) if r.name == "rate-post-scans"]).scope_down_statement).and_statement) == 1 &&
      toset([
        for s in one(one(one([for r in aws_wafv2_web_acl.this.rule : one(one(r.statement).rate_based_statement) if r.name == "rate-post-scans"]).scope_down_statement).and_statement).statement :
        "${one(s.byte_match_statement).search_string}|${one(s.byte_match_statement).positional_constraint}|${length(one(one(s.byte_match_statement).field_to_match).method) == 1 ? "method" : length(one(one(s.byte_match_statement).field_to_match).uri_path) == 1 ? "uri_path" : "other"}"
      ]) == toset(["POST|EXACTLY|method", "/v1/scans|EXACTLY|uri_path"])
    )
    error_message = "The rate rule counts only requests that are exactly POST and exactly the path /v1/scans."
  }
}
run "metrics_and_sampled_requests_are_on_for_the_acl_and_every_rule" {
  command = plan
  assert {
    condition     = one(aws_wafv2_web_acl.this.visibility_config).cloudwatch_metrics_enabled && one(aws_wafv2_web_acl.this.visibility_config).sampled_requests_enabled && one(aws_wafv2_web_acl.this.visibility_config).metric_name == "graveyard-prod-edge"
    error_message = "The ACL has metrics and sampled requests."
  }
  assert {
    condition     = alltrue([for r in aws_wafv2_web_acl.this.rule : one(r.visibility_config).cloudwatch_metrics_enabled && one(r.visibility_config).sampled_requests_enabled && startswith(one(r.visibility_config).metric_name, "graveyard-prod-edge-")])
    error_message = "Every rule has metrics and sampled requests."
  }
}
run "limit_and_window_follow_the_variables" {
  command = plan
  variables {
    scan_rate_limit          = 50
    scan_rate_window_seconds = 600
  }
  assert {
    condition     = one([for r in aws_wafv2_web_acl.this.rule : one(one(r.statement).rate_based_statement).limit if r.name == "rate-post-scans"]) == 50 && one([for r in aws_wafv2_web_acl.this.rule : one(one(r.statement).rate_based_statement).evaluation_window_sec if r.name == "rate-post-scans"]) == 600
    error_message = "The limit and the window come from the variables."
  }
}
run "a_limit_below_10_is_rejected" {
  command = plan
  variables {
    scan_rate_limit = 5
  }
  expect_failures = [var.scan_rate_limit]
}
run "a_window_waf_does_not_know_is_rejected" {
  command = plan
  variables {
    scan_rate_window_seconds = 90
  }
  expect_failures = [var.scan_rate_window_seconds]
}
run "the_name_output_is_the_acl_name" {
  command = plan
  assert {
    condition     = output.web_acl_name == "graveyard-prod-edge"
    error_message = "The name output is <prefix>-edge."
  }
}
