# --- Scanner Lambda (runs per account) ---

data "archive_file" "scanner" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/scanner"
  output_path = "${path.module}/.build/scanner.zip"
}

resource "aws_lambda_function" "scanner" {
  function_name    = "sra-verify-scanner"
  role             = aws_iam_role.scanner.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.11"
  timeout          = var.lambda_timeout
  memory_size      = var.lambda_memory
  filename         = data.archive_file.scanner.output_path
  source_code_hash = data.archive_file.scanner.output_base64sha256

  layers = [aws_lambda_layer_version.sraverify.arn]

  environment {
    variables = {
      S3_BUCKET            = aws_s3_bucket.findings.id
      SCAN_REGIONS         = join(",", var.scan_regions)
      AUDIT_ACCOUNTS       = join(",", var.audit_accounts)
      LOG_ARCHIVE_ACCOUNTS = join(",", var.log_archive_accounts)
      SRA_MEMBER_ROLE_NAME = var.sra_member_role_name
      PARTITION            = data.aws_partition.current.partition
    }
  }
}

resource "aws_cloudwatch_log_group" "scanner" {
  name              = "/aws/lambda/${aws_lambda_function.scanner.function_name}"
  retention_in_days = 14
}

# --- Orchestrator Lambda (invokes scanner per account) ---

data "archive_file" "orchestrator" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/orchestrator"
  output_path = "${path.module}/.build/orchestrator.zip"
}

resource "aws_lambda_function" "orchestrator" {
  function_name    = "sra-verify-orchestrator"
  role             = aws_iam_role.orchestrator.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.11"
  timeout          = var.lambda_timeout
  memory_size      = 256
  filename         = data.archive_file.orchestrator.output_path
  source_code_hash = data.archive_file.orchestrator.output_base64sha256

  environment {
    variables = {
      SCANNER_FUNCTION_NAME = aws_lambda_function.scanner.function_name
      S3_BUCKET             = aws_s3_bucket.findings.id
      SCAN_REGIONS          = join(",", var.scan_regions)
      AUDIT_ACCOUNTS        = join(",", var.audit_accounts)
      LOG_ARCHIVE_ACCOUNTS  = join(",", var.log_archive_accounts)
      SRA_MEMBER_ROLE_NAME  = var.sra_member_role_name
      PARTITION             = data.aws_partition.current.partition
    }
  }
}

resource "aws_cloudwatch_log_group" "orchestrator" {
  name              = "/aws/lambda/${aws_lambda_function.orchestrator.function_name}"
  retention_in_days = 14
}

# --- Lambda Layer for sraverify ---

resource "aws_lambda_layer_version" "sraverify" {
  layer_name          = "sraverify"
  description         = "SRA Verify library and dependencies"
  compatible_runtimes = ["python3.11"]
  filename            = "${path.module}/.build/sraverify-layer.zip"
  source_code_hash    = filebase64sha256("${path.module}/.build/sraverify-layer.zip")
}
