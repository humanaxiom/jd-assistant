#!/usr/bin/env bash
# Read-only inventory of an RTX inference/app host. RUN THIS FIRST.
#
# WHY THIS EXISTS AND WHY IT COMES FIRST
# --------------------------------------
# CLAUDE.md's standing lesson is "CHECK THE BANK, NOT THE COUNTER": do not claim a
# property you have not queried. A provisioning script written against an ASSUMED
# distro/driver/GPU is exactly that failure in a new costume — it would install a CUDA
# stack against a driver nobody looked at. So nothing is installed until this has run
# and its output has been read.
#
# It writes NOTHING, installs NOTHING, and contacts no third party. Every command is a
# read. Safe to run on a production box, safe to run twice.
#
# USAGE
#   scp deploy/rtx/triage.sh asalah@rcg-asalah-1.research.sfu.ca:/tmp/
#   ssh asalah@rcg-asalah-1.research.sfu.ca 'bash /tmp/triage.sh' | tee rtx-1.txt
#   # then the same for rcg-asalah-2
#
# Review rtx-1.txt / rtx-2.txt before pasting them anywhere: they name hostnames and
# listening ports. They contain no credentials and no JD content by construction.

set -uo pipefail   # NOT -e: a missing tool is a FINDING, not a crash.

section() { printf '\n=== %s ===\n' "$1"; }
have()    { command -v "$1" >/dev/null 2>&1; }
# Run a command if it exists; otherwise say so. Never let a missing tool end the run.
try()     { if have "$1"; then "$@" 2>&1; else echo "(absent: $1)"; fi; }

printf 'JD Bank RTX triage · host=%s · %s\n' "$(hostname -f 2>/dev/null || hostname)" "$(date -Is)"

section 'OS / kernel / arch'
try uname -a
[ -r /etc/os-release ] && grep -E '^(NAME|VERSION|ID|VERSION_ID)=' /etc/os-release || echo '(no /etc/os-release)'

section 'CPU / memory'
grep -m1 'model name' /proc/cpuinfo 2>/dev/null || echo '(no /proc/cpuinfo model name)'
echo "cores: $(nproc 2>/dev/null || echo '?')"
try free -h

section 'Disk (model weights are tens of GB — this is a go/no-go number)'
try df -h /
try df -h /var/lib/docker
echo "-- home --"; try df -h "$HOME"

section 'GPU'
if have nvidia-smi; then
  nvidia-smi 2>&1
  echo '-- per-GPU detail --'
  nvidia-smi --query-gpu=index,name,memory.total,memory.used,driver_version,compute_cap \
             --format=csv 2>&1
else
  echo '(absent: nvidia-smi — no NVIDIA driver installed, or not on PATH)'
  echo '-- is the card even visible on the PCI bus? --'
  try lspci -nn | grep -i -E 'nvidia|vga|3d' || echo '(lspci found no NVIDIA device)'
fi

section 'CUDA toolkit (optional — vLLM in Docker does NOT need it on the host)'
try nvcc --version

section 'Docker'
try docker --version
try docker compose version
echo '-- can this user run docker without sudo? --'
if have docker; then docker info >/dev/null 2>&1 && echo 'yes' || echo "no (user $(id -un) may need the docker group, or dockerd is not running)"; fi
echo "-- groups for $(id -un) --"; id -nG 2>&1

section 'NVIDIA container toolkit (what lets a container SEE the GPU)'
try nvidia-ctk --version
ls -la /etc/docker/daemon.json 2>&1 && cat /etc/docker/daemon.json 2>&1 || echo '(no /etc/docker/daemon.json)'

section 'Python (informational only — ADR-006 is Docker-only, no host venv)'
try python3 --version

section 'Listening sockets — THE SECURITY-RELEVANT ONE'
# These hosts have PUBLIC IPs (206.12.17.82/.83). Anything bound to 0.0.0.0 is exposed
# to the internet. vLLM ships NO authentication by default, so a vLLM bound to 0.0.0.0
# here is an open inference endpoint carrying JD text. This section is how we find out.
if have ss; then ss -tulpn 2>/dev/null || ss -tuln 2>&1
elif have netstat; then netstat -tulpn 2>&1
else echo '(absent: ss and netstat)'; fi

section 'Firewall posture'
try ufw status verbose
try firewall-cmd --state
try firewall-cmd --list-all
echo '-- iptables filter INPUT --'
if have iptables; then (iptables -S INPUT 2>&1 || sudo -n iptables -S INPUT 2>&1 || echo '(needs root)'); else echo '(absent: iptables)'; fi

section 'MAC layer'
try getenforce
try aa-status --summary

section 'Outbound reachability (can this box PULL images and weights?)'
for target in https://download.docker.com https://huggingface.co https://pypi.org; do
  if have curl; then
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 12 "$target" 2>&1)
    echo "$target -> HTTP ${code:-fail}"
  else
    echo '(absent: curl)'; break
  fi
done

section 'Reachability of the CURRENT inference host (aria-gb10-2, ADR-003)'
# If this box can reach aria-gb10-2, a staged migration is possible: stand vLLM up here
# while the existing Ollama endpoint keeps serving, and cut over once vectors match.
if have curl; then
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://aria-gb10-2:11434/v1/models 2>&1)
  echo "http://aria-gb10-2:11434/v1/models -> HTTP ${code:-unreachable}"
else echo '(absent: curl)'; fi

section 'Is anything already serving here?'
for port in 8000 8001 11434; do
  if have curl; then
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:${port}/v1/models" 2>&1)
    echo "127.0.0.1:${port}/v1/models -> HTTP ${code:-closed}"
  fi
done

section 'The other RTX box'
peer=$([ "$(hostname -s 2>/dev/null)" = 'rcg-asalah-1' ] && echo rcg-asalah-2 || echo rcg-asalah-1)
echo "peer: ${peer}.research.sfu.ca"
try getent hosts "${peer}.research.sfu.ca"
try ping -c1 -W3 "${peer}.research.sfu.ca"

printf '\n=== triage complete — paste this whole file back ===\n'
