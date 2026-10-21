#!/usr/bin/env bash
# Load vendor creds from 111RUNNER.md and run DBaaS smoke tests.
# Does not print secret values.
set -euo pipefail
export PATH=/root/.pulumi/bin:/pulumi_venv/bin:${PATH:-}
# shellcheck disable=SC1091
source /pulumi_venv/bin/activate

python3 - <<'PY' >/tmp/dbaas-smoke-env.sh
import re
from pathlib import Path

text = Path("/app/111RUNNER.md").read_text()
keys = [
    "SSH_PUBLIC_KEY",
    "UPCLOUD_USERNAME",
    "UPCLOUD_PASSWORD",
    "OVH_ENDPOINT",
    "OVH_CLIENT_ID",
    "OVH_CLIENT_SECRET",
    "OVH_SUBSIDIARY",
    "OVH_PROJECT_ID",
    "OVH_CLOUD_PROJECT_SERVICE",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_DEFAULT_REGION",
    "VULTR_API_KEY",
]
for key in keys:
    m = re.search(rf'^declare -x {re.escape(key)}="(.*)"\s*$', text, re.M)
    if not m:
        print(f"# missing {key}")
        continue
    val = m.group(1).replace("'", "'\"'\"'")
    print(f"export {key}='{val}'")
PY

# shellcheck disable=SC1091
source /tmp/dbaas-smoke-env.sh
rm -f /tmp/dbaas-smoke-env.sh

for k in SSH_PUBLIC_KEY UPCLOUD_USERNAME UPCLOUD_PASSWORD OVH_CLIENT_ID \
         OVH_CLIENT_SECRET OVH_CLOUD_PROJECT_SERVICE OVH_ENDPOINT VULTR_API_KEY; do
  if [ -n "${!k:-}" ]; then
    echo "have $k"
  else
    echo "MISSING $k"
  fi
done
if [ -z "${SSH_PUBLIC_KEY:-}" ]; then
  echo "SSH_PUBLIC_KEY is required (set in env or 111RUNNER.md); refusing to run with an embedded key"
  exit 2
fi

export SC_DATA_DB_PATH=/root/.cache/sparecores-data/sc-data-all.db
export SC_DATA_NO_UPDATE=1
export PULUMI_BACKEND_URL="${PULUMI_BACKEND_URL:-file:///data/backend}"
export PULUMI_CONFIG_PASSPHRASE="${PULUMI_CONFIG_PASSPHRASE:-}"

mkdir -p /tmp/dbaas-smoke
rc=0

run_one() {
  local name="$1"
  local script="$2"
  echo "===== ${name} ====="
  if python "$script" >"/tmp/dbaas-smoke/${name}.log" 2>&1; then
    echo "${name}_OK"
  else
    echo "${name}_FAIL:$?"
    rc=1
  fi
  # Strip likely secret lines from the tail we show
  grep -vE 'password|PASSWORD|secret|SECRET|Authorization|Bearer' \
    "/tmp/dbaas-smoke/${name}.log" | tail -n 50 || true
}

run_one UPCLOUD /app/scripts/test_upcloud_dbaas.py
run_one OVH /app/scripts/test_ovh_dbaas.py
run_one VULTR /app/scripts/test_vultr_dbaas.py

echo "===== DONE rc=$rc ====="
exit "$rc"
