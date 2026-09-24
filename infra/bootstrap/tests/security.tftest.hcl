mock_provider "aws" {
  override_during = plan
  mock_resource "aws_s3_bucket" { defaults = { arn = "arn:aws:s3:::traceworth-offline-test-state" } }
}
variables {
  expected_account_id = "123456789012"
  state_bucket_name   = "traceworth-offline-test-state"
}
run "protected_state" {
  command = plan
  assert {
    condition     = aws_s3_bucket_public_access_block.state.block_public_acls && aws_s3_bucket_public_access_block.state.block_public_policy && aws_s3_bucket_public_access_block.state.ignore_public_acls && aws_s3_bucket_public_access_block.state.restrict_public_buckets
    error_message = "Terraform state bucket must block public access."
  }
  assert {
    condition     = aws_s3_bucket_versioning.state.versioning_configuration[0].status == "Enabled" && !aws_s3_bucket.state.force_destroy
    error_message = "State must be versioned and protected from forced deletion."
  }
  assert {
    condition     = one(aws_s3_bucket_server_side_encryption_configuration.state.rule).apply_server_side_encryption_by_default[0].sse_algorithm == "AES256"
    error_message = "State must use server-side encryption."
  }
  assert {
    condition     = jsondecode(aws_s3_bucket_policy.state.policy).Statement[0].Effect == "Deny" && jsondecode(aws_s3_bucket_policy.state.policy).Statement[0].Condition.Bool["aws:SecureTransport"] == "false"
    error_message = "State access without TLS must be denied."
  }
}
