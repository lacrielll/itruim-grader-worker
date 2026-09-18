# Grader Worker — secure setup

## Purpose and trust boundary

`grader-worker` is the trusted local executor for coding-assignment jobs from
Quiz Platform. It fetches an exact submission snapshot, runs the deterministic
pipeline in an ephemeral gVisor container, produces public/private diagnostics,
and starts LLM review only after the deterministic gate passes.

The engine and demo grader may be public. Hidden tests, reference solutions and
production grader packs must live in a separate **private** repository or local
store. The public demo starter is `<DEMO_LAB_REPOSITORY_URL>` and is
intentionally reduced.

## Supported environment

- Python 3.12+;
- Docker Engine on a dedicated Linux/WSL system;
- gVisor `runsc`, with no `runc` fallback;
- CPU image `itruim-grader-cpu:cpu-v1`;
- no student-sandbox network;
- read-only root/submission, bounded tmpfs and CPU/RAM/PID/time limits;
- private tests mounted separately from the student UID;
- optional LLM providers, used only after the deterministic gate.

## Installation

```bash
git clone <PRIVATE_GRADER_REPOSITORY_URL>
cd grader-worker
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
cp .env.example .env
chmod 600 .env
```

Install gVisor using its official documentation, register the runtime and
restart Docker:

```bash
sudo runsc install
sudo systemctl restart docker
docker info --format '{{json .Runtimes}}'
```

On WSL systems where systrap cannot start, register `runsc-ptrace` and set
`GRADER_OCI_RUNTIME=runsc-ptrace`. Prefer standard `runsc` on Linux when its
self-test succeeds.

## Image and self-tests

```bash
docker build -t itruim-grader-cpu:cpu-v1 -f images/cpu/Dockerfile .
python -m unittest discover -s tests -v
grader-worker plan --assignment lab1
grader-worker doctor
grader-worker selftest --assignment lab1
```

`doctor` must pass. The worker must remain unavailable when gVisor, the pinned
image or the disposable-container probe is unavailable.

## Platform connection

1. Create a grader-worker credential in the Quiz Platform admin UI.
2. Copy the one-time token into `.env` on the grader host.
3. Configure:

```env
GRADER_API_URL=https://<PLATFORM>.workers.dev
GRADER_TOKEN=<ONE_TIME_TOKEN>
GRADER_OCI_RUNTIME=runsc
GRADER_CPU_IMAGE=itruim-grader-cpu:cpu-v1
```

Verify connectivity and process one polling cycle:

```bash
grader-worker doctor
grader-worker run --once
```

Start the persistent worker with `grader-worker run`. Run it under
systemd/supervisor as a dedicated unprivileged user. Do not run the process as
root or grant unrelated host privileges.
Access to the Docker socket is effectively root-equivalent on the host, so the
grader host must be dedicated and contain no unrelated data. The student
container never receives the socket; only the trusted orchestrator uses it.

## LLM review

`LLM_PROVIDER_ORDER` defines provider fallback. Configure only providers you
actually use. When quotas are unavailable, the worker must report no LLM
capacity rather than bypassing the deterministic gate. Student input is
depersonalized; code comments/docstrings are removed before review, and report
text is treated as untrusted data rather than instructions.

## Lab 1 example

- public assignment/starter: `<DEMO_LAB_REPOSITORY_URL>`;
- trusted grader: `graders/lab1/`;
- configuration: `graders/lab1/assignment-template.json`;
- pipeline preview: `grader-worker plan --assignment lab1`;
- local solution precheck:

```bash
grader-worker precheck --assignment lab1 --path /path/to/solution
```

For local UI testing without GitHub, run `grader-worker serve-uploads`. It binds
to loopback only and enforces snapshot limits. Never expose it publicly or set
`LOCAL_DEV_UPLOADS` in production.

## Security checklist

- use a dedicated clean machine/VM/WSL distribution and system user;
- never expose cloud/SSH/GitHub/LLM secrets to the sandbox image or mounts;
- never mount the Docker socket/API into a student container;
- require gVisor; runtime failure is an infrastructure failure, never fallback;
- use no network, read-only root, `no-new-privileges` and minimal capabilities;
- mount submissions, canonical contracts and datasets read-only;
- limit writable tmpfs/result channels by size;
- enforce CPU, RAM, swap, PID, wall-time and output limits;
- reject dataset symlinks, hardlinks, devices, FIFOs and sockets;
- keep suspicious artifacts local and associate events with the submission;
- expose only allowlisted public diagnostics, never raw stderr, host paths or
  hidden-test details;
- keep `.env` mode `0600` and support immediate worker-token revocation;
- patch Docker/gVisor/base images regularly and pin production images by digest;
- do not store plaintext secrets and untrusted snapshots in the same backups.

AST/precheck is defense in depth, **not** the security boundary. Plain Docker
with `runc` is not considered a sufficient boundary for hostile code either.

## Production smoke test

Before publishing an assignment, submit three jobs using a test student:

1. a deterministic rejection;
2. a deterministic pass that produces an LLM question;
3. a complete successful flow through teacher decision and achievement award.

Verify limits, infrastructure retry, absence of private logs in the student UI,
and correct reports/nominations in the teacher UI.
