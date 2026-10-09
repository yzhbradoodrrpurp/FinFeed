#!/usr/bin/env bash
# Deploy a committed revision from an existing checkout on the Oracle VM.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo on the Oracle instance'; exit 1; }
exec 9>/run/finfeed-deploy.lock
flock -n 9 || { echo 'Another deployment is running'; exit 1; }
repo_dir=${1:?Usage: sudo bash deploy.sh /path/to/FinFeed [revision]}
revision=${2:-oracle-backend}
commit=$(git -C "$repo_dir" rev-parse --verify "$revision^{commit}")
release=$(mktemp -d "/opt/finfeed/releases/$commit.XXXXXX")
previous=$(readlink -f /opt/finfeed/current || true)
activated=false
rollback() {
  if [[ $activated == true && -n $previous ]]; then
    ln -s "$previous" /opt/finfeed/rollback-link
    mv -Tf /opt/finfeed/rollback-link /opt/finfeed/current
    systemctl restart finfeed
    echo 'Deployment failed; previous release restored'
  fi
}
trap rollback ERR
# Archive committed source only; no .env, local credentials, or private records.
git -C "$repo_dir" archive "$commit" | tar -x -C "$release"
python3 -m venv "$release/.venv"
"$release/.venv/bin/python" -m pip install -r "$release/dashboard/requirements-cloud.txt"
# Install the pinned optional proxy on both supported Linux architectures.
(cd "$release/dashboard" && "$release/.venv/bin/python" -c 'from deployment.mihomo_runtime import install; install()')
chown -R root:root "$release"
install -d -o finfeed -g finfeed -m 700 "$release/dashboard/.cache"
chown -R finfeed:finfeed "$release/dashboard/.cache"
ln -s "$release" /opt/finfeed/next
mv -Tf /opt/finfeed/next /opt/finfeed/current
activated=true
systemctl enable finfeed
systemctl restart finfeed
healthy=false
for attempt in $(seq 1 60); do
  if curl --fail --silent --max-time 2 http://127.0.0.1:10000/api/health >/dev/null; then
    healthy=true; break
  fi
  sleep 2
done
if [[ $healthy != true ]]; then
  echo 'New backend did not become healthy'
  false
fi
printf 'Deployed commit %s\n' "$commit"
printf '%s\n' 'Keep previous releases for rollback. Validate HTTPS, login and data before cutover.'
