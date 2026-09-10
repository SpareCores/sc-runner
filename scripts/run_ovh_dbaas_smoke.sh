#!/usr/bin/env bash
# Re-run OVH DBaaS smoke only.
set -uo pipefail
export PATH=/root/.pulumi/bin:/pulumi_venv/bin:${PATH:-}
# shellcheck disable=SC1091
source /pulumi_venv/bin/activate

python3 - <<'PY' >/tmp/dbaas-smoke-env.sh
import re
from pathlib import Path

text = Path("/app/111RUNNER.md").read_text()
keys = [
    "OVH_ENDPOINT",
    "OVH_CLIENT_ID",
    "OVH_CLIENT_SECRET",
    "OVH_SUBSIDIARY",
    "OVH_PROJECT_ID",
    "OVH_CLOUD_PROJECT_SERVICE",
]
for key in keys:
    m = re.search(rf'^declare -x {re.escape(key)}="(.*)"\s*$', text, re.M)
    if not m:
        continue
    val = m.group(1).replace("'", "'\"'\"'")
    print(f"export {key}='{val}'")
PY
# shellcheck disable=SC1091
source /tmp/dbaas-smoke-env.sh
rm -f /tmp/dbaas-smoke-env.sh

for k in OVH_CLIENT_ID OVH_CLIENT_SECRET OVH_CLOUD_PROJECT_SERVICE OVH_ENDPOINT; do
  if [ -n "${!k:-}" ]; then echo "have $k"; else echo "MISSING $k"; fi
done

export SC_DATA_DB_PATH=/root/.cache/sparecores-data/sc-data-all.db
export SC_DATA_NO_UPDATE=1
export PULUMI_BACKEND_URL="${PULUMI_BACKEND_URL:-file:///data/backend}"
export PULUMI_CONFIG_PASSPHRASE="${PULUMI_CONFIG_PASSPHRASE:-}"

mkdir -p /tmp/dbaas-smoke
set +e
python /app/scripts/test_ovh_dbaas.py > /tmp/dbaas-smoke/OVH2.log 2>&1
rc=$?
set -e
echo "OVH_EXIT:$rc"
grep -vE 'password|PASSWORD|secret|SECRET|Bearer|Client.Secret' /tmp/dbaas-smoke/OVH2.log | tail -n 100
exit "$rc"
