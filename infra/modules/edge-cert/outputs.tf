output "certificate_arn" {
  description = "ARN of the issued certificate. Taken from the validation resource, so a distribution that uses it waits for issuance."
  value       = aws_acm_certificate_validation.this.certificate_arn
}
