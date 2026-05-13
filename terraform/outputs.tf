output "findings_bucket_name" {
  description = "S3 bucket for SRA Verify findings"
  value       = aws_s3_bucket.findings.id
}

output "orchestrator_function_name" {
  description = "Name of the orchestrator Lambda to invoke on-demand"
  value       = aws_lambda_function.orchestrator.function_name
}

output "invoke_command" {
  description = "AWS CLI command to trigger a scan"
  value       = "aws lambda invoke --function-name ${aws_lambda_function.orchestrator.function_name} --payload '{}' /dev/stdout"
}
