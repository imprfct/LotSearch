# Tests

Критически важные тесты для LotSearch Bot.

## Структура тестов

```
tests/
├── __init__.py
├── conftest.py           # Фикстуры и конфигурация pytest
├── test_models.py        # Тесты моделей данных
└── test_parser.py        # Тесты парсера (+ интеграционные тесты с реальным сайтом)
```

## Запуск тестов

### Все тесты (без интеграционных):
```bash
pytest
```

### С покрытием кода:
```bash
pytest --cov=. --cov-report=html
```

### Только быстрые тесты (без реального сайта):
```bash
pytest -m "not integration"
```

### Интеграционные тесты (проверка реального сайта):
```bash
pytest -m integration
```

### Конкретный файл:
```bash
pytest tests/test_parser.py
```

### Verbose режим:
```bash
pytest -v
```

## Что тестируется

###  test_models.py
- ✅ Создание объектов Item
- ✅ Сравнение по URL
- ✅ Использование в set (hashable)

### 🌐 test_parser.py
- ✅ Парсинг валидного HTML
- ✅ Обработка пустого/невалидного HTML
- ✅ Обработка неполных карточек товаров
- ✅ Получение страницы (успех/ошибка/таймаут)
- ✅ Интеграция get_items_from_url
- ✅ **КРИТИЧНО:** Доступность реального сайта (integration)
- ✅ **КРИТИЧНО:** Парсинг реальных данных (integration)

## Критически важные тесты

Тесты, помеченные как `@pytest.mark.integration`, проверяют работу с **реальным сайтом**:

1. **test_real_website_accessible** - проверяет, что сайт доступен
2. **test_real_website_parsing** - проверяет, что структура сайта не изменилась

⚠️ **Эти тесты должны проходить перед каждым деплоем!**

## Фикстуры (conftest.py)

- `mock_env_vars` - мок переменных окружения для тестов
- `sample_html` - образец HTML с карточками товаров
- `invalid_html` - образец HTML без товаров

## CI/CD

Добавьте в ваш CI/CD pipeline:

```yaml
# Пример для GitHub Actions
- name: Run tests
  run: |
    pip install -r requirements.txt
    pytest -v
    pytest -m integration  # Проверка реального сайта
```
