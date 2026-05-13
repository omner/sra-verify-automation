# SRA Verify Automation (Terraform + Lambda)

Automated multi-account deployment of [sra-verify](https://github.com/awslabs/sra-verify) using the library interface, orchestrated by AWS Lambda and triggered on-demand.

## Architecture

```
Manual Invoke (CLI / Console)
    → Orchestrator Lambda
        → Lists org accounts
        → Classifies each (management/audit/log-archive/application)
        → Invokes Scanner Lambda per account (parallel, up to 10 concurrent)
    → Scanner Lambda (per account)
        → Assumes SRAMemberRole
        → Runs sraverify checks via library
        → Writes per-account CSV to S3
    → Orchestrator consolidates all CSVs into single report
```

## Documentation

- [Multi-Account Deployment & Execution Guide](docs/MULTI_ACCOUNT_GUIDE.md) — step-by-step instructions for deploying and running across an AWS Organization, including cleanup.

## Prerequisites

1. **SRAMemberRole deployed to all accounts** — use the `1-sraverify-member-roles.yaml` from the sra-verify repo via CloudFormation StackSets.
2. **Python 3.11+** and **pip** for building the Lambda layer.
3. **Terraform >= 1.5**.

## Setup

### 1. Build the Lambda layer

```bash
./scripts/build-layer.sh
```

### 2. Configure variables

```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# Edit terraform.tfvars with your account IDs and regions
```

### 3. Deploy

```bash
cd terraform
terraform init
terraform plan
terraform apply
```

### 4. Run a scan

```bash
# Scan all org accounts
aws lambda invoke --function-name sra-verify-orchestrator --payload '{}' /dev/stdout

# Scan specific accounts only
aws lambda invoke --function-name sra-verify-orchestrator \
  --payload '{"account_ids": ["123456789012", "987654321098"]}' /dev/stdout

# Scan only management account type
aws lambda invoke --function-name sra-verify-orchestrator \
  --payload '{"account_type": "management"}' /dev/stdout
```

### 5. Review results

Findings are stored in the S3 bucket under:
- `sraverify/reports/raw/{scan_id}/{account_id}.csv` — per-account results
- `sraverify/reports/consolidated/{scan_id}/sra-verify-consolidated.csv` — combined report

## Limitations

- Lambda timeout is 15 minutes max. With ≤20 accounts and parallel execution this is sufficient.
- The orchestrator invokes scanners synchronously. For larger orgs, consider Step Functions.
- The SRAMemberRole StackSet deployment is a separate prerequisite (not managed by this Terraform).
