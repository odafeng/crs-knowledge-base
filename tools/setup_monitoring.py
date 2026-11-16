"""Health and job-failure alerts for one GutHub Google Cloud project (F3 #78, docs/runbook-cutover.md).

    python3 tools/setup_monitoring.py guthub-staging guthub-api-xxxx-an.a.run.app [channel ...]

Creates, if missing (matched by display name, so reruns change nothing):
- an uptime check on https://<host>/api/v1/health every 5 minutes;
- an alert when that check fails from more than one region;
- an alert when any Cloud Run job execution fails (the daily purge, Paper Watch).

Channels are notification channel resource names (projects/<p>/notificationChannels/<id>); without any, incidents
still open in the Cloud Console but nobody is emailed. Spend alerts are the billing budgets, set up separately.
Uses the Monitoring REST API with the caller's gcloud credentials. Uptime-metric alerts are not billed; other alert
conditions are free until at least 2027-09 (Google's announced start of alerting charges).
"""

import json
import subprocess
import sys
import urllib.request

API = "https://monitoring.googleapis.com/v3"
UPTIME_NAME = "GutHub API health"
UPTIME_ALERT = "GutHub API health check failing"
JOB_ALERT = "GutHub Cloud Run job failed"


def call(method: str, url: str, body: dict | None = None) -> dict:
    token = subprocess.run(
        ["gcloud", "auth", "print-access-token"], check=True, capture_output=True, text=True
    ).stdout.strip()
    request = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def existing(project: str, collection: str, key: str) -> dict[str, dict]:
    items = call("GET", f"{API}/projects/{project}/{collection}?pageSize=500").get(key, [])
    return {item["displayName"]: item for item in items}


def main(project: str, host: str, channels: list[str]) -> None:
    checks = existing(project, "uptimeCheckConfigs", "uptimeCheckConfigs")
    check = checks.get(UPTIME_NAME) or call(
        "POST",
        f"{API}/projects/{project}/uptimeCheckConfigs",
        {
            "displayName": UPTIME_NAME,
            "monitoredResource": {"type": "uptime_url", "labels": {"project_id": project, "host": host}},
            "httpCheck": {"path": "/api/v1/health", "port": 443, "useSsl": True, "validateSsl": True},
            "period": "300s",
            "timeout": "10s",
        },
    )
    check_id = check["name"].rsplit("/", 1)[-1]
    print(f"uptime check: {check_id}")

    policies = existing(project, "alertPolicies", "alertPolicies")
    wanted = {
        UPTIME_ALERT: {
            "displayName": "health check fails from more than one region",
            "conditionThreshold": {
                "filter": (
                    'metric.type="monitoring.googleapis.com/uptime_check/check_passed" '
                    f'AND metric.label.check_id="{check_id}" AND resource.type="uptime_url"'
                ),
                "aggregations": [
                    {
                        "alignmentPeriod": "1200s",
                        "perSeriesAligner": "ALIGN_NEXT_OLDER",
                        "crossSeriesReducer": "REDUCE_COUNT_FALSE",
                        "groupByFields": ["resource.label.*"],
                    }
                ],
                "comparison": "COMPARISON_GT",
                "thresholdValue": 1,
                "duration": "60s",
                "trigger": {"count": 1},
            },
        },
        JOB_ALERT: {
            "displayName": "a job execution ended as failed",
            "conditionThreshold": {
                "filter": (
                    'metric.type="run.googleapis.com/job/completed_execution_count" '
                    'AND metric.label.result="failed" AND resource.type="cloud_run_job"'
                ),
                "aggregations": [
                    {
                        "alignmentPeriod": "300s",
                        "perSeriesAligner": "ALIGN_SUM",
                        "crossSeriesReducer": "REDUCE_SUM",
                        "groupByFields": ["resource.label.job_name"],
                    }
                ],
                "comparison": "COMPARISON_GT",
                "thresholdValue": 0,
                "duration": "0s",
                "trigger": {"count": 1},
            },
        },
    }
    for name, condition in wanted.items():
        if name in policies:
            print(f"alert policy exists: {name}")
            continue
        call(
            "POST",
            f"{API}/projects/{project}/alertPolicies",
            {
                "displayName": name,
                "combiner": "OR",
                "conditions": [condition],
                "notificationChannels": channels,
                "documentation": {
                    "content": "What to check and how to recover: docs/runbook-cutover.md in the repository.",
                    "mimeType": "text/markdown",
                },
            },
        )
        print(f"alert policy created: {name}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
