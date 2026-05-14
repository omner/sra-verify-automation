# Multi-Account Deployment & Execution Guide

This guide walks you through deploying and running the SRA Verify automation across an AWS Organization.

## Account Roles

| Account | What you do there | Why |
|---------|-------------------|-----|
| **Management account** | Deploy `SRAMemberRole` via StackSets + deploy the role locally to the management account itself | StackSets can't target the management account, and the scanner needs to assume into it for org-level checks |
| **Audit account** (Security Tooling) | Deploy the Terraform (Lambdas, S3 bucket, IAM roles) | This is where the scanning infrastructure lives and executes from |
| **All member accounts** (including log archive) | Receive `SRAMemberRole` via StackSets | The scanner Lambda assumes this role to run checks |

---

## Phase 1: Deploy SRAMemberRole to All Accounts

Run this from the **management account** (or delegated admin for CloudFormation).

```bash
# Download the role template
wget https://raw.githubusercontent.com/awslabs/sra-verify/refs/heads/main/1-sraverify-member-roles.yaml

# Create the StackSet (deploys to all member accounts)
aws cloudformation create-stack-set \
  --template-body file://1-sraverify-member-roles.yaml \
  --stack-set-name sraverify-member-roles \
  --permission-model SERVICE_MANAGED \
  --auto-deployment Enabled=true,RetainStacksOnAccountRemoval=false \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters ParameterKey=SRAVerifyAccountID,ParameterValue=<AUDIT_ACCOUNT_ID> \
  --region <YOUR_REGION>

# Create stack instances across the org
aws cloudformation create-stack-instances \
  --stack-set-name sraverify-member-roles \
  --deployment-targets OrganizationalUnitIds='["<ROOT_OU_ID>"]' \
  --regions '["<YOUR_REGION>"]' \
  --operation-preferences FailureTolerancePercentage=100,MaxConcurrentPercentage=100 \
  --region <YOUR_REGION>

# Deploy the role to the management account itself (StackSets skip it)
aws cloudformation deploy \
  --template-file 1-sraverify-member-roles.yaml \
  --stack-name sraverify-member-roles \
  --parameter-overrides SRAVerifyAccountID=<AUDIT_ACCOUNT_ID> \
  --capabilities CAPABILITY_NAMED_IAM
```

**Resources created per account:**

- IAM Role: `SRAMemberRole`
- IAM Managed Policy: `SRAVerifyLeastPrivilege` (read-only across ~20 services)
- IAM Managed Policy: `SRAVerifyCheckPermissions`

---

## Phase 2: Deploy the Scanning Infrastructure

Run this from the **audit account**.

```bash
# 1. Clone the repo
git clone https://github.com/<your-username>/sra-verify-automation.git
cd sra-verify-automation

# 2. Build the Lambda layer (requires Python 3.11+ and pip)
./scripts/build-layer.sh

# 3. Configure
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
```

Edit `terraform/terraform.tfvars`:

```hcl
aws_region           = "us-east-1"
scan_regions         = ["us-east-1", "us-west-2"]
audit_accounts       = ["<AUDIT_ACCOUNT_ID>"]
log_archive_accounts = ["<LOG_ARCHIVE_ACCOUNT_ID>"]
```

```bash
# 4. Deploy
cd terraform
terraform init
terraform plan
terraform apply
```

**Resources created in the audit account:**

| Resource | Name | Purpose |
|----------|------|---------|
| S3 Bucket | `sra-verify-findings-*` | Stores scan results |
| Lambda Function | `sra-verify-orchestrator` | Coordinates the scan |
| Lambda Function | `sra-verify-scanner` | Runs checks per account |
| Lambda Layer | `sraverify` | Contains the sra-verify library |
| IAM Role | `sra-verify-orchestrator-role` | Permissions for orchestrator |
| IAM Role | `SRAVerifyCodeBuildServiceRole` | Permissions for scanner (includes `sts:AssumeRole` to `SRAMemberRole`). Named to match the trust policy expected by `SRAMemberRole` in target accounts. |
| CloudWatch Log Groups | `/aws/lambda/sra-verify-*` | Lambda logs (14-day retention) |

---

## Phase 3: Run a Scan

From the **audit account** (or anywhere with permission to invoke the Lambda):

```bash
# Scan all accounts in the org
aws lambda invoke \
  --function-name sra-verify-orchestrator \
  --payload '{}' \
  --cli-read-timeout 900 \
  response.json

cat response.json
```

### Optional overrides

```bash
# Scan specific accounts only
aws lambda invoke \
  --function-name sra-verify-orchestrator \
  --payload '{"account_ids": ["111111111111", "222222222222"]}' \
  --cli-read-timeout 900 \
  response.json

# Scan only management-type checks
aws lambda invoke \
  --function-name sra-verify-orchestrator \
  --payload '{"account_type": "management"}' \
  --cli-read-timeout 900 \
  response.json
```

> **Note:** `--cli-read-timeout 900` is needed because the Lambda can run up to 15 minutes.

---

## Phase 4: Review Results

```bash
# Get the bucket name
BUCKET=$(cd terraform && terraform output -raw findings_bucket_name)

# List scan runs
aws s3 ls s3://$BUCKET/sraverify/reports/consolidated/

# Download the consolidated report
aws s3 cp s3://$BUCKET/sraverify/reports/consolidated/<SCAN_ID>/sra-verify-consolidated.csv .

# Or download per-account raw files
aws s3 cp s3://$BUCKET/sraverify/reports/raw/<SCAN_ID>/ ./raw-reports/ --recursive
```

### Using the Dashboard

Each scan automatically uploads the SRA Verify interactive dashboard alongside the CSV. To use it:

1. Generate a presigned URL for the CSV (valid for 60 minutes):

```bash
SCAN_ID=<your-scan-id>
CSV_URL=$(aws s3 presign s3://$BUCKET/sraverify/reports/consolidated/$SCAN_ID/sra-verify-consolidated.csv --expires-in 3600)
```

2. Open the dashboard in your browser. You have two options:

**Option A: Download and open locally**
```bash
aws s3 cp s3://$BUCKET/sraverify/reports/consolidated/$SCAN_ID/sra-verify-dashboard.html .
open sra-verify-dashboard.html   # macOS
```

**Option B: Use a presigned URL for the dashboard**
```bash
DASHBOARD_URL=$(aws s3 presign s3://$BUCKET/sraverify/reports/consolidated/$SCAN_ID/sra-verify-dashboard.html --expires-in 3600)
echo $DASHBOARD_URL   # Open this in a browser
```

3. In the dashboard, paste the CSV presigned URL and click **Load URL**.

> **Security note:** Do not share presigned URLs externally. They grant temporary access to the S3 objects using your credentials. For customer-facing delivery, download the files and share them through your preferred secure channel.

---

## Cleanup / Teardown

If you want to remove everything after you're done:

### Audit account (Terraform resources)

```bash
cd terraform

# Empty the S3 bucket first (Terraform won't delete a non-empty bucket)
BUCKET=$(terraform output -raw findings_bucket_name)
aws s3 rm s3://$BUCKET --recursive

terraform destroy
```

### Management account (StackSet + local stack)

```bash
# Delete stack instances first
aws cloudformation delete-stack-instances \
  --stack-set-name sraverify-member-roles \
  --deployment-targets OrganizationalUnitIds='["<ROOT_OU_ID>"]' \
  --regions '["<YOUR_REGION>"]' \
  --no-retain-stacks \
  --region <YOUR_REGION>

# Wait for instances to delete, then delete the StackSet
aws cloudformation delete-stack-set \
  --stack-set-name sraverify-member-roles \
  --region <YOUR_REGION>

# Delete the management account's local stack
aws cloudformation delete-stack --stack-name sraverify-member-roles
```

This removes `SRAMemberRole` and its policies from all accounts.

---

## Important Notes

- The orchestrator Lambda calls the Organizations API. This works from the audit account because the `SRAMemberRole` in the management account grants `organizations:ListAccounts` and `organizations:DescribeOrganization`, and the scanner assumes into the management account first to retrieve the account list.
- The scanner Lambda's `sts:AssumeRole` targets `arn:*:iam::*:role/SRAMemberRole`. It can only assume into accounts where the role's trust policy allows the audit account. The StackSet handles this automatically.
- The scanner Lambda role is named `SRAVerifyCodeBuildServiceRole` to match the trust policy condition in `SRAMemberRole`. This is required by the upstream `1-sraverify-member-roles.yaml` template which expects this exact role name.
- The S3 bucket has `force_destroy = false`. You must empty it manually before running `terraform destroy`.
- Lambda logs auto-expire after 14 days.
- For organizations with more than 20 accounts, consider increasing `lambda_timeout` or switching to a Step Functions-based orchestration.
