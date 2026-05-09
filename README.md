# DuckBot

DuckBot — это CLI-проект для автоматизации DuckMyDuck с многопрофильной авторизацией, конфигом, логированием и разнесенной бизнес-логикой.

Проект работает только через реальный `webapp_url` или `init_data` из Telegram WebApp. Сам бот не генерирует ссылку и не получает `init_data` через Telegram-клиент.

## Что умеет проект

- Работает с несколькими профилями последовательно и изолированно.
- Сам меняет `Telegram init_data` на игровой JWT через `POST /auth/telegram`.
- Всегда ходит в API как Android WebView с фиксированным mobile fingerprint.
- Кормит и разводит уток.
- Обрабатывает яйца.
- Собирает подтверждаемые награды из алертов.
- Собирает обычные награды задач через `tasks/reward`.
- Умеет работать с кастомными турнирными задачами через `tasks/reward/custom`.
- Анализирует активные турниры и механику Clan Show.
- Пишет логи в консоль и файл, маскируя секреты.

## Архитектура

```text
duckbot/
  __main__.py
  config.py
  constants.py
  exceptions.py
  masking.py
  app/
    runner.py
  cli/
    app.py
  game/
    __init__.py
    automation.py
    alerts_service.py
    base.py
    clan_show_service.py
    duck_service.py
    egg_service.py
    models.py
    player_service.py
    task_service.py
    tournament_service.py
  http/
    api_client.py
    auth_manager.py
    header_builder.py
  storage/
    runtime_state.py
  support/
    logging_setup.py
config.example.yaml
profiles.local.example.yaml
requirements.txt
README.md
```

Зоны ответственности внутри `duckbot/game`:

- `player_service.py` — снимок игрока и алерты.
- `duck_service.py` — выбор активных уток, кормление, разведение.
- `egg_service.py` — merge/open логика яиц.
- `alerts_service.py` — подтверждение наград из алертов.
- `task_service.py` — обычные и кастомные награды задач.
- `tournament_service.py` — анализ турниров.
- `clan_show_service.py` — аналитика Clan Show.
- `automation.py` — только orchestration цикла.

## Быстрый старт

1. Создайте виртуальное окружение:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

2. Установите зависимости:

```powershell
pip install -r requirements.txt
```

3. Создайте рабочие конфиги:

```powershell
Copy-Item config.example.yaml config.yaml
Copy-Item profiles.local.example.yaml profiles.local.yaml
```

4. Заполните `profiles.local.yaml`.

5. Проверьте авторизацию:

```powershell
python -m duckbot auth-check --profile main
```

6. Запустите один цикл:

```powershell
python -m duckbot once --profile main
```

## Настройка `config.yaml`

`config.yaml` хранит только общие настройки без секретов.

Ключевые поля:

- `api_base_url` — базовый API, по умолчанию `https://api.duckmyduck.com`.
- `request_timeout_seconds` — таймаут одного запроса.
- `cycle_sleep_seconds` — пауза между глобальными циклами в режиме `run`.
- `between_profiles_delay_seconds` — пауза между профилями.
- `between_actions_delay_seconds` — пауза между игровыми действиями.
- `after_feed_delay_seconds` — пауза после кормления и открытия яиц.
- `logging` — уровень логов, файл и ротация.
- `retry` — повторы, базовая задержка и множитель ожидания для `429`.
- `auth.state_path` — путь к runtime-кэшу JWT.

Флаги `features`:

- `process_eggs` — включить обработку яиц.
- `collect_alert_rewards` — подтверждать награды из алертов.
- `collect_task_rewards` — собирать обычные награды задач.
- `collect_custom_task_rewards` — собирать кастомные турнирные награды.
- `inspect_tournaments` — анализировать активные турниры.
- `inspect_clan_show` — анализировать Clan Show.

Параметры `game`:

- `max_merge_slot` — размер активного поля яиц.
- `clan_show_log_best_targets_limit` — сколько лучших целей Clan Show показывать в логах.
- `clan_show_log_recent_attacks_limit` — сколько недавних атак показывать в логах аналитики.
- `feed_rules` — компактные лимиты кормления по редкости и уровням. Можно задавать списком на 5 уровней, например `COMMON: [30, 30, 35, 40, 50]`.
- `breed_rules` — компактные правила скрещивания по редкости и уровням, например `COMMON: { currency: "corn", levels: [1, 2, 3, 4, 5] }`.

Секция `http_headers` хранит безопасные общие заголовки. Mobile fingerprint не переопределяется и всегда остается Android.

## Настройка `profiles.local.yaml`

Этот файл содержит секреты и не должен попадать в git.

Для каждого профиля обязательны:

- `name`
- `enabled`
- ровно один источник авторизации: `webapp_url` или `init_data`

Пример:

```yaml
profiles:
  - name: "main"
    enabled: true
    webapp_url: "https://selector.duckmyduck.com/#tgWebAppData=..."

  - name: "farm2"
    enabled: true
    init_data: "query_id=...&user=%7B...%7D&auth_date=...&signature=...&hash=..."
```

Важно:

- нельзя указывать одновременно `webapp_url` и `init_data`
- нельзя оставлять оба поля пустыми
- `init_data` можно хранить как raw-строку или percent-encoded вариант

## Команды

Проверка авторизации:

```powershell
python -m duckbot auth-check --profile main
```

Один цикл по одному профилю:

```powershell
python -m duckbot once --profile main
```

Один цикл по всем включенным профилям:

```powershell
python -m duckbot once --all
```

Бесконечный рабочий цикл:

```powershell
python -m duckbot run --all
```

## Как устроена авторизация

Поток авторизации такой:

1. Профиль хранит `webapp_url` или `init_data`.
2. Если задан `webapp_url`, из него извлекается `tgWebAppData`.
3. Бот вызывает `POST /auth/telegram`.
4. Сервер игры возвращает JWT.
5. JWT сохраняется в `runtime/state.json`.
6. При старте, при `401` и перед истечением `exp` токен обновляется автоматически.

## Что реализовано по новой механике

По `endpoints.txt` и ответам API вынесены отдельные сценарии:

- `/alert/action` — подтверждение наград из алертов.
- `/tasks` + `/tasks/reward` — сбор обычных наград задач.
- `/tasks/reward/custom` — обработка кастомных турнирных задач.
- `/tournaments` — анализ активных турниров.
- `/clans/show/sabotages` — чтение доступных саботажей.
- `/clans/show/sabotage/best-targets` — выбор лучших целей по шансам и риску.
- `/clans/show/sabotage/attacks` — чтение истории атак.

Что важно:

- `collect_custom_task_rewards` по умолчанию выключен, потому что такие задачи расходуют яйца.
- Для кастомных наград бот сам подбирает `slotIds` по критериям задачи и сначала предпочитает инвентарные слоты вне активного merge-поля.
- Использование `/clans/show/sabotage/use` автоматически не включено: там нужен осознанный выбор цели и это уже боевая мутация, а не безопасный сбор наград.

## Что исправлено

- Исправлена ошибка со стейкингом: раньше бот резал список уток по `duckSlotsCount` до фильтрации состояний, поэтому `STAKE` съедал один слот и часть кормимых уток пропускалась.
- Теперь активные утки выбираются только из состояний `FEED`, `BREED` и `BREEDING`, и только потом ограничиваются количеством слотов.
- Игровая логика больше не живет в одном монолите: она разнесена по сервисам с четкой зоной ответственности.
- После кастомных турнирных наград список яиц больше не переиспользуется вслепую в том же цикле, чтобы не работать по устаревшему снимку.

## Логи и runtime-состояние

- Логи по умолчанию пишутся в `logs/duckbot.log`.
- JWT и служебное состояние профилей хранятся в `runtime/state.json`.
- В логах маскируются:
  - `authorization`
  - JWT
  - `init_data`
  - полный `webapp_url`
  - чувствительные query-параметры Telegram

## Mobile fingerprint

Все запросы всегда отправляются как Android WebView.

Неизменяемые заголовки:

- `sec-ch-ua-platform: "Android"`
- `sec-ch-ua-mobile: ?1`
- `user-agent: Mozilla/5.0 (Linux; Android 12; Pixel 6 Build/SQ3A.220705.004; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/143.0.0.0 Mobile Safari/537.36`

## Запуск в Windows

Сам бот работает как обычный долгоживущий процесс. Для автозапуска можно использовать:

- `Task Scheduler`
- `NSSM`
- любой другой менеджер процессов

Команда запуска:

```powershell
python -m duckbot run --all
```

Рабочая директория должна указывать на корень проекта, где лежат `config.yaml` и `profiles.local.yaml`.

## Проверка проекта

Запуск тестов:

```powershell
python -m unittest discover -s tests -v
```

Быстрый smoke flow:

1. `python -m duckbot auth-check --profile main`
2. `python -m duckbot once --profile main`
3. `python -m duckbot run --all`

## Устранение неполадок

`INIT_WRONG`

- `init_data` устарел
- в профиль попала неполная ссылка
- скопирован не `tgWebAppData`, а другая часть URL

`401 Unauthorized`

- сервер отозвал старый JWT
- бот сам попытается получить новый через `/auth/telegram`

`Файл config.yaml не найден`

- создайте `config.yaml` из `config.example.yaml`

`Профиль не найден`

- проверьте имя профиля в `profiles.local.yaml`
- проверьте корректность YAML
