"""
Scanner Lambda: runs sra-verify checks against a single account.

Expected event payload:
{
    "account_id": "123456789012",
    "account_type": "application",  # or management, audit, log-archive
    "scan_id": "20260513_143000"
}
"""

import json
import os
import csv
import io
import boto3
from sraverify import SRAVerify
from sraverify.core.session import get_session


def lambda_handler(event, context):
    account_id = event["account_id"]
    account_type = event["account_type"]
    scan_id = event.get("scan_id", "manual")

    regions = os.environ["SCAN_REGIONS"].split(",")
    audit_accounts = os.environ["AUDIT_ACCOUNTS"].split(",")
    log_archive_accounts = os.environ["LOG_ARCHIVE_ACCOUNTS"].split(",")
    role_name = os.environ["SRA_MEMBER_ROLE_NAME"]
    partition = os.environ["PARTITION"]
    s3_bucket = os.environ["S3_BUCKET"]

    role_arn = f"arn:{partition}:iam::{account_id}:role/{role_name}"

    print(f"Scanning account {account_id} as {account_type} with role {role_arn}")

    try:
        session = get_session(role_arn=role_arn)
        sra = SRAVerify(session=session, regions=regions)

        findings = sra.run_checks(
            account_type=account_type,
            audit_accounts=audit_accounts,
            log_archive_accounts=log_archive_accounts,
        )
    except Exception as e:
        print(f"Error scanning account {account_id}: {e}")
        findings = [{
            "CheckId": "SCAN-ERROR",
            "Status": "ERROR",
            "Region": "global",
            "Severity": "HIGH",
            "Title": f"Failed to scan account {account_id}",
            "Description": str(e),
            "ResourceId": None,
            "ResourceType": None,
            "AccountId": account_id,
            "CheckedValue": None,
            "ActualValue": str(e),
            "Remediation": "Check IAM role trust policy and permissions",
            "Service": "SRAVerify",
            "CheckLogic": None,
            "AccountType": account_type,
        }]

    # Write findings to S3
    if findings:
        csv_key = f"sraverify/reports/raw/{scan_id}/{account_id}.csv"
        csv_content = findings_to_csv(findings)

        s3 = boto3.client("s3")
        s3.put_object(Bucket=s3_bucket, Key=csv_key, Body=csv_content)
        print(f"Uploaded {len(findings)} findings to s3://{s3_bucket}/{csv_key}")

    return {
        "account_id": account_id,
        "account_type": account_type,
        "findings_count": len(findings),
        "pass": sum(1 for f in findings if f.get("Status") == "PASS"),
        "fail": sum(1 for f in findings if f.get("Status") == "FAIL"),
        "error": sum(1 for f in findings if f.get("Status") == "ERROR"),
    }


def findings_to_csv(findings):
    """Convert findings list to CSV string."""
    if not findings:
        return ""

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=findings[0].keys())
    writer.writeheader()
    writer.writerows(findings)
    return output.getvalue()
