# The ACM certificate of one env, in us-east-1 (CloudFront reads certificates from there only), validated by DNS with records in
# the existing hosted zone (spec infra-edge, EDGE-CERT-1). The root passes its us-east-1 provider as this module's one provider
# (EDGE-CERT-2). Route 53 is global, so the records go through the same provider and the same endpoint.
locals {
  primary = var.domain_names[0]
  sans    = slice(var.domain_names, 1, length(var.domain_names))
}
resource "aws_acm_certificate" "this" {
  domain_name               = local.primary
  subject_alternative_names = local.sans
  validation_method         = "DNS"
  key_algorithm             = "RSA_2048"
  lifecycle {
    # A replaced certificate is issued before the old one is detached from the distributions.
    create_before_destroy = true
  }
}
# Keyed by the hostnames the caller gave, which are known at plan time. The validation names, types and values are not, so they
# are looked up inside the values.
resource "aws_route53_record" "validation" {
  for_each = toset(var.domain_names)
  zone_id  = var.zone_id
  name     = one([for o in aws_acm_certificate.this.domain_validation_options : o.resource_record_name if o.domain_name == each.key])
  type     = one([for o in aws_acm_certificate.this.domain_validation_options : o.resource_record_type if o.domain_name == each.key])
  records  = [one([for o in aws_acm_certificate.this.domain_validation_options : o.resource_record_value if o.domain_name == each.key])]
  ttl      = 60
  # A name that already exists is not taken over: the apply fails instead.
  allow_overwrite = false
}
resource "aws_acm_certificate_validation" "this" {
  certificate_arn         = aws_acm_certificate.this.arn
  validation_record_fqdns = [for r in aws_route53_record.validation : r.fqdn]
}
