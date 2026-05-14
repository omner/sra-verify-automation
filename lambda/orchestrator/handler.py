"""
Orchestrator Lambda: lists org accounts, invokes scanner per account, consolidates results.

Invoke with empty payload {} or optionally:
{
    "account_ids": ["123456789012"],  # override: scan specific accounts only
    "account_type": "all"             # override: scan specific account type only
}
"""

import json
import os
import csv
import io
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3


def lambda_handler(event, context):
    scanner_fn = os.environ["SCANNER_FUNCTION_NAME"]
    s3_bucket = os.environ["S3_BUCKET"]
    audit_accounts = os.environ["AUDIT_ACCOUNTS"].split(",")
    log_archive_accounts = os.environ["LOG_ARCHIVE_ACCOUNTS"].split(",")

    scan_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # Determine accounts to scan
    if "account_ids" in event and event["account_ids"]:
        account_ids = event["account_ids"]
    else:
        account_ids = list_org_accounts()

    print(f"Scan {scan_id}: {len(account_ids)} accounts to scan")

    # Classify accounts
    org_client = boto3.client("organizations")
    mgmt_account = org_client.describe_organization()["Organization"]["MasterAccountId"]

    scan_tasks = build_scan_tasks(
        account_ids, mgmt_account, audit_accounts, log_archive_accounts
    )

    # Optionally filter by account_type
    if event.get("account_type") and event["account_type"] != "all":
        scan_tasks = [t for t in scan_tasks if t["account_type"] == event["account_type"]]

    print(f"Dispatching {len(scan_tasks)} scan tasks")

    # Invoke scanner Lambda per account (parallel, up to 10 concurrent)
    lambda_client = boto3.client("lambda")
    results = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {}
        for task in scan_tasks:
            payload = {
                "account_id": task["account_id"],
                "account_type": task["account_type"],
                "scan_id": scan_id,
            }
            future = executor.submit(invoke_scanner, lambda_client, scanner_fn, payload)
            futures[future] = task

        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
                results.append(result)
                print(f"  Account {task['account_id']} ({task['account_type']}): "
                      f"{result.get('findings_count', 0)} findings")
            except Exception as e:
                print(f"  Account {task['account_id']} FAILED: {e}")
                results.append({
                    "account_id": task["account_id"],
                    "account_type": task["account_type"],
                    "findings_count": 0,
                    "error": str(e),
                })

    # Consolidate results from S3
    consolidate_findings(s3_bucket, scan_id)

    summary = {
        "scan_id": scan_id,
        "accounts_scanned": len(results),
        "total_findings": sum(r.get("findings_count", 0) for r in results),
        "total_pass": sum(r.get("pass", 0) for r in results),
        "total_fail": sum(r.get("fail", 0) for r in results),
        "total_error": sum(r.get("error_count", r.get("error", 0)) for r in results if isinstance(r.get("error", 0), int)),
        "s3_csv": f"s3://{s3_bucket}/sraverify/reports/consolidated/{scan_id}/sra-verify-consolidated.csv",
        "s3_dashboard": f"s3://{s3_bucket}/sraverify/reports/consolidated/{scan_id}/sra-verify-dashboard.html",
    }

    print(f"Scan complete: {json.dumps(summary, indent=2)}")
    return summary


def list_org_accounts():
    """List all active accounts in the organization."""
    org = boto3.client("organizations")
    accounts = []
    paginator = org.get_paginator("list_accounts")
    for page in paginator.paginate():
        for acct in page["Accounts"]:
            if acct["Status"] == "ACTIVE":
                accounts.append(acct["Id"])
    return accounts


def build_scan_tasks(account_ids, mgmt_account, audit_accounts, log_archive_accounts):
    """Classify each account and build scan task list."""
    tasks = []
    for acct_id in account_ids:
        if acct_id == mgmt_account:
            account_type = "management"
        elif acct_id in audit_accounts:
            account_type = "audit"
        elif acct_id in log_archive_accounts:
            account_type = "log-archive"
        else:
            account_type = "application"

        tasks.append({"account_id": acct_id, "account_type": account_type})
    return tasks


def invoke_scanner(lambda_client, function_name, payload):
    """Invoke the scanner Lambda synchronously."""
    response = lambda_client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload),
    )
    response_payload = json.loads(response["Payload"].read())

    if "FunctionError" in response:
        raise RuntimeError(f"Scanner error: {response_payload}")

    return response_payload


def consolidate_findings(s3_bucket, scan_id):
    """Read all per-account CSVs, write a consolidated file, and copy the dashboard."""
    s3 = boto3.client("s3")
    prefix = f"sraverify/reports/raw/{scan_id}/"

    all_rows = []
    headers = None

    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=s3_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            response = s3.get_object(Bucket=s3_bucket, Key=obj["Key"])
            content = response["Body"].read().decode("utf-8")
            reader = csv.DictReader(io.StringIO(content))
            if headers is None:
                headers = reader.fieldnames
            for row in reader:
                all_rows.append(row)

    if not all_rows or not headers:
        print("No findings to consolidate")
        return

    # Write consolidated CSV
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    writer.writerows(all_rows)

    consolidated_key = f"sraverify/reports/consolidated/{scan_id}/sra-verify-consolidated.csv"
    s3.put_object(Bucket=s3_bucket, Key=consolidated_key, Body=output.getvalue())
    print(f"Consolidated {len(all_rows)} findings to s3://{s3_bucket}/{consolidated_key}")

    # Copy dashboard HTML to the same prefix
    upload_dashboard(s3, s3_bucket, scan_id)


def upload_dashboard(s3, s3_bucket, scan_id):
    """Upload the SRA Verify dashboard HTML to S3 next to the consolidated CSV."""
    import urllib.request

    dashboard_url = "https://raw.githubusercontent.com/awslabs/sra-verify/main/sra-verify-dashboard.html"
    dashboard_key = f"sraverify/reports/consolidated/{scan_id}/sra-verify-dashboard.html"

    try:
        with urllib.request.urlopen(dashboard_url) as resp:
            dashboard_content = resp.read()

        s3.put_object(
            Bucket=s3_bucket,
            Key=dashboard_key,
            Body=dashboard_content,
            ContentType="text/html",
        )
        print(f"Dashboard uploaded to s3://{s3_bucket}/{dashboard_key}")
    except Exception as e:
        print(f"Warning: could not upload dashboard: {e}")
