import asyncio
import html
import json
import logging
import os
from typing import Optional

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "7692664960").split(",") if x.strip().isdigit()}
DB_PATH = os.getenv("DB_PATH", "erudit_studio.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("erudit")
router = Router()


class Apply(StatesGroup):
    text = State()
    gender = State()
    roles = State()
    media = State()
    yesno = State()
    mic_model = State()
    confirm = State()


class AdminInput(StatesGroup):
    value = State()


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users(
                user_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL DEFAULT '',
                full_name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS vacancies(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                emoji TEXT NOT NULL DEFAULT '🎭',
                description TEXT NOT NULL DEFAULT '',
                requirements TEXT NOT NULL DEFAULT '',
                plus_text TEXT NOT NULL DEFAULT '',
                slots INTEGER NOT NULL DEFAULT 1,
                priority INTEGER NOT NULL DEFAULT 0,
                photo_url TEXT NOT NULL DEFAULT '',
                is_open INTEGER NOT NULL DEFAULT 1,
                is_visible INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 100,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS applications(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                age TEXT NOT NULL,
                gender TEXT NOT NULL,
                roles_json TEXT NOT NULL,
                skills TEXT NOT NULL,
                examples_text TEXT NOT NULL DEFAULT '',
                availability TEXT NOT NULL,
                software TEXT NOT NULL,
                device_info TEXT NOT NULL,
                team_experience TEXT NOT NULL,
                motivation TEXT NOT NULL,
                unpaid TEXT NOT NULL,
                revisions TEXT NOT NULL,
                microphone TEXT NOT NULL,
                microphone_model TEXT NOT NULL DEFAULT '',
                discord TEXT NOT NULL,
                additional TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS application_media(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL,
                file_type TEXT NOT NULL,
                file_id TEXT NOT NULL,
                caption TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(application_id) REFERENCES applications(id) ON DELETE CASCADE
            )
        """)
        await db.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')")

        defaults = {
            "applications_open": "1",
            "main_photo_url": "",
            "vacancies_photo_url": "",
            "about_photo_url": "",
            "stages_photo_url": "",
            "faq_photo_url": "",
            "application_photo_url": "",
            "welcome_text": "🎬 Мы собираем команду для долгосрочного Minecraft cinematic проекта.\nВыберите нужный раздел ниже.",
            "about_text": "ERUDIT STUDIO — команда, создающая фильмы и cinematic-проекты в Minecraft.\n\nМы объединяем актёров, озвучку, билдеров, аниматоров, монтажёров, дизайнеров, сценаристов и технических специалистов.",
            "stages_text": "1️⃣ Отправка заявки\n↓\n2️⃣ Проверка анкеты\n↓\n3️⃣ Проверка навыков и портфолио\n↓\n4️⃣ Связь с кандидатом\n↓\n5️⃣ Решение по вступлению в команду",
        }
        for k, v in defaults.items():
            await db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))

        cur = await db.execute("SELECT COUNT(*) FROM vacancies")
        if (await cur.fetchone())[0] == 0:
            seed = [
                ("Актёр", "🎭", "Участие в сценах и игровая актёрская работа."),
                ("Озвучка", "🎙", "Озвучивание персонажей, реплик и сцен."),
                ("Билдер", "🏗", "Создание локаций, зданий, декораций и интерьеров."),
                ("Аниматор", "🎞", "Анимация персонажей и cinematic-сцен."),
                ("Монтажёр", "🎥", "Монтаж, эффекты, цвет и сборка сцен."),
                ("Дизайнер", "🎨", "Постеры, превью и визуальное оформление."),
                ("Сценарист", "📝", "Сюжет, диалоги, сцены и драматургия."),
                ("Технический отдел", "💻", "Моды, инструменты и техническая часть съёмок."),
            ]
            for i, (title, emoji, desc) in enumerate(seed, 1):
                await db.execute("""
                    INSERT INTO vacancies(title,emoji,description,requirements,plus_text,slots,sort_order)
                    VALUES(?,?,?,?,?,?,?)
                """, (title, emoji, desc, "Ответственность, подробная анкета и готовность работать в команде.", "Портфолио и опыт командной работы.", 1, i * 10))
        await db.commit()


async def setting(key):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row[0] if row else ""


async def set_setting(key, value):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        await db.commit()


async def ensure_user(user):
    if not user:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users(user_id,username,full_name) VALUES(?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,full_name=excluded.full_name,updated_at=CURRENT_TIMESTAMP
        """, (user.id, user.username or "", user.full_name or ""))
        await db.commit()


async def vacancies(open_only=False, visible_only=False):
    sql = "SELECT id,title,emoji,description,requirements,plus_text,slots,priority,photo_url,is_open,is_visible,sort_order FROM vacancies"
    where = []
    if open_only:
        where.append("is_open=1")
    if visible_only:
        where.append("is_visible=1")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY priority DESC, sort_order ASC, id ASC"
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(sql)
        return await cur.fetchall()


async def vacancy(vid):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id,title,emoji,description,requirements,plus_text,slots,priority,photo_url,is_open,is_visible,sort_order FROM vacancies WHERE id=?", (vid,))
        return await cur.fetchone()


async def update_vacancy(vid, field, value):
    allowed = {"title","emoji","description","requirements","plus_text","slots","priority","photo_url","is_open","is_visible","sort_order"}
    if field not in allowed:
        raise ValueError("bad field")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE vacancies SET {field}=? WHERE id=?", (value, vid))
        await db.commit()


async def create_vacancy(data):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COALESCE(MAX(sort_order),0)+10 FROM vacancies")
        order = (await cur.fetchone())[0]
        cur = await db.execute("""
            INSERT INTO vacancies(title,emoji,description,requirements,plus_text,slots,photo_url,sort_order)
            VALUES(?,?,?,?,?,?,?,?)
        """, (data["title"], data["emoji"], data["description"], data["requirements"], data["plus_text"], data["slots"], data["photo_url"], order))
        await db.commit()
        return cur.lastrowid


async def save_application(user_id, d):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            INSERT INTO applications(user_id,name,age,gender,roles_json,skills,examples_text,availability,software,device_info,team_experience,motivation,unpaid,revisions,microphone,microphone_model,discord,additional,status)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'new')
        """, (user_id,d["name"],d["age"],d["gender"],json.dumps(d["roles"]),d["skills"],d["examples"],d["availability"],d["software"],d["device"],d["team_experience"],d["motivation"],d["unpaid"],d["revisions"],d["microphone"],d.get("microphone_model",""),d["discord"],d.get("additional","")))
        app_id = cur.lastrowid
        for m in d.get("media", []):
            await db.execute("INSERT INTO application_media(application_id,file_type,file_id,caption) VALUES(?,?,?,?)", (app_id,m["file_type"],m["file_id"],m.get("caption","")))
        await db.commit()
        return app_id


async def get_app(app_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT id,user_id,name,age,gender,roles_json,skills,examples_text,availability,software,device_info,team_experience,motivation,unpaid,revisions,microphone,microphone_model,discord,additional,status,created_at,updated_at
            FROM applications WHERE id=?
        """, (app_id,))
        return await cur.fetchone()


async def latest_app(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT id,user_id,name,age,gender,roles_json,skills,examples_text,availability,software,device_info,team_experience,motivation,unpaid,revisions,microphone,microphone_model,discord,additional,status,created_at,updated_at
            FROM applications WHERE user_id=? ORDER BY id DESC LIMIT 1
        """, (user_id,))
        return await cur.fetchone()


async def list_apps(status="all", limit=60):
    sql = "SELECT id,user_id,name,roles_json,status,created_at FROM applications"
    params = []
    if status != "all":
        sql += " WHERE status=?"
        params.append(status)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(sql, tuple(params))
        return await cur.fetchall()


async def app_media(app_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id,file_type,file_id,caption FROM application_media WHERE application_id=? ORDER BY id", (app_id,))
        return await cur.fetchall()


async def set_app_status(app_id, status):
    if status not in {"new","review","accepted","rejected"}:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE applications SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, app_id))
        await db.commit()


async def stats():
    async with aiosqlite.connect(DB_PATH) as db:
        async def c(sql):
            cur = await db.execute(sql)
            return (await cur.fetchone())[0]
        return {
            "users": await c("SELECT COUNT(*) FROM users"),
            "apps": await c("SELECT COUNT(*) FROM applications"),
            "new": await c("SELECT COUNT(*) FROM applications WHERE status='new'"),
            "review": await c("SELECT COUNT(*) FROM applications WHERE status='review'"),
            "accepted": await c("SELECT COUNT(*) FROM applications WHERE status='accepted'"),
            "rejected": await c("SELECT COUNT(*) FROM applications WHERE status='rejected'"),
            "vacancies": await c("SELECT COUNT(*) FROM vacancies"),
            "open_vacancies": await c("SELECT COUNT(*) FROM vacancies WHERE is_open=1 AND is_visible=1"),
        }


def e(x): return html.escape(str(x or ""))
def admin(uid): return uid in ADMIN_IDS
def is_url(x): return x.startswith("http://") or x.startswith("https://")
def norm_url(x):
    x = x.strip()
    if x == "-": return ""
    if x.startswith("t.me/"): return "https://" + x
    if x.startswith("@"): return "https://t.me/" + x[1:]
    return x

def status_text(s): return {"new":"🟡 Новая","review":"🔵 На рассмотрении","accepted":"🟢 Принята","rejected":"🔴 Отклонена"}.get(s,s)

async def safe_delete(msg):
    try: await msg.delete()
    except Exception: pass

async def send_card(msg, text, kb=None, photo="", delete_old=False):
    sent = None
    if photo and is_url(photo):
        try: sent = await msg.answer_photo(photo=photo, caption=text, reply_markup=kb)
        except Exception as ex: log.warning("photo failed: %s", ex)
    if sent is None: sent = await msg.answer(text, reply_markup=kb)
    if delete_old: await safe_delete(msg)
    return sent

async def role_names(ids):
    out=[]
    for rid in ids:
        v=await vacancy(int(rid))
        out.append(f"{v[2]} {v[1]}" if v else f"Роль #{rid}")
    return out

async def role_names_json(x):
    try: ids=json.loads(x)
    except Exception: ids=[]
    return await role_names(ids)


def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Подать заявку",callback_data="apply:start"),InlineKeyboardButton(text="🎭 Вакансии",callback_data="vacancies")],
        [InlineKeyboardButton(text="🎬 О студии",callback_data="about"),InlineKeyboardButton(text="📋 Этапы отбора",callback_data="stages")],
        [InlineKeyboardButton(text="❓ FAQ",callback_data="faq"),InlineKeyboardButton(text="👤 Моя заявка",callback_data="myapp")],
    ])

def home_kb(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Главное меню",callback_data="home")]])
def cancel_kb(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отменить",callback_data="apply:cancel")]])
def gender_kb(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👨 Парень",callback_data="gender:Парень"),InlineKeyboardButton(text="👩 Девушка",callback_data="gender:Девушка")],[InlineKeyboardButton(text="❌ Отменить",callback_data="apply:cancel")]])
def yesno_kb(kind): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Да",callback_data=f"yn:{kind}:Да"),InlineKeyboardButton(text="❌ Нет",callback_data=f"yn:{kind}:Нет")],[InlineKeyboardButton(text="🚫 Отменить заявку",callback_data="apply:cancel")]])
def media_kb(n): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"✅ Готово ({n})",callback_data="media:done")],[InlineKeyboardButton(text="⏭ Без файлов",callback_data="media:done")],[InlineKeyboardButton(text="❌ Отменить",callback_data="apply:cancel")]])
def confirm_kb(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Отправить заявку",callback_data="apply:confirm")],[InlineKeyboardButton(text="❌ Отменить",callback_data="apply:cancel")]])

async def role_kb(selected):
    rows=[]
    for v in await vacancies(True,True):
        rows.append([InlineKeyboardButton(text=f"{'✅ ' if v[0] in selected else ''}{v[2]} {v[1]}",callback_data=f"role:{v[0]}")])
    rows += [[InlineKeyboardButton(text=f"➡️ Продолжить ({len(selected)}/2)",callback_data="roles:done")],[InlineKeyboardButton(text="❌ Отменить",callback_data="apply:cancel")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def vacancy_kb():
    rows=[]
    for v in await vacancies(True,True):
        rows.append([InlineKeyboardButton(text=f"{'🔥 ' if v[7] else ''}{v[2]} {v[1]}",callback_data=f"vacancy:{v[0]}")])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню",callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def faq_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎓 Нужен опыт?",callback_data="faq:experience"),InlineKeyboardButton(text="🎭 Можно 2 роли?",callback_data="faq:roles")],
        [InlineKeyboardButton(text="💻 Нужен мощный ПК?",callback_data="faq:pc"),InlineKeyboardButton(text="💰 Есть оплата?",callback_data="faq:payment")],
        [InlineKeyboardButton(text="📁 Без портфолио?",callback_data="faq:portfolio"),InlineKeyboardButton(text="📋 Как проходит отбор?",callback_data="faq:selection")],
        [InlineKeyboardButton(text="🏠 Главное меню",callback_data="home")],
    ])


async def show_home(msg, delete_old=False):
    await ensure_user(msg.from_user)
    await send_card(msg,"🎬 <b>ERUDIT STUDIO</b>\n<i>Minecraft Cinematic Project</i>\n\n"+e(await setting("welcome_text")),main_kb(),await setting("main_photo_url"),delete_old)

@router.message(CommandStart())
async def start(message:Message,state:FSMContext):
    await state.clear(); await show_home(message)

@router.callback_query(F.data=="home")
async def home(callback:CallbackQuery,state:FSMContext):
    await state.clear(); await show_home(callback.message,True); await callback.answer()

@router.callback_query(F.data=="vacancies")
async def show_vacancies(callback:CallbackQuery,state:FSMContext):
    await state.clear(); vs=await vacancies(True,True)
    urgent=[v for v in vs if v[7]]
    text="🎭 <b>АКТУАЛЬНЫЕ ВАКАНСИИ</b>\n\n"
    text += "Выберите направление, чтобы посмотреть описание и требования." if vs else "Сейчас активный набор временно закрыт."
    if urgent: text += "\n\n🔥 <b>Особенно нужны:</b>\n"+"\n".join(f"• {v[2]} {e(v[1])}" for v in urgent[:6])
    await send_card(callback.message,text,await vacancy_kb(),await setting("vacancies_photo_url"),True); await callback.answer()

@router.callback_query(F.data.startswith("vacancy:"))
async def vacancy_card(callback:CallbackQuery):
    vid=int(callback.data.split(":")[1]); v=await vacancy(vid)
    if not v or not v[10]: await callback.answer("Вакансия недоступна",show_alert=True); return
    text=f"{'🔥 ' if v[7] else ''}{v[2]} <b>{e(v[1].upper())}</b>\n\n{e(v[3])}\n\n📋 <b>Требования:</b>\n{e(v[4] or '—')}\n\n⭐ <b>Будет плюсом:</b>\n{e(v[5] or '—')}\n\n👥 Нужно людей: <b>{v[6]}</b>\n📌 Набор: <b>{'🟢 открыт' if v[9] else '🔴 закрыт'}</b>"
    rows=[]
    if v[9]: rows.append([InlineKeyboardButton(text="📩 Подать заявку на эту роль",callback_data=f"applyfor:{vid}")])
    rows += [[InlineKeyboardButton(text="⬅️ К вакансиям",callback_data="vacancies")],[InlineKeyboardButton(text="🏠 Главное меню",callback_data="home")]]
    await send_card(callback.message,text,InlineKeyboardMarkup(inline_keyboard=rows),v[8],True); await callback.answer()

@router.callback_query(F.data=="about")
async def about(callback:CallbackQuery,state:FSMContext):
    await state.clear(); await send_card(callback.message,"🎬 <b>О ERUDIT STUDIO</b>\n\n"+e(await setting("about_text")),home_kb(),await setting("about_photo_url"),True); await callback.answer()

@router.callback_query(F.data=="stages")
async def stages(callback:CallbackQuery,state:FSMContext):
    await state.clear(); await send_card(callback.message,"📋 <b>ЭТАПЫ ОТБОРА</b>\n\n"+e(await setting("stages_text")),home_kb(),await setting("stages_photo_url"),True); await callback.answer()

@router.callback_query(F.data=="faq")
async def faq(callback:CallbackQuery,state:FSMContext):
    await state.clear(); await send_card(callback.message,"❓ <b>ЧАСТЫЕ ВОПРОСЫ</b>\n\nВыберите вопрос:",faq_kb(),await setting("faq_photo_url"),True); await callback.answer()

FAQ={
"experience":"🎓 <b>Нужен ли опыт?</b>\n\nОпыт — плюс, но подать заявку можно и без него. Расскажите, чему хотите научиться.",
"roles":"🎭 <b>Можно выбрать две роли?</b>\n\nДа. Максимум — <b>2 роли</b>.",
"pc":"💻 <b>Нужен мощный ПК?</b>\n\nЗависит от роли. В анкете укажите характеристики устройства и FPS.",
"payment":"💰 <b>Есть ли оплата?</b>\n\nНа старте возможна работа без оплаты. Готовность указывается в анкете.",
"portfolio":"📁 <b>Можно без портфолио?</b>\n\nДа. Можно написать «Без опыта, но хочу попробовать». Примеры работ повышают информативность заявки.",
"selection":"📋 <b>Как проходит отбор?</b>\n\nЗаявка → проверка → портфолио/навыки → связь → решение.",}

@router.callback_query(F.data.startswith("faq:"))
async def faq_item(callback:CallbackQuery):
    key=callback.data.split(":")[1]
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ К FAQ",callback_data="faq")],[InlineKeyboardButton(text="🏠 Главное меню",callback_data="home")]])
    await callback.message.answer(FAQ.get(key,"Вопрос не найден"),reply_markup=kb); await safe_delete(callback.message); await callback.answer()

@router.callback_query(F.data=="myapp")
async def myapp(callback:CallbackQuery,state:FSMContext):
    await state.clear(); a=await latest_app(callback.from_user.id)
    if not a:
        kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📩 Подать заявку",callback_data="apply:start")],[InlineKeyboardButton(text="🏠 Главное меню",callback_data="home")]])
        text="👤 <b>МОЯ ЗАЯВКА</b>\n\n📭 У вас пока нет заявок."
    else:
        text=f"👤 <b>МОЯ ЗАЯВКА #{a[0]}</b>\n\n📌 {status_text(a[19])}\n🎭 {e(', '.join(await role_names_json(a[5])))}\n🗓 {e(a[20])}"; kb=home_kb()
    await callback.message.answer(text,reply_markup=kb); await safe_delete(callback.message); await callback.answer()


TEXT_STEPS=[
("name","1/16. Имя","Как вас зовут?"),
("age","2/16. Возраст","Сколько вам лет?"),
("skills","5/16. Что вы умеете?","Опишите максимально подробно: строительство, анимация, монтаж, актёрская игра, озвучка, Blockbench, эффекты и другое."),
("examples","6/16. Примеры работ","Пришлите ссылки на TikTok / YouTube / Google Drive. Если опыта нет — напишите «Без опыта, но хочу попробовать.»"),
("availability","7/16. Сколько времени готовы уделять проекту?","Укажите: будние дни, выходные, часов в неделю."),
("software","8/16. В каких программах работаете?","Minecraft, Mine-Imator, Blender, Blockbench, CapCut, After Effects, Premiere Pro, Photoshop, OBS или другое."),
("device","9/16. На каком устройстве работаете?","ПК / Ноутбук\nПроцессор:\nВидеокарта:\nОЗУ:\nСредний FPS в Minecraft:"),
("team_experience","10/16. Есть ли опыт работы в команде?","Если да — расскажите где именно. Если нет — так и напишите."),
("motivation","11/16. Почему хотите попасть именно в ERUDIT STUDIO?","Ответ «просто хочу» не рассматривается."),
("discord","15/16. Ваш Discord","Укажите Discord."),
("additional","16/16. Дополнительная информация","Расскажите всё, что считаете важным. Если добавить нечего — отправьте -"),
]

async def prompt_text(msg,state,key):
    for k,title,prompt in TEXT_STEPS:
        if k==key:
            await state.update_data(step=key); await state.set_state(Apply.text)
            await msg.answer(f"<b>{title}</b>\n\n{prompt}",reply_markup=cancel_kb()); return

async def begin_apply(msg,state,preset=None):
    if await setting("applications_open")!="1": await msg.answer("⛔ Приём заявок временно закрыт.",reply_markup=home_kb()); return
    if not await vacancies(True,True): await msg.answer("🎭 Сейчас нет открытых вакансий.",reply_markup=home_kb()); return
    await state.clear(); await state.update_data(roles=[preset] if preset else [],media=[])
    await send_card(msg,"📩 <b>ЗАЯВКА В ERUDIT STUDIO</b>\n\nАнкета заполняется по шагам. Отвечайте подробно.\n⚠️ Односложные ответы могут быть отклонены.",None,await setting("application_photo_url"))
    await prompt_text(msg,state,"name")

@router.callback_query(F.data=="apply:start")
async def apply_start(callback:CallbackQuery,state:FSMContext):
    await safe_delete(callback.message); await begin_apply(callback.message,state); await callback.answer()

@router.callback_query(F.data.startswith("applyfor:"))
async def apply_for(callback:CallbackQuery,state:FSMContext):
    vid=int(callback.data.split(":")[1]); v=await vacancy(vid)
    if not v or not v[9] or not v[10]: await callback.answer("Набор закрыт",show_alert=True); return
    await safe_delete(callback.message); await begin_apply(callback.message,state,vid); await callback.answer()

@router.callback_query(F.data=="apply:cancel")
async def apply_cancel(callback:CallbackQuery,state:FSMContext):
    await state.clear(); await show_home(callback.message,True); await callback.answer("Отменено")

@router.message(Apply.text)
async def apply_text(message:Message,state:FSMContext):
    if not message.text: await message.answer("Ответьте текстом."); return
    d=await state.get_data(); step=d.get("step"); val=message.text.strip()
    if step in {"name"} and len(val)<2: await message.answer("Введите имя подробнее."); return
    if step in {"skills","motivation"} and len(val)<10: await message.answer("Ответьте подробнее."); return
    if step=="additional" and val=="-": val=""
    await state.update_data(**{step:val})
    if step=="name": await prompt_text(message,state,"age")
    elif step=="age":
        await state.set_state(Apply.gender); await message.answer("<b>3/16. Пол</b>",reply_markup=gender_kb())
    elif step=="skills": await prompt_text(message,state,"examples")
    elif step=="examples":
        await state.set_state(Apply.media); await message.answer("📎 <b>Дополнительные материалы</b>\n\nОтправьте фото, видео, голос, аудио или документ. Когда закончите — нажмите Готово.",reply_markup=media_kb(0))
    elif step=="availability": await prompt_text(message,state,"software")
    elif step=="software": await prompt_text(message,state,"device")
    elif step=="device": await prompt_text(message,state,"team_experience")
    elif step=="team_experience": await prompt_text(message,state,"motivation")
    elif step=="motivation":
        await state.update_data(yn_kind="unpaid"); await state.set_state(Apply.yesno); await message.answer("<b>12/16. Готовы ли работать без оплаты на старте?</b>",reply_markup=yesno_kb("unpaid"))
    elif step=="discord": await prompt_text(message,state,"additional")
    elif step=="additional":
        d=await state.get_data(); names=", ".join(await role_names(d["roles"]))
        await state.set_state(Apply.confirm); await message.answer(f"📩 <b>ПРОВЕРЬТЕ ЗАЯВКУ</b>\n\n👤 {e(d['name'])}, {e(d['age'])}\n⚧ {e(d['gender'])}\n🎭 {e(names)}\n📎 Материалов: {len(d.get('media',[]))}\n💬 Discord: {e(d['discord'])}",reply_markup=confirm_kb())

@router.callback_query(Apply.gender,F.data.startswith("gender:"))
async def apply_gender(callback:CallbackQuery,state:FSMContext):
    await state.update_data(gender=callback.data.split(":",1)[1]); await state.set_state(Apply.roles)
    d=await state.get_data(); await callback.message.answer("<b>4/16. Желаемая роль</b>\n\nМожно выбрать максимум две.",reply_markup=await role_kb(d.get("roles",[]))); await safe_delete(callback.message); await callback.answer()

@router.callback_query(Apply.roles,F.data.startswith("role:"))
async def role_toggle(callback:CallbackQuery,state:FSMContext):
    vid=int(callback.data.split(":")[1]); v=await vacancy(vid)
    if not v or not v[9] or not v[10]: await callback.answer("Вакансия закрыта",show_alert=True); return
    d=await state.get_data(); selected=d.get("roles",[])
    if vid in selected: selected.remove(vid)
    elif len(selected)>=2: await callback.answer("Максимум 2 роли",show_alert=True); return
    else: selected.append(vid)
    await state.update_data(roles=selected)
    try: await callback.message.edit_reply_markup(reply_markup=await role_kb(selected))
    except TelegramBadRequest: pass
    await callback.answer()

@router.callback_query(Apply.roles,F.data=="roles:done")
async def roles_done(callback:CallbackQuery,state:FSMContext):
    d=await state.get_data()
    if not d.get("roles"): await callback.answer("Выберите роль",show_alert=True); return
    await safe_delete(callback.message); await prompt_text(callback.message,state,"skills"); await callback.answer()

@router.message(Apply.media)
async def media_add(message:Message,state:FSMContext):
    ft=fid=None
    if message.photo: ft,fid="photo",message.photo[-1].file_id
    elif message.video: ft,fid="video",message.video.file_id
    elif message.voice: ft,fid="voice",message.voice.file_id
    elif message.audio: ft,fid="audio",message.audio.file_id
    elif message.document: ft,fid="document",message.document.file_id
    elif message.animation: ft,fid="animation",message.animation.file_id
    if not ft: await message.answer("Отправьте медиа/файл или нажмите Готово."); return
    d=await state.get_data(); m=d.get("media",[]); m.append({"file_type":ft,"file_id":fid,"caption":message.caption or ""}); await state.update_data(media=m)
    await message.answer(f"✅ Добавлено. Всего: <b>{len(m)}</b>",reply_markup=media_kb(len(m)))

@router.callback_query(Apply.media,F.data=="media:done")
async def media_done(callback:CallbackQuery,state:FSMContext):
    await safe_delete(callback.message); await prompt_text(callback.message,state,"availability"); await callback.answer()

@router.callback_query(Apply.yesno,F.data.startswith("yn:"))
async def yesno(callback:CallbackQuery,state:FSMContext):
    _,kind,val=callback.data.split(":",2); await state.update_data(**{kind:val}); await safe_delete(callback.message)
    if kind=="unpaid": await state.set_state(Apply.yesno); await callback.message.answer("<b>13/16. Готовы ли переделывать работу после замечаний руководителя?</b>",reply_markup=yesno_kb("revisions"))
    elif kind=="revisions": await state.set_state(Apply.yesno); await callback.message.answer("<b>14/16. Есть ли микрофон?</b>",reply_markup=yesno_kb("microphone"))
    elif kind=="microphone":
        if val=="Да": await state.set_state(Apply.mic_model); await callback.message.answer("🎙 Какой у вас микрофон?",reply_markup=cancel_kb())
        else: await state.update_data(microphone_model=""); await prompt_text(callback.message,state,"discord")
    await callback.answer()

@router.message(Apply.mic_model)
async def mic_model(message:Message,state:FSMContext):
    if not message.text: return
    await state.update_data(microphone_model=message.text.strip()); await prompt_text(message,state,"discord")

@router.callback_query(Apply.confirm,F.data=="apply:confirm")
async def apply_confirm(callback:CallbackQuery,state:FSMContext,bot:Bot):
    d=await state.get_data(); app_id=await save_application(callback.from_user.id,d); await state.clear()
    await callback.message.answer(f"✅ <b>Заявка #{app_id} отправлена!</b>\n\nСтатус можно смотреть в разделе «Моя заявка».",reply_markup=home_kb()); await safe_delete(callback.message); await callback.answer("Отправлено")
    a=await get_app(app_id); roles=", ".join(await role_names_json(a[5]))
    text=f"📩 <b>НОВАЯ ЗАЯВКА #{app_id}</b>\n\n👤 {e(a[2])}, {e(a[3])}\n🎭 {e(roles)}\n💬 Discord: {e(a[17])}\n🆔 <code>{a[1]}</code>"
    for aid in ADMIN_IDS:
        try: await bot.send_message(aid,text,reply_markup=admin_app_kb(app_id,a[19]))
        except Exception as ex: log.warning("notify admin: %s",ex)


# -------------------- ADMIN --------------------
def admin_home_kb(): return InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📥 Заявки",callback_data="adm:apps"),InlineKeyboardButton(text="🎭 Вакансии",callback_data="adm:vacancies")],
    [InlineKeyboardButton(text="➕ Добавить вакансию",callback_data="adm:addvac"),InlineKeyboardButton(text="📊 Статистика",callback_data="adm:stats")],
    [InlineKeyboardButton(text="🖼 Оформление",callback_data="adm:settings"),InlineKeyboardButton(text="🎛 Приём заявок",callback_data="adm:toggle")],
    [InlineKeyboardButton(text="🏠 Меню бота",callback_data="home")],])
def admin_back(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Админ-панель",callback_data="adm:home")]])

async def show_admin(msg,delete_old=False):
    s=await stats(); accepting=await setting("applications_open")=="1"
    await msg.answer(f"⚙️ <b>ERUDIT STUDIO — ADMIN</b>\n\n📥 Новых: <b>{s['new']}</b>\n🔵 На рассмотрении: <b>{s['review']}</b>\n🎭 Открытых вакансий: <b>{s['open_vacancies']}</b>\n🎛 Приём заявок: <b>{'🟢 открыт' if accepting else '🔴 закрыт'}</b>",reply_markup=admin_home_kb())
    if delete_old: await safe_delete(msg)

@router.message(Command("admin"))
async def admin_cmd(message:Message,state:FSMContext):
    if not admin(message.from_user.id): await message.answer("⛔ Нет доступа."); return
    await state.clear(); await show_admin(message)

@router.callback_query(F.data=="adm:home")
async def adm_home(callback:CallbackQuery,state:FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear(); await show_admin(callback.message,True); await callback.answer()

@router.callback_query(F.data=="adm:vacancies")
async def adm_vacancies(callback:CallbackQuery,state:FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear(); rows=[]
    for v in await vacancies():
        flags=("🔥" if v[7] else "")+("🟢" if v[9] else "🔴")+("" if v[10] else "🙈")
        rows.append([InlineKeyboardButton(text=f"{flags} {v[2]} {v[1]}",callback_data=f"adm:vac:{v[0]}")])
    rows += [[InlineKeyboardButton(text="➕ Добавить вакансию",callback_data="adm:addvac")],[InlineKeyboardButton(text="⬅️ Админ-панель",callback_data="adm:home")]]
    await callback.message.answer("🎭 <b>УПРАВЛЕНИЕ ВАКАНСИЯМИ</b>",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await safe_delete(callback.message); await callback.answer()


def vac_admin_kb(v):
    vid=v[0]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Название",callback_data=f"adm:editvac:{vid}:title"),InlineKeyboardButton(text="😀 Эмодзи",callback_data=f"adm:editvac:{vid}:emoji")],
        [InlineKeyboardButton(text="📝 Описание",callback_data=f"adm:editvac:{vid}:description"),InlineKeyboardButton(text="📋 Требования",callback_data=f"adm:editvac:{vid}:requirements")],
        [InlineKeyboardButton(text="⭐ Будет плюсом",callback_data=f"adm:editvac:{vid}:plus_text"),InlineKeyboardButton(text="👥 Кол-во",callback_data=f"adm:editvac:{vid}:slots")],
        [InlineKeyboardButton(text="🖼 Фото",callback_data=f"adm:editvac:{vid}:photo_url")],
        [InlineKeyboardButton(text="🔥 Убрать срочность" if v[7] else "🔥 Сделать срочной",callback_data=f"adm:prio:{vid}")],
        [InlineKeyboardButton(text="🔴 Закрыть" if v[9] else "🟢 Открыть",callback_data=f"adm:open:{vid}"),InlineKeyboardButton(text="🙈 Скрыть" if v[10] else "👁 Показать",callback_data=f"adm:visible:{vid}")],
        [InlineKeyboardButton(text="🗑 Удалить",callback_data=f"adm:delvacask:{vid}")],
        [InlineKeyboardButton(text="⬅️ К вакансиям",callback_data="adm:vacancies")],])

@router.callback_query(F.data.startswith("adm:vac:"))
async def adm_vac_card(callback:CallbackQuery):
    if not admin(callback.from_user.id): return
    vid=int(callback.data.split(":")[2]); v=await vacancy(vid)
    if not v: return
    await callback.message.answer(f"🎭 <b>ВАКАНСИЯ #{vid}</b>\n\n{v[2]} <b>{e(v[1])}</b>\nНабор: {'🟢 открыт' if v[9] else '🔴 закрыт'}\nВидимость: {'👁' if v[10] else '🙈'}\nПриоритет: {'🔥 срочно' if v[7] else 'обычный'}\nНужно: {v[6]}\n\n<b>Описание:</b>\n{e(v[3])}\n\n<b>Требования:</b>\n{e(v[4])}\n\n<b>Будет плюсом:</b>\n{e(v[5])}",reply_markup=vac_admin_kb(v)); await safe_delete(callback.message); await callback.answer()

VAC_ADD_FIELDS=["title","emoji","description","requirements","plus_text","slots","photo_url"]
VAC_ADD_PROMPTS={"title":"Название роли:","emoji":"Эмодзи роли, например 🏗:","description":"Описание роли:","requirements":"Требования:","plus_text":"Что будет плюсом? (- чтобы пусто)","slots":"Сколько человек нужно?", "photo_url":"Прямая HTTPS-ссылка на фото (- если без фото):"}

@router.callback_query(F.data=="adm:addvac")
async def adm_addvac(callback:CallbackQuery,state:FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear(); await state.set_state(AdminInput.value); await state.update_data(admin_action="addvac",vac_step=0,vac_data={}); await callback.message.answer("➕ <b>НОВАЯ ВАКАНСИЯ</b>\n\n"+VAC_ADD_PROMPTS[VAC_ADD_FIELDS[0]],reply_markup=admin_back()); await safe_delete(callback.message); await callback.answer()

EDIT_NAMES={"title":"название","emoji":"эмодзи","description":"описание","requirements":"требования","plus_text":"что будет плюсом","slots":"количество людей","photo_url":"фото"}

@router.callback_query(F.data.startswith("adm:editvac:"))
async def adm_editvac(callback:CallbackQuery,state:FSMContext):
    if not admin(callback.from_user.id): return
    _,_,vid,field=callback.data.split(":",3); await state.clear(); await state.set_state(AdminInput.value); await state.update_data(admin_action="editvac",vid=int(vid),field=field)
    await callback.message.answer(f"✏️ Отправьте новое значение: <b>{EDIT_NAMES[field]}</b>.\nДля фото/поля «будет плюсом» можно отправить - чтобы очистить.",reply_markup=admin_back()); await callback.answer()

@router.callback_query(F.data.startswith("adm:prio:"))
async def adm_prio(callback:CallbackQuery):
    vid=int(callback.data.split(":")[2]); v=await vacancy(vid); await update_vacancy(vid,"priority",0 if v[7] else 1); v=await vacancy(vid); await callback.message.edit_reply_markup(reply_markup=vac_admin_kb(v)); await callback.answer("Изменено")

@router.callback_query(F.data.startswith("adm:open:"))
async def adm_open(callback:CallbackQuery):
    vid=int(callback.data.split(":")[2]); v=await vacancy(vid); await update_vacancy(vid,"is_open",0 if v[9] else 1); v=await vacancy(vid); await callback.message.edit_reply_markup(reply_markup=vac_admin_kb(v)); await callback.answer("Изменено")

@router.callback_query(F.data.startswith("adm:visible:"))
async def adm_visible(callback:CallbackQuery):
    vid=int(callback.data.split(":")[2]); v=await vacancy(vid); await update_vacancy(vid,"is_visible",0 if v[10] else 1); v=await vacancy(vid); await callback.message.edit_reply_markup(reply_markup=vac_admin_kb(v)); await callback.answer("Изменено")

@router.callback_query(F.data.startswith("adm:delvacask:"))
async def adm_delask(callback:CallbackQuery):
    vid=int(callback.data.split(":")[2]); kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🗑 Да, удалить",callback_data=f"adm:delvac:{vid}")],[InlineKeyboardButton(text="❌ Нет",callback_data=f"adm:vac:{vid}")]])
    await callback.message.answer("⚠️ Удалить вакансию?",reply_markup=kb); await safe_delete(callback.message); await callback.answer()

@router.callback_query(F.data.startswith("adm:delvac:"))
async def adm_del(callback:CallbackQuery):
    vid=int(callback.data.split(":")[2]);
    async with aiosqlite.connect(DB_PATH) as db: await db.execute("DELETE FROM vacancies WHERE id=?",(vid,)); await db.commit()
    await callback.message.answer("✅ Вакансия удалена.",reply_markup=admin_back()); await safe_delete(callback.message); await callback.answer()

@router.callback_query(F.data=="adm:apps")
async def adm_apps(callback:CallbackQuery,state:FSMContext):
    if not admin(callback.from_user.id): return
    await state.clear(); s=await stats(); kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"🟡 Новые ({s['new']})",callback_data="adm:applist:new"),InlineKeyboardButton(text=f"🔵 Рассмотрение ({s['review']})",callback_data="adm:applist:review")],[InlineKeyboardButton(text=f"✅ Принятые ({s['accepted']})",callback_data="adm:applist:accepted"),InlineKeyboardButton(text=f"❌ Отклонённые ({s['rejected']})",callback_data="adm:applist:rejected")],[InlineKeyboardButton(text=f"📚 Все ({s['apps']})",callback_data="adm:applist:all")],[InlineKeyboardButton(text="⬅️ Админ-панель",callback_data="adm:home")]])
    await callback.message.answer("📥 <b>ЗАЯВКИ</b>",reply_markup=kb); await safe_delete(callback.message); await callback.answer()

@router.callback_query(F.data.startswith("adm:applist:"))
async def adm_applist(callback:CallbackQuery):
    st=callback.data.split(":")[2]; rows=[]
    for a in await list_apps(st): rows.append([InlineKeyboardButton(text=f"#{a[0]} {status_text(a[4])} — {a[2]}",callback_data=f"adm:app:{a[0]}")])
    rows.append([InlineKeyboardButton(text="⬅️ Категории",callback_data="adm:apps")]); await callback.message.answer("📥 Выберите заявку:" if len(rows)>1 else "📭 Заявок нет.",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await safe_delete(callback.message); await callback.answer()


def admin_app_kb(app_id,status):
    rows=[[InlineKeyboardButton(text="📄 Полная анкета",callback_data=f"adm:full:{app_id}"),InlineKeyboardButton(text="📎 Материалы",callback_data=f"adm:media:{app_id}")]]
    if status!="review": rows.append([InlineKeyboardButton(text="🔵 На рассмотрение",callback_data=f"adm:status:{app_id}:review")])
    rows += [[InlineKeyboardButton(text="✅ Принять",callback_data=f"adm:status:{app_id}:accepted"),InlineKeyboardButton(text="❌ Отклонить",callback_data=f"adm:status:{app_id}:rejected")],[InlineKeyboardButton(text="💬 Написать кандидату",callback_data=f"adm:reply:{app_id}")],[InlineKeyboardButton(text="⬅️ К заявкам",callback_data="adm:apps")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.callback_query(F.data.startswith("adm:app:"))
async def adm_app(callback:CallbackQuery):
    app_id=int(callback.data.split(":")[2]); a=await get_app(app_id); names=", ".join(await role_names_json(a[5])); media=await app_media(app_id)
    await callback.message.answer(f"📩 <b>ЗАЯВКА #{app_id}</b>\n\n📌 {status_text(a[19])}\n👤 {e(a[2])}, {e(a[3])}\n🎭 {e(names)}\n💬 Discord: {e(a[17])}\n🆔 <code>{a[1]}</code>\n📎 Материалов: {len(media)}\n\n<b>Навыки:</b>\n{e(a[6][:900])}\n\n<b>Почему ERUDIT STUDIO:</b>\n{e(a[12][:900])}",reply_markup=admin_app_kb(app_id,a[19])); await safe_delete(callback.message); await callback.answer()

@router.callback_query(F.data.startswith("adm:full:"))
async def adm_full(callback:CallbackQuery):
    app_id=int(callback.data.split(":")[2]); a=await get_app(app_id); roles=", ".join(await role_names_json(a[5])); text=f"📩 <b>ЗАЯВКА #{app_id}</b>\n\n1. Имя: {e(a[2])}\n2. Возраст: {e(a[3])}\n3. Пол: {e(a[4])}\n4. Роли: {e(roles)}\n\n5. <b>Навыки:</b>\n{e(a[6])}\n\n6. <b>Примеры:</b>\n{e(a[7])}\n\n7. <b>Время:</b>\n{e(a[8])}\n\n8. <b>Программы:</b>\n{e(a[9])}\n\n9. <b>Устройство:</b>\n{e(a[10])}\n\n10. <b>Команда:</b>\n{e(a[11])}\n\n11. <b>Мотивация:</b>\n{e(a[12])}\n\n12. Без оплаты: {e(a[13])}\n13. Правки: {e(a[14])}\n14. Микрофон: {e(a[15])} {e(a[16])}\n15. Discord: {e(a[17])}\n16. Дополнительно: {e(a[18] or '—')}"
    for i in range(0,len(text),3800): await callback.message.answer(text[i:i+3800])
    await callback.answer("Отправлено")

@router.callback_query(F.data.startswith("adm:media:"))
async def adm_media(callback:CallbackQuery,bot:Bot):
    app_id=int(callback.data.split(":")[2]); mm=await app_media(app_id)
    if not mm: await callback.answer("Материалов нет",show_alert=True); return
    await callback.answer("Отправляю")
    for _,ft,fid,cap in mm:
        try:
            if ft=="photo": await bot.send_photo(callback.from_user.id,fid,caption=cap or None)
            elif ft=="video": await bot.send_video(callback.from_user.id,fid,caption=cap or None)
            elif ft=="voice": await bot.send_voice(callback.from_user.id,fid,caption=cap or None)
            elif ft=="audio": await bot.send_audio(callback.from_user.id,fid,caption=cap or None)
            elif ft=="document": await bot.send_document(callback.from_user.id,fid,caption=cap or None)
            elif ft=="animation": await bot.send_animation(callback.from_user.id,fid,caption=cap or None)
        except Exception as ex: await callback.message.answer(f"⚠️ Ошибка материала: {e(ex)}")

@router.callback_query(F.data.startswith("adm:status:"))
async def adm_status(callback:CallbackQuery,bot:Bot):
    _,_,app_id,st=callback.data.split(":",3); app_id=int(app_id); a=await get_app(app_id); await set_app_status(app_id,st)
    notice={"review":f"🔵 Заявка #{app_id} находится на рассмотрении.","accepted":f"✅ Ваша заявка #{app_id} в ERUDIT STUDIO одобрена! Администрация свяжется с вами.","rejected":f"❌ Заявка #{app_id} не прошла отбор. Спасибо за интерес к ERUDIT STUDIO."}.get(st)
    try: await bot.send_message(a[1],notice,reply_markup=home_kb())
    except Exception: pass
    a=await get_app(app_id)
    try: await callback.message.edit_reply_markup(reply_markup=admin_app_kb(app_id,a[19]))
    except TelegramBadRequest: pass
    await callback.answer("Статус изменён")

@router.callback_query(F.data.startswith("adm:reply:"))
async def adm_reply(callback:CallbackQuery,state:FSMContext):
    app_id=int(callback.data.split(":")[2]); a=await get_app(app_id); await state.clear(); await state.set_state(AdminInput.value); await state.update_data(admin_action="reply",app_id=app_id,user_id=a[1]); await callback.message.answer("💬 Напишите сообщение кандидату:",reply_markup=admin_back()); await callback.answer()

@router.callback_query(F.data=="adm:stats")
async def adm_stats(callback:CallbackQuery):
    s=await stats(); await callback.message.answer(f"📊 <b>СТАТИСТИКА</b>\n\n👥 Пользователей: {s['users']}\n📩 Заявок: {s['apps']}\n🟡 Новые: {s['new']}\n🔵 Рассмотрение: {s['review']}\n✅ Принятые: {s['accepted']}\n❌ Отклонённые: {s['rejected']}\n🎭 Вакансий: {s['vacancies']}\n🟢 Открытых: {s['open_vacancies']}",reply_markup=admin_back()); await safe_delete(callback.message); await callback.answer()

@router.callback_query(F.data=="adm:toggle")
async def adm_toggle(callback:CallbackQuery):
    nv="0" if await setting("applications_open")=="1" else "1"; await set_setting("applications_open",nv); await callback.answer("Приём открыт" if nv=="1" else "Приём закрыт",show_alert=True); await show_admin(callback.message,True)

SET_KEYS={"main_photo_url":"Фото главного меню","vacancies_photo_url":"Фото вакансий","about_photo_url":"Фото «О студии»","stages_photo_url":"Фото этапов","faq_photo_url":"Фото FAQ","application_photo_url":"Фото анкеты","welcome_text":"Текст главного меню","about_text":"Текст «О студии»","stages_text":"Текст этапов"}

def settings_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Фото меню",callback_data="adm:set:main_photo_url")],
        [InlineKeyboardButton(text="🎭 Фото вакансий",callback_data="adm:set:vacancies_photo_url"),InlineKeyboardButton(text="🎬 Фото студии",callback_data="adm:set:about_photo_url")],
        [InlineKeyboardButton(text="📋 Фото этапов",callback_data="adm:set:stages_photo_url"),InlineKeyboardButton(text="❓ Фото FAQ",callback_data="adm:set:faq_photo_url")],
        [InlineKeyboardButton(text="📩 Фото анкеты",callback_data="adm:set:application_photo_url")],
        [InlineKeyboardButton(text="📝 Текст меню",callback_data="adm:set:welcome_text")],[InlineKeyboardButton(text="📝 Текст о студии",callback_data="adm:set:about_text")],[InlineKeyboardButton(text="📝 Текст этапов",callback_data="adm:set:stages_text")],
        [InlineKeyboardButton(text="⬅️ Админ-панель",callback_data="adm:home")],])

@router.callback_query(F.data=="adm:settings")
async def adm_settings(callback:CallbackQuery,state:FSMContext):
    await state.clear(); await callback.message.answer("🖼 <b>ОФОРМЛЕНИЕ И ТЕКСТЫ</b>\n\nФото задаются прямыми HTTPS-ссылками.",reply_markup=settings_kb()); await safe_delete(callback.message); await callback.answer()

@router.callback_query(F.data.startswith("adm:set:"))
async def adm_set(callback:CallbackQuery,state:FSMContext):
    key=callback.data.split(":",2)[2]; await state.clear(); await state.set_state(AdminInput.value); await state.update_data(admin_action="setting",key=key); await callback.message.answer(f"⚙️ Изменяем: <b>{SET_KEYS[key]}</b>\n\nОтправьте новое значение. Для фото - очищает поле.",reply_markup=admin_back()); await callback.answer()

@router.message(AdminInput.value)
async def admin_input(message:Message,state:FSMContext,bot:Bot):
    if not admin(message.from_user.id) or not message.text: return
    d=await state.get_data(); act=d.get("admin_action"); val=message.text.strip()
    if act=="reply":
        try: await bot.send_message(d["user_id"],"💬 <b>ERUDIT STUDIO</b>\n\n"+e(val),reply_markup=home_kb()); out="✅ Сообщение отправлено."
        except Exception as ex: out=f"❌ Ошибка: {e(ex)}"
        await state.clear(); await message.answer(out,reply_markup=admin_back()); return
    if act=="setting":
        key=d["key"]
        if key.endswith("_photo_url"):
            val=norm_url(val)
            if val and not is_url(val): await message.answer("Нужна http(s) ссылка или -"); return
        await set_setting(key,val); await state.clear(); await message.answer("✅ Сохранено.",reply_markup=settings_kb()); return
    if act=="editvac":
        vid,field=d["vid"],d["field"]
        if field=="slots":
            try: val=int(val); assert 1<=val<=999
            except Exception: await message.answer("Введите число 1–999"); return
        if field=="photo_url":
            val=norm_url(val)
            if val and not is_url(val): await message.answer("Нужна http(s) ссылка или -"); return
        if field=="plus_text" and val=="-": val=""
        await update_vacancy(vid,field,val); await state.clear(); v=await vacancy(vid); await message.answer("✅ Изменено.",reply_markup=vac_admin_kb(v)); return
    if act=="addvac":
        step=d.get("vac_step",0); data=d.get("vac_data",{}); field=VAC_ADD_FIELDS[step]
        if field=="slots":
            try: val=int(val); assert 1<=val<=999
            except Exception: await message.answer("Введите число 1–999"); return
        if field=="photo_url":
            val=norm_url(val)
            if val and not is_url(val): await message.answer("Нужна http(s) ссылка или -"); return
        if field=="plus_text" and val=="-": val=""
        data[field]=val; step+=1
        if step>=len(VAC_ADD_FIELDS):
            vid=await create_vacancy(data); await state.clear(); v=await vacancy(vid); await message.answer("✅ Вакансия создана.",reply_markup=vac_admin_kb(v)); return
        await state.update_data(vac_step=step,vac_data=data); await message.answer(VAC_ADD_PROMPTS[VAC_ADD_FIELDS[step]])

@router.message()
async def fallback(message:Message):
    await ensure_user(message.from_user); await message.answer("Используйте кнопки меню 👇",reply_markup=main_kb())


async def main():
    if not BOT_TOKEN or BOT_TOKEN=="PASTE_BOT_TOKEN_HERE": raise RuntimeError("Вставьте BOT_TOKEN в bot.py или переменную окружения BOT_TOKEN")
    if not ADMIN_IDS: raise RuntimeError("Укажите ADMIN_IDS")
    await init_db()
    bot=Bot(BOT_TOKEN,default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp=Dispatcher(); dp.include_router(router)
    await bot.set_my_commands([BotCommand(command="start",description="Открыть ERUDIT STUDIO"),BotCommand(command="admin",description="Админ-панель")])
    await bot.delete_webhook(drop_pending_updates=True)
    me=await bot.get_me(); print(f"ERUDIT STUDIO BOT запущен ✅ @{me.username} ({me.id})")
    try: await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types())
    finally: await bot.session.close()

if __name__=="__main__": asyncio.run(main())
