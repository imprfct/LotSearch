# LotSearch Bot 🔍

Telegram бот для мониторинга новых лотов на сайте coins.ay.by. Автоматически отслеживает появление новых товаров и отправляет уведомления в Telegram.

## 🚀 Возможности

- ✅ Автоматический мониторинг указанных URL
- ✅ Уведомления о новых лотах с фотографиями и ценами
- ✅ Настраиваемый интервал проверки
- ✅ Современная архитектура с использованием aiogram 3.x
- ✅ Легкая настройка через переменные окружения

## 📁 Структура проекта

```
LotSearch/
├── bot/                    # Модуль бота
│   ├── __init__.py
│   └── handlers.py        # Обработчики команд
├── config/                # Конфигурация
│   ├── __init__.py
│   └── settings.py       # Настройки из .env
├── models/               # Модели данных
│   ├── __init__.py
│   └── item.py          # Модель Item
├── services/            # Бизнес-логика
│   ├── __init__.py
│   ├── parser.py       # Парсинг сайта
│   └── monitor.py      # Мониторинг лотов
├── utils/              # Утилиты
├── .env                # Переменные окружения (создать из .env.example)
├── .env.example        # Пример переменных окружения
├── .gitignore          # Игнорируемые файлы
├── main.py            # Точка входа в приложение
├── requirements.txt   # Зависимости
└── README.md         # Этот файл
```

## ⚙️ Установка

### 1. Клонируйте репозиторий
```bash
git clone <url>
cd LotSearch
```

### 2. Создайте виртуальное окружение
```bash
python -m venv venv
```

### 3. Активируйте виртуальное окружение

**Windows (PowerShell):**
```powershell
.\venv\Scripts\Activate.ps1
```

**Windows (CMD):**
```cmd
venv\Scripts\activate.bat
```

**Linux/Mac:**
```bash
source venv/bin/activate
```

### 4. Установите зависимости
```bash
pip install -r requirements.txt
```

### 5. Настройте переменные окружения

Скопируйте `.env.example` в `.env`:
```bash
copy .env.example .env  # Windows
cp .env.example .env    # Linux/Mac
```

Отредактируйте `.env` и укажите свои данные:
```env
BOT_TOKEN=your_bot_token_here
ADMIN_CHAT_ID=your_chat_id_here
CHECK_INTERVAL_MINUTES=60
MONITOR_URLS=https://coins.ay.by/sssr/yubilejnye/iz-dragocennyh-metallov/,https://coins.ay.by/rossiya/?f=1&ti1=6/
```

**Как получить BOT_TOKEN:**
1. Найдите [@BotFather](https://t.me/BotFather) в Telegram
2. Отправьте команду `/newbot`
3. Следуйте инструкциям и получите токен

**Как получить CHAT_ID:**
1. Найдите [@userinfobot](https://t.me/userinfobot) в Telegram
2. Отправьте любое сообщение
3. Бот вернет ваш Chat ID

## 🏃 Запуск

```bash
python main.py
```

Бот начнет работу и будет проверять новые лоты с указанным интервалом.

## 📝 Использование

1. Запустите бота
2. Напишите боту команду `/start` в Telegram
3. Бот автоматически начнет мониторинг и будет присылать уведомления о новых лотах

## 🛠️ Технологии

- **Python 3.8+**
- **aiogram 3.x** - современный фреймворк для Telegram ботов
- **BeautifulSoup4** - парсинг HTML
- **APScheduler** - планирование задач
- **python-dotenv** - управление переменными окружения
- **requests** - HTTP запросы

## 🔧 Настройка

Вы можете настроить следующие параметры в `.env`:

- `BOT_TOKEN` - токен вашего бота
- `ADMIN_CHAT_ID` - ID чата для уведомлений
- `CHECK_INTERVAL_MINUTES` - интервал проверки в минутах (по умолчанию 60)
- `MONITOR_URLS` - список URL для мониторинга (через запятую)

## 📄 Лицензия

Этот проект создан для личного использования.

## 👨‍💻 Автор

Рефакторинг выполнен с использованием современных практик разработки и лучших паттернов архитектуры Python приложений.
