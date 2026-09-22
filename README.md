# BabyUp → MonoMarket

Конвертер Rozetka XML-фида Horoshop в JSON прайс-лист MonoMarket.

## Источник

`https://babyup.ua/marketplace-integration/rozetka-feed/ff442a101279a54baa44e63e8da3cec2`

## Результат

`docs/mono.json`

## Маппинг

- `offer/@id` → `code`
- `price` → `price`
- `price_old` → `old_price`
- `offer/@available` → `availability`
- `stock_quantity` → `stock`
- склад MonoMarket → `warehouses[0].id = "1"`
- `warranty_type = "no"`
- `warranty_period = 0`
- `max_pay_in_parts = 6`
- `days_to_dispatch = 2`
- `manufacture = null`

Если товар недоступен, `stock` принудительно устанавливается в `0`.

## GitHub Pages

1. Создать публичный репозиторий и загрузить содержимое архива в корень.
2. Открыть `Settings → Pages`.
3. В `Build and deployment` выбрать `Deploy from a branch`.
4. Branch: `main`, Folder: `/docs`.
5. Запустить `Actions → Update MonoMarket feed → Run workflow`.
6. Постоянный URL будет иметь вид:

`https://USERNAME.github.io/REPOSITORY/mono.json`

Workflow автоматически обновляет JSON один раз в сутки.

## Переменные

При необходимости значения можно переопределить через environment variables:

`SOURCE_URL`, `OUTPUT_FILE`, `WAREHOUSE_ID`, `WARRANTY_TYPE`, `WARRANTY_PERIOD`, `MAX_PAY_IN_PARTS`, `DAYS_TO_DISPATCH`, `LIMIT`.
