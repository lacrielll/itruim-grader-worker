# Универсальный grader: execution pipeline

## Цель

Grader проверяет не только Python. Лаборатория описывает линейный набор этапов,
а каждый этап явно выбирает зарегистрированный runtime-профиль. Python-файл
лаборатории является доверенной конфигурацией, но компилируется в ограниченный
execution plan: он не получает `docker.sock`, host network, произвольные mount,
image или capabilities.

```text
snapshot → validate → compile → tests → evidence → reviewer → assessment
```

Нелинейный DAG намеренно не поддерживается. Этап может завершить pipeline,
продолжить его после warning, быть пропущен после critical или повториться после
инфраструктурной ошибки.

## Модель

- `RuntimeProfile` — разрешённый администратором image, executor, команды и
  верхние границы ресурсов.
- `Stage` — шаг проверки и выбранный runtime.
- `StageResult` — единый результат: status, evidence, diagnostics, metrics,
  artifacts и achievement nominations.
- `PipelineDefinition` — линейная версия проверки лаборатории.
- `LinearPipelineRunner` — переходы, fail-fast и infrastructure retry.

Статусы этапа: `passed`, `warning`, `failed`, `infra_error`, `skipped`.
`failed` означает ошибку решения студента. `infra_error` никогда не считается
ошибкой студента и может автоматически повторяться.

## Runtime на каждом этапе

```python
PIPELINE = PipelineDefinition(
    id="cpp-basics",
    stages=(
        CommandStage(
            id="compile",
            title="Компиляция",
            runtime="cpp-gcc-14",
            command=("grader-compile",),
        ),
        CommandStage(
            id="tests",
            title="Автоматические тесты",
            runtime="cpp-tests",
            command=("grader-tests",),
        ),
    ),
)
```

Команды — заранее разрешённые команды образа, а не shell-строки из UI.
Неуспешная компиляция возвращает `failed`, следующие этапы получают `skipped`,
LLM не запускается. Преподаватель может только ужесточить лимит профиля.

## Уже реализовано

- registry runtime-профилей и resource ceilings;
- runtime на каждом этапе;
- линейный runner, fail-fast, warning и infrastructure retry;
- networkless `CommandStage` в отдельном gVisor-контейнере;
- read-only submission/root, dropped capabilities, no-new-privileges;
- bounded tmpfs для `/tmp` и `/workspace`;
- preview через `grader-worker plan --assignment lab1`;
- Lab 1 представлена совместимым `LegacyGraderStage`.

## Датасеты

Набор устанавливается доверенной ingestion-командой до запуска посылок:

```bash
grader-worker dataset-ingest \
  --dataset-id course/mnist-train \
  --dataset-version 1 \
  --path /trusted-downloads/mnist-train
```

Registry отклоняет symlink, hardlink, device, FIFO и socket, применяет лимиты,
считает SHA-256 manifest, копирует обычные файлы в content-addressed store и
делает версию неизменяемой. Этап использует только логическое имя и digest:

```python
CommandStage(
    id="fit",
    title="Обучение",
    runtime="python-cpu",
    datasets=(
        DatasetMount(
            alias="train",
            dataset_id="course/mnist-train",
            version="1",
            digest="sha256:...",
        ),
    ),
    command=("python", "train.py", "--dataset", "/datasets/train"),
)
```

Worker сам разрешает host path и монтирует только каталог конкретного digest в
`/datasets/<alias>` с `readonly` и `rprivate`. Student/teacher payload никогда
не содержит host path. Датасет можно копировать внутри ограниченного sandbox —
конфиденциальность здесь не является целью, важны целостность и отсутствие
пути к host filesystem.

## Следующий обязательный слой

До разделения compile и tests нужен типизированный artifact transport. Общий
writable workspace небезопасен: ранний этап может подменить вход следующего.

1. Этап пишет только в bounded tmpfs.
2. Orchestrator извлекает только allowlisted output.
3. Проверяет число, размер, тип и digest.
4. Сохраняет immutable artifact.
5. Следующий чистый контейнер получает artifact read-only.

После этого добавляются parser-адаптеры (`pytest`, JUnit, CTest), profiles для
C/C++/Java/Node и одноразовый PostgreSQL service runtime. PostgreSQL получает
приватную сеть и volume на одну посылку; SQL студента не выполняется от
superuser и никогда не видит БД платформы.

## Граница доверия

```text
platform control plane
        ↓ validated plan
trusted orchestrator
        ↓ bounded protocol
fresh untrusted sandbox per stage
```

AST-политика — ранняя диагностика, а не sandbox. Основная защита — gVisor, UID
separation, filesystem permissions, отсутствие сети, лимиты и отсутствие
секретов внутри student runtime.
