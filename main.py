import logging
import os
from urllib.parse import urlparse
import psycopg2.errors

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor
import json

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, \
    InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, \
    ConversationHandler


# Логування
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)



# Оставь только эту:
PREORDER_INFO, PREORDER_PHOTO, PREORDER_LINK, PREORDER_MODEL = range(19, 23)

ADMIN_MENU, ADD_CATEGORY, ADD_PRODUCT_NAME, ADD_PRODUCT_PRICE, ADD_PRODUCT_DESCRIPTION, ADD_PRODUCT_PHOTOS, ADD_PRODUCT_CATEGORY = range(7)

EDIT_CATEGORY_NAME, EDIT_PRODUCT_FIELD, SELECT_CATEGORY_TO_EDIT, SELECT_CATEGORY_TO_DELETE = range(7, 11)

SELECT_PRODUCT_TO_EDIT, SELECT_PRODUCT_TO_DELETE, EDIT_PRODUCT_NAME, EDIT_PRODUCT_PRICE, EDIT_PRODUCT_DESCRIPTION = range(11, 16)

ADD_SUBCATEGORY, SELECT_PARENT_CATEGORY = range(16, 18)

CONTACT_MESSAGE = 18
ADD_PRODUCT_SOURCE_LINK = 24

EDIT_PRODUCT_PHOTOS, EDIT_PRODUCT_CATEGORY = range(25, 27)

ADMIN_USERS_MENU, ADD_ADMIN_ID, DELETE_ADMIN_SELECT = range(27, 30)

class ShopBot:
    def __init__(self, token: str):
        self.token = token
        self.admin_ids = []

        # Отладочный вывод
        database_url = os.getenv('DATABASE_URL')
        print(f"DATABASE_URL найден: {database_url is not None}")
        print(f"DATABASE_URL: {database_url}")

        if database_url:
            url = urlparse(database_url)
            self.db_config = {
                'host': url.hostname,
                'database': url.path[1:],
                'user': url.username,
                'password': url.password,
                'port': url.port
            }
            print(f"Используется Railway БД: {url.hostname}")
        else:
            self.db_config = {
                'host': os.getenv('DB_HOST', 'localhost'),
                'database': os.getenv('DB_NAME', 'shop_bot'),
                'user': os.getenv('DB_USER', 'shop_bot'),
                'password': os.getenv('DB_PASSWORD', 'shop_bot'),
                'port': int(os.getenv('DB_PORT', 5432))
            }
            print("Используется localhost БД")

        print(f"Конфигурация БД: {self.db_config}")

        self.contact_info = {
            'phone': '+38 050 908 58 75',
            'instagram': '@sneakerhead.store13',
            'email': 'ruillia4@gmail.com',
            'telegram': '@IR_Sneakerhead'
        }
        self.init_database()

    def init_database(self):
        """Ініціалізація бази даних"""
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Таблиця категорій з підтримкою підкатегорій
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                emoji TEXT DEFAULT '📦',
                parent_id INTEGER DEFAULT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                FOREIGN KEY (parent_id) REFERENCES categories (id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_messages (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                message_type TEXT NOT NULL,
                message_text TEXT,
                product_id INTEGER DEFAULT NULL,
                product_name TEXT DEFAULT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                is_read BOOLEAN DEFAULT FALSE
            )
        ''')

        # Таблиця товарів
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                price REAL NOT NULL,
                photos TEXT,
                category_id INTEGER,
                is_available BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                FOREIGN KEY (category_id) REFERENCES categories (id)
            )
        ''')

        # Таблиця адмінів
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # МИГРАЦИЯ: Добавляем колонку source_link если её нет
        try:
            cursor.execute("ALTER TABLE products ADD COLUMN source_link TEXT")
            print("Колонка source_link добавлена")
        except psycopg2.errors.DuplicateColumn:
            print("Колонка source_link уже существует")
        except Exception as e:
            print(f"Ошибка при добавлении колонки source_link: {e}")

        conn.commit()
        conn.close()
        self.load_admins()

    def load_admins(self):
        """Загружение списка админов из БД"""
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM admins')
        self.admin_ids = [row[0] for row in cursor.fetchall()]
        conn.close()

    def is_admin(self, user_id: int) -> bool:
        """Перевірка чи є користувач адміном"""
        return user_id in self.admin_ids

    def add_admin(self, user_id: int, username: str = None):
        """Додавання нового адміна"""
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            INSERT INTO admins (user_id, username) VALUES (%s, %s)
            ON CONFLICT (user_id) DO NOTHING
        ''', (user_id, username))
        conn.commit()
        conn.close()
        self.load_admins()

    async def delete_admin_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню выбора админа для удаления"""
        query = update.callback_query
        await query.answer()

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT user_id, username FROM admins ORDER BY added_at')
        admins = cursor.fetchall()
        conn.close()

        current_user_id = update.effective_user.id

        text = "🗑️ <b>Видалення адміна</b>\n\nОберіть адміна для видалення:"
        keyboard = []

        for user_id, username in admins:
            if user_id != current_user_id:  # Нельзя удалить самого себя
                button_text = f"{user_id} (@{username or 'немає'})"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"delete_admin_{user_id}")])

        if not keyboard:
            text += "\n\n❌ Немає адмінів для видалення (не можна видалити себе)"

        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_users")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
        return DELETE_ADMIN_SELECT

    async def process_delete_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка удаления админа"""
        query = update.callback_query
        await query.answer()

        admin_id_to_delete = int(query.data.split('_')[2])
        current_user_id = update.effective_user.id

        # Проверяем, что не пытаемся удалить себя
        if admin_id_to_delete == current_user_id:
            await query.answer("❌ Не можна видалити себе з адмінів!", show_alert=True)
            return DELETE_ADMIN_SELECT

        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Получаем info об админе
            cursor.execute('SELECT username FROM admins WHERE user_id = %s', (admin_id_to_delete,))
            admin_info = cursor.fetchone()

            if admin_info:
                # Удаляем из базы
                cursor.execute('DELETE FROM admins WHERE user_id = %s', (admin_id_to_delete,))
                conn.commit()

                # Обновляем список в памяти
                self.load_admins()

                await query.edit_message_text(
                    f"✅ <b>Адміна видалено!</b>\n\n"
                    f"ID: {admin_id_to_delete}\n"
                    f"Username: @{admin_info['username'] or 'немає'}",
                    parse_mode='HTML'
                )
            else:
                await query.edit_message_text("❌ Адмін не знайдений")

            conn.close()
            return ConversationHandler.END

        except Exception as e:
            await query.edit_message_text(f"❌ Помилка: {str(e)}")
            return ConversationHandler.END

    # ==================== КОРИСТУВАЦЬКА ЧАСТИНА ====================

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Головна команда /start"""
        user = update.effective_user

        welcome_text = f"""
    🛍️ <b>Ласкаво просимо до нашого магазину!</b>

    Привіт, {user.first_name}! 👋

    Тут ви можете:
    🔍 Переглядати наш асортимент
    📱 Фільтрувати товари за категоріями
    💰 Дізнаватися актуальні ціни
    📸 Переглядати фотографії товарів
    📞 Зв'язатися з нами щодо товарів

    <i>Натисніть кнопку нижче, щоб почати покупки!</i>
        """

        keyboard = [
            [InlineKeyboardButton("🛒 Переглянути товари", callback_data="show_categories")],
            [InlineKeyboardButton("🎯 Передзамовлення", callback_data="preorder")],
            [InlineKeyboardButton("ℹ️ Про магазин", callback_data="about")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.message:
            await update.message.reply_text(welcome_text, parse_mode='HTML', reply_markup=reply_markup)
        else:
            # Якщо це callback query, спочатку видаляємо попереднє повідомлення та надсилаємо нове
            try:
                await update.callback_query.edit_message_text(welcome_text, parse_mode='HTML',
                                                              reply_markup=reply_markup)
            except Exception:
                # Якщо не вдається відредагувати (наприклад, повідомлення містить фото),
                # видаляємо його та надсилаємо нове
                await update.callback_query.delete_message()
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=welcome_text,
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )

    async def preorder_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало процесса предзаказа"""
        query = update.callback_query
        await query.answer()

        text = """
    🎯 <b>Передзамовлення товару</b>

    Заповніть інформацію про товар, який вас цікавить.
    Всі поля необов'язкові - заповнюйте тільки те, що знаєте.

    <b>Крок 1/4:</b> Опишіть товар текстом
    - Назва товару
    - Бренд/виробник  
    - Розмір, колір
    - Бюджет
    - Додаткові побажання

    Або натисніть "Пропустити" якщо хочете відправити тільки фото/лінк.
        """

        keyboard = [
            [InlineKeyboardButton("⏭️ Пропустити", callback_data="skip_preorder_info")],
            [InlineKeyboardButton("❌ Скасувати", callback_data="cancel_preorder")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if query.message.photo:
            await query.edit_message_caption(caption=text, parse_mode='HTML', reply_markup=reply_markup)
        else:
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)

        context.user_data['preorder_data'] = {}
        return PREORDER_INFO

    async def process_preorder_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстовой информации"""
        context.user_data['preorder_data']['info'] = update.message.text
        return await self.ask_preorder_photo(update, context)

    async def skip_preorder_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Пропуск текстовой информации"""
        query = update.callback_query
        await query.answer()
        context.user_data['preorder_data']['info'] = None
        return await self.ask_preorder_photo(update, context)

    async def ask_preorder_photo(self, update, context):
        """Запрос фото товара"""
        text = """
    📸 <b>Крок 2/4:</b> Надішліть фото товару

    Якщо у вас є фотографія товару який вас цікавить - надішліть її.
        """

        keyboard = [
            [InlineKeyboardButton("⏭️ Пропустити", callback_data="skip_preorder_photo")],
            [InlineKeyboardButton("❌ Скасувати", callback_data="cancel_preorder")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if hasattr(update, 'callback_query') and update.callback_query:
            if update.callback_query.message.photo:
                await update.callback_query.edit_message_caption(caption=text, parse_mode='HTML',
                                                                 reply_markup=reply_markup)
            else:
                await update.callback_query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
        else:
            await update.message.reply_text(text, parse_mode='HTML', reply_markup=reply_markup)

        return PREORDER_PHOTO

    async def process_preorder_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка фото товара"""
        if update.message.photo:
            context.user_data['preorder_data']['photo'] = update.message.photo[-1].file_id
            await update.message.reply_text("✅ Фото збережено!")
        return await self.ask_preorder_link(update, context)

    async def skip_preorder_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Пропуск фото"""
        query = update.callback_query
        await query.answer()
        context.user_data['preorder_data']['photo'] = None
        return await self.ask_preorder_link(update, context)

    async def ask_preorder_link(self, update, context):
        """Запрос ссылки на товар"""
        text = """
    🔗 <b>Крок 3/4:</b> Надішліть лінк на товар

    Якщо ви знайшли товар в інтернеті - надішліть лінк на нього.
        """

        keyboard = [
            [InlineKeyboardButton("⏭️ Пропустити", callback_data="skip_preorder_link")],
            [InlineKeyboardButton("❌ Скасувати", callback_data="cancel_preorder")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if hasattr(update, 'callback_query') and update.callback_query:
            if update.callback_query.message.photo:
                await update.callback_query.edit_message_caption(caption=text, parse_mode='HTML',
                                                                 reply_markup=reply_markup)
            else:
                await update.callback_query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
        else:
            await update.message.reply_text(text, parse_mode='HTML', reply_markup=reply_markup)

        return PREORDER_LINK

    async def process_preorder_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ссылки"""
        context.user_data['preorder_data']['link'] = update.message.text
        await update.message.reply_text("✅ Лінк збережено!")
        return await self.ask_preorder_model(update, context)

    async def skip_preorder_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Пропуск ссылки"""
        query = update.callback_query
        await query.answer()
        context.user_data['preorder_data']['link'] = None
        return await self.ask_preorder_model(update, context)

    async def ask_preorder_model(self, update, context):
        """Запрос названия модели"""
        text = """
    🏷️ <b>Крок 4/4:</b> Назва моделі

    Якщо знаєте точну назву моделі товару - напишіть її.
        """

        keyboard = [
            [InlineKeyboardButton("⏭️ Пропустити", callback_data="skip_preorder_model")],
            [InlineKeyboardButton("❌ Скасувати", callback_data="cancel_preorder")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if hasattr(update, 'callback_query') and update.callback_query:
            if update.callback_query.message.photo:
                await update.callback_query.edit_message_caption(caption=text, parse_mode='HTML',
                                                                 reply_markup=reply_markup)
            else:
                await update.callback_query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
        else:
            await update.message.reply_text(text, parse_mode='HTML', reply_markup=reply_markup)

        return PREORDER_MODEL

    async def process_preorder_model(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка названия модели"""
        context.user_data['preorder_data']['model'] = update.message.text
        await update.message.reply_text("✅ Назву моделі збережено!")
        return await self.finish_preorder(update, context)

    async def skip_preorder_model(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Пропуск названия модели"""
        query = update.callback_query
        await query.answer()
        context.user_data['preorder_data']['model'] = None
        return await self.finish_preorder(update, context)

    async def finish_preorder(self, update, context):
        """Завершение предзаказа"""
        user = update.effective_user if hasattr(update, 'effective_user') else update.callback_query.from_user
        preorder_data = context.user_data.get('preorder_data', {})

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        message_text = f"Предзаказ:\n"
        if preorder_data.get('info'):
            message_text += f"Опис: {preorder_data['info']}\n"
        if preorder_data.get('model'):
            message_text += f"Модель: {preorder_data['model']}\n"
        if preorder_data.get('link'):
            message_text += f"Лінк: {preorder_data['link']}\n"

        cursor.execute('''
            INSERT INTO user_messages (user_id, username, full_name, message_type, message_text)
            VALUES (%s, %s, %s, %s, %s)
        ''', (user.id, user.username, user.full_name, 'preorder', message_text))
        conn.commit()
        conn.close()

        # Формируем сообщение для админов
        admin_message = f"""
    🎯 <b>Новий запит на передзамовлення</b>

    👤 <b>Від:</b> {user.full_name} (@{user.username or 'немає username'})
    🆔 <b>User ID:</b> {user.id}
    """

        if preorder_data.get('info'):
            admin_message += f"\n📝 <b>Опис:</b>\n{preorder_data['info']}\n"

        if preorder_data.get('model'):
            admin_message += f"🏷️ <b>Модель:</b> {preorder_data['model']}\n"

        if preorder_data.get('link'):
            admin_message += f"🔗 <b>Лінк:</b> {preorder_data['link']}\n"

        admin_message += f"""

        """

        # Отправляем админам
        for admin_id in self.admin_ids:
            try:
                if preorder_data.get('photo'):
                    await context.bot.send_photo(
                        chat_id=admin_id,
                        photo=preorder_data['photo'],
                        caption=admin_message,
                        parse_mode='HTML'
                    )
                else:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=admin_message,
                        parse_mode='HTML'
                    )
            except Exception as e:
                logger.error(f"Error sending preorder to admin {admin_id}: {e}")

        # Ответ пользователю
        response_text = """
    ✅ <b>Ваш запит на передзамовлення надіслано!</b>

    Ми розглянемо вашу заявку та зв'яжемося з вами найближчим часом.
        """

        keyboard = [[InlineKeyboardButton("🏠 На головну", callback_data="start")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if hasattr(update, 'callback_query') and update.callback_query:
            await context.bot.send_message(
                chat_id=update.callback_query.message.chat_id,
                text=response_text,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(response_text, parse_mode='HTML', reply_markup=reply_markup)

        context.user_data.clear()
        return ConversationHandler.END

    async def process_preorder(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка информации о предзаказе"""
        user_message = update.message.text
        user = update.effective_user

        # Отправляем информацию всем админам
        admin_message = f"""
    🎯 <b>Новий запит на передзамовлення</b>

    👤 <b>Від:</b> {user.full_name} (@{user.username or 'немає username'})
    🆔 <b>User ID:</b> {user.id}

    📝 <b>Деталі замовлення:</b>
    {user_message}

    <b>Контактна інформація:</b>
    - Телефон: {self.contact_info['phone']}
    - Email: {self.contact_info['email']}
    - Telegram: {self.contact_info['telegram']}
    - Instagram: {self.contact_info['instagram']}
        """

        # Отправляем админам
        for admin_id in self.admin_ids:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=admin_message,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"Error sending preorder message to admin {admin_id}: {e}")

        # Ответ пользователю
        response_text = f"""
    ✅ <b>Ваш запит на передзамовлення надіслано!</b>

    Ми розглянемо вашу заявку та зв'яжемося з вами найближчим часом для уточнення деталей та вартості.

    <b>Контакти для прямого зв'язку:</b>
    - Телефон: {self.contact_info['phone']}
    - Email: {self.contact_info['email']}
    - Telegram: {self.contact_info['telegram']}
    - Instagram: {self.contact_info['instagram']}

    <b>Орієнтовні терміни:</b>
    - Пошук товару: 1-3 дні
    - Доставка з Європи/США: 7-14 днів
        """

        keyboard = [[InlineKeyboardButton("🏠 На головну", callback_data="start")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(response_text, parse_mode='HTML', reply_markup=reply_markup)
        return ConversationHandler.END

    async def admin_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Просмотр сообщений от пользователей"""
        query = update.callback_query
        await query.answer()

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT id, user_id, username, full_name, message_type, message_text, product_name, created_at, is_read
            FROM user_messages 
            ORDER BY created_at DESC 
            LIMIT 10
        ''')
        messages = cursor.fetchall()

        # Подсчитываем непрочитанные
        cursor.execute('SELECT COUNT(*) FROM user_messages WHERE is_read = FALSE')
        cursor.execute('SELECT COUNT(*) as count FROM user_messages WHERE is_read = FALSE')
        unread_count = cursor.fetchone()['count']
        conn.close()

        if not messages:
            text = "📭 <b>Немає повідомлень</b>"
        else:
            text = f"💬 <b>Повідомлення користувачів</b>\n\n"
            text += f"Непрочитаних: {unread_count}\n\n"

            for row in messages:
                msg_id = row['id']
                user_id = row['user_id']
                username = row['username']
                full_name = row['full_name']
                msg_type = row['message_type']
                msg_text = row['message_text']
                product_name = row['product_name']
                created_at = row['created_at']
                is_read = row['is_read']
                status = "📩" if not is_read else "📨"
                type_icon = "🛒" if msg_type == "contact_seller" else "🎯"

                text += f"{status} {type_icon} <b>{full_name}</b>\n"
                text += f"@{username or 'без username'}\n"

                if product_name:
                    text += f"Товар: {product_name}\n"

                # Увеличиваем лимит символов для сообщения
                if len(msg_text) > 100:
                    text += f"Текст: {msg_text[:100]}...\n"
                else:
                    text += f"Текст: {msg_text}\n"

                text += f"Дата: {created_at}\n"
                text += f"ID: {msg_id}\n\n"

        keyboard = [
            [InlineKeyboardButton("📋 Всі повідомлення", callback_data="all_messages")],
            [InlineKeyboardButton("✅ Позначити всі прочитаними", callback_data="mark_all_read")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)

    async def cancel_preorder(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена предзаказа"""
        query = update.callback_query
        await query.answer()

        cancel_text = "❌ <b>Передзамовлення скасовано</b>"

        if query.message.photo:
            await query.edit_message_caption(caption=cancel_text, parse_mode='HTML')
        else:
            await query.edit_message_text(cancel_text, parse_mode='HTML')

        return ConversationHandler.END

    async def show_categories(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показ категорій товарів"""
        query = update.callback_query
        await query.answer()

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Отримуємо тільки головні категорії (без батьківських)
        cursor.execute('SELECT id, name, emoji FROM categories WHERE parent_id IS NULL ORDER BY name')
        categories = cursor.fetchall()
        conn.close()

        if not categories:
            text = "😔 <b>Поки що немає доступних категорій</b>\n\nЗавітайте пізніше!"
            keyboard = [[InlineKeyboardButton("🏠 На головну", callback_data="start")]]
        else:
            text = "📂 <b>Оберіть категорію товарів:</b>\n\n"
            keyboard = []

            for row in categories:  # ИСПРАВЛЕНО: используем row
                cat_id = row['id']
                name = row['name']
                emoji = row['emoji']

                # Підрахунок товарів у категорії (включаючи підкатегорії)
                conn = psycopg2.connect(**self.db_config)
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute('''
                    SELECT COUNT(*) as count FROM products p 
                    JOIN categories c ON p.category_id = c.id 
                    WHERE (c.id = %s OR c.parent_id = %s) AND p.is_available = TRUE
                ''', (cat_id, cat_id))
                count = cursor.fetchone()['count']  # ИСПРАВЛЕНО: обращение по ключу
                conn.close()

                button_text = f"{emoji} {name} ({count})"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"category_{cat_id}")])

            keyboard.append([InlineKeyboardButton("🏠 На головну", callback_data="start")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        try:

            await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
        except Exception:

            try:
                await query.delete_message()
            except Exception:
                pass
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                parse_mode='HTML',
                reply_markup=reply_markup
            )

    async def show_products_in_category(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показ товаров в категории"""
        query = update.callback_query
        await query.answer()

        category_id = int(query.data.split('_')[1])

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Получение названия категории
        cursor.execute('SELECT name, emoji, parent_id FROM categories WHERE id = %s', (category_id,))
        category_info = cursor.fetchone()

        # Проверяем есть ли подкатегории
        cursor.execute('SELECT id, name, emoji FROM categories WHERE parent_id = %s ORDER BY name', (category_id,))
        subcategories = cursor.fetchall()

        if subcategories:
            # Показываем подкатегории (это главная категория)
            text = f"📂 <b>{category_info['emoji']} {category_info['name']}</b>\n\nОберіть підкатегорію:"
            keyboard = []

            for row in subcategories:
                subcat_id = row['id']
                name = row['name']
                emoji = row['emoji']

                # Подсчёт товаров в подкатегории
                cursor.execute('SELECT COUNT(*) as count FROM products WHERE category_id = %s AND is_available = TRUE',
                               (subcat_id,))
                count = cursor.fetchone()['count']
                button_text = f"{emoji} {name} ({count})"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"category_{subcat_id}")])

            # Также показываем товары из главной категории
            cursor.execute('SELECT COUNT(*) as count FROM products WHERE category_id = %s AND is_available = TRUE',
                           (category_id,))
            main_count = cursor.fetchone()['count']
            if main_count > 0:
                keyboard.insert(0, [InlineKeyboardButton(f"📦 Загальні товари ({main_count})",
                                                         callback_data=f"products_{category_id}")])

            # Добавляем кнопку "Весь ассортимент" ТОЛЬКО для подкатегорий
            cursor.execute('''
                SELECT COUNT(*) as count FROM products p 
                JOIN categories c ON p.category_id = c.id 
                WHERE c.parent_id = %s AND p.is_available = TRUE
            ''', (category_id,))
            subcategories_products_count = cursor.fetchone()['count']

            if subcategories_products_count > 0:
                keyboard.append(
                    [InlineKeyboardButton(f"🛍️ Весь асортимент ({subcategories_products_count})",
                                          callback_data=f"all_subcategories_{category_id}")])

            keyboard.append([InlineKeyboardButton("🔙 До категорій", callback_data="show_categories")])
            keyboard.append([InlineKeyboardButton("🏠 На головну", callback_data="start")])

            reply_markup = InlineKeyboardMarkup(keyboard)

            # Обработка ошибки "Message is not modified"
            try:
                await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
            except Exception:
                try:
                    await query.delete_message()
                except Exception:
                    pass

                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=text,
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )

            conn.close()
            return

        # Получение товаров (для подкатегорий или категорий без подкатегорий)
        cursor.execute('''
            SELECT id, name, price, description, photos 
            FROM products 
            WHERE category_id = %s AND is_available = TRUE 
            ORDER BY name
        ''', (category_id,))
        products = cursor.fetchall()

        # Проверяем количество товаров для кнопки "Весь асортимент"
        product_count = len(products)

        conn.close()

        if not products:
            text = f"😔 <b>У категорії \"{category_info['emoji']} {category_info['name']}\" поки що немає товарів</b>"
            keyboard = []

            # Если это подкатегория, добавляем возврат к родительской категории
            if category_info['parent_id']:
                keyboard.append([InlineKeyboardButton("🔙 До категорій",
                                                      callback_data=f"category_{category_info['parent_id']}")])
            keyboard.append([InlineKeyboardButton("🏠 На головну", callback_data="start")])

            reply_markup = InlineKeyboardMarkup(keyboard)

            try:
                await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
            except Exception:
                try:
                    await query.delete_message()
                except Exception:
                    pass

                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=text,
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
            return

        # Это подкатегория с товарами - показываем меню с пошаговым просмотром и "Весь асортимент"
        text = f"📂 <b>{category_info['emoji']} {category_info['name']}</b>\n\nЗнайдено {product_count} товарів."

        keyboard = [
            [InlineKeyboardButton(f"🛍️ Весь асортимент ({product_count})",
                                  callback_data=f"all_in_category_{category_id}")]
        ]

        # Если это подкатегория, добавляем возврат к родительской категории
        if category_info['parent_id']:
            keyboard.append([InlineKeyboardButton("🔙 До  категорій",
                                                  callback_data=f"category_{category_info['parent_id']}")])

        keyboard.append([InlineKeyboardButton("🏠 На головну", callback_data="start")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
        except Exception:
            try:
                await query.delete_message()
            except Exception:
                pass

            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                parse_mode='HTML',
                reply_markup=reply_markup
            )

    async def browse_one_by_one(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Пошаговый просмотр товаров категории"""
        query = update.callback_query
        await query.answer()

        category_id = int(query.data.split('_')[2])

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT id, name, price, description, photos 
            FROM products 
            WHERE category_id = %s AND is_available = TRUE 
            ORDER BY name
        ''', (category_id,))
        products = cursor.fetchall()
        conn.close()

        if not products:
            await query.answer("Товарів немає", show_alert=True)
            return

        # Показываем первый товар
        context.user_data['current_category'] = category_id
        context.user_data['products'] = products
        context.user_data['current_product_index'] = 0

        await self.show_product(update, context, show_category_header=True)

    async def show_products_in_category(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показ товаров в категории"""
        query = update.callback_query
        await query.answer()

        category_id = int(query.data.split('_')[1])

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Получение названия категории
        cursor.execute('SELECT name, emoji, parent_id FROM categories WHERE id = %s', (category_id,))
        category_info = cursor.fetchone()

        # Проверяем есть ли подкатегории
        cursor.execute('SELECT id, name, emoji FROM categories WHERE parent_id = %s ORDER BY name', (category_id,))
        subcategories = cursor.fetchall()

        if subcategories:
            # Показываем подкатегории (это главная категория)
            text = f"📂 <b>{category_info['emoji']} {category_info['name']}</b>\n\nОберіть підкатегорію:"
            keyboard = []

            for row in subcategories:
                subcat_id = row['id']
                name = row['name']
                emoji = row['emoji']

                # Подсчёт товаров в подкатегории
                cursor.execute('SELECT COUNT(*) as count FROM products WHERE category_id = %s AND is_available = TRUE',
                               (subcat_id,))
                count = cursor.fetchone()['count']
                button_text = f"{emoji} {name} ({count})"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"category_{subcat_id}")])

            # Также показываем товары из главной категории
            cursor.execute('SELECT COUNT(*) as count FROM products WHERE category_id = %s AND is_available = TRUE',
                           (category_id,))
            main_count = cursor.fetchone()['count']
            if main_count > 0:
                keyboard.insert(0, [InlineKeyboardButton(f"📦 Загальні товари ({main_count})",
                                                         callback_data=f"products_{category_id}")])

            # Добавляем кнопку "Весь ассортимент" ТОЛЬКО для подкатегорий
            cursor.execute('''
                SELECT COUNT(*) as count FROM products p 
                JOIN categories c ON p.category_id = c.id 
                WHERE c.parent_id = %s AND p.is_available = TRUE
            ''', (category_id,))
            subcategories_products_count = cursor.fetchone()['count']

            if subcategories_products_count > 0:
                keyboard.append(
                    [InlineKeyboardButton(f"🛍️ Весь асортимент ({subcategories_products_count})",
                                          callback_data=f"all_subcategories_{category_id}")])

            keyboard.append([InlineKeyboardButton("🔙 До категорій", callback_data="show_categories")])
            keyboard.append([InlineKeyboardButton("🏠 На головну", callback_data="start")])

            reply_markup = InlineKeyboardMarkup(keyboard)

            # Обработка ошибки "Message is not modified"
            try:
                await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
            except Exception:
                try:
                    await query.delete_message()
                except Exception:
                    pass

                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=text,
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )

            conn.close()
            return

        # Получение товаров (для подкатегорий или категорий без подкатегорий)
        cursor.execute('''
            SELECT id, name, price, description, photos 
            FROM products 
            WHERE category_id = %s AND is_available = TRUE 
            ORDER BY name
        ''', (category_id,))
        products = cursor.fetchall()

        # Проверяем количество товаров для кнопки "Весь асортимент"
        product_count = len(products)

        conn.close()

        if not products:
            text = f"😔 <b>У категорії \"{category_info['emoji']} {category_info['name']}\" поки що немає товарів</b>"
            keyboard = []

            # Если это подкатегория, добавляем возврат к родительской категории
            if category_info['parent_id']:
                keyboard.append([InlineKeyboardButton("🔙 До категорій",
                                                      callback_data=f"category_{category_info['parent_id']}")])
            keyboard.append([InlineKeyboardButton("🏠 На головну", callback_data="start")])

            reply_markup = InlineKeyboardMarkup(keyboard)

            try:
                await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
            except Exception:
                try:
                    await query.delete_message()
                except Exception:
                    pass

                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=text,
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
            return

        # Это подкатегория с товарами - показываем меню с пошаговым просмотром и "Весь асортимент"
        text = f"📂 <b>{category_info['emoji']} {category_info['name']}</b>\n\nЗнайдено {product_count} товарів."

        keyboard = [
            [InlineKeyboardButton(f"🛍️ Весь асортимент ({product_count})",
                                  callback_data=f"all_in_category_{category_id}")]
        ]

        # Если это подкатегория, добавляем возврат к родительской категории
        if category_info['parent_id']:
            keyboard.append([InlineKeyboardButton("🔙 До  категорій",
                                                  callback_data=f"category_{category_info['parent_id']}")])

        keyboard.append([InlineKeyboardButton("🏠 На головну", callback_data="start")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
        except Exception:
            try:
                await query.delete_message()
            except Exception:
                pass

            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                parse_mode='HTML',
                reply_markup=reply_markup
            )


    async def show_all_products_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показ всех товаров для пользователя"""
        query = update.callback_query
        await query.answer()

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT p.id, p.name, p.price, p.description, p.photos, c.name as cat_name, c.emoji as cat_emoji
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            WHERE p.is_available = TRUE
            ORDER BY c.name, p.name
        ''')
        products = cursor.fetchall()
        conn.close()

        if not products:
            text = "😔 <b>Поки що немає доступних товарів</b>"
            keyboard = [[InlineKeyboardButton("🏠 На головну", callback_data="start")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
            return

        # Преобразуем данные в формат, который ожидает show_product
        # Оставляем данные как RealDictRow объекты, которые работают как словари
        formatted_products = products

        context.user_data['current_category'] = None
        context.user_data['products'] = formatted_products
        context.user_data['current_product_index'] = 0
        context.user_data['all_products_mode'] = True

        await self.show_product(update, context, show_category_header=False)

    async def show_product(self, update: Update, context: ContextTypes.DEFAULT_TYPE, show_category_header=False):
        """Показ конкретного товара сразу со всеми фотографиями"""
        products = context.user_data.get('products', [])
        current_index = context.user_data.get('current_product_index', 0)
        all_products_mode = context.user_data.get('all_products_mode', False)

        if not products or current_index >= len(products):
            if all_products_mode:
                await self.start(update, context)
            else:
                await self.show_categories(update, context)
            return

        product = products[current_index]
        product_id = product['id']
        name = product['name']
        price = product['price']
        description = product['description']
        photos_json = product['photos']

        # Парсинг фотографий
        try:
            photos = json.loads(photos_json) if photos_json else []
        except:
            photos = []

        # Получание информации о категории для товара
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT c.name, c.emoji, pc.name as parent_name, pc.emoji as parent_emoji
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            LEFT JOIN categories pc ON c.parent_id = pc.id
            WHERE p.id = %s
        ''', (product_id,))
        cat_info = cursor.fetchone()
        conn.close()

        # Формування тексту
        header = ""
        if show_category_header and context.user_data.get('current_category') and not all_products_mode:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('SELECT name, emoji FROM categories WHERE id = %s',
                           (context.user_data['current_category'],))
            category_info = cursor.fetchone()
            conn.close()
            header = f"📂 <b>{category_info['emoji']} {category_info['name']}</b>\n\n"
        elif all_products_mode and cat_info and cat_info['name']:
            if cat_info['parent_name']:  # Є батьківська категорія
                header = f"📂 <b>{cat_info['parent_emoji']} {cat_info['parent_name']} → {cat_info['emoji']} {cat_info['name']}</b>\n\n"
            else:
                header = f"📂 <b>{cat_info['emoji']} {cat_info['name']}</b>\n\n"

        text = f"""{header}🛍️ <b>{name}</b>

    💰 <b>Ціна:</b> {price:.2f} грн

    📝 <b>Опис:</b>
    {description or 'Опис відсутній'}

    <i>Товар #{current_index + 1} з {len(products)}</i>"""

        # Кнопки навігації
        keyboard = []

        # Кнопка зв'язку з продавцем
        keyboard.append(
            [InlineKeyboardButton("📞 Зв'язатися щодо товару", callback_data=f"contact_seller_{product_id}")])

        # Навігація між товарами
        nav_buttons = []
        if current_index > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Попередній", callback_data="prev_product"))
        if current_index < len(products) - 1:
            nav_buttons.append(InlineKeyboardButton("Наступний ➡️", callback_data="next_product"))

        if nav_buttons:
            keyboard.append(nav_buttons)

        # Кнопки повернення
        if all_products_mode:
            keyboard.append([InlineKeyboardButton("🏠 На головну", callback_data="start")])
        elif context.user_data.get('show_all_in_category'):
            keyboard.append([InlineKeyboardButton("🔙 До категорії",
                                                  callback_data=f"category_{context.user_data['current_category']}")])
            keyboard.append([InlineKeyboardButton("🏠 На головну", callback_data="start")])
        else:
            keyboard.append([InlineKeyboardButton("🔙 До категорій", callback_data="show_categories")])
            keyboard.append([InlineKeyboardButton("🏠 На головну", callback_data="start")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        # Відправка повідомлення з фото або без
        if photos:
            if len(photos) == 1:
                # Одно фото - обычная отправка
                try:
                    if update.callback_query:
                        await update.callback_query.delete_message()

                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=photos[0],
                        caption=text,
                        parse_mode='HTML',
                        reply_markup=reply_markup
                    )
                except Exception as e:
                    logger.error(f"Error sending photo: {e}")
                    if update.callback_query:
                        await update.callback_query.edit_message_text(text, parse_mode='HTML',
                                                                      reply_markup=reply_markup)
                    else:
                        await update.message.reply_text(text, parse_mode='HTML', reply_markup=reply_markup)
            else:
                # Несколько фото - отправляем медиагруппу
                try:
                    if update.callback_query:
                        await update.callback_query.delete_message()

                    # Создаем медиагруппу
                    media = []
                    for i, photo in enumerate(photos):
                        if i == 0:
                            # Первое фото с полным описанием
                            media.append(InputMediaPhoto(media=photo, caption=text, parse_mode='HTML'))
                        else:
                            # Остальные фото без подписи
                            media.append(InputMediaPhoto(media=photo))

                    # Отправляем медиагруппу
                    await context.bot.send_media_group(
                        chat_id=update.effective_chat.id,
                        media=media
                    )

                    # Отправляем кнопки отдельным сообщением

                except Exception as e:
                    logger.error(f"Error sending media group: {e}")
                    # Fallback - отправляем как обычное фото
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=photos[0],
                        caption=text,
                        parse_mode='HTML',
                        reply_markup=reply_markup
                    )
        else:
            # Без фото
            if update.callback_query:
                try:
                    await update.callback_query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
                except Exception:
                    await update.callback_query.delete_message()
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=text,
                        parse_mode='HTML',
                        reply_markup=reply_markup
                    )
            else:
                await update.message.reply_text(text, parse_mode='HTML', reply_markup=reply_markup)


    async def contact_seller(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Початок процесу зв'язку з продавцем"""
        query = update.callback_query
        await query.answer()

        product_id = int(query.data.split('_')[2])
        context.user_data['contact_product_id'] = product_id

        # Получаем информацию о товаре
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT name FROM products WHERE id = %s', (product_id,))
        product = cursor.fetchone()
        conn.close()

        if not product:
            await query.answer("Товар не знайдено", show_alert=True)
            return ConversationHandler.END

        text = f"""
    📞 <b>Зв'язок з продавцем</b>

    Товар: <b>{product['name']}</b>

    Напишіть ваше повідомлення або питання щодо цього товару:
        """

        keyboard = [[InlineKeyboardButton("❌ Скасувати", callback_data="cancel_contact")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Проверяем, есть ли фото в сообщении
        if query.message.photo:
            # Если есть фото, редактируем caption
            await query.edit_message_caption(caption=text, parse_mode='HTML', reply_markup=reply_markup)
        else:
            # Если нет фото, редактируем текст
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)

        return CONTACT_MESSAGE

    async def process_contact_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка повідомлення для продавця"""
        user_message = update.message.text
        user = update.effective_user
        product_id = context.user_data.get('contact_product_id')

        if not product_id:
            await update.message.reply_text("Помилка: товар не вибрано")
            return ConversationHandler.END

        # Отримання інформації про товар
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT name, price, source_link FROM products WHERE id = %s', (product_id,))
        product = cursor.fetchone()

        if not product:
            cursor.close()
            conn.close()
            await update.message.reply_text("Товар не знайдено")
            return ConversationHandler.END

        # Сохраняем сообщение в БД
        cursor.execute('''
            INSERT INTO user_messages (user_id, username, full_name, message_type, message_text, product_id, product_name)
            VALUES (%s, %s, %s, %s, %s, %s ,%s)
        ''', (user.id, user.username, user.full_name, 'contact_seller', user_message, product_id, product['name']))

        conn.commit()
        conn.close()

        # Формируем сообщение для админов
        admin_message = f"""
📞 <b>Нове повідомлення від користувача</b>

👤 <b>Від:</b> {user.full_name} (@{user.username or 'немає username'})
🆔 <b>User ID:</b> {user.id}

🛏️ <b>Товар:</b> {product['name']}
💰 <b>Ціна:</b> {product['price']:.2f} грн
{f"🔗 <b>Джерело:</b> {product['source_link']}" if product['source_link'] else ""}

💬 <b>Повідомлення:</b>
{user_message}

"""

        # Відправка адмінам
        for admin_id in self.admin_ids:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=admin_message,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"Error sending message to admin {admin_id}: {e}")

        # Відповідь користувачу
        response_text = f"""
    ✅ <b>Ваше повідомлення надіслано!</b>

    Ми зв'яжемося з вами найближчим часом.

    <b>Контакти для прямого зв'язку:</b>
    * Телефон: {self.contact_info['phone']}
    * Email: {self.contact_info['email']}
    * Telegram: {self.contact_info['telegram']}
    * Instagram: {self.contact_info['instagram']}
        """

        keyboard = [[InlineKeyboardButton("🏠 На головну", callback_data="start")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(response_text, parse_mode='HTML', reply_markup=reply_markup)
        return ConversationHandler.END

    async def cancel_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Скасування зв'язку з продавцем"""
        query = update.callback_query
        await query.answer()

        await query.delete_message()
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ <b>Зв'язок скасовано</b>",
            parse_mode='HTML'
        )

        return ConversationHandler.END



    async def about(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Інформація про магазин"""
        query = update.callback_query
        await query.answer()

        text = f"""
ℹ️ <b>Про наш магазин</b>

👕 Ми спеціалізуємось на продажу оригінального одягу та взуття з Європи та США.
У нас можна придбати товари в наявності та під замовлення.


📞 <b>Контакти:</b>
<b>Контактна інформація:</b>
* Телефон: {self.contact_info['phone']}
* Email: {self.contact_info['email']}
* Telegram: {self.contact_info['telegram']}
* Instagram: {self.contact_info['instagram']}

📦 <b>Доставка:</b>
• 🚚 Нова Пошта по всій Україні — 7–14 днів (термін залежить від міста та роботи митниці).
• 🚖 По м. Ужгород — швидка доставка / самовивіз.


💳 <b>Оплата:</b>
• Повна оплата на карту 💳
• Накладений платіж (оплата при отриманні) 💵
• 

<i>💙💛 Дякуємо, що обираєте Sneakerhead Store!</i>
        """

        keyboard = [
            [InlineKeyboardButton("🛒 До товарів", callback_data="show_categories")],
            [InlineKeyboardButton("🏠 На головну", callback_data="start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)

    # ==================== АДМІН ПАНЕЛЬ ====================

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Адмін панель"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ У вас немає прав адміністратора")
            return ConversationHandler.END

        text = """
🔧 <b>Адміністративна панель</b>

Оберіть дію:
        """

        keyboard = [
            [InlineKeyboardButton("📂 Управління категоріями", callback_data="admin_categories")],
            [InlineKeyboardButton("💬 Повідомлення", callback_data="admin_messages")],
            [InlineKeyboardButton("📦 Управління товарами", callback_data="admin_products")],
            [InlineKeyboardButton("👥 Управління адмінами", callback_data="admin_users")],
            [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton("❌ Вийти з панелі", callback_data="exit_admin")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(text, parse_mode='HTML', reply_markup=reply_markup)
        return ADMIN_MENU

    async def admin_categories_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню управління категоріями"""
        query = update.callback_query
        await query.answer()

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT c.id, c.name, c.emoji, pc.name as parent_name
            FROM categories c
            LEFT JOIN categories pc ON c.parent_id = pc.id
            ORDER BY c.parent_id, c.name
        ''')
        categories = cursor.fetchall()
        conn.close()

        text = "📂 <b>Управління категоріями</b>\n\n"
        if categories:
            text += "<b>Існуючі категорії:</b>\n"
            for row in categories:
                cat_id = row['id']
                name = row['name']
                emoji = row['emoji']
                parent_name = row['parent_name']

                if parent_name:
                    text += f"  ↳ {emoji} {name} (підкатегорія {parent_name})\n"
                else:
                    text += f"• {emoji} {name}\n"
        else:
            text += "<i>Категорії відсутні</i>"

        keyboard = [
            [InlineKeyboardButton("➕ Додати категорію", callback_data="add_category")],
            [InlineKeyboardButton("📁 Додати підкатегорію", callback_data="add_subcategory")],
            [InlineKeyboardButton("✏️ Редагувати категорію", callback_data="edit_category_select")],
            [InlineKeyboardButton("🗑️ Видалити категорію", callback_data="delete_category_select")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)


    # ==================== УПРАВЛІННЯ КАТЕГОРІЯМИ ====================

    async def add_category_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Початок додавання категорії"""
        query = update.callback_query
        await query.answer()

        await query.edit_message_text(
            "📂 <b>Додавання нової категорії</b>\n\n"
            "Введіть назву категорії та емодзі через пробіл:\n"
            "<i>Приклад: Електроніка 📱</i>\n\n"
            "Або надішліть /cancel для скасування",
            parse_mode='HTML'
        )
        return ADD_CATEGORY

    async def process_add_category(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка додавання категорії"""
        text = update.message.text.strip()

        if ' ' in text:
            parts = text.split(' ')
            emoji = parts[-1]
            name = ' '.join(parts[:-1])
        else:
            name = text
            emoji = '📦'

        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('INSERT INTO categories (name, emoji) VALUES (%s, %s)', (name, emoji))
            conn.commit()
            conn.close()

            await update.message.reply_text(
                f"✅ <b>Категорію додано!</b>\n\n"
                f"{emoji} {name}",
                parse_mode='HTML'
            )
        except psycopg2.IntegrityError:
            await update.message.reply_text("❌ Категорія з такою назвою вже існує!")
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка: {str(e)}")

        return ConversationHandler.END

    async def add_subcategory_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Початок додавання підкатегорії"""
        query = update.callback_query
        await query.answer()

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT id, name, emoji FROM categories WHERE parent_id IS NULL ORDER BY name')
        parent_categories = cursor.fetchall()
        conn.close()

        if not parent_categories:
            await query.edit_message_text(
                "❌ <b>Спочатку створіть головні категорії!</b>",
                parse_mode='HTML'
            )
            return ConversationHandler.END

        text = "📁 <b>Додавання підкатегорії</b>\n\nОберіть батьківську категорію:"
        keyboard = []

        for cat_id, name, emoji in parent_categories:
            keyboard.append([InlineKeyboardButton(f"{emoji} {name}", callback_data=f"parent_cat_{cat_id}")])

        keyboard.append([InlineKeyboardButton("❌ Скасувати", callback_data="admin_categories")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
        return SELECT_PARENT_CATEGORY

    async def process_product_photos_done(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Завершення додавання фотографій"""
        # Отримуємо категорії для вибору
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT c.id, c.name, c.emoji, c.parent_id, pc.name as parent_name
            FROM categories c
            LEFT JOIN categories pc ON c.parent_id = pc.id
            ORDER BY CASE WHEN c.parent_id IS NULL THEN 0 ELSE 1 END, c.parent_id, c.name
        ''')
        categories = cursor.fetchall()
        conn.close()

        if not categories:
            await update.message.reply_text(
                "⛔ Спочатку створіть категорії в адмін панелі!"
            )
            return ConversationHandler.END

        text = "Крок 5/5: Оберіть категорію для товару:"
        keyboard = []

        current_parent = None
        for cat_id, name, emoji, parent_id, parent_name in categories:
            if parent_id is None:  # Головна категорія
                keyboard.append([InlineKeyboardButton(f"{emoji} {name}", callback_data=f"select_cat_{cat_id}")])
                current_parent = cat_id
            else:  # Підкатегорія
                keyboard.append([InlineKeyboardButton(f"  ↳ {emoji} {name}", callback_data=f"select_cat_{cat_id}")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup)


        return ADD_PRODUCT_CATEGORY


    async def mark_all_read(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отметить все сообщения как прочитанные"""
        query = update.callback_query
        await query.answer()

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('UPDATE user_messages SET is_read = 1 WHERE is_read = 0')
        updated_count = cursor.rowcount
        conn.commit()
        conn.close()

        await query.answer(f"Позначено {updated_count} повідомлень як прочитані", show_alert=True)

        # Обновляем отображение
        await self.admin_messages(update, context)

    async def all_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать все сообщения с возможностью удаления"""
        query = update.callback_query
        await query.answer()

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT id, user_id, username, full_name, message_type, message_text, product_name, created_at, is_read
            FROM user_messages 
            ORDER BY created_at DESC 
            LIMIT 20
        ''')
        messages = cursor.fetchall()
        conn.close()

        if not messages:
            text = "📭 <b>Немає повідомлень</b>"
            keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_messages")]]
        else:
            text = f"📋 <b>Всі повідомлення (останні 20)</b>\n\n"

            keyboard = []
            for msg_id, user_id, username, full_name, msg_type, msg_text, product_name, created_at, is_read in messages:
                status = "📩" if not is_read else "📨"
                type_icon = "🛒" if msg_type == "contact_seller" else "🎯"

                text += f"{status} {type_icon} <b>ID {msg_id}</b> - {full_name}\n"
                if product_name:
                    text += f"Товар: {product_name}\n"
                text += f"{msg_text[:30]}...\n"
                text += f"<i>{created_at}</i>\n\n"

                # Кнопка для удаления каждого сообщения
                keyboard.append(
                    [InlineKeyboardButton(f"🗑️ Видалити ID {msg_id}", callback_data=f"delete_msg_{msg_id}")])

            keyboard.extend([
                [InlineKeyboardButton("🗑️ Видалити всі", callback_data="delete_all_messages")],
                [InlineKeyboardButton("🔙 Назад", callback_data="admin_messages")]
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)

    async def delete_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Удалить конкретное сообщение"""
        query = update.callback_query
        await query.answer()

        msg_id = int(query.data.split('_')[2])

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('DELETE FROM user_messages WHERE id = %s', (msg_id,))
        conn.commit()
        conn.close()

        await query.answer(f"Повідомлення ID {msg_id} видалено", show_alert=True)

        # Обновляем список
        await self.all_messages(update, context)

    async def delete_all_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Подтверждение удаления всех сообщений"""
        query = update.callback_query
        await query.answer()

        text = "⚠️ <b>Видалення всіх повідомлень</b>\n\nВи впевнені що хочете видалити ВСІ повідомлення? Цю дію неможливо відмінити."

        keyboard = [
            [InlineKeyboardButton("🗑️ Так, видалити всі", callback_data="confirm_delete_all")],
            [InlineKeyboardButton("❌ Скасувати", callback_data="all_messages")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)

    async def confirm_delete_all_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Подтвержденное удаление всех сообщений"""
        query = update.callback_query
        await query.answer()

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT COUNT(*) FROM user_messages')
        count = cursor.fetchone()[0]
        cursor.execute('DELETE FROM user_messages')
        conn.commit()
        conn.close()

        await query.answer(f"Видалено {count} повідомлень", show_alert=True)
        await self.admin_messages(update, context)

    async def delete_category_select(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Выбор категории для удаления"""
        query = update.callback_query
        await query.answer()

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT c.id, c.name, c.emoji, pc.name as parent_name,
                   (SELECT COUNT(*) FROM products WHERE category_id = c.id) as product_count
            FROM categories c
            LEFT JOIN categories pc ON c.parent_id = pc.id
            ORDER BY c.parent_id, c.name
        ''')
        categories = cursor.fetchall()
        conn.close()

        if not categories:
            await query.edit_message_text("⛔ Категорії відсутні")
            return ConversationHandler.END

        text = "🗑️ <b>Оберіть категорію для видалення:</b>\n\n<i>⚠️ Увага: при видаленні категорії всі товари в ній будуть також видалені!</i>\n"
        keyboard = []

        for row in categories:
            cat_id = row['id']
            name = row['name']
            emoji = row['emoji']
            parent_name = row['parent_name']
            product_count = row['product_count']

            if parent_name:
                button_text = f"  ↳ {emoji} {name} ({product_count} товарів)"
            else:
                button_text = f"{emoji} {name} ({product_count} товарів)"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"delete_cat_{cat_id}")])

        keyboard.append([InlineKeyboardButton("⛔ Скасувати", callback_data="admin_categories")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
        return SELECT_CATEGORY_TO_DELETE




    # ==================== УПРАВЛІННЯ ТОВАРАМИ ====================

    async def add_product_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Початок додавання товару"""
        query = update.callback_query
        await query.answer()

        await query.edit_message_text(
            "📦 <b>Додавання нового товару</b>\n\n"
            "Крок 1/5: Введіть назву товару\n\n"
            "Або надішліть /cancel для скасування",
            parse_mode='HTML'
        )
        return ADD_PRODUCT_NAME

    async def process_product_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка назви товару"""
        context.user_data['product_name'] = update.message.text.strip()

        await update.message.reply_text(
            f"✅ Назва: <b>{context.user_data['product_name']}</b>\n\n"
            "Крок 2/5: Введіть ціну товару (у гривнях)\n"
            "<i>Приклад: 1250.50</i>",
            parse_mode='HTML'
        )
        return ADD_PRODUCT_PRICE

    async def process_product_price(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка ціни товару"""
        try:
            price = float(update.message.text.strip())
            if price <= 0:
                raise ValueError("Ціна повинна бути більше нуля")

            context.user_data['product_price'] = price

            await update.message.reply_text(
                f"✅ Ціна: <b>{price:.2f} грн</b>\n\n"
                "Крок 3/5: Введіть опис товару",
                parse_mode='HTML'
            )
            return ADD_PRODUCT_DESCRIPTION
        except ValueError:
            await update.message.reply_text(
                "❌ Невірна ціна! Введіть число більше нуля.\n"
                "<i>Приклад: 1250.50</i>",
                parse_mode='HTML'
            )
            return ADD_PRODUCT_PRICE

    async def process_product_description(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка опису товару"""
        context.user_data['product_description'] = update.message.text.strip()

        await update.message.reply_text(
            f"✅ Опис збережено\n\n"
            "Крок 4/5: Надішліть фотографії товару\n"
            "Можете надісилати кілька фото по черзі.\n\n"
            "Коли закінчите, натисніть /done\n"
            "Або /skip щоб пропустити фотографії",
            parse_mode='HTML'
        )
        context.user_data['product_photos'] = []
        return ADD_PRODUCT_PHOTOS

    async def process_product_photos(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка фотографій товару"""
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            context.user_data['product_photos'].append(file_id)

            photo_count = len(context.user_data['product_photos'])
            await update.message.reply_text(
                f"📸 Фото {photo_count} збережено!\n\n"
                "Надішліть ще фото або натисніть /done для завершення"
            )
            return ADD_PRODUCT_PHOTOS
        else:
            await update.message.reply_text(
                "❌ Надішліть фотографію або /done для продовження"
            )
            return ADD_PRODUCT_PHOTOS

    async def process_product_photos_done(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Завершення додавання фотографій"""
        # Отримуємо категорії для вибору
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT c.id, c.name, c.emoji, pc.name as parent_name
            FROM categories c
            LEFT JOIN categories pc ON c.parent_id = pc.id
            ORDER BY c.parent_id, c.name
        ''')
        categories = cursor.fetchall()
        conn.close()

        if not categories:
            await update.message.reply_text(
                "❌ Спочатку створіть категорії в адмін панелі!"
            )
            return ConversationHandler.END

        text = "Крок 5/5: Оберіть категорію для товару:"
        keyboard = []

        for cat_id, name, emoji, parent_name in categories:
            if parent_name:
                button_text = f"  ↳ {emoji} {name}"
            else:
                button_text = f"{emoji} {name}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"select_cat_{cat_id}")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup)
        return ADD_PRODUCT_CATEGORY

    async def process_product_edit_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка вибору товару для редагування"""
        query = update.callback_query
        await query.answer()

        try:
            # Проверяем формат callback_data
            callback_parts = query.data.split('_')
            if len(callback_parts) < 3:
                await query.edit_message_text("❌ Помилка: неправильний формат даних")
                return ConversationHandler.END

            product_id = int(callback_parts[2])
            context.user_data['edit_product_id'] = product_id

            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('SELECT name, price, description FROM products WHERE id = %s', (product_id,))
            product_info = cursor.fetchone()
            conn.close()

            if not product_info:
                await query.edit_message_text("❌ Товар не знайдено")
                return ConversationHandler.END

            text = f"✏️ <b>Редагування товару</b>\n\n"
            text += f"<b>Назва:</b> {product_info['name']}\n"
            text += f"<b>Ціна:</b> {product_info['price']:.2f} грн\n"
            text += f"<b>Опис:</b> {product_info['description'] or 'Відсутній'}\n\n"
            text += "Що бажаєте відредагувати?"

            keyboard = [
                [InlineKeyboardButton("📝 Назву", callback_data="edit_product_name")],
                [InlineKeyboardButton("💰 Ціну", callback_data="edit_product_price")],
                [InlineKeyboardButton("📄 Опис", callback_data="edit_product_description")],
                [InlineKeyboardButton("📸 Фотографії", callback_data="edit_product_photos")],
                [InlineKeyboardButton("📂 Категорію", callback_data="edit_product_category")],
                [InlineKeyboardButton("❌ Скасувати", callback_data="admin_products")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
            return EDIT_PRODUCT_FIELD

        except (ValueError, IndexError) as e:
            await query.edit_message_text(f"❌ Помилка обробки даних: {str(e)}")
            return ConversationHandler.END
        except Exception as e:
            await query.edit_message_text(f"❌ Непередбачена помилка: {str(e)}")
            return ConversationHandler.END



    async def admin_products_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню управління товарами"""
        query = update.callback_query
        await query.answer()

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT p.id, p.name, p.price, c.name as cat_name, c.emoji as cat_emoji
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            ORDER BY p.name LIMIT 10
        ''')
        products = cursor.fetchall()
        conn.close()

        text = "📦 <b>Управління товарами</b>\n\n"
        if products:
            text += "<b>Останні товари:</b>\n"
            for row in products:
                prod_id = row['id']
                name = row['name']
                price = row['price']
                cat_name = row['cat_name']
                cat_emoji = row['cat_emoji']

                category_text = f"{cat_emoji} {cat_name}" if cat_name else "Без категорії"
                text += f"• {name} - {price:.2f} грн ({category_text})\n"
        else:
            text += "<i>Товари відсутні</i>"

        keyboard = [
            [InlineKeyboardButton("➕ Додати товар", callback_data="add_product")],
            [InlineKeyboardButton("✏️ Редагувати товар", callback_data="edit_product_select")],
            [InlineKeyboardButton("🗑️ Видалити товар", callback_data="delete_product_select")],
            [InlineKeyboardButton("👁️ Переглянути всі товари", callback_data="view_all_products")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)

    # ==================== УПРАВЛІННЯ КАТЕГОРІЯМИ ====================

    async def add_category_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Початок додавання категорії"""
        query = update.callback_query
        await query.answer()

        await query.edit_message_text(
            "📂 <b>Додавання нової категорії</b>\n\n"
            "Введіть назву категорії та емодзі через пробіл:\n"
            "<i>Приклад: Електроніка 📱</i>\n\n"
            "Або надішліть /cancel для скасування",
            parse_mode='HTML'
        )
        return ADD_CATEGORY

    async def process_add_category(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка додавання категорії"""
        text = update.message.text.strip()

        if ' ' in text:
            parts = text.split(' ')
            emoji = parts[-1]
            name = ' '.join(parts[:-1])
        else:
            name = text
            emoji = '📦'

        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('INSERT INTO categories (name, emoji) VALUES (%s, %s)', (name, emoji))
            conn.commit()
            conn.close()

            await update.message.reply_text(
                f"✅ <b>Категорію додано!</b>\n\n"
                f"{emoji} {name}",
                parse_mode='HTML'
            )
        except psycopg2.IntegrityError:
            await update.message.reply_text("❌ Категорія з такою назвою вже існує!")
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка: {str(e)}")

        return ConversationHandler.END

    async def add_subcategory_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Початок додавання підкатегорії"""
        query = update.callback_query
        await query.answer()

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT id, name, emoji FROM categories WHERE parent_id IS NULL ORDER BY name')
        parent_categories = cursor.fetchall()
        conn.close()

        if not parent_categories:
            await query.edit_message_text(
                "❌ <b>Спочатку створіть головні категорії!</b>",
                parse_mode='HTML'
            )
            return ConversationHandler.END

        text = "📁 <b>Додавання підкатегорії</b>\n\nОберіть батьківську категорію:"
        keyboard = []

        # ИСПРАВЬТЕ ЭТУ СТРОКУ:
        for category in parent_categories:
            cat_id = category['id']
            name = category['name']
            emoji = category['emoji']
            keyboard.append([InlineKeyboardButton(f"{emoji} {name}", callback_data=f"parent_cat_{cat_id}")])

        keyboard.append([InlineKeyboardButton("❌ Скасувати", callback_data="admin_categories")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
        return SELECT_PARENT_CATEGORY


    async def process_parent_category_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка вибору батьківської категорії"""
        query = update.callback_query
        await query.answer()

        try:
            # Проверяем формат callback_data
            callback_parts = query.data.split('_')
            if len(callback_parts) < 3:
                await query.edit_message_text("❌ Помилка: неправильний формат даних")
                return ConversationHandler.END

            parent_id = int(callback_parts[2])
            context.user_data['parent_category_id'] = parent_id

            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('SELECT name, emoji FROM categories WHERE id = %s', (parent_id,))
            parent_info = cursor.fetchone()
            conn.close()

            if not parent_info:
                await query.edit_message_text("❌ Категорія не знайдена")
                return ConversationHandler.END

            await query.edit_message_text(
                f"📁 <b>Додавання підкатегорії</b>\n\n"
                f"Батьківська категорія: {parent_info['emoji']} {parent_info['name']}\n\n"
                f"Введіть назву підкатегорії та емодзі через пробіл:\n"
                f"<i>Приклад: Чоловіче взуття 👞</i>\n\n"
                f"Або надішліть /cancel для скасування",
                parse_mode='HTML'
            )
            return ADD_SUBCATEGORY

        except (ValueError, IndexError) as e:
            await query.edit_message_text(f"❌ Помилка обробки даних: {str(e)}")
            return ConversationHandler.END
        except Exception as e:
            await query.edit_message_text(f"❌ Непередбачена помилка: {str(e)}")
            return ConversationHandler.END

    async def process_add_subcategory(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка додавання підкатегорії"""
        text = update.message.text.strip()
        parent_id = context.user_data.get('parent_category_id')

        if not parent_id:
            await update.message.reply_text("❌ Помилка: батьківська категорія не вибрана")
            return ConversationHandler.END

        if ' ' in text:
            parts = text.split(' ')
            emoji = parts[-1]
            name = ' '.join(parts[:-1])
        else:
            name = text
            emoji = '📦'

        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('INSERT INTO categories (name, emoji, parent_id) VALUES (%s, %s, %s)',
                           (name, emoji, parent_id))

            # Отримуємо інформацію про батьківську категорію
            cursor.execute('SELECT name, emoji FROM categories WHERE id = %s', (parent_id,))
            parent_info = cursor.fetchone()

            conn.commit()
            conn.close()

            await update.message.reply_text(
                f"✅ <b>Підкатегорію додано!</b>\n\n"
                f"Батьківська: {parent_info['emoji']} {parent_info['name']}\n"
                f"Підкатегорія: {emoji} {name}",
                parse_mode='HTML'
            )
        except psycopg2.IntegrityError:
            await update.message.reply_text("❌ Категорія з такою назвою вже існує!")
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка: {str(e)}")

        return ConversationHandler.END

    async def edit_category_select(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Вибір категорії для редагування"""
        query = update.callback_query
        await query.answer()

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT c.id, c.name, c.emoji, pc.name as parent_name
            FROM categories c
            LEFT JOIN categories pc ON c.parent_id = pc.id
            ORDER BY c.parent_id, c.name
        ''')
        categories = cursor.fetchall()
        conn.close()

        if not categories:
            await query.edit_message_text("❌ Категорії відсутні")
            return ConversationHandler.END

        text = "✏️ <b>Оберіть категорію для редагування:</b>"
        keyboard = []

        for row in categories:
            cat_id = row['id']
            name = row['name']
            emoji = row['emoji']
            parent_name = row['parent_name']

            if parent_name:
                button_text = f"  ↳ {emoji} {name} (підкат. {parent_name})"
            else:
                button_text = f"{emoji} {name}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"edit_cat_{cat_id}")])

        keyboard.append([InlineKeyboardButton("❌ Скасувати", callback_data="admin_categories")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
        return SELECT_CATEGORY_TO_EDIT

    async def process_category_edit_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка вибору категорії для редагування"""
        query = update.callback_query
        await query.answer()

        try:
            # Проверяем формат callback_data
            callback_parts = query.data.split('_')
            if len(callback_parts) < 3:
                await query.edit_message_text("❌ Помилка: неправильний формат даних")
                return ConversationHandler.END

            category_id = int(callback_parts[2])
            context.user_data['edit_category_id'] = category_id

            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('SELECT name, emoji FROM categories WHERE id = %s', (category_id,))
            category_info = cursor.fetchone()
            conn.close()

            if not category_info:
                await query.edit_message_text("❌ Категорія не знайдена")
                return ConversationHandler.END

            await query.edit_message_text(
                f"✏️ <b>Редагування категорії</b>\n\n"
                f"Поточна назва: {category_info['emoji']} {category_info['name']}\n\n"
                f"Введіть нову назву та емодзі через пробіл:\n"
                f"<i>Приклад: Електроніка 📱</i>\n\n"
                f"Або надішліть /cancel для скасування",
                parse_mode='HTML'
            )
            return EDIT_CATEGORY_NAME

        except (ValueError, IndexError) as e:
            await query.edit_message_text(f"❌ Помилка обробки даних: {str(e)}")
            return ConversationHandler.END
        except Exception as e:
            await query.edit_message_text(f"❌ Непередбачена помилка: {str(e)}")
            return ConversationHandler.END

    async def process_category_edit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка редагування категорії"""
        text = update.message.text.strip()
        category_id = context.user_data.get('edit_category_id')

        if not category_id:
            await update.message.reply_text("❌ Помилка: категорія не вибрана")
            return ConversationHandler.END

        if ' ' in text:
            parts = text.split(' ')
            emoji = parts[-1]
            name = ' '.join(parts[:-1])
        else:
            name = text
            emoji = '📦'

        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('UPDATE categories SET name = %s, emoji = %s WHERE id = %s',
                           (name, emoji, category_id))
            conn.commit()
            conn.close()

            await update.message.reply_text(
                f"✅ <b>Категорію оновлено!</b>\n\n"
                f"Нова назва: {emoji} {name}",
                parse_mode='HTML'
            )
        except psycopg2.IntegrityError:
            await update.message.reply_text("❌ Категорія з такою назвою вже існує!")
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка: {str(e)}")

        return ConversationHandler.END



    async def process_category_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка видалення категорії"""
        query = update.callback_query
        await query.answer()

        category_id = int(query.data.split('_')[2])

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Отримуємо інформацію про категорію
        cursor.execute('SELECT name, emoji FROM categories WHERE id = %s', (category_id,))
        category_info = cursor.fetchone()

        # Підрахунок товарів
        cursor.execute('SELECT COUNT(*) as count FROM products WHERE category_id = %s', (category_id,))
        product_count = cursor.fetchone()['count']

        # Перевіряємо чи є підкатегорії
        cursor.execute('SELECT COUNT(*) as count FROM categories WHERE parent_id = %s', (category_id,))
        subcategory_count = cursor.fetchone()['count']
        if subcategory_count > 0:
            await query.edit_message_text(
                f"❌ <b>Неможливо видалити категорію</b>\n\n"
                f"{category_info[1]} {category_info[0]}\n\n"
                f"Ця категорія має {subcategory_count} підкатегорій. Спочатку видаліть підкатегорії.",
                parse_mode='HTML'
            )
            conn.close()
            return ConversationHandler.END

        # Підтвердження видалення
        text = f"⚠️ <b>Підтвердження видалення</b>\n\n"
        text += f"Категорія: {category_info['emoji']} {category_info['name']}\n"
        text += f"Товарів буде видалено: {product_count}\n\n"
        text += f"Ви впевнені?"

        keyboard = [
            [InlineKeyboardButton("✅ Так, видалити", callback_data=f"confirm_delete_cat_{category_id}")],
            [InlineKeyboardButton("❌ Скасувати", callback_data="admin_categories")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
        conn.close()
        return SELECT_CATEGORY_TO_DELETE

    async def confirm_category_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Підтвердження видалення категорії"""
        query = update.callback_query
        await query.answer()

        category_id = int(query.data.split('_')[3])

        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Отримуємо інформацію
            cursor.execute('SELECT name, emoji FROM categories WHERE id = %s', (category_id,))
            category_info = cursor.fetchone()

            cursor.execute('SELECT COUNT(*) as count FROM products WHERE category_id = %s', (category_id,))
            product_count = cursor.fetchone()['count']

            # Видаляємо товари та категорію
            cursor.execute('DELETE FROM products WHERE category_id = %s', (category_id,))
            cursor.execute('DELETE FROM categories WHERE id = %s', (category_id,))

            conn.commit()
            conn.close()

            await query.edit_message_text(
                f"✅ <b>Категорію видалено!</b>\n\n"
                f"Видалено: {category_info['emoji']} {category_info['name']}\n"
                f"Товарів видалено: {product_count}",
                parse_mode='HTML'
            )

        except Exception as e:
            await query.edit_message_text(f"❌ Помилка при видаленні: {str(e)}")

        return ConversationHandler.END

    # ==================== УПРАВЛІННЯ ТОВАРАМИ ====================

    async def add_product_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Початок додавання товару"""
        query = update.callback_query
        await query.answer()

        await query.edit_message_text(
            "📦 <b>Додавання нового товару</b>\n\n"
            "Крок 1/5: Введіть назву товару\n\n"
            "Або надішліть /cancel для скасування",
            parse_mode='HTML'
        )
        return ADD_PRODUCT_NAME

    async def process_product_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка назви товару"""
        context.user_data['product_name'] = update.message.text.strip()

        await update.message.reply_text(
            f"✅ Назва: <b>{context.user_data['product_name']}</b>\n\n"
            "Крок 2/5: Введіть ціну товару (у гривнях)\n"
            "<i>Приклад: 1250.50</i>",
            parse_mode='HTML'
        )
        return ADD_PRODUCT_PRICE

    async def process_product_price(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка ціни товару"""
        try:
            price = float(update.message.text.strip())
            if price <= 0:
                raise ValueError("Ціна повинна бути більше нуля")

            context.user_data['product_price'] = price

            await update.message.reply_text(
                f"✅ Ціна: <b>{price:.2f} грн</b>\n\n"
                "Крок 3/5: Введіть опис товару",
                parse_mode='HTML'
            )
            return ADD_PRODUCT_DESCRIPTION
        except ValueError:
            await update.message.reply_text(
                "❌ Невірна ціна! Введіть число більше нуля.\n"
                "<i>Приклад: 1250.50</i>",
                parse_mode='HTML'
            )
            return ADD_PRODUCT_PRICE

    async def process_product_description(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка опису товару"""
        context.user_data['product_description'] = update.message.text.strip()

        await update.message.reply_text(
            f"✅ Опис збережено\n\n"
            "Крок 4/5: Надішліть фотографії товару\n"
            "Можете надісилати кілька фото по черзі.\n\n"
            "Коли закінчите, натисніть /done\n"
            "Або /skip щоб пропустити фотографії",
            parse_mode='HTML'
        )
        context.user_data['product_photos'] = []
        return ADD_PRODUCT_PHOTOS

    async def process_product_photos(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка фотографій товару"""
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            context.user_data['product_photos'].append(file_id)

            photo_count = len(context.user_data['product_photos'])
            await update.message.reply_text(
                f"📸 Фото {photo_count} збережено!\n\n"
                "Надішліть ще фото або натисніть /done для завершення"
            )
            return ADD_PRODUCT_PHOTOS
        else:
            await update.message.reply_text(
                "❌ Надішліть фотографію або /done для продовження"
            )
            return ADD_PRODUCT_PHOTOS

    async def process_product_photos_done(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Завершення додавання фотографій"""
        await update.message.reply_text(
            "Крок 5/6: Надішліть посилання на джерело товару\n"
            "(для внутрішнього використання адміністрації)\n\n"
            "Або /skip щоб пропустити"
        )
        return ADD_PRODUCT_SOURCE_LINK

    async def process_product_source_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ссылки на источник товара"""
        context.user_data['product_source_link'] = update.message.text.strip()
        return await self.show_categories_for_product(update, context)

    async def skip_source_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Пропуск ссылки на источник"""
        context.user_data['product_source_link'] = None
        return await self.show_categories_for_product(update, context)

    async def show_categories_for_product(self, update, context):
        """Показ категорий для выбора"""
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT c.id, c.name, c.emoji, pc.name as parent_name
            FROM categories c
            LEFT JOIN categories pc ON c.parent_id = pc.id
            ORDER BY c.parent_id, c.name
        ''')
        categories = cursor.fetchall()
        conn.close()

        if not categories:
            await update.message.reply_text(
                "❌ Спочатку створіть категорії в адмін панелі!"
            )
            return ConversationHandler.END

        text = "Крок 6/6: Оберіть категорію для товару:"
        keyboard = []

        for row in categories:
            cat_id = row['id']
            name = row['name']
            emoji = row['emoji']
            parent_name = row['parent_name']

            if parent_name:
                button_text = f"  ↳ {emoji} {name} (підкат. {parent_name})"
            else:
                button_text = f"{emoji} {name}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"select_cat_{cat_id}")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup)
        return ADD_PRODUCT_CATEGORY

    async def process_product_category(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Завершення створення товару"""
        query = update.callback_query
        await query.answer()

        category_id = int(query.data.split('_')[2])

        # Зберігаємо товар
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            photos_json = json.dumps(context.user_data.get('product_photos', []))

            cursor.execute('''
                INSERT INTO products (name, description, price, photos, category_id, source_link)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (
                context.user_data['product_name'],
                context.user_data['product_description'],
                context.user_data['product_price'],
                photos_json,
                category_id,
                context.user_data.get('product_source_link')
            ))

            # Отримуємо назву категорії
            cursor.execute('''
                SELECT c.name, c.emoji, pc.name as parent_name
                FROM categories c
                LEFT JOIN categories pc ON c.parent_id = pc.id
                WHERE c.id = %s
            ''', (category_id,))
            category_info = cursor.fetchone()

            conn.commit()
            conn.close()

            photo_count = len(context.user_data.get('product_photos', []))

            category_text = category_info['emoji'] + " " + category_info['name']
            if category_info['parent_name']:
                category_text = f"{category_info['parent_name']} → {category_text}"

            await query.edit_message_text(
                f"✅ <b>Товар успішно створено!</b>\n\n"
                f"📦 <b>Назва:</b> {context.user_data['product_name']}\n"
                f"💰 <b>Ціна:</b> {context.user_data['product_price']:.2f} грн\n"
                f"📂 <b>Категорія:</b> {category_text}\n"
                f"📸 <b>Фотографій:</b> {photo_count}",
                parse_mode='HTML'
            )

        except Exception as e:
            await query.edit_message_text(f"❌ Помилка при створенні товару: {str(e)}")

        # Очищуємо дані
        context.user_data.clear()
        return ConversationHandler.END

    async def edit_product_select(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Вибір товару для редагування"""
        query = update.callback_query
        await query.answer()

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT p.id, p.name, p.price, c.name, c.emoji
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            ORDER BY p.name
            LIMIT 20
        ''')
        products = cursor.fetchall()
        conn.close()

        if not products:
            await query.edit_message_text("❌ Товари відсутні")
            return ConversationHandler.END

        text = "✏️ <b>Оберіть товар для редагування:</b>"
        keyboard = []

        for row in products:
            prod_id = row['id']
            name = row['name']
            price = row['price']
            cat_name = row.get('name')  # Это будет название категории
            cat_emoji = row.get('emoji')

            category_text = f"{cat_emoji} {cat_name}" if cat_name else "Без категорії"
            button_text = f"{name} - {price:.2f}грн ({category_text})"
            keyboard.append([InlineKeyboardButton(button_text[:60] + "..." if len(button_text) > 60 else button_text,
                                                  callback_data=f"edit_prod_{prod_id}")])

        keyboard.append([InlineKeyboardButton("❌ Скасувати", callback_data="admin_products")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
        return SELECT_PRODUCT_TO_EDIT


    async def edit_product_name_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Початок редагування назви товару"""
        query = update.callback_query
        await query.answer()

        product_id = context.user_data.get('edit_product_id')
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT name FROM products WHERE id = %s', (product_id,))
        current_name = cursor.fetchone()['name']
        conn.close()

        await query.edit_message_text(
            f"📝 <b>Редагування назви товару</b>\n\n"
            f"Поточна назва: <b>{current_name}</b>\n\n"
            f"Введіть нову назву:",
            parse_mode='HTML'
        )
        return EDIT_PRODUCT_NAME

    async def process_product_name_edit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка нової назви товару"""
        new_name = update.message.text.strip()
        product_id = context.user_data.get('edit_product_id')

        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('UPDATE products SET name = %s WHERE id = %s', (new_name, product_id))
            conn.commit()
            conn.close()

            await update.message.reply_text(
                f"✅ <b>Назву товару оновлено!</b>\n\n"
                f"Нова назва: <b>{new_name}</b>",
                parse_mode='HTML'
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка: {str(e)}")

        return ConversationHandler.END

    async def edit_product_price_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Початок редагування ціни товару"""
        query = update.callback_query
        await query.answer()

        product_id = context.user_data.get('edit_product_id')
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT name, price FROM products WHERE id = %s', (product_id,))
        product_info = cursor.fetchone()
        conn.close()

        await query.edit_message_text(
            f"💰 <b>Редагування ціни товару</b>\n\n"
            f"Товар: <b>{product_info['name']}</b>\n"
            f"Поточна ціна: <b>{product_info['price']:.2f} грн</b>\n\n"
            f"Введіть нову ціну:",
            parse_mode='HTML'
        )
        return EDIT_PRODUCT_PRICE

    async def process_product_price_edit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка нової ціни товару"""
        try:
            new_price = float(update.message.text.strip())
            if new_price <= 0:
                raise ValueError("Ціна повинна бути більше нуля")

            product_id = context.user_data.get('edit_product_id')

            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('UPDATE products SET price = %s WHERE id = %s', (new_price, product_id))
            conn.commit()
            conn.close()

            await update.message.reply_text(
                f"✅ <b>Ціну товару оновлено!</b>\n\n"
                f"Нова ціна: <b>{new_price:.2f} грн</b>",
                parse_mode='HTML'
            )
        except ValueError:
            await update.message.reply_text(
                "❌ Невірна ціна! Введіть число більше нуля.\n"
                "<i>Приклад: 1250.50</i>",
                parse_mode='HTML'
            )
            return EDIT_PRODUCT_PRICE
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка: {str(e)}")

        return ConversationHandler.END

    async def edit_product_description_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Початок редагування опису товару"""
        query = update.callback_query
        await query.answer()

        product_id = context.user_data.get('edit_product_id')
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT name, description FROM products WHERE id = %s', (product_id,))
        product_info = cursor.fetchone()
        conn.close()

        await query.edit_message_text(
            f"📄 <b>Редагування опису товару</b>\n\n"
            f"Товар: <b>{product_info['name']}</b>\n\n"
            f"Поточний опис: <i>{product_info['description'] or 'Відсутній'}</i>\n\n"
            f"Введіть новий опис:",
            parse_mode='HTML'
        )
        return EDIT_PRODUCT_DESCRIPTION

    async def process_product_description_edit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка нового опису товару"""
        new_description = update.message.text.strip()
        product_id = context.user_data.get('edit_product_id')

        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('UPDATE products SET description = %s WHERE id = %s', (new_description, product_id))
            conn.commit()
            conn.close()

            await update.message.reply_text(
                f"✅ <b>Опис товару оновлено!</b>\n\n"
                f"Новий опис: <i>{new_description}</i>",
                parse_mode='HTML'
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка: {str(e)}")

        return ConversationHandler.END

    async def delete_product_select(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Вибір товару для видалення"""
        query = update.callback_query
        await query.answer()

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT p.id, p.name, p.price, c.name, c.emoji
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            ORDER BY p.name
            LIMIT 20
        ''')
        products = cursor.fetchall()
        conn.close()

        if not products:
            await query.edit_message_text("❌ Товари відсутні")
            return ConversationHandler.END

        text = "🗑️ <b>Оберіть товар для видалення:</b>"
        keyboard = []

        for row in products:
            prod_id = row['id']
            name = row['name']
            price = row['price']
            cat_name = row.get('name')
            cat_emoji = row.get('emoji')

            category_text = f"{cat_emoji} {cat_name}" if cat_name else "Без категорії"
            button_text = f"{name} - {price:.2f}грн ({category_text})"
            keyboard.append([InlineKeyboardButton(button_text[:60] + "..." if len(button_text) > 60 else button_text,
                                                  callback_data=f"delete_prod_{prod_id}")])

        keyboard.append([InlineKeyboardButton("❌ Скасувати", callback_data="admin_products")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
        return SELECT_PRODUCT_TO_DELETE

    async def process_product_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка видалення товару"""
        query = update.callback_query
        await query.answer()

        product_id = int(query.data.split('_')[2])

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT name, price FROM products WHERE id = %s', (product_id,))
        product_info = cursor.fetchone()
        conn.close()

        # Підтвердження видалення
        text = f"⚠️ <b>Підтвердження видалення</b>\n\n"
        text += f"Товар: <b>{product_info['name']}</b>\n"
        text += f"Ціна: {product_info['price']:.2f} грн\n\n"
        text += f"Ви впевнені що хочете видалити цей товар?"

        keyboard = [
            [InlineKeyboardButton("✅ Так, видалити", callback_data=f"confirm_delete_prod_{product_id}")],
            [InlineKeyboardButton("❌ Скасувати", callback_data="admin_products")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
        return SELECT_PRODUCT_TO_DELETE

    async def confirm_product_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Підтвердження видалення товару"""
        query = update.callback_query
        await query.answer()

        product_id = int(query.data.split('_')[3])

        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('SELECT name FROM products WHERE id = %s', (product_id,))
            product_name = cursor.fetchone()['name']

            cursor.execute('DELETE FROM products WHERE id = %s', (product_id,))
            conn.commit()
            conn.close()

            await query.edit_message_text(
                f"✅ <b>Товар видалено!</b>\n\n"
                f"Видалено: <b>{product_name}</b>",
                parse_mode='HTML'
            )
        except Exception as e:
            await query.edit_message_text(f"❌ Помилка при видаленні: {str(e)}")

        return ConversationHandler.END

    async def view_all_products(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Перегляд всіх товарів для адміна"""
        query = update.callback_query
        await query.answer()

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT p.id, p.name, p.price, p.is_available, c.name as cat_name, c.emoji as cat_emoji
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            ORDER BY c.name, p.name
        ''')
        products = cursor.fetchall()
        conn.close()

        if not products:
            text = "❌ <b>Товари відсутні</b>"
        else:
            text = f"📋 <b>Всі товари ({len(products)})</b>\n\n"
            current_category = None

            for row in products:
                prod_id = row['id']
                name = row['name']
                price = row['price']
                is_available = row['is_available']
                cat_name = row['cat_name']
                cat_emoji = row['cat_emoji']

                category_text = f"{cat_emoji} {cat_name}" if cat_name else "🚫 Без категорії"
                if category_text != current_category:
                    text += f"\n<b>{category_text}:</b>\n"
                    current_category = category_text

                status = "✅" if is_available else "❌"
                text += f"  {status} {name} - {price:.2f} грн\n"

        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_products")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)

    # ==================== СТАТИСТИКА ====================

    async def admin_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Статистика магазину"""
        query = update.callback_query
        await query.answer()

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Загальна статистика
        cursor.execute('SELECT COUNT(*) as count FROM categories WHERE parent_id IS NULL')
        main_categories_count = cursor.fetchone()['count']

        cursor.execute('SELECT COUNT(*) as count FROM categories WHERE parent_id IS NOT NULL')
        subcategories_count = cursor.fetchone()['count']

        cursor.execute('SELECT COUNT(*) as count FROM products WHERE is_available = TRUE')
        products_count = cursor.fetchone()['count']

        cursor.execute('SELECT COUNT(*) as count FROM products WHERE is_available = FALSE')
        unavailable_count = cursor.fetchone()['count']

        cursor.execute('SELECT COUNT(*) as count FROM admins')
        admins_count = cursor.fetchone()['count']

        # Топ категорії
        cursor.execute('''
            SELECT c.name, c.emoji, COUNT(p.id) as product_count
            FROM categories c
            LEFT JOIN products p ON c.id = p.category_id AND p.is_available = TRUE
            GROUP BY c.id, c.name, c.emoji
            ORDER BY product_count DESC
            LIMIT 5
        ''')
        top_categories = cursor.fetchall()

        # Середня ціна
        cursor.execute('SELECT AVG(price) as avg_price FROM products WHERE is_available = TRUE')
        avg_price = cursor.fetchone()['avg_price'] or 0

        conn.close()

        text = f"""
    📊 <b>Статистика магазину</b>

    📈 <b>Загальні показники:</b>
    📂 Головних категорій: {main_categories_count}
    📁 Підкатегорій: {subcategories_count}
    📦 Доступних товарів: {products_count}
    ❌ Недоступних товарів: {unavailable_count}
    👥 Адмінів: {admins_count}
    💰 Середня ціна: {avg_price:.2f} грн

    🏆 <b>Топ категорії:</b>
    """

        for row in top_categories:
            name = row['name']
            emoji = row['emoji']
            count = row['product_count']
            text += f"{emoji} {name}: {count} товарів\n"

        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)


    async def admin_users_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню управления админами"""
        query = update.callback_query
        await query.answer()

        # Получаем список админов
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT user_id, username FROM admins ORDER BY added_at')
        admins = cursor.fetchall()
        conn.close()

        text = "👥 <b>Управління адмінами</b>\n\n"
        text += f"Поточні адміни ({len(admins)}):\n"

        for user_id, username in admins:
            text += f"• {user_id} (@{username or 'немає username'})\n"

        keyboard = [
            [InlineKeyboardButton("➕ Додати адміна", callback_data="add_admin")],
            [InlineKeyboardButton("🗑️ Видалити адміна", callback_data="delete_admin_menu")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
        return ADMIN_USERS_MENU

    # ==================== ДОПОМІЖНІ ФУНКЦІЇ ====================

    async def cancel_operation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Скасування операції"""
        await update.message.reply_text("❌ Операцію скасовано")
        context.user_data.clear()
        return ConversationHandler.END

    async def skip_photos(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Пропуск фотографій"""
        context.user_data['product_photos'] = []
        return await self.process_product_photos_done(update, context)

    async def admin_back(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Повернення до адмін панелі"""
        query = update.callback_query
        await query.answer()

        text = """
🔧 <b>Адміністративна панель</b>

Оберіть дію:
        """

        keyboard = [
            [InlineKeyboardButton("📂 Управління категоріями", callback_data="admin_categories")],
            [InlineKeyboardButton("📦 Управління товарами", callback_data="admin_products")],
            [InlineKeyboardButton("👥 Управління адмінами", callback_data="admin_users")],
            [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton("❌ Вийти з панелі", callback_data="exit_admin")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)

    async def exit_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Вихід з адмін панелі"""
        query = update.callback_query
        await query.answer()

        await query.edit_message_text(
            "👋 <b>Ви вийшли з адміністративної панелі</b>\n\n"
            "Для входу знову використайте /admin",
            parse_mode='HTML'
        )

    async def edit_product_photos_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        product_id = context.user_data.get('edit_product_id')
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT name, photos FROM products WHERE id = %s', (product_id,))
        product_info = cursor.fetchone()
        conn.close()

        try:
            photos = json.loads(product_info['photos']) if product_info['photos'] else []
        except:
            photos = []

        await query.edit_message_text(
            f"📸 <b>Редагування фотографій товару</b>\n\n"
            f"Товар: <b>{product_info['name']}</b>\n"
            f"Поточна кількість фото: {len(photos)}\n\n"
            f"Надішліть нові фотографії товару.\n"
            f"Коли закінчите, натисніть /done\n"
            f"Або /cancel для скасування",
            parse_mode='HTML'
        )

        context.user_data['new_product_photos'] = []
        return EDIT_PRODUCT_PHOTOS

    async def process_product_photos_edit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка новых фотографий товара"""
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            context.user_data['new_product_photos'].append(file_id)

            photo_count = len(context.user_data['new_product_photos'])
            await update.message.reply_text(
                f"📸 Фото {photo_count} збережено!\n\n"
                "Надішліть ще фото або натисніть /done для завершення"
            )
            return EDIT_PRODUCT_PHOTOS
        else:
            await update.message.reply_text(
                "❌ Надішліть фотографію або /done для продовження"
            )
            return EDIT_PRODUCT_PHOTOS

    async def process_product_photos_edit_done(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Завершение редактирования фотографий"""
        new_photos = context.user_data.get('new_product_photos', [])
        product_id = context.user_data.get('edit_product_id')

        if not new_photos:
            await update.message.reply_text("❌ Не було додано жодного фото. Операцію скасовано.")
            return ConversationHandler.END

        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            photos_json = json.dumps(new_photos)
            cursor.execute('UPDATE products SET photos = %s WHERE id = %s', (photos_json, product_id))

            conn.commit()
            conn.close()

            await update.message.reply_text(
                f"✅ <b>Фотографії товару оновлено!</b>\n\n"
                f"Додано фотографій: {len(new_photos)}",
                parse_mode='HTML'
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка: {str(e)}")

        return ConversationHandler.END

    async def admin_users_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню управления админами"""
        query = update.callback_query
        await query.answer()

        # Получаем список админов
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT user_id, username FROM admins ORDER BY added_at')
        admins = cursor.fetchall()
        conn.close()

        text = "👥 <b>Управління адмінами</b>\n\n"
        text += f"Поточні адміни ({len(admins)}):\n"

        for user_id, username in admins:
            text += f"• {user_id} (@{username or 'немає username'})\n"

        keyboard = [
            [InlineKeyboardButton("➕ Додати адміна", callback_data="add_admin")],
            [InlineKeyboardButton("🗑️ Видалити адміна", callback_data="delete_admin_menu")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
        return ADMIN_USERS_MENU

    async def add_admin_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало добавления админа"""
        query = update.callback_query
        await query.answer()

        text = "➕ <b>Додавання нового адміна</b>\n\n"
        text += "Надішліть ID користувача якого хочете зробити адміном.\n"
        text += "ID можна дізнатися через @userinfobot\n\n"
        text += "Або надішліть /cancel для скасування"

        await query.edit_message_text(text, parse_mode='HTML')
        return ADD_ADMIN_ID

    async def process_add_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка добавления админа"""
        try:
            new_admin_id = int(update.message.text.strip())

            # Проверяем, не является ли уже админом
            if new_admin_id in self.admin_ids:
                await update.message.reply_text("❌ Цей користувач вже є адміном!")
                return ADD_ADMIN_ID

            # Получаем info о пользователе
            try:
                chat_member = await context.bot.get_chat_member(new_admin_id, new_admin_id)
                username = chat_member.user.username
                full_name = chat_member.user.full_name
            except:
                username = None
                full_name = "Невідомий користувач"

            # Добавляем в базу
            self.add_admin(new_admin_id, username)

            await update.message.reply_text(
                f"✅ <b>Адміна додано!</b>\n\n"
                f"ID: {new_admin_id}\n"
                f"Ім'я: {full_name}\n"
                f"Username: @{username or 'немає'}",
                parse_mode='HTML'
            )

            return ConversationHandler.END

        except ValueError:
            await update.message.reply_text(
                "❌ Невірний формат ID. Введіть числовий ID користувача."
            )
            return ADD_ADMIN_ID
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка: {str(e)}")
            return ConversationHandler.END


    async def edit_product_category_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        product_id = context.user_data.get('edit_product_id')
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Получаем информацию о товаре
        cursor.execute('''
            SELECT p.name, c.name as cat_name, c.emoji as cat_emoji, pc.name as parent_name
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            LEFT JOIN categories pc ON c.parent_id = pc.id
            WHERE p.id = %s
        ''', (product_id,))
        product_info = cursor.fetchone()

        # Получаем все категории
        cursor.execute('''
            SELECT c.id, c.name, c.emoji, pc.name as parent_name
            FROM categories c
            LEFT JOIN categories pc ON c.parent_id = pc.id
            ORDER BY c.parent_id, c.name
        ''')
        categories = cursor.fetchall()
        conn.close()

        current_category = ""
        if product_info['cat_name']:
            if product_info['parent_name']:
                current_category = f"{product_info['parent_name']} → {product_info['cat_emoji']} {product_info['cat_name']}"
            else:
                current_category = f"{product_info['cat_emoji']} {product_info['cat_name']}"
        else:
            current_category = "Без категорії"

        text = f"📂 <b>Редагування категорії товару</b>\n\n"
        text += f"Товар: <b>{product_info['name']}</b>\n"
        text += f"Поточна категорія: {current_category}\n\n"
        text += "Оберіть нову категорію:"

        keyboard = []
        for row in categories:  # ИСПРАВЛЕНО: используем row вместо распаковки
            cat_id = row['id']
            name = row['name']
            emoji = row['emoji']
            parent_name = row['parent_name']

            if parent_name:
                button_text = f"  ↳ {emoji} {name}"
            else:
                button_text = f"{emoji} {name}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"new_cat_{cat_id}")])

        keyboard.append([InlineKeyboardButton("❌ Скасувати", callback_data="admin_products")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
        return EDIT_PRODUCT_CATEGORY

    async def process_product_category_edit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка изменения категории товара"""
        query = update.callback_query
        await query.answer()

        new_category_id = int(query.data.split('_')[2])
        product_id = context.user_data.get('edit_product_id')

        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Обновляем категорию товара
            cursor.execute('UPDATE products SET category_id = %s WHERE id = %s', (new_category_id, product_id))

            # Получаем информацию о новой категории
            cursor.execute('''
                SELECT c.name, c.emoji, pc.name as parent_name
                FROM categories c
                LEFT JOIN categories pc ON c.parent_id = pc.id
                WHERE c.id = %s
            ''', (new_category_id,))
            category_info = cursor.fetchone()

            conn.commit()
            conn.close()

            category_text = f"{category_info['emoji']} {category_info['name']}"
            if category_info['parent_name']:
                category_text = f"{category_info['parent_name']} → {category_text}"

            await query.edit_message_text(
                f"✅ <b>Категорію товару оновлено!</b>\n\n"
                f"Нова категорія: {category_text}",
                parse_mode='HTML'
            )
        except Exception as e:
            await query.edit_message_text(f"❌ Помилка: {str(e)}")

        return ConversationHandler.END

    # ==================== ЗАПУСК БОТА ====================

    def run(self):
        """Запуск бота"""
        application = Application.builder().token(self.token).build()

        preorder_conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.preorder_start, pattern="^preorder$")],
            states={
                PREORDER_INFO: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_preorder_info),
                    CallbackQueryHandler(self.skip_preorder_info, pattern="^skip_preorder_info$"),
                    CallbackQueryHandler(self.cancel_preorder, pattern="^cancel_preorder$"),
                ],
                PREORDER_PHOTO: [
                    MessageHandler(filters.PHOTO, self.process_preorder_photo),
                    CallbackQueryHandler(self.skip_preorder_photo, pattern="^skip_preorder_photo$"),
                    CallbackQueryHandler(self.cancel_preorder, pattern="^cancel_preorder$"),
                ],
                PREORDER_LINK: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_preorder_link),
                    CallbackQueryHandler(self.skip_preorder_link, pattern="^skip_preorder_link$"),
                    CallbackQueryHandler(self.cancel_preorder, pattern="^cancel_preorder$"),
                ],
                PREORDER_MODEL: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_preorder_model),
                    CallbackQueryHandler(self.skip_preorder_model, pattern="^skip_preorder_model$"),
                    CallbackQueryHandler(self.cancel_preorder, pattern="^cancel_preorder$"),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", self.cancel_preorder),
                CallbackQueryHandler(self.cancel_preorder, pattern="^cancel_preorder$"),
            ],
        )

        # ConversationHandler для контакту з продавцем
        contact_conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.contact_seller, pattern="^contact_seller_")],
            states={
                CONTACT_MESSAGE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_contact_message),
                    CallbackQueryHandler(self.cancel_contact, pattern="^cancel_contact$"),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", self.cancel_contact),
                CallbackQueryHandler(self.cancel_contact, pattern="^cancel_contact$"),
            ],
        )

        admin_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("admin", self.admin_panel)],
            states={
                ADMIN_MENU: [
                    CallbackQueryHandler(self.admin_users_menu, pattern="^admin_users$"
                                                                        ""),
                    CallbackQueryHandler(self.mark_all_read, pattern="^mark_all_read$"),
                    CallbackQueryHandler(self.all_messages, pattern="^all_messages$"),
                    CallbackQueryHandler(self.delete_message, pattern="^delete_msg_"),
                    CallbackQueryHandler(self.delete_all_messages, pattern="^delete_all_messages$"),
                    CallbackQueryHandler(self.confirm_delete_all_messages, pattern="^confirm_delete_all$"),
                    CallbackQueryHandler(self.admin_categories_menu, pattern="^admin_categories$"),
                    CallbackQueryHandler(self.admin_products_menu, pattern="^admin_products$"),
                    CallbackQueryHandler(self.admin_stats, pattern="^admin_stats$"),
                    CallbackQueryHandler(self.admin_back, pattern="^admin_back$"),
                    CallbackQueryHandler(self.exit_admin, pattern="^exit_admin$"),
                    CallbackQueryHandler(self.admin_messages, pattern="^admin_messages$"),

                ],

                # Категорії
                ADD_CATEGORY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_add_category),
                    CommandHandler("cancel", self.cancel_operation),
                ],
                SELECT_PARENT_CATEGORY: [
                    CallbackQueryHandler(self.process_parent_category_selection, pattern="^parent_cat_"),
                    CallbackQueryHandler(self.admin_categories_menu, pattern="^admin_categories$"),
                ],
                ADD_SUBCATEGORY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_add_subcategory),
                    CommandHandler("cancel", self.cancel_operation),
                ],
                SELECT_CATEGORY_TO_EDIT: [
                    CallbackQueryHandler(self.process_category_edit_selection, pattern="^edit_cat_"),
                    CallbackQueryHandler(self.admin_categories_menu, pattern="^admin_categories$"),
                ],
                EDIT_CATEGORY_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_category_edit),
                    CommandHandler("cancel", self.cancel_operation),
                ],
                SELECT_CATEGORY_TO_DELETE: [
                    CallbackQueryHandler(self.process_category_delete, pattern="^delete_cat_"),
                    CallbackQueryHandler(self.confirm_category_delete, pattern="^confirm_delete_cat_"),
                    CallbackQueryHandler(self.admin_categories_menu, pattern="^admin_categories$"),
                ],

                # Товари
                ADD_PRODUCT_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_product_name),
                    CommandHandler("cancel", self.cancel_operation),
                ],
                ADD_PRODUCT_PRICE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_product_price),
                    CommandHandler("cancel", self.cancel_operation),
                ],
                ADD_PRODUCT_DESCRIPTION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_product_description),
                    CommandHandler("cancel", self.cancel_operation),
                ],
                ADD_PRODUCT_PHOTOS: [
                    MessageHandler(filters.PHOTO, self.process_product_photos),
                    CommandHandler("done", self.process_product_photos_done),
                    CommandHandler("skip", self.skip_photos),
                    CommandHandler("cancel", self.cancel_operation),
                    CommandHandler("skip", self.skip_source_link),
                ],
                ADD_PRODUCT_CATEGORY: [
                    CallbackQueryHandler(self.process_product_category, pattern="^select_cat_"),
                    CommandHandler("cancel", self.cancel_operation),
                ],
                ADD_PRODUCT_SOURCE_LINK: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_product_source_link),
                    CommandHandler("skip", self.skip_source_link),
                    CommandHandler("cancel", self.cancel_operation),
                ],
                SELECT_PRODUCT_TO_EDIT: [
                    CallbackQueryHandler(self.process_product_edit_selection, pattern="^edit_prod_"),
                    CallbackQueryHandler(self.admin_products_menu, pattern="^admin_products$"),
                ],
                EDIT_PRODUCT_FIELD: [
                    CallbackQueryHandler(self.edit_product_name_start, pattern="^edit_product_name$"),
                    CallbackQueryHandler(self.edit_product_price_start, pattern="^edit_product_price$"),
                    CallbackQueryHandler(self.edit_product_description_start, pattern="^edit_product_description$"),
                    CallbackQueryHandler(self.admin_products_menu, pattern="^admin_products$"),
                    CallbackQueryHandler(self.edit_product_photos_start, pattern="^edit_product_photos$"),
                    CallbackQueryHandler(self.edit_product_category_start, pattern="^edit_product_category$"),
                ],
                EDIT_PRODUCT_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_product_name_edit),
                    CommandHandler("cancel", self.cancel_operation),
                ],
                EDIT_PRODUCT_PRICE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_product_price_edit),
                    CommandHandler("cancel", self.cancel_operation),
                ],
                EDIT_PRODUCT_DESCRIPTION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_product_description_edit),
                    CommandHandler("cancel", self.cancel_operation),
                ],
                EDIT_PRODUCT_PHOTOS: [
                    MessageHandler(filters.PHOTO, self.process_product_photos_edit),
                    CommandHandler("done", self.process_product_photos_edit_done),
                    CommandHandler("cancel", self.cancel_operation),
                ],
                EDIT_PRODUCT_CATEGORY: [
                    CallbackQueryHandler(self.process_product_category_edit, pattern="^new_cat_"),
                    CallbackQueryHandler(self.admin_products_menu, pattern="^admin_products$"),
                ],
                SELECT_PRODUCT_TO_DELETE: [
                    CallbackQueryHandler(self.process_product_delete, pattern="^delete_prod_"),
                    CallbackQueryHandler(self.confirm_product_delete, pattern="^confirm_delete_prod_"),
                    CallbackQueryHandler(self.admin_products_menu, pattern="^admin_products$"),
                ],

                ADMIN_USERS_MENU: [
                    CallbackQueryHandler(self.add_admin_start, pattern="^add_admin$"),
                    CallbackQueryHandler(self.delete_admin_menu, pattern="^delete_admin_menu$"),

                    CallbackQueryHandler(self.admin_back, pattern="^admin_back$"),
                ],
                ADD_ADMIN_ID: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_add_admin),
                    CommandHandler("cancel", self.cancel_operation),
                ],
                DELETE_ADMIN_SELECT: [
                    CallbackQueryHandler(self.process_delete_admin, pattern="^delete_admin_"),
                    CallbackQueryHandler(self.admin_users_menu, pattern="^admin_users$"),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", self.cancel_operation),
                CallbackQueryHandler(self.add_category_start, pattern="^add_category$"),
                CallbackQueryHandler(self.add_subcategory_start, pattern="^add_subcategory$"),
                CallbackQueryHandler(self.edit_category_select, pattern="^edit_category_select$"),
                CallbackQueryHandler(self.delete_category_select, pattern="^delete_category_select$"),
                CallbackQueryHandler(self.add_product_start, pattern="^add_product$"),
                CallbackQueryHandler(self.edit_product_select, pattern="^edit_product_select$"),
                CallbackQueryHandler(self.delete_product_select, pattern="^delete_product_select$"),
                CallbackQueryHandler(self.view_all_products, pattern="^view_all_products$"),
            ],
        )

        # Хендлери для користувачів
        application.add_handler(CallbackQueryHandler(self.show_all_products_in_category, pattern="^all_in_category_"))
        application.add_handler(
            CallbackQueryHandler(self.show_all_subcategories_products, pattern="^all_subcategories_"))
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CallbackQueryHandler(self.start, pattern="^start$"))
        application.add_handler(CallbackQueryHandler(self.show_categories, pattern="^show_categories$"))
        application.add_handler(CallbackQueryHandler(self.show_products_in_category, pattern="^category_"))
        application.add_handler(CallbackQueryHandler(self.show_products_in_category, pattern="^products_"))
        application.add_handler(CallbackQueryHandler(self.show_all_products_user, pattern="^show_all_products_user$"))
        application.add_handler(CallbackQueryHandler(self.about, pattern="^about$"))
        application.add_handler(preorder_conv_handler)
        application.add_handler(CallbackQueryHandler(self.browse_one_by_one, pattern="^browse_one_"))



        # Хендлери для адміна
        application.add_handler(admin_conv_handler)
        application.add_handler(contact_conv_handler)

        if os.getenv('RAILWAY_ENVIRONMENT') != 'production':
            print("🤖 Бот запущено локально")
            application.run_polling()
        else:
            # Для Railway
            PORT = int(os.environ.get('PORT', 8080))
            APP_NAME = os.environ.get('RAILWAY_PUBLIC_DOMAIN')

            if APP_NAME:
                webhook_url = f"https://{APP_NAME}/{self.token}"
                print(f"🚀 Бот запущено на Railway: {webhook_url}")

                application.run_webhook(
                    listen="0.0.0.0",
                    port=PORT,
                    url_path=self.token,
                    webhook_url=webhook_url
                )
            else:
                # Fallback для локального тестирования
                application.run_polling()

# ==================== ОСНОВНИЙ ФАЙЛ ДЛЯ ЗАПУСКУ ====================

if __name__ == '__main__':
    load_dotenv()  # Загружаем переменные из .env файла

    BOT_TOKEN = os.getenv('BOT_TOKEN')
    ADMIN_ID = int(os.getenv('ADMIN_ID'))


    shop_bot = ShopBot(BOT_TOKEN)
    shop_bot.add_admin(ADMIN_ID, "your_username")

    try:
        shop_bot.run()
    except KeyboardInterrupt:
        print("\n👋 Бот зупинено")

