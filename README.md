
---

# Запуск

## Требования

- Python 3.12+ и [uv](https://docs.astral.sh/uv/)
- Playwright + Chromium (полный, **не** headless-shell)
- Сеть до `fedresurs.ru` и Bitrix24
- Linux без графической сессии — дополнительно `xvfb`
- Для Bitrix24 — входящий webhook с правами на `crm`

## 1. Установка

```bash
cd moll-fedresurs-new
uv sync
uv run playwright install chromium
```

Linux-сервер без GUI:

```bash
sudo apt install -y xvfb
# при необходимости системных библиотек Chromium:
uv run playwright install --with-deps chromium
```

## 2. Конфигурация

```bash
cp .env.example .env
```

Заполнить в `.env`:

| Переменная | Назначение |
|---|---|
| `BITRIX_BASE_URL` | адрес портала, например `https://company.bitrix24.ru` |
| `BITRIX_KEY_202` | ключ входящего webhook |
| `BITRIX_USER_ID` | ID пользователя webhook |
| `BITRIX_WRITE_ENABLED` | `false` по умолчанию; запись в Bitrix включается только вместе с `sync --write` |
| `BITRIX_DRY_RUN` | `true` по умолчанию |
| `PORTAL_LAUNCH_MODE` | `local` (macOS/Windows), `xvfb` (Linux-сервер), `cdp` (внешний Chrome) |
| `PORTAL_PROFILE_DIR` | каталог persistent-профиля браузера, по умолчанию `var/browser-profile` |

`.env` и `var/` в `.gitignore`; секреты в репозиторий не попадают.

Linux-сервер:

```bash
export PORTAL_LAUNCH_MODE=xvfb
```

## 3. Первый запуск

```bash
# 1. создать/обновить SQLite
uv run python src/main.py init-db

# 2. проверить настройки, БД и доступ к Bitrix (read-only)
uv run python src/main.py doctor --network

# 3. проверить доступ к порталу и поведение Qrator
uv run python src/main.py probe
```

`probe` должен показать живую сессию, TTL cookie `qrator_jsid2` и долю ошибок.
Если вместо этого 403/451 — см. раздел «Ограничения источника».

```bash
# 4. собрать свежие торги и детализацию по 50 кандидатам
uv run python src/main.py collect \
  --trade-type PublicOffer \
  --lookback-hours 24 \
  --details-limit 50

# 5. проверить, что уйдёт в Bitrix (ничего не пишется)
uv run python src/main.py sync --limit 20
```

## 4. Включение записи в Bitrix

Запись включается **двумя** независимыми условиями:

```bash
# .env
BITRIX_WRITE_ENABLED=true
BITRIX_DRY_RUN=false
```

```bash
uv run python src/main.py sync --limit 20 --write
```

### Переход на прод-портал

**Поля, созданные в одном портале, не переносятся в другой.** В текущем
тестовом и продовом порталах `UF_CRM_138_STATUS` и `UF_CRM_138_PRICE_FORM`
уже созданы (2026-11-15); для нового портала их нужно создать заново и сверить
всю схему.

Порядок:

1. Переключить `.env` на прод (`BITRIX_BASE_URL`, `BITRIX_KEY_202`,
   `BITRIX_USER_ID`). Запись пока оставить выключенной:
   `BITRIX_WRITE_ENABLED=false`, `BITRIX_DRY_RUN=true`.
2. Проверить прод read-only:
   ```bash
   uv run python src/main.py doctor --network
   ```
   В выводе смотреть `type.id` для 1078/1120 и наличие воронок 179/180.
3. Проверить и создать недостающие поля:
   ```bash
   # dry-run: показывает, что будет создано
   uv run python tools/create_missing_fields.py

   # создать (идемпотентно)
   uv run python tools/create_missing_fields.py --apply
   ```
   Скрипт сам определяет `crm.type.id` через `crm.type.getByEntityTypeId` и
   создаёт поля с правильным префиксом `UF_CRM_<type.id>_*`.
4. Снять фактическую схему полей:
   ```bash
   uv run python tools/dump_bitrix_fields.py
   ```
   Результат — `var/discovery/*.json`.
5. Сверить дамп с `config/bitrix_fieldmap.toml` по `title`/`fieldName`/`type`.

### Если на проде схема отличается

**Другой `crm.type.id` (не 138/148).** `create_missing_fields.py` создаст поля
с правильным префиксом, но `config/bitrix_fieldmap.toml` и тесты всё ещё
ссылаются на `UF_CRM_138_*` / `UF_CRM_148_*`. Нужно:

- заменить префиксы в `config/bitrix_fieldmap.toml` на фактические;
- обновить `tests/test_fieldmap.py` (там зафиксированы `crm_type_id`,
  количество полей и префиксы);
- перезапустить `uv run pytest` и `doctor`.

**Поля называются иначе.** Сопоставить логические имена с фактическими по
`title` в дампе и обновить `config/bitrix_fieldmap.toml` (слева — логическое
имя, справа — оригинальное `UF_CRM_*`). Если нужного поля нет вообще —
добавить его в `REQUIRED_FIELDS` в `tools/create_missing_fields.py` (или
создать вручную через `userfieldconfig.add`) и повторить шаг 3.

**Другой тип поля.** Если сопоставленное поле — `enumeration`, `crm_entity`
или `file`, а код передаёт строку, Bitrix вернёт ошибку валидации. Варианты:
привести значение к формату поля (id варианта списка, `T1078_<id>`) или
попросить администратора изменить тип поля на строковый.

**Нет `xmlId` или он не фильтруется.** Дедупликация в `bitrix/sync.py`
опирается на `xmlId`. Fallback: создать UF-поле «GUID источника» (string),
переключить `entity_map`/`sync` на него и обновить fieldmap.

**Нет `parentId1078`.** Связь «лот → торги» не настроена. Включить relation
parent↔child в настройках смарт-процесса или использовать UF-привязку
`T1078_<id>` / UF-строку с GUID торгов.

**После любых правок схемы:** `doctor --network` → `pytest` → `sync` без
`--write` (dry-run) → точечная запись одного торга и его лота
(`sync --guid <guid> --write`) → проверка карточки в Bitrix → только потом
массовая запись. Имена полей с тестового портала не копировать вслепую.

## 5. Команды

| Команда | Что делает |
|---|---|
| `init-db` | создаёт/мигрирует SQLite |
| `doctor [--network]` | проверяет настройки, field map, БД, доступ к Bitrix |
| `probe` | проверяет портал: сессия, cookie, 451, задержки |
| `collect` | собирает торги; по умолчанию — свежие, с `--from/--to` — по периоду торгов |
| `collect --details-limit N` | после discovery тянет карточки, лоты и сообщения для N кандидатов |
| `sync [--limit N] [--write]` | выгружает очередь в Bitrix; по умолчанию dry-run и только кандидаты |
| `refilter [--dry-run]` | пересчитывает решения по лотам из уже собранных данных |

`sync` по умолчанию выгружает только записи с `is_candidate=1`; лоты в статусе
`review` и исключённые остаются в SQLite. Для отладки можно добавить
`--include-non-candidates` или выставить `SYNC_ONLY_CANDIDATES=false`.

Полезные параметры `collect`:

- `--lookback-hours 24` — глубина инкрементального прохода;
- `--page-size 15` — не менять без проверки: Qrator блокирует «небраузерные» размеры;
- `--max-pages N` — ограничить проход для отладки;
- `--trade-type PublicOffer` — сузить выборку на источнике.

## 6. Регулярный запуск

Пример cron (пути заменить на свои):

```cron
*/30 * * * * cd /opt/moll-fedresurs-new && flock -n /tmp/fedresurs-collect.lock .venv/bin/python src/main.py collect --trade-type PublicOffer --lookback-hours 2 --details-limit 30 >> var/log/cron.log 2>&1
*/5  * * * * cd /opt/moll-fedresurs-new && flock -n /tmp/fedresurs-sync.lock .venv/bin/python src/main.py sync --limit 50 >> var/log/cron.log 2>&1
```

`flock -n` не даёт двум проходам пересечься: один `collect` может идти
дольше 30 минут на первичном наполнении.

Первый прогон с `--lookback-hours 24` может занять заметное время: источник
отдаётся по 15 записей на страницу с паузами.

## 7. Где смотреть результат

| Что | Где |
|---|---|
| БД | `var/fedresurs.sqlite3` |
| Логи (JSON) | `var/log/fedresurs.jsonl` |
| Сырые ответы источника | таблица `raw_payloads` |
| Журнал запросов | таблица `fetch_log` |
| Ошибки | таблица `errors` (отдельно от «нет данных») |
| Состояние окон сбора | `collection_windows` + `window_sightings` |
| Очередь Bitrix | `sync_jobs`, `bitrix_id_map` |

## 8. Ограничения источника (важно)

- Прямой HTTP и headless-браузер блокируются Qrator. Нужен **headful** Chromium
  с постоянным профилем; на Linux — через `xvfb`.
- Qrator отдаёт **HTTP 451** на размеры страницы, которые не использует SPA:
  для списка торгов безопасно `limit=15`, для лотов и сообщений — `limit=3`.
- Cookie `qrator_jsid2` живёт около 15 минут; сервис обновляет её сам.
- `tradeStartDate/tradeEndDate` фильтруют **период торгов**, а не дату
  публикации. Инкрементальный сбор использует сортировку списка по `dateCreate`
  и останавливается на уже известных записях.
- Внутренний API неофициальный и может измениться; сырые ответы сохраняются,
  чтобы можно было переразобрать данные без повторного обхода.

## 9. Тесты

```bash
uv run pytest
```

Покрыты: идемпотентность БД, версии, очередь синхронизации, нормализация,
правила отбора и построение payload'ов Bitrix.

## 10. Типовые проблемы

| Симптом | Причина / решение |
|---|---|
| `403`/`451` в `probe` | запущен headless; переключить на headful/`xvfb`, проверить IP |
| `DISPLAY is not set` | установить `xvfb` или задать `PORTAL_LAUNCH_MODE=cdp` |
| `Executable doesn't exist ... chrome` | выполнить `uv run playwright install chromium` |
| `ValidationError: base_url Field required` | в `.env` опечатка в имени `BITRIX_BASE_URL` |
| `crm.item.list` не находит `xmlId` | проверить `dump_bitrix_fields.py` на целевом портале |
| Лоты не уходят | сначала должны быть созданы торги; `sync` идёт в порядке «торги → лоты» |