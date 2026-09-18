# Local workflow smoke test — 2026-09-16

Executed through `runsc-ptrace` without Git checkout. Secrets and raw provider
requests are intentionally not recorded.

1. Incomplete implementation: deterministic contract gate failed with 17 missing
   required symbols; LLM was not invoked.
2. Reference implementation plus content-free report: deterministic 18/18; LLM
   assigned 60/60 correctness and 0/40 understanding, then requested a concrete
   explanation of `multiplicative_persistence` and `analyze_time_series`.
3. Reference implementation plus substantive report: deterministic 18/18; LLM
   assigned 100/100 and recommended `accept`.

Observed provider route during the second scenario: Cloudflare timed out, Groq
returned an authentication failure, and OpenRouter completed successfully. The
third scenario was intentionally routed directly to OpenRouter to shorten the
smoke test. Follow-up action: verify the Groq credential and tune the Cloudflare
timeout independently of this code path.
