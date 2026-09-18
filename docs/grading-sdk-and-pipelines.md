# Grading SDK and programmable pipelines

## Stable boundaries

- `grader_contracts` is the public, immutable interface implemented by the student.
- `@check`/`@case` describe trusted deterministic checks without exposing private inputs.
- checks emit typed results and evidence; `critical` failures close the LLM gate, while `warning` and `info` remain evidence.
- pipeline handlers react to typed events and return actions. They cannot write platform state.
- grader, runtime, LLM and custom handlers may only nominate allowlisted achievements. The platform is the sole award authority.

## Check DSL

```python
from grader_worker.grading_dsl import achievement, case, check, require

@check(
    id="fit.loss_decreases",
    title="Loss уменьшается",
    kind="integration",
    severity="critical",
    points=20,
    achievements=[achievement("assignment/lab-2/converged")],
)
@case(id="seed-1", seed=1, shape=(32, 10))
@case(id="seed-7", seed=7, shape=(64, 20))
def test_fit(context, seed, shape):
    result = context.fit(seed=seed, shape=shape)
    require.finite(result.loss[-1])
    require.less(result.loss[-1], result.loss[0])
    return {"type": "metric", "name": "loss_delta", "value": result.loss[-1] - result.loss[0]}
```

Supported kinds are `contract`, `static`, `unit`, `property`, `integration`, `e2e`, `performance`, `security` and `artifact`.

## Event pipeline

```python
from grader_worker.pipeline import on

class LabPipeline:
    @on("submission.finalized", emits=["assignment/lab-2/efficient"])
    def efficient(self, event, state, achievements):
        if state["metrics"]["peak_memory_mb"] <= 512:
            achievements.nominate(
                "assignment/lab-2/efficient",
                evidence_ids=["runtime:peak_memory_mb"],
                reason_code="memory_under_512",
            )
```

Handlers have an allowlist, an action limit and evidence-reference validation. The available API intentionally contains `nominate` and `progress`, but no `award`, database or network operation.

OOM and hard runtime termination are produced outside the killed container. `resolve_achievement_triggers` evaluates declarative runtime triggers against those events before the result is sent to the platform.

## Achievement namespaces

- `common/<key>` — platform-wide;
- `course/<course-key>/<key>` — reusable course achievement;
- `run/<run-key>/<key>` — one course run;
- `assignment/<assignment-key>/<key>` — one laboratory;
- `custom/<owner-key>/<key>` — teacher extension.

The trusted platform event `submission.finalized` covers the common “finish the
lab” case after teacher approval (including a completed manual defense):

```json
{
  "allowed_sources": ["platform"],
  "trigger": {"source": "platform", "event": "submission.finalized"}
}
```

An optional `trigger.actions` array can restrict it to selected final decisions,
for example `approve` or `finalize_manual_defense`. Any number of assignment
definitions may subscribe to the same completion event; normal repeatability
and idempotency rules still apply.

Every definition controls visibility, repeatability, award policy, allowed sources and visual presentation. An immutable definition snapshot and evidence IDs are stored with every award.

## LLM pipeline

An assignment version defines whether LLM review is enabled, whether questions are allowed, the answer deadline and `max_rounds` (currently hard-limited to two). Each model response is stored as an immutable `llm_review_steps` row and appended to `state_json`.

The current flow is:

```text
deterministic gate
  -> initial review
  -> optional question 1
  -> answer evaluation
  -> optional question 2
  -> final recommendation
  -> teacher decision
```

The model may nominate only definitions whose `allowed_sources` contain `llm`. Automatic awards additionally require `confidence=high`; other nominations wait for teacher confirmation. Student material remains untrusted and is sanitized before every call.

## Current Lab 1 example

`graders/lab1/suite.py` builds eighteen parameterized unit checks with the DSL. `graders/lab1/pipeline.py` nominates `assignment/lab-1/all-functions` only when every required function passed. Existing contracts and sandbox isolation are unchanged.
