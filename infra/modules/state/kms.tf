resource "aws_kms_key" "state" {
  description             = "Graveyard Terraform state and saved plans (INF-STATE-1)"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_kms_alias" "state" {
  name          = "alias/graveyard-tfstate"
  target_key_id = aws_kms_key.state.key_id
}

resource "aws_kms_key_policy" "state" {
  key_id = aws_kms_key.state.id
  policy = local.key_policy
}
