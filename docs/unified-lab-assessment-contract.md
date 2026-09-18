# Unified lab assessment contract

Одинаковый для всех лабораторных поток:

```text
grader/runtime evidence → critical gate → configurable code reviewer
→ optional questions → platform assessment → teacher decision
```

## Evidence

Каждое наблюдение имеет стабильный `id`, `source`, `severity`, `category`,
человекочитаемый `summary`, структурированные `facts`, `confidence` и опциональный
`criterion_id`. Разрешённые severity:

- `critical` — только deterministic grader/runtime/pipeline; блокирует LLM;
- `warning` — требует внимания, но не означает автоматическое снижение;
- `positive` — подтверждённая сильная сторона, но не означает автоматическое повышение.

Code Reviewer видит очищенный код и может создавать только `warning`/`positive`.
Его настройка принадлежит версии лабораторной: focus, вопросы и число кругов.

## Platform Assessment

Assessment обязателен после успешного deterministic gate, даже если Code
Reviewer отключён. Он не получает код, repository, персональные данные, hidden
tests или private logs. Вход: versioned rubric и immutable evidence. Выход:

- score для каждого criterion в допустимом range/step;
- обязательные ссылки на существующие `evidence_id`;
- проверяемая итоговая сумма;
- recommendation и teacher summary;
- сгруппированный evidence report.

Assessment не отменяет deterministic evidence и остаётся предложением. Финальное
решение и любое изменение оценки принадлежат преподавателю и журналируются.
