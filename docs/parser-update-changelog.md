# Обновление парсера - Changelog

## Дата: 11 октября 2025

### ❌ Проблема
Парсер не находил товары на сайте coins.ay.by. Структура HTML изменилась.

### 🔍 Анализ
- **Старая структура**: `<div class="product-card">` с подэлементами `.product-card__name`, `.product-card__image`, `.product-card__price`
- **Новая структура**: `<div class="item-type-card__card">` с другой организацией элементов

### ✅ Решение

#### Изменения в `services/parser.py`:

1. **Поиск карточек товаров**:
   ```python
   # Было:
   soup.find_all('div', class_='product-card')
   
   # Стало:
   soup.find_all('div', class_='item-type-card__card')
   ```

2. **Извлечение ссылки и названия**:
   ```python
   # Было:
   link_tag = card.find('a', class_='product-card__name')
   
   # Стало:
   link_tag = card.find('a', href=lambda x: x and '/lot/' in x)
   ```

3. **Извлечение изображения**:
   ```python
   # Было:
   img_tag = card.find('img', class_='product-card__image')
   
   # Стало:
   img_tag = card.find('img')
   ```

4. **Извлечение цены** (самое большое изменение):
   ```python
   # Было:
   price_tag = card.find('div', class_='product-card__price')
   price = price_tag.get_text(strip=True)
   
   # Стало:
   all_texts = list(card.stripped_strings)
   # Ищем пару: число + "бел. руб."
   for i, text in enumerate(all_texts):
       if i == 0:  # Пропускаем название
           continue
       clean_text = text.replace(',', '').replace('.', '').replace(' ', '')
       if clean_text.isdigit():
           if i + 1 < len(all_texts) and 'руб' in all_texts[i+1].lower():
               price = f"{text} {all_texts[i+1]}"
               break
   ```

5. **Обработка URL**:
   ```python
   # Было:
   link = 'https://coins.ay.by' + link_tag.get('href')
   
   # Стало:
   link = link_tag.get('href')
   if not link.startswith('http'):
       link = 'https://ay.by' + link
   ```

### 📊 Результаты

- ✅ Парсер корректно извлекает 29 товаров
- ✅ Название товара извлекается правильно
- ✅ Цена форматируется как "135,01 бел. руб."
- ✅ Изображения извлекаются
- ✅ URL корректные (ay.by вместо coins.ay.by)
- ✅ Все тесты обновлены и проходят

### 🧪 Тесты

Обновлены тестовые фикстуры в `tests/conftest.py` и `tests/test_parser.py`:
- Изменена HTML структура в `sample_html`
- Обновлены ожидаемые значения (URL, цены)
- Исправлена проверка домена (ay.by вместо coins.ay.by)

### 📝 Примечания

- Домен изменился: `coins.ay.by` → `ay.by`
- Новая структура более гибкая и основана на поиске по содержимому
- Парсер теперь устойчивее к изменениям CSS классов
