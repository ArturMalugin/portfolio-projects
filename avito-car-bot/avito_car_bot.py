import os
import logging
import sqlite3
from datetime import datetime
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# Загрузка переменных окружения
load_dotenv()

# Состояния разговора
CHOOSING_ACTION, SETTING_URL, SETTING_PRICE = range(3)

class AvitoCarBot:
    def __init__(self):
        """Инициализация бота"""
        self.logger = self.setup_logger()
        self.db_conn = self.setup_database()
        self.keyboard = [
            ['Добавить URL 🔗', 'Мои URL 📋'],
            ['Удалить URL 🗑', 'Помощь ❓']
        ]
        self.markup = ReplyKeyboardMarkup(self.keyboard, resize_keyboard=True)

    def setup_logger(self) -> logging.Logger:
        """Настройка логирования"""
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.INFO
        )
        return logging.getLogger(__name__)

    def setup_database(self) -> sqlite3.Connection:
        """Настройка базы данных"""
        conn = sqlite3.connect('avito_monitor.db')
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS monitored_urls
        (user_id INTEGER, url TEXT, max_price INTEGER)
        ''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS found_ads
        (url TEXT, ad_id TEXT, UNIQUE(url, ad_id))
        ''')
        conn.commit()
        return conn

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Начало работы с ботом"""
        self.logger.info("Пользователь начал работу с ботом")
        await update.message.reply_text(
            "👋 Привет! Я бот для мониторинга объявлений о продаже автомобилей на Avito.\n\n"
            "Что вы хотите сделать?",
            reply_markup=self.markup
        )
        return CHOOSING_ACTION

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Отображение справки"""
        self.logger.info("Получена команда: Помощь ❓")
        await update.message.reply_text(
            "🔍 Я помогу вам отслеживать новые объявления о продаже автомобилей на Avito.\n\n"
            "Доступные команды:\n"
            "• Добавить URL 🔗 - добавить новый URL для мониторинга\n"
            "• Мои URL 📋 - показать список отслеживаемых URL\n"
            "• Удалить URL 🗑 - удалить URL из мониторинга\n"
            "• Помощь ❓ - показать эту справку\n\n"
            "Как использовать:\n"
            "1. Перейдите на Avito и настройте фильтры поиска автомобилей\n"
            "2. Скопируйте URL страницы с результатами\n"
            "3. Отправьте URL мне через 'Добавить URL 🔗'\n"
            "4. Укажите максимальную цену (или 0 для отключения фильтра)\n"
            "5. Готово! Я буду отправлять вам уведомления о новых объявлениях",
            reply_markup=self.markup
        )
        return CHOOSING_ACTION

    async def add_url_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Начало процесса добавления URL"""
        self.logger.info("Получена команда: Добавить URL 🔗")
        await update.message.reply_text(
            "Отправьте мне URL страницы с результатами поиска на Avito.\n"
            "URL должен начинаться с https://www.avito.ru/",
            reply_markup=self.markup
        )
        return SETTING_URL

    async def handle_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Обработка полученного URL"""
        try:
            url = update.message.text.strip()
            self.logger.info(f"Получен URL: {url}")
            
            if not url.startswith('http'):
                await update.message.reply_text(
                    "❌ Пожалуйста, отправьте корректный URL, начинающийся с http:// или https://\n"
                    "Например: https://www.avito.ru/moskva/avtomobili"
                )
                return SETTING_URL
            
            if 'avito.ru' not in url:
                await update.message.reply_text(
                    "❌ URL должен быть с сайта Авито (avito.ru)\n"
                    "Например: https://www.avito.ru/moskva/avtomobili"
                )
                return SETTING_URL
            
            if '/avtomobili' not in url:
                await update.message.reply_text(
                    "❌ URL должен быть из раздела автомобилей\n"
                    "Например: https://www.avito.ru/moskva/avtomobili"
                )
                return SETTING_URL
                
            context.user_data['url'] = url
            await update.message.reply_text(
                "✅ URL принят!\n\n"
                "Теперь укажите максимальную цену в рублях.\n"
                "Отправьте 0, если не хотите ограничивать цену."
            )
            return SETTING_PRICE
            
        except Exception as e:
            self.logger.error(f"Ошибка в handle_url: {e}")
            await self.send_error_message(update)
            return CHOOSING_ACTION

    async def handle_price(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Обработка полученной максимальной цены"""
        try:
            price_text = update.message.text.strip()
            self.logger.info(f"Получена цена: {price_text}")
            
            try:
                max_price = int(price_text)
                if max_price < 0:
                    raise ValueError("Цена не может быть отрицательной")
            except ValueError:
                await update.message.reply_text(
                    "❌ Пожалуйста, введите корректное число.\n"
                    "Например: 500000"
                )
                return SETTING_PRICE

            url = context.user_data.get('url')
            if not url:
                await update.message.reply_text(
                    "❌ Произошла ошибка. Попробуйте добавить URL заново."
                )
                return CHOOSING_ACTION

            # Сохраняем URL и цену в базу данных
            cursor = self.db_conn.cursor()
            cursor.execute(
                'INSERT INTO monitored_urls (user_id, url, max_price) VALUES (?, ?, ?)',
                (update.effective_user.id, url, max_price)
            )
            self.db_conn.commit()

            await update.message.reply_text(
                "✅ Готово! Я буду отслеживать новые объявления по этому URL.\n\n"
                f"URL: {url}\n"
                f"Максимальная цена: {'Без ограничений' if max_price == 0 else f'{max_price:,} ₽'}",
                reply_markup=self.markup
            )
            
            # Проверяем объявления сразу после добавления URL
            await self.check_new_ads(context, update.effective_user.id, url, max_price)
            
            return CHOOSING_ACTION

        except Exception as e:
            self.logger.error(f"Ошибка в handle_price: {e}")
            await self.send_error_message(update)
            return CHOOSING_ACTION

    async def list_urls(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Отображение списка отслеживаемых URL"""
        try:
            self.logger.info("Получена команда: Мои URL 📋")
            cursor = self.db_conn.cursor()
            cursor.execute(
                'SELECT url, max_price FROM monitored_urls WHERE user_id = ?',
                (update.effective_user.id,)
            )
            urls = cursor.fetchall()

            if not urls:
                await update.message.reply_text(
                    "У вас пока нет отслеживаемых URL.\n"
                    "Используйте 'Добавить URL 🔗' чтобы начать мониторинг.",
                    reply_markup=self.markup
                )
            else:
                message = "📋 Ваши отслеживаемые URL:\n\n"
                for i, (url, max_price) in enumerate(urls, 1):
                    message += f"{i}. {url}\n"
                    message += f"   Макс. цена: {'Без ограничений' if max_price == 0 else f'{max_price:,} ₽'}\n\n"
                await update.message.reply_text(message, reply_markup=self.markup)

            return CHOOSING_ACTION

        except Exception as e:
            self.logger.error(f"Ошибка в list_urls: {e}")
            await self.send_error_message(update)
            return CHOOSING_ACTION

    async def delete_url_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Удаление URL из мониторинга"""
        try:
            self.logger.info("Получена команда: Удалить URL 🗑")
            cursor = self.db_conn.cursor()
            cursor.execute(
                'SELECT url FROM monitored_urls WHERE user_id = ?',
                (update.effective_user.id,)
            )
            urls = cursor.fetchall()

            if not urls:
                await update.message.reply_text(
                    "У вас нет отслеживаемых URL для удаления.",
                    reply_markup=self.markup
                )
            else:
                message = "Выберите номер URL для удаления:\n\n"
                for i, (url,) in enumerate(urls, 1):
                    message += f"{i}. {url}\n"
                await update.message.reply_text(message)
                context.user_data['urls_to_delete'] = urls
                return CHOOSING_ACTION

        except Exception as e:
            self.logger.error(f"Ошибка в delete_url_command: {e}")
            await self.send_error_message(update)
            return CHOOSING_ACTION

    async def handle_delete_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Обработка выбора URL для удаления"""
        try:
            urls = context.user_data.get('urls_to_delete', [])
            if not urls:
                await update.message.reply_text(
                    "❌ Произошла ошибка. Попробуйте удалить URL заново.",
                    reply_markup=self.markup
                )
                return CHOOSING_ACTION

            try:
                choice = int(update.message.text.strip())
                if not (1 <= choice <= len(urls)):
                    raise ValueError
            except ValueError:
                await update.message.reply_text(
                    "❌ Пожалуйста, введите корректный номер URL.",
                    reply_markup=self.markup
                )
                return CHOOSING_ACTION

            url_to_delete = urls[choice - 1][0]
            cursor = self.db_conn.cursor()
            cursor.execute(
                'DELETE FROM monitored_urls WHERE user_id = ? AND url = ?',
                (update.effective_user.id, url_to_delete)
            )
            self.db_conn.commit()

            await update.message.reply_text(
                f"✅ URL успешно удален:\n{url_to_delete}",
                reply_markup=self.markup
            )
            del context.user_data['urls_to_delete']
            return CHOOSING_ACTION

        except Exception as e:
            self.logger.error(f"Ошибка в handle_delete_choice: {e}")
            await self.send_error_message(update)
            return CHOOSING_ACTION

    async def check_new_ads(self, context: ContextTypes.DEFAULT_TYPE, user_id: int, url: str, max_price: int) -> None:
        """Проверка новых объявлений"""
        try:
            self.logger.info(f"Проверка объявлений для URL: {url}")
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, headers=headers)
            soup = BeautifulSoup(response.text, 'lxml')
            
            ads = soup.find_all('div', {'data-marker': 'item'})
            cursor = self.db_conn.cursor()
            
            for ad in ads:
                try:
                    ad_id = ad.get('data-item-id')
                    if not ad_id:
                        continue
                        
                    # Проверяем, видели ли мы это объявление раньше
                    cursor.execute(
                        'SELECT 1 FROM found_ads WHERE url = ? AND ad_id = ?',
                        (url, ad_id)
                    )
                    if cursor.fetchone():
                        continue
                        
                    # Получаем данные объявления
                    title = ad.find('h3', {'itemprop': 'name'}).text.strip()
                    price_elem = ad.find('meta', {'itemprop': 'price'})
                    if not price_elem:
                        continue
                    
                    price = int(price_elem.get('content', '0'))
                    if max_price > 0 and price > max_price:
                        continue
                        
                    link = 'https://www.avito.ru' + ad.find('a', {'data-marker': 'item-title'})['href']
                    
                    # Сохраняем объявление в базу
                    cursor.execute(
                        'INSERT OR IGNORE INTO found_ads (url, ad_id) VALUES (?, ?)',
                        (url, ad_id)
                    )
                    self.db_conn.commit()
                    
                    # Отправляем уведомление
                    message = (
                        f"🚗 Новое объявление!\n\n"
                        f"📌 {title}\n"
                        f"💰 {price:,} ₽\n"
                        f"🔗 {link}"
                    )
                    await context.bot.send_message(user_id, message)
                    
                except Exception as e:
                    self.logger.error(f"Ошибка при обработке объявления: {e}")
                    continue
                    
        except Exception as e:
            self.logger.error(f"Ошибка в check_new_ads: {e}")

    async def send_error_message(self, update: Update) -> None:
        """Отправка сообщения об ошибке"""
        await update.message.reply_text(
            "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз или обратитесь к администратору.",
            reply_markup=self.markup
        )

def main() -> None:
    """Запуск бота"""
    # Получаем токен из переменных окружения
    token = os.getenv('TELEGRAM_TOKEN')
    if not token:
        raise ValueError("Не найден TELEGRAM_TOKEN в переменных окружения")

    # Создаем и настраиваем бота
    bot = AvitoCarBot()
    
    # Создаем приложение с увеличенным таймаутом
    application = Application.builder().token(token).read_timeout(30).write_timeout(30).build()

    # Создаем обработчик разговора
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', bot.start),
            MessageHandler(filters.Regex('^Добавить URL 🔗$'), bot.add_url_command),
            MessageHandler(filters.Regex('^Мои URL 📋$'), bot.list_urls),
            MessageHandler(filters.Regex('^Удалить URL 🗑$'), bot.delete_url_command),
            MessageHandler(filters.Regex('^Помощь ❓$'), bot.help_command),
        ],
        states={
            CHOOSING_ACTION: [
                MessageHandler(filters.Regex('^Добавить URL 🔗$'), bot.add_url_command),
                MessageHandler(filters.Regex('^Мои URL 📋$'), bot.list_urls),
                MessageHandler(filters.Regex('^Удалить URL 🗑$'), bot.delete_url_command),
                MessageHandler(filters.Regex('^Помощь ❓$'), bot.help_command),
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_delete_choice),
            ],
            SETTING_URL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_url),
            ],
            SETTING_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_price),
            ],
        },
        fallbacks=[
            CommandHandler('help', bot.help_command),
            MessageHandler(filters.Regex('^Помощь ❓$'), bot.help_command),
        ],
    )

    # Добавляем обработчик разговора
    application.add_handler(conv_handler)

    # Запускаем бота
    print("Инициализация бота...")
    print("Бот запускается... Для остановки нажмите Ctrl+C")
    application.run_polling() 