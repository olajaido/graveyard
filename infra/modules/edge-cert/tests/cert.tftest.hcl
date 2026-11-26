# Offline tests for edge-cert (EDGE-CERT-1, EDGE-CERT-2, EDGE-DNS-1). The provider is mocked (the root passes us-east-1); the certificate's validation
# options are overridden because the real values are known only after the apply.
mock_provider "aws" {}
override_resource {
  target          = aws_acm_certificate.this
  override_during = plan
  values = {
    arn = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"
    domain_validation_options = [
      { domain_name = "lastrites.dev", resource_record_name = "_a1.lastrites.dev.", resource_record_type = "CNAME", resource_record_value = "_v1.acm-validations.aws." },
      { domain_name = "www.lastrites.dev", resource_record_name = "_a2.www.lastrites.dev.", resource_record_type = "CNAME", resource_record_value = "_v2.acm-validations.aws." },
      { domain_name = "api.lastrites.dev", resource_record_name = "_a3.api.lastrites.dev.", resource_record_type = "CNAME", resource_record_value = "_v3.acm-validations.aws." },
    ]
  }
}
variables {
  domain_names = ["lastrites.dev", "www.lastrites.dev", "api.lastrites.dev"]
  zone_id      = "Z0123456789ABCDEFGHIJ"
}
run "the_certificate_covers_exactly_the_given_names_and_is_validated_by_dns" {
  command = plan
  assert {
    condition     = aws_acm_certificate.this.domain_name == "lastrites.dev" && toset(aws_acm_certificate.this.subject_alternative_names) == toset(["www.lastrites.dev", "api.lastrites.dev"])
    error_message = "The first name is primary and the others are alternative names, nothing else."
  }
  assert {
    condition     = aws_acm_certificate.this.validation_method == "DNS" && aws_acm_certificate.this.key_algorithm == "RSA_2048"
    error_message = "DNS validation, RSA 2048."
  }
}
run "there_is_one_validation_record_per_name_in_the_given_zone" {
  command = plan
  assert {
    condition     = toset(keys(aws_route53_record.validation)) == toset(["lastrites.dev", "www.lastrites.dev", "api.lastrites.dev"])
    error_message = "One record per hostname, no record for any other name."
  }
  assert {
    condition = alltrue([
      for k, r in aws_route53_record.validation : r.zone_id == "Z0123456789ABCDEFGHIJ" && r.type == "CNAME" && r.ttl == 60 && r.allow_overwrite == false
    ])
    error_message = "Validation records are CNAMEs in the given zone with TTL 60 and no overwrite."
  }
  assert {
    condition = (
      aws_route53_record.validation["www.lastrites.dev"].name == "_a2.www.lastrites.dev." &&
      aws_route53_record.validation["www.lastrites.dev"].records == toset(["_v2.acm-validations.aws."])
    )
    error_message = "Each record uses the name and value ACM gave for its own hostname."
  }
}
run "the_output_is_the_validated_certificate" {
  command = plan
  assert {
    condition     = output.certificate_arn == "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"
    error_message = "The output must be the certificate ARN, through the validation resource."
  }
  assert {
    condition     = aws_acm_certificate_validation.this.certificate_arn == aws_acm_certificate.this.arn
    error_message = "Validation waits for this certificate."
  }
}
run "a_wildcard_name_is_rejected" {
  command = plan
  variables {
    domain_names = ["*.lastrites.dev"]
  }
  expect_failures = [var.domain_names]
}
run "duplicate_names_are_rejected" {
  command = plan
  variables {
    domain_names = ["lastrites.dev", "lastrites.dev"]
  }
  expect_failures = [var.domain_names]
}
run "a_bad_zone_id_is_rejected" {
  command = plan
  variables {
    zone_id = "not-a-zone"
  }
  expect_failures = [var.zone_id]
}
