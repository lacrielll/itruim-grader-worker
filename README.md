# Itruim grader worker

Documentation: **[Русский](docs/getting-started.ru.md)** · **[English](docs/getting-started.en.md)**

Companion grader for the [**Itruim** learning platform](https://github.com/lacrielll/itruim). It polls the Itruim API and executes untrusted student
snapshots in disposable Docker containers.

The repository includes both sides of a minimal example:

- [`examples/lab1`](examples/lab1) — a small demonstration assignment given to a student;
- [`graders/lab1`](graders/lab1) — its public, intentionally reduced grader configuration.

The example demonstrates the integration contract and is not a production course assignment. Real tests and assignment-specific secrets belong in a private grader repository.

Current milestone supports the CPU profile and the Lab 1 deterministic grader.
No student dependencies are installed at job time. Network is disabled inside
the sandbox.

The universal linear stage/runtime model is documented in
[`docs/universal-grader.md`](docs/universal-grader.md). Inspect a trusted
assignment plan without executing a submission:

```bash
grader-worker plan --assignment lab1
```

The untrusted process is allowed to start only with gVisor (`runsc`). There is
no fallback to ordinary `runc`. Install `runsc` using the official gVisor
instructions, run `sudo runsc install`, restart Docker and verify that
`docker info --format '{{json .Runtimes}}'` contains `runsc`. Until then the
worker intentionally stays unavailable and does not execute student code.

On WSL, where the default systrap platform may fail during `StartRoot`, register
the ptrace platform as `runsc-ptrace`. The worker defaults to that runtime here;
override it explicitly with `GRADER_OCI_RUNTIME` on another host.

For the dedicated WSL distribution, disable Windows interop and Windows-drive
automount, keep SSH/API keys out of the distribution, and run this worker as a
dedicated unprivileged user. Sandbox networking remains disabled.

```bash
docker build -t itruim-grader-cpu:cpu-v1 -f images/cpu/Dockerfile .
python3 -m unittest discover -s tests -v

export GRADER_API_URL=http://localhost:5173
export GRADER_TOKEN=the-one-time-worker-token
export GRADER_OCI_RUNTIME=runsc-ptrace
python3 -m grader_worker.cli doctor
python3 -m grader_worker.cli run
```

## Local solution uploads

For local development, solutions can stay entirely on the machine instead of
being pushed to Git. Start the loopback upload service in a second terminal:

```bash
grader-worker serve-uploads
```

It accepts a ZIP or a browser-selected directory at `127.0.0.1:8790`, validates
the same 10 MB / 500 file snapshot limits and stores it under
`.worker-state/local-uploads`. The normal worker reads the snapshot from that
directory when the queued submission uses a `local-upload://` source.

The quiz platform must also have `LOCAL_DEV_UPLOADS=true` in its local
`.dev.vars`. Never set this variable on the deployed Worker. The intake server
refuses non-loopback binding and rejects browser origins outside
`LOCAL_UPLOAD_ALLOWED_ORIGINS`.

`doctor` verifies Docker, the pinned image and a disposable-container probe
before the worker reports itself ready to the backend.

## Run the platform and grader together

1. Start Itruim locally and enable `LOCAL_DEV_UPLOADS=true` in its `.dev.vars`.
2. Build the CPU image and run `grader-worker doctor`.
3. Start `grader-worker serve-uploads` and then `grader-worker run` in separate terminals.
4. Create a laboratory in Itruim using `graders/lab1/assignment-template.json` as a reference.
5. Upload a copy of `examples/lab1`, submit it from the student workspace, and follow the result through the grading queue.

See the [Russian](docs/getting-started.ru.md) or [English](docs/getting-started.en.md) guide for the complete setup.

## License

The grader worker is licensed under Apache License 2.0. The demonstration assignment in `examples/lab1` is explicitly excluded and currently has no reuse license; see its local `LICENSE` file.
