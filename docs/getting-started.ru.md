# Grader Worker — безопасный запуск

## Назначение и граница доверия

`grader-worker` — доверенный локальный исполнитель очереди лабораторных из
Quiz Platform. Он получает exact submission snapshot, запускает deterministic
pipeline в одноразовом gVisor-контейнере, формирует публичные/приватные
диагностики и только после успешного deterministic gate запускает LLM-review.

Сам движок и демонстрационный grader можно публиковать. Закрытые тесты,
эталонные решения и production grader-packs должны находиться в отдельном
**приватном** репозитории или локальном хранилище. Демонстрационный starter:
`<DEMO_LAB_REPOSITORY_URL>`; он намеренно сокращён.

## Поддерживаемый контур

- Python 3.12+;
- Docker Engine на выделенной Linux/WSL-системе;
- gVisor `runsc` без fallback на `runc`;
- CPU image `itruim-grader-cpu:cpu-v1`;
- сеть student sandbox отключена;
- read-only root и submission, ограниченные tmpfs, CPU/RAM/PID/time limits;
- приватные тесты монтируются отдельно и недоступны student UID;
- LLM providers опциональны и запускаются только после deterministic gate.

## Установка

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

Установите gVisor по официальной инструкции, зарегистрируйте runtime и
перезапустите Docker:

```bash
sudo runsc install
sudo systemctl restart docker
docker info --format '{{json .Runtimes}}'
```

На WSL, где systrap не работает, зарегистрируйте отдельный `runsc-ptrace` и
укажите `GRADER_OCI_RUNTIME=runsc-ptrace`. На обычном Linux предпочтительнее
стандартный `runsc`, если его self-test проходит.

## Образ и self-test

```bash
docker build -t itruim-grader-cpu:cpu-v1 -f images/cpu/Dockerfile .
python -m unittest discover -s tests -v
grader-worker plan --assignment lab1
grader-worker doctor
grader-worker selftest --assignment lab1
```

`doctor` обязан завершиться успешно. Worker не должен запускаться, если gVisor,
образ или disposable-container probe недоступны.

## Подключение к платформе

1. В админке Quiz Platform создайте grader-worker credential.
2. Скопируйте показанный один раз token в `.env` на grader-host.
3. Настройте:

```env
GRADER_API_URL=https://<PLATFORM>.workers.dev
GRADER_TOKEN=<ONE_TIME_TOKEN>
GRADER_OCI_RUNTIME=runsc
GRADER_CPU_IMAGE=itruim-grader-cpu:cpu-v1
```

Проверка связи и один цикл:

```bash
grader-worker doctor
grader-worker run --once
```

Постоянный процесс:

```bash
grader-worker run
```

Запускайте его через systemd/supervisor от отдельного непривилегированного
пользователя. Не запускайте worker от root и не помещайте пользователя в иные
привилегированные группы, кроме минимально необходимого доступа к Docker.
Доступ к Docker socket сам по себе практически эквивалентен root на host,
поэтому grader-host должен быть выделенным и не содержать посторонних данных.
Student container никогда не получает socket; им пользуется только orchestrator.

## LLM review

Порядок fallback задаёт `LLM_PROVIDER_ORDER`. Заполните только используемые
provider secrets. Если провайдеры отсутствуют или исчерпали квоту, worker
должен объявить отсутствие LLM capacity, а не обходить deterministic gate.
Студенческий контент деперсонализируется; код перед review очищается от
комментариев/docstrings, а отчёт рассматривается как недоверенные данные, не
как инструкции.

## Первая лабораторная

- публичная постановка и starter: `<DEMO_LAB_REPOSITORY_URL>`;
- trusted grader: `graders/lab1/`;
- configuration: `graders/lab1/assignment-template.json`;
- pipeline preview: `grader-worker plan --assignment lab1`;
- локальная предварительная проверка решения:

```bash
grader-worker precheck --assignment lab1 --path /path/to/solution
```

Для локальной UI-разработки без GitHub:

```bash
grader-worker serve-uploads
```

Сервис слушает только loopback, принимает ZIP/директорию и ограничивает размер
snapshot. Не выставляйте его наружу и не включайте `LOCAL_DEV_UPLOADS` в production.

## Security checklist перед реальными работами

- отдельная чистая машина/VM/WSL и отдельный системный пользователь;
- никаких cloud/SSH/GitHub/LLM secrets внутри sandbox image или mounts;
- Docker API/socket никогда не монтируется в student container;
- только gVisor; при его ошибке job получает infra failure, fallback запрещён;
- `--network none`, read-only root, `no-new-privileges`, минимальные capabilities;
- submission, canonical contracts и datasets монтируются только read-only;
- writable области — только размерно ограниченные tmpfs/result channel;
- CPU, RAM, swap, PID, wall time и output size ограничены;
- dataset ingestion отклоняет symlink, hardlink, device, FIFO и socket;
- подозрительные события и артефакты остаются локально и связываются с submission;
- наружу возвращаются только allowlisted публичные диагностики, не stderr и не
  внутренние пути/тесты;
- worker token можно отозвать из платформы; `.env` имеет права `0600`;
- регулярно обновляются Docker, gVisor и base image; image фиксируется digest;
- backup host не включает открытые student snapshots и secrets вместе.

AST/precheck — дополнительная диагностика, **не** security boundary. Docker с
обычным `runc` также не считается достаточной границей для враждебного кода.

## Production smoke-test

Перед публикацией лабораторной выполните три посылки тестового студента:

1. deterministic reject;
2. deterministic pass с LLM-вопросом;
3. успешный полный путь до решения преподавателя и достижения.

Проверьте лимиты, retry после infra failure, отсутствие внутренних логов у
студента и появление отчёта/номинаций у преподавателя.
