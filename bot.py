import telebot
import os
from dotenv import load_dotenv
import requests
import json
from telebot import types
from loguru import logger

load_dotenv()
TOKEN = os.getenv('TELEGRAM_TOKEN')
bot = telebot.TeleBot(TOKEN)

FAV_FILE = 'favorites.json'  # файл для хранения избранного и рейтингов

logger.add('bot.log', rotation='1 MB') # Лог файл

# Вспомогательные функции для избранного

def load_favs():
    try:
        with open(FAV_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def save_favs(data):
    with open(FAV_FILE, 'w') as f:
        json.dump(data, f)

searching_users = set()

@bot.message_handler(func=lambda message: message.text and message.text.lower() == 'привет')
def greet_user(message):
    bot.reply_to(message, 'Привет')

@bot.message_handler(commands=['start'])
def start(message):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton('🔎 Поиск рецепта'), types.KeyboardButton('⭐ Избранное'))
    bot.send_message(message.chat.id, 'Добро пожаловать! Выберите действие:', reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == '🔎 Поиск рецепта')
def ask_for_recipe(message):
    searching_users.add(message.from_user.id)
    bot.send_message(message.chat.id, 'Введите название блюда, например: pasta')

@bot.message_handler(func=lambda message: message.from_user.id in searching_users and message.text)
def get_search_text(message):
    searching_users.discard(message.from_user.id)
    title = message.text.strip()
    if not title:
        bot.reply_to(message, 'Название блюда не может быть пустым')
        return
    try:
        url = f'https://www.themealdb.com/api/json/v1/1/search.php?s={title}'
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        meals = data.get('meals')
        if not meals:
            bot.reply_to(message, 'Ничего не найдено')
            return
        meals = meals[:5] # максимум 5 результатов
        for meal in meals:
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton('Подробнее', callback_data=f"desc_{meal['idMeal']}"))
            caption = meal['strMeal'][:1024]
            bot.send_photo(message.chat.id, meal['strMealThumb'], caption=caption, reply_markup=kb)
        logger.info(f"Пользователь {message.from_user.id} ищет '{title}', найдено {len(meals)} вариантов.")
    except Exception as e:
        logger.exception(e)
        bot.reply_to(message, 'Ошибка поиска рецепта. Попробуйте позже.')

@bot.callback_query_handler(func=lambda call: call.data.startswith('desc_'))
def show_meal_details(call):
    meal_id = call.data.split('_')[1]
    meal = get_meal_by_id(meal_id)
    if meal:
        send_meal(call.message.chat.id, meal)
        bot.answer_callback_query(call.id)
    else:
        bot.answer_callback_query(call.id, 'Ошибка при получении рецепта!')

@bot.message_handler(func=lambda m: m.text == '⭐ Избранное')
def fav_button(message):
    show_favs(message)

# Поиск рецепта
@bot.message_handler(commands=['найти'])
def find_recipe(message):
    try:
        title = message.text.partition(' ')[2]
        if not title:
            bot.reply_to(message, 'Напиши название блюда после /найти')
            return
        url = f'https://www.themealdb.com/api/json/v1/1/search.php?s={title}'
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        meals = data.get('meals')
        if not meals:
            bot.reply_to(message, 'Ничего не найдено')
            return
        for meal in meals[:5]:  # Показываем максимум 5 результатов
            send_meal(message.chat.id, meal)
        send_meal(message.chat.id, meal)
        logger.info(f"Пользователь {message.from_user.id} ищет '{title}', найдено {meal['strMeal']}")
    except Exception as e:
        logger.exception(e)
        bot.reply_to(message, 'Ошибка поиска рецепта. Попробуйте позже.')

# Отправка рецепта, фотографии, видео

def send_meal(chat_id, meal):
    try:
        caption = f"<b>{meal['strMeal']}</b>"
        # Комментарий: отправляем длинную инструкцию отдельным сообщением, чтобы не возникало ошибки
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton('🌟 В избранное', callback_data=f"fav_{meal['idMeal']}"))
        bot.send_photo(chat_id, meal['strMealThumb'], caption=caption[:1024], parse_mode='HTML', reply_markup=kb)
        if meal.get('strInstructions'):
            bot.send_message(chat_id, meal['strInstructions'])
        if meal.get('strYoutube'):
            bot.send_message(chat_id, f"Видео: {meal['strYoutube']}")
        rate_kb = types.InlineKeyboardMarkup(row_width=5)
        rate_kb.add(*[types.InlineKeyboardButton(f'{i} ⭐', callback_data=f"rate_{meal['idMeal']}_{i}") for i in range(1,6)])
        bot.send_message(chat_id, 'Поставьте оценку рецепту:', reply_markup=rate_kb)
    except Exception as e:
        logger.exception(e)
        bot.send_message(chat_id, 'Ошибка при показе рецепта.')

def send_menu(chat_id):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton('🔎 Поиск рецепта'), types.KeyboardButton('⭐ Избранное'))
    bot.send_message(chat_id, 'Меню:', reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith('fav_'))
def add_fav(call):
    try:
        meal_id = call.data.split('_')[1]
        user_id = str(call.from_user.id)
        favs = load_favs()
        user_favs = favs.get(user_id, {})
        if meal_id not in user_favs:
            user_favs[meal_id] = {'rating': 0}
            favs[user_id] = user_favs
            save_favs(favs)
        logger.info(f"Пользователь {user_id} добавил {meal_id} в избранное")
        bot.answer_callback_query(call.id, 'Добавлено в избранное!')
        send_menu(call.message.chat.id)
    except Exception as e:
        logger.exception(e)
        bot.answer_callback_query(call.id, 'Ошибка добавления в избранное')
        send_menu(call.message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('rate_'))
def rate_meal(call):
    try:
        _, meal_id, stars = call.data.split('_')
        user_id = str(call.from_user.id)
        favs = load_favs()
        user_favs = favs.get(user_id, {})
        if meal_id in user_favs:
            user_favs[meal_id]['rating'] = int(stars)
            bot.answer_callback_query(call.id, f'Ваша оценка: {stars} ⭐')
        else:
            user_favs[meal_id] = {'rating': int(stars)}
            bot.answer_callback_query(call.id, 'Добавлено в избранное и оценено!')
        favs[user_id] = user_favs
        save_favs(favs)
        logger.info(f"Пользователь {user_id} поставил {stars}⭐ рецепту {meal_id}")
        send_menu(call.message.chat.id)
    except Exception as e:
        logger.exception(e)
        bot.answer_callback_query(call.id, 'Ошибка при выставлении оценки')
        send_menu(call.message.chat.id)

# Показать избранное
@bot.message_handler(commands=['избранное'])
def show_favs(message):
    try:
        user_id = str(message.from_user.id)
        favs = load_favs()
        user_favs = favs.get(user_id, {})
        if not user_favs:
            bot.send_message(message.chat.id, 'У вас нет избранных рецептов.')
            return
        favs_sorted = sorted(user_favs.items(), key=lambda x: x[1]['rating'], reverse=True)
        kb = types.InlineKeyboardMarkup()
        for meal_id, data in favs_sorted:
            meal = get_meal_by_id(meal_id)
            if not meal:
                continue
            btn_text = f"{meal['strMeal']} — {data['rating']} ⭐"
            kb.add(types.InlineKeyboardButton(btn_text, callback_data=f"favshow_{meal_id}"))
        bot.send_message(message.chat.id, 'Ваши избранные рецепты:', reply_markup=kb)
        logger.info(f"Пользователь {user_id} запросил избранное")
    except Exception as e:
        logger.exception(e)
        bot.send_message(message.chat.id, 'Ошибка показа избранных рецептов')

@bot.callback_query_handler(func=lambda call: call.data.startswith('favshow_'))
def show_fav_details(call):
    meal_id = call.data.split('_')[1]
    meal = get_meal_by_id(meal_id)
    if meal:
        send_meal(call.message.chat.id, meal)
        bot.answer_callback_query(call.id)
    else:
        bot.answer_callback_query(call.id, 'Ошибка при получении рецепта!')

def get_meal_by_id(meal_id):
    try:
        resp = requests.get(f'https://www.themealdb.com/api/json/v1/1/lookup.php?i={meal_id}', timeout=10)
        resp.raise_for_status()
        meals = resp.json().get('meals')
        return meals[0] if meals else None
    except Exception as e:
        logger.error(f'Ошибка получения рецепта {meal_id}: {e}')
        return None

if __name__ == '__main__':
    print('Бот запущен...')
    bot.infinity_polling()
