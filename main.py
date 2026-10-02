import asyncio
import logging
import io
import pandas as pd
import html
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from config import BOT_TOKEN, ADMIN_ID, CHANNEL_USERNAME
from database import (
    init_db, AsyncSessionLocal, User, Grade, Subject, Lesson, FileItem, TeacherSubject, Assignment, Submission, Attendance,
    delete_grade, delete_subject, delete_lesson, delete_file_item,
    update_subject_name, update_lesson_name, increment_file_views,
    get_dashboard_stats, get_top_viewed_files, get_all_user_ids,
    get_teacher_allowed_subjects, assign_subject_to_teacher,
    get_all_teachers_with_subjects, remove_teacher_permission,
    is_student_subscribed, get_user_subscriptions,
    create_subscription_code, redeem_subscription_code, check_or_use_free_lecture, get_unused_codes,
    update_teacher_profile, get_all_teachers_list, get_teacher_details,
    get_classified_students, get_student_profile, toggle_block_user, search_user_by_query,
    get_broadcast_target_ids, export_all_data_for_excel,
    create_assignment, submit_assignment, grade_submission, record_attendance, get_student_grades, get_student_attendance
)

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ==================== حالات FSM ====================
class AdminStates(StatesGroup):
    waiting_for_grade_name = State()
    waiting_for_subject_name = State()
    waiting_for_lesson_title = State()
    waiting_for_file = State()
    waiting_for_new_subject_name = State()
    waiting_for_new_lesson_title = State()
    
    # الإذاعة الموجهة
    waiting_for_broadcast_target = State()
    waiting_for_broadcast_subject = State()
    waiting_for_broadcast_message = State()
    
    # إدارة المدرسين
    waiting_for_teacher_id = State()
    waiting_for_teacher_edit_name = State()
    waiting_for_teacher_edit_bio = State()
    waiting_for_teacher_edit_channel = State()
    waiting_for_teacher_edit_notes = State()
    
    # المراسلة المباشرة والبحث
    waiting_for_direct_message = State()
    waiting_for_search_user = State()

    # الواجبات والدرجات والحضور
    waiting_for_assignment_title = State()
    waiting_for_assignment_desc = State()
    waiting_for_grading_score = State()
    waiting_for_attendance_student_id = State()

class StudentStates(StatesGroup):
    waiting_for_search_query = State()
    waiting_for_sub_code = State()
    waiting_for_assignment_file = State()

def get_cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ إلغاء العملية")]],
        resize_keyboard=True
    )

def get_main_keyboard(user_id: int, is_admin: bool = False, is_teacher: bool = False):
    is_super = str(user_id) == str(ADMIN_ID)
    
    if is_teacher and not is_super and not is_admin:
        buttons = [
            [KeyboardButton(text="⚙️ لوحة تحكم إدارة المحتوى")],
            [KeyboardButton(text="👨‍🏫 أدوات المدرس (الواجبات والحضور)")],
            [KeyboardButton(text="ℹ️ عن المنصة")]
        ]
        return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

    buttons = [
        [KeyboardButton(text="🎓 المراحل الدراسية"), KeyboardButton(text="📊 لوحة الطالب (Dashboard)")],
        [KeyboardButton(text="⭐ الأساتذة والاشتراك"), KeyboardButton(text="📋 اشتراكاتي")],
        [KeyboardButton(text="🔍 بحث عن درس/ملف"), KeyboardButton(text="📞 الدعم والاتصال")],
        [KeyboardButton(text="ℹ️ عن المنصة")]
    ]
    if is_admin or is_super:
        buttons.append([KeyboardButton(text="⚙️ لوحة تحكم إدارة المحتوى")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

@dp.message(F.text == "❌ إلغاء العملية")
async def cancel_handler(message: types.Message, state: FSMContext):
    u_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        u_res = await session.execute(select(User).where(User.id == u_id))
        u = u_res.scalar_one_or_none()
        is_admin = u.is_admin if u else False
        is_teacher = u.is_teacher if u else False

    await state.clear()
    await message.answer("✅ تم إلغاء العملية الحالية والعودة للقائمة الرئيسية.", reply_markup=get_main_keyboard(u_id, is_admin, is_teacher))

# --- فحص الاشتراكات والمستخدمين المحظورين ---

async def is_user_subscribed(user_id: int) -> bool:
    if str(user_id) == str(ADMIN_ID):
        return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ["creator", "administrator", "member"]
    except Exception as e:
        logging.error(f"Error checking channel subscription: {e}")
        return False

def get_join_channel_keyboard():
    channel_url = f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}"
    buttons = [
        [InlineKeyboardButton(text="📢 اشترك بالقناة الآن", url=channel_url)],
        [InlineKeyboardButton(text="🔄 تم الاشتراك (تحقق)", callback_data="check_subscription")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.callback_query(F.data == "check_subscription")
async def check_sub_callback(callback: types.CallbackQuery):
    if await is_user_subscribed(callback.from_user.id):
        await callback.message.delete()
        await callback.message.answer("✅ شكرًا لاشتراكك! يمكنك الآن استخدام خدمات البوت بالكامل.")
    else:
        await callback.answer("❌ لم تقم بالاشتراك في القناة بعد! يرجى الانضمام أولاً.", show_alert=True)

@dp.message.middleware()
async def check_subscription_and_block_middleware(handler, event: types.Message, data):
    user_id = event.from_user.id
    
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(User).where(User.id == user_id))
        u = res.scalar_one_or_none()
        if u and u.is_blocked:
            await event.answer("❌ تم حظر حسابك من استخدام هذا البوت بقرار من الإدارة.")
            return

    if not await is_user_subscribed(user_id):
        text = (
            f"⚠️️ **عذراً عزيزي الطالب!**\n\n"
            f"لاستخدام البوت والاستفادة من الملخصات والمحاضرات، يرجى الاشتراك أولاً في قناة المنصة الرسمية:\n"
            f"👉 {CHANNEL_USERNAME}"
        )
        await event.answer(text, reply_markup=get_join_channel_keyboard(), parse_mode="Markdown")
        return
    return await handler(event, data)

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    user_id = message.from_user.id
    full_name = message.from_user.full_name
    username = message.from_user.username
    is_super_admin = str(user_id) == str(ADMIN_ID)

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            new_user = User(id=user_id, full_name=full_name, username=username, is_admin=is_super_admin, is_teacher=is_super_admin)
            session.add(new_user)
            await session.commit()
            is_admin, is_teacher = is_super_admin, is_super_admin
        else:
            user.full_name = full_name
            user.username = username
            await session.commit()
            is_admin, is_teacher = user.is_admin or is_super_admin, user.is_teacher or is_super_admin

    welcome_text = (
        f"✨ **أهلاً بك يا {full_name} في منصة النخبة التعليمية (E E P)** 🎓\n\n"
        f"💡 **تنويه متاح لك:** يمكنك مشاهدة **محاضرة واحدة من اختيارك مجاناً** بالكامل التجريبية قبل الاشتراك!\n\n"
        f"تصفح المواد والدروس عبر الأزرار أدناه، أو ادخل كود الاشتراك عند طلب المادة."
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard(user_id, is_admin, is_teacher), parse_mode="Markdown")

# --- إرسال المرفقات المعالج ---
async def send_file_item_to_user(message_or_callback, f: FileItem):
    await increment_file_views(f.id)
    views = (f.views_count or 0) + 1
    caption = f"📌 **{f.title}**\n\n👁️️ عدد المشاهدات: `{views}`"

    target = message_or_callback.message if isinstance(message_or_callback, types.CallbackQuery) else message_or_callback

    if f.file_type == "text":
        await target.answer(f"📝 **{f.title}**\n\n👁️ عدد المشاهدات: `{views}`", parse_mode="Markdown")
    elif f.file_type == "document":
        await target.answer_document(f.file_id, caption=caption, parse_mode="Markdown", protect_content=True)
    elif f.file_type == "photo":
        await target.answer_photo(f.file_id, caption=caption, parse_mode="Markdown", protect_content=True)
    elif f.file_type == "video":
        await target.answer_video(f.file_id, caption=caption, parse_mode="Markdown", protect_content=True)
    elif f.file_type == "voice":
        await target.answer_voice(f.file_id, caption=caption, parse_mode="Markdown", protect_content=True)
    elif f.file_type == "audio":
        await target.answer_audio(f.file_id, caption=caption, parse_mode="Markdown", protect_content=True)

# ==================== أقسام الطالب العامة والتفاعلية ====================

@dp.message(F.text == "📊 لوحة الطالب (Dashboard)")
async def student_dashboard(message: types.Message):
    u_id = message.from_user.id
    subs = await get_user_subscriptions(u_id)
    grades = await get_student_grades(u_id)
    attendance = await get_student_attendance(u_id)

    total_subs = len(subs)
    total_assignments = len(grades)
    attendance_count = len(attendance)
    present_count = sum(1 for a in attendance if a["status"] == "حاضر")
    attendance_rate = (present_count / attendance_count * 100) if attendance_count > 0 else 100.0

    text = (
        f"📊 **لوحة تحكم الطالب (Student Dashboard)** 🎓\n\n"
        f"📚 **المقررات المسجل فيها:** `{total_subs}` مادة\n"
        f"📝 **الواجبات والأنشطة المسلمة:** `{total_assignments}` واجب\n"
        f"📈 **نسبة الحضور العامة:** `{attendance_rate:.1f}%`\n\n"
        f"اختر أحد الخيارات أدناه لمتابعة أنشطتك الأكاديمية:"
    )

    buttons = [
        [InlineKeyboardButton(text="📝 تسليم واجب جديد", callback_data="st_submit_assignment_menu")],
        [InlineKeyboardButton(text="💯 كشف الدرجات والتقييمات", callback_data="st_view_grades")],
        [InlineKeyboardButton(text="📅 سجل الحضور والغياب", callback_data="st_view_attendance")]
    ]
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")

@dp.callback_query(F.data == "st_view_grades")
async def view_student_grades_action(callback: types.CallbackQuery):
    grades = await get_student_grades(callback.from_user.id)
    if not grades:
        await callback.message.answer("ℹ️ لا توجد تقييمات أو درجات مرصودة لك حالياً.")
        await callback.answer()
        return

    text = "💯 **كشف الدرجات والتقييمات الخاص بك:**\n\n"
    for g in grades:
        score_str = f"{g['score']}/{g['max_score']}" if g['score'] is not None else "قيد التصحيح"
        text += f"• 📘 **المادة:** {g['subject']}\n  📝 **الواجب:** {g['assignment']}\n  📊 **الدرجة:** `{score_str}`\n  💬 **ملاحظات المدرس:** {g['feedback']}\n-------------------\n"

    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "st_view_attendance")
async def view_student_attendance_action(callback: types.CallbackQuery):
    records = await get_student_attendance(callback.from_user.id)
    if not records:
        await callback.message.answer("ℹ️ لا توجد سجلات حضور ورصد لك حتى الآن.")
        await callback.answer()
        return

    text = "📅 **سجل الحضور والغياب التفصيلي:**\n\n"
    for r in records:
        st_icon = "✅" if r['status'] == "حاضر" else "❌"
        text += f"• 📘 **المادة:** {r['subject']} | الحالة: {st_icon} `{r['status']}` | التاريخ: {r['date']}\n"

    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "st_submit_assignment_menu")
async def student_submit_assignment_menu(callback: types.CallbackQuery):
    u_id = callback.from_user.id
    subs = await get_user_subscriptions(u_id)
    if not subs:
        await callback.message.answer("⚠️ يجب أن تكون مشتركاً في مادة لتسليم الواجبات الخاصة بها.")
        await callback.answer()
        return

    async with AsyncSessionLocal() as session:
        sub_ids = [s["subject_id"] for s in subs]
        res = await session.execute(select(Assignment).where(Assignment.subject_id.in_(sub_ids)))
        assignments = res.scalars().all()

    if not assignments:
        await callback.message.answer("ℹ️ لا توجد واجبات مطلوبة للتسليم حالياً.")
        await callback.answer()
        return

    builder = [[InlineKeyboardButton(text=f"📝 {a.title}", callback_data=f"st_sub_ass_{a.id}")] for a in assignments]
    await callback.message.answer("📝 **اختر الواجب المراد تسليمه:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("st_sub_ass_"))
async def start_student_sub_ass(callback: types.CallbackQuery, state: FSMContext):
    ass_id = int(callback.data.split("_")[3])
    await state.update_data(target_ass_id=ass_id)
    await callback.message.answer("📤 **قم برفع وإرسال ملف الواجب الآن (PDF / Word / صورة):**", reply_markup=get_cancel_keyboard())
    await state.set_state(StudentStates.waiting_for_assignment_file)
    await callback.answer()

@dp.message(StudentStates.waiting_for_assignment_file)
async def process_student_assignment_upload(message: types.Message, state: FSMContext):
    data = await state.get_data()
    ass_id = data.get("target_ass_id")
    file_id, file_type = None, "document"

    if message.document: file_id, file_type = message.document.file_id, "document"
    elif message.photo: file_id, file_type = message.photo[-1].file_id, "photo"
    else:
        await message.answer("⚠️ يرجى رفع ملف أو صورة كواجب مادة!")
        return

    success = await submit_assignment(ass_id, message.from_user.id, file_id, file_type)
    if success:
        await message.answer("✅ **تم تسليم الواجب بنجاح بنظام المتابعة!**", reply_markup=get_main_keyboard(message.from_user.id))
    else:
        await message.answer("❌ حدث خطأ أثناء التسليم.")
    await state.clear()

@dp.message(F.text == "⭐ الأساتذة والاشتراك")
async def show_teachers_subscription(message: types.Message):
    teachers = await get_all_teachers_with_subjects()
    if not teachers:
        await message.answer("ℹ️ لا يوجد أساتذة مضافون حالياً للاشتراك معهم.")
        return

    builder = []
    user_id = message.from_user.id
    for item in teachers:
        subscribed = await is_student_subscribed(user_id, item["subject_id"])
        sub_status = "✅ مشترك" if subscribed else "🔑 ادخل كود الاشتراك"
        btn_text = f"👨‍🏫 {item['teacher_name']} - 📘 {item['subject_name']} ({sub_status})"
        builder.append([InlineKeyboardButton(text=btn_text, callback_data=f"enter_code_sub_{item['subject_id']}")])

    await message.answer(
        "⭐ **قائمة الأساتذة والمواد المتاحة للاشتراك:**\nاضغط على مادة الأستاذ لإدخال كود الاشتراك الخاص بها:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=builder),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("enter_code_sub_"))
async def prompt_for_code(callback: types.CallbackQuery, state: FSMContext):
    subject_id = int(callback.data.split("_")[3])
    user_id = callback.from_user.id

    if await is_student_subscribed(user_id, subject_id):
        await callback.answer("✅ أنت مشترك بالفعل في هذه المادة!", show_alert=True)
        return

    await state.update_data(target_subject_id=subject_id)
    await callback.message.answer(
        "🔑 **يرجى إرسال رمز/كود الاشتراك الخاص بالمادة:**\n\n"
        "💡 يمكنك الحصول على الكود من إدارة المنصة أو المدرس مباشرة.",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await state.set_state(StudentStates.waiting_for_sub_code)
    await callback.answer()

@dp.message(StudentStates.waiting_for_sub_code)
async def process_student_sub_code(message: types.Message, state: FSMContext):
    code_text = message.text.strip()
    data = await state.get_data()
    subject_id = data.get("target_subject_id")

    if not subject_id:
        await message.answer("❌ حدث خطأ، يرجى إعادة اختيار المادة من البداية.")
        await state.clear()
        return

    success, response_msg = await redeem_subscription_code(message.from_user.id, subject_id, code_text)
    if success:
        await message.answer(response_msg, reply_markup=get_main_keyboard(message.from_user.id))
        await state.clear()
    else:
        await message.answer(f"{response_msg}\n\nيرجى إعادة كتابة الرمز الصحيح أو الضغط على إلغاء:", reply_markup=get_cancel_keyboard())

@dp.message(F.text == "📋 اشتراكاتي")
async def show_my_subscriptions(message: types.Message):
    subs = await get_user_subscriptions(message.from_user.id)
    if not subs:
        await message.answer("ℹ️ أنت غير مشترك في أي مادة حالياً. يمكنك الاشتراك بالأكواد عبر قسم '⭐ الأساتذة والاشتراك'.")
        return

    text = "📋 **المواد والأساتذة المشترك معهم حالياً:**\n\n"
    builder = []
    for s in subs:
        text += f"• 📘 **{s['subject_name']}** (الأستاذ: {s['teacher_name']}) | نوع الاشتراك: `{s['sub_type']}`\n"
        builder.append([InlineKeyboardButton(text=f"📖 تصفح دروس {s['subject_name']}", callback_data=f"show_lessons_{s['subject_id']}")])

    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")

@dp.message(F.text == "🎓 المراحل الدراسية")
async def show_grades(message: types.Message):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Grade))
        grades = result.scalars().all()

        if not grades:
            await message.answer("ℹ️ لا توجد أي مراحل دراسية مضافة حتى الآن.")
            return

        builder = [[InlineKeyboardButton(text=f"📚 {g.name}", callback_data=f"show_subjects_{g.id}")] for g in grades]
        await message.answer("📌 **يرجى اختيار المرحلة الدراسية:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("show_subjects_"))
async def show_subjects(callback: types.CallbackQuery):
    grade_id = int(callback.data.split("_")[2])
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Subject).where(Subject.grade_id == grade_id))
        subjects = result.scalars().all()

        if not subjects:
            await callback.message.answer("⚠️ لا توجد مواد مضافة لهذه المرحلة حالياً.")
            await callback.answer()
            return

        builder = []
        for s in subjects:
            ts_res = await session.execute(
                select(User).join(TeacherSubject, TeacherSubject.teacher_id == User.id).where(TeacherSubject.subject_id == s.id)
            )
            teacher = ts_res.scalar_one_or_none()
            t_name = f" ({teacher.approved_name or teacher.full_name})" if teacher else ""
            builder.append([InlineKeyboardButton(text=f"📖 {s.name}{t_name}", callback_data=f"show_lessons_{s.id}")])

        await callback.message.answer("📘 **اختر المادة الدراسية:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
        await callback.answer()

@dp.callback_query(F.data.startswith("show_lessons_"))
async def show_lessons(callback: types.CallbackQuery):
    subject_id = int(callback.data.split("_")[2])
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Lesson).where(Lesson.subject_id == subject_id))
        lessons = result.scalars().all()

        if not lessons:
            await callback.message.answer("⚠️ لا توجد محاضرات أو دروس مضافة لهذه المادة بعد.")
            await callback.answer()
            return

        builder = [[InlineKeyboardButton(text=f"📝 {l.title}", callback_data=f"show_files_{l.id}")] for l in lessons]
        await callback.message.answer("📜 **فهرست المحاضرات والدروس المتاحة:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
        await callback.answer()

@dp.callback_query(F.data.startswith("show_files_"))
async def show_files(callback: types.CallbackQuery, state: FSMContext):
    lesson_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id

    async with AsyncSessionLocal() as session:
        res = await session.execute(select(Lesson).where(Lesson.id == lesson_id))
        lesson = res.scalar_one_or_none()
        if not lesson:
            await callback.answer("❌ الدرس غير موجود.", show_alert=True)
            return
        subject_id = lesson.subject_id

        allowed_subs = await get_teacher_allowed_subjects(user_id)
        is_owner_teacher = subject_id in allowed_subs

    is_subbed = await is_student_subscribed(user_id, subject_id)
    
    if not is_subbed and str(user_id) != str(ADMIN_ID) and not is_owner_teacher:
        used_free_now = await check_or_use_free_lecture(user_id)
        if used_free_now:
            await callback.message.answer("🎁 **لقد استخدمت حقك في مشاهدة هذه المحاضرة مجاناً بتجربة مفتوحة!**\nشاهد المرفقات أدناه:")
        else:
            await state.update_data(target_subject_id=subject_id)
            builder = [[InlineKeyboardButton(text="🔑 أدخل كود الاشتراك", callback_data=f"enter_code_sub_{subject_id}")]]
            await callback.message.answer(
                "🔒 **هذه المحاضرة محمية ومتاحة للمشتركين فقط!**\n\n"
                "لقد استنفدت المحاضرة المجانية التجريبية سابقاً.\n"
                "يرجى الاشتراك بالرمز لمتابعة باقي دروس هذه المادة.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=builder),
                parse_mode="Markdown"
            )
            await callback.answer()
            return

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(FileItem).where(FileItem.lesson_id == lesson_id))
        files = result.scalars().all()

        if not files:
            await callback.message.answer("⚠️ لا توجد منشورات أو ملخصات مرفوعة لهذه المحاضرة حالياً.")
            await callback.answer()
            return

        await callback.message.answer("📂 **المحتويات والمرفقات المتاحة للمشاهدة:**")
        for f in files:
            await send_file_item_to_user(callback, f)

        await callback.answer()

@dp.message(F.text == "🔍 بحث عن درس/ملف")
async def start_search(message: types.Message, state: FSMContext):
    await message.answer("🔎 **اكتب كلمة البحث (اسم المحاضرة، الموضوع، أو اسم المادة):**", reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
    await state.set_state(StudentStates.waiting_for_search_query)

@dp.message(StudentStates.waiting_for_search_query)
async def process_search(message: types.Message, state: FSMContext):
    query = message.text.strip()
    async with AsyncSessionLocal() as session:
        lessons_res = await session.execute(
            select(Lesson)
            .options(selectinload(Lesson.subject).selectinload(Subject.grade))
            .where(Lesson.title.ilike(f"%{query}%"))
        )
        lessons = lessons_res.scalars().all()

        files_res = await session.execute(
            select(FileItem)
            .options(selectinload(FileItem.lesson).selectinload(Lesson.subject).selectinload(Subject.grade))
            .where(FileItem.title.ilike(f"%{query}%"))
        )
        files = files_res.scalars().all()

        if not lessons and not files:
            await message.answer("❌ لم يتم العثور على أي نتائج تطابق بحثك.", reply_markup=get_main_keyboard(message.from_user.id))
            await state.clear()
            return

        builder = []
        for l in lessons:
            grade_name = l.subject.grade.name if l.subject and l.subject.grade else ""
            subject_name = l.subject.name if l.subject else ""
            btn_text = f"📝 [{grade_name} ➔ {subject_name}] ➔ {l.title}"
            builder.append([InlineKeyboardButton(text=btn_text, callback_data=f"show_files_{l.id}")])

        for f in files:
            lesson = f.lesson
            subject = lesson.subject if lesson else None
            grade = subject.grade if subject else None
            g_name = grade.name if grade else ""
            s_name = subject.name if subject else ""
            l_name = lesson.title if lesson else ""

            btn_text = f"📂 [{g_name} ➔ {s_name} ➔ {l_name}] ➔ {f.title[:25]}"
            builder.append([InlineKeyboardButton(text=btn_text, callback_data=f"get_single_file_{f.id}")])

        await message.answer(
            f"🔎 **نتائج البحث عن:** `{query}`:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=builder),
            parse_mode="Markdown"
        )
        await state.clear()

@dp.callback_query(F.data.startswith("get_single_file_"))
async def get_single_file(callback: types.CallbackQuery, state: FSMContext):
    file_item_id = int(callback.data.split("_")[3])
    user_id = callback.from_user.id

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(FileItem).options(selectinload(FileItem.lesson)).where(FileItem.id == file_item_id))
        f = result.scalar_one_or_none()

        if not f:
            await callback.message.answer("❌ المحتوى غير موجود أو تم حذفه.")
            await callback.answer()
            return
        subject_id = f.lesson.subject_id if f.lesson else None

    if subject_id and not await is_student_subscribed(user_id, subject_id) and str(user_id) != str(ADMIN_ID):
        used_free_now = await check_or_use_free_lecture(user_id)
        if not used_free_now:
            await callback.message.answer("🔒 هذا المحتوى تابع لمادة تتطلب اشتراكاً عبر كود.")
            await callback.answer()
            return

    await send_file_item_to_user(callback, f)
    await callback.answer()

# ==================== أدوات المدرس (الواجبات والحضور) ====================

@dp.message(F.text == "👨‍🏫 أدوات المدرس (الواجبات والحضور)")
async def teacher_tools_menu(message: types.Message):
    u_id = message.from_user.id
    allowed_subs = await get_teacher_allowed_subjects(u_id)
    if not allowed_subs and str(u_id) != str(ADMIN_ID):
        await message.answer("⚠️ هذه اللوحة مخصصة للأساتذة المسندة إليهم مواد فقط.")
        return

    buttons = [
        [InlineKeyboardButton(text="➕ إنشاء واجب جديد", callback_data="tch_create_ass")],
        [InlineKeyboardButton(text="💯 تصحيح تسليمات الطلاب", callback_data="tch_grade_submissions")],
        [InlineKeyboardButton(text="📝 رصد الحضور والغياب", callback_data="tch_record_attendance")]
    ]
    await message.answer("👨‍🏫 **أدوات وإدارة المدرس الفعالة:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")

@dp.callback_query(F.data == "tch_create_ass")
async def tch_create_assignment_start(callback: types.CallbackQuery, state: FSMContext):
    u_id = callback.from_user.id
    allowed_ids = await get_teacher_allowed_subjects(u_id)
    
    async with AsyncSessionLocal() as session:
        if str(u_id) == str(ADMIN_ID):
            subjects = (await session.execute(select(Subject))).scalars().all()
        else:
            subjects = (await session.execute(select(Subject).where(Subject.id.in_(allowed_ids)))).scalars().all()

    if not subjects:
        await callback.message.answer("⚠️ لا توجد مواد مسندة إليك.")
        await callback.answer()
        return

    builder = [[InlineKeyboardButton(text=f"📘 {s.name}", callback_data=f"tch_ass_sub_{s.id}")] for s in subjects]
    await callback.message.answer("📘 **اختر المادة لإنشاء الواجب:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("tch_ass_sub_"))
async def tch_ass_sub_selected(callback: types.CallbackQuery, state: FSMContext):
    sub_id = int(callback.data.split("_")[3])
    await state.update_data(ass_subject_id=sub_id)
    await callback.message.answer("✏️ **أرسل عنوان الواجب/النشاط:**", reply_markup=get_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_assignment_title)
    await callback.answer()

@dp.message(AdminStates.waiting_for_assignment_title)
async def save_ass_title(message: types.Message, state: FSMContext):
    await state.update_data(ass_title=message.text.strip())
    await message.answer("📝 **أرسل الآن وصف الواجب أو التعليمات للطلاب:**", reply_markup=get_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_assignment_desc)

@dp.message(AdminStates.waiting_for_assignment_desc)
async def save_ass_desc(message: types.Message, state: FSMContext):
    data = await state.get_data()
    sub_id = data.get("ass_subject_id")
    title = data.get("ass_title")
    desc = message.text.strip()

    ass_id = await create_assignment(title, desc, sub_id)
    if ass_id:
        await message.answer("✅ **تم إنشاء الواجب بنجاح وإتاحته للطلاب!**", reply_markup=get_main_keyboard(message.from_user.id))
    else:
        await message.answer("❌ حدث خطأ أثناء إنشاء الواجب.")
    await state.clear()

@dp.callback_query(F.data == "tch_grade_submissions")
async def tch_grade_submissions_list(callback: types.CallbackQuery):
    async with AsyncSessionLocal() as session:
        res = await session.execute(
            select(Submission, Assignment, User)
            .join(Assignment, Submission.assignment_id == Assignment.id)
            .join(User, Submission.student_id == User.id)
            .where(Submission.score == None)
        )
        unreviewed = res.all()

    if not unreviewed:
        await callback.message.answer("🎉 لا توجد تسليمات غير مصححة حالياً.")
        await callback.answer()
        return

    builder = []
    for sub, ass, st in unreviewed:
        btn_text = f"👤 {st.full_name or st.id} - 📝 {ass.title}"
        builder.append([InlineKeyboardButton(text=btn_text, callback_data=f"grade_sub_item_{sub.id}")])

    await callback.message.answer("💯 **اختر التسليم لتصحيحه وإرسال الدرجة:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("grade_sub_item_"))
async def preview_and_grade_submission(callback: types.CallbackQuery, state: FSMContext):
    sub_id = int(callback.data.split("_")[3])
    await state.update_data(target_sub_id=sub_id)

    async with AsyncSessionLocal() as session:
        res = await session.execute(select(Submission).where(Submission.id == sub_id))
        sub = res.scalar_one_or_none()

    if sub and sub.file_id:
        await callback.message.answer_document(sub.file_id, caption="📄 **ملف الواجب المرفوع من الطالب**")

    await callback.message.answer("✏️ **أرسل الدرجة المستحقة للطالب (مثال: 85):**", reply_markup=get_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_grading_score)
    await callback.answer()

@dp.message(AdminStates.waiting_for_grading_score)
async def save_grading_score(message: types.Message, state: FSMContext):
    try:
        score = float(message.text.strip())
        data = await state.get_data()
        sub_id = data.get("target_sub_id")

        success = await grade_submission(sub_id, score, "تم التصحيح والاعتماد بواسطة المدرس.")
        if success:
            await message.answer("✅ **تم رصد الدرجة وإرسالها لكشف طالبك بنجاح!**", reply_markup=get_main_keyboard(message.from_user.id))
        else:
            await message.answer("❌ حدث خطأ أثناء رصد الدرجة.")
    except ValueError:
        await message.answer("⚠️ يرجى إدخال رقم صحيح للدرجة.")
        return
    await state.clear()

@dp.callback_query(F.data == "tch_record_attendance")
async def tch_record_attendance_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📌 **أرسل معرّف ID الطالب لرصد حضوره بالمحاضرة:**", reply_markup=get_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_attendance_student_id)
    await callback.answer()

@dp.message(AdminStates.waiting_for_attendance_student_id)
async def process_attendance_record(message: types.Message, state: FSMContext):
    try:
        st_id = int(message.text.strip())
        u_id = message.from_user.id
        allowed = await get_teacher_allowed_subjects(u_id)
        sub_id = allowed[0] if allowed else 1

        await record_attendance(st_id, sub_id, "حاضر")
        await message.answer(f"✅ **تم رصد حضور الطالب (`{st_id}`) بنجاح!**", reply_markup=get_main_keyboard(message.from_user.id), parse_mode="Markdown")
    except ValueError:
        await message.answer("❌ رقم ID غير صالح.")
    await state.clear()

# ==================== لوحة التحكم المحدثة ====================

@dp.message(F.text.contains("⚙️ لوحة تحكم إدارة المحتوى"))
async def admin_panel(message: types.Message):
    u_id = message.from_user.id
    is_super = str(u_id) == str(ADMIN_ID)

    async with AsyncSessionLocal() as session:
        res = await session.execute(select(User).where(User.id == u_id))
        user = res.scalar_one_or_none()

    if not is_super and not (user and (user.is_admin or user.is_teacher)):
        await message.answer("عذراً، هذه اللوحة مخصصة للمشرفين والمدرسين فقط.")
        return

    buttons = []
    if is_super or (user and user.is_admin):
        buttons.append([InlineKeyboardButton(text="👨‍🏫 إدارة المدرسين (Teacher Management)", callback_data="super_teachers_mgr")])
        buttons.append([InlineKeyboardButton(text="👥 إدارة الطلاب والمحادثات", callback_data="super_students_mgr")])
        buttons.append([InlineKeyboardButton(text="📢 نظام الإذاعة الموجهة", callback_data="super_targeted_broadcast")])
        buttons.append([InlineKeyboardButton(text="📊 الإحصائيات وسجل النشاط", callback_data="admin_stats"), InlineKeyboardButton(text="📥 تصدير Excel/CSV", callback_data="admin_export_excel")])
        buttons.append([InlineKeyboardButton(text="🔑 إنشاء كود جديد", callback_data="super_create_code"), InlineKeyboardButton(text="📋 عرض الأكواد", callback_data="super_view_codes")])
        buttons.append([InlineKeyboardButton(text="➕ إضافة مرحلة", callback_data="admin_add_grade"), InlineKeyboardButton(text="📘 إضافة مادة", callback_data="admin_add_subject")])

    if user and user.is_teacher:
        buttons.append([InlineKeyboardButton(text="📚 استعراض محتوياتي المنشورة (معاينة)", callback_data="teacher_my_content")])

    buttons.append([InlineKeyboardButton(text="📝 إضافة درس / محاضرة", callback_data="admin_add_lesson")])
    buttons.append([InlineKeyboardButton(text="📤 نشر محتوى داخل محاضرة", callback_data="admin_add_file")])
    buttons.append([InlineKeyboardButton(text="✏️ تعديل / إعادة تسمية", callback_data="admin_edit_menu")])
    buttons.append([InlineKeyboardButton(text="🗑️ إدارة الحذف", callback_data="admin_delete_menu")])

    await message.answer("⚙️ **لوحة التحكم الشاملة لإدارة المنصة:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")

# --- استعراض المدرس لمحتوياته المخصصة بدون اشتراك ---
@dp.callback_query(F.data == "teacher_my_content")
async def teacher_my_content_view(callback: types.CallbackQuery):
    u_id = callback.from_user.id
    allowed_ids = await get_teacher_allowed_subjects(u_id)

    if not allowed_ids and str(u_id) != str(ADMIN_ID):
        await callback.message.answer("⚠️ ليس لديك أي مواد مخصصة حالياً.")
        await callback.answer()
        return

    async with AsyncSessionLocal() as session:
        if str(u_id) == str(ADMIN_ID):
            subjects = (await session.execute(select(Subject).options(selectinload(Subject.grade)))).scalars().all()
        else:
            subjects = (await session.execute(select(Subject).options(selectinload(Subject.grade)).where(Subject.id.in_(allowed_ids)))).scalars().all()

    if not subjects:
        await callback.message.answer("⚠️ لا توجد مواد مسندة إليك.")
        await callback.answer()
        return

    builder = [[InlineKeyboardButton(text=f"📘 {s.grade.name} ➔ {s.name}", callback_data=f"show_lessons_{s.id}")] for s in subjects]
    await callback.message.answer("📚 **اختر المادة المخصصة لك لاستعراض كافة دروسها ومحتوياتها مجاناً:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
    await callback.answer()

# --- 1. قسم إدارة المدرسين ---

@dp.callback_query(F.data == "super_teachers_mgr")
async def super_teachers_mgr_menu(callback: types.CallbackQuery):
    if str(callback.from_user.id) != str(ADMIN_ID): return

    buttons = [
        [InlineKeyboardButton(text="📜 قائمة المدرسين المعتمدين", callback_data="view_teachers_list")],
        [InlineKeyboardButton(text="➕ تعيين مدرس جديد", callback_data="super_assign_teacher")],
        [InlineKeyboardButton(text="❌ إزالة صلاحية مدرس", callback_data="super_revoke_teacher_menu")]
    ]
    await callback.message.answer("👨‍🏫 **إدارة المدرسين:**\nاختر الإجراء المطلوب أدناه:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "view_teachers_list")
async def view_teachers_list(callback: types.CallbackQuery):
    teachers = await get_all_teachers_list()
    if not teachers:
        await callback.message.answer("ℹ️ لا يوجد مدرسون مضافون حالياً.")
        await callback.answer()
        return

    builder = []
    for t in teachers:
        name = t.approved_name or t.full_name or f"مدرس [{t.id}]"
        builder.append([InlineKeyboardButton(text=f"👨‍🏫 {name}", callback_data=f"teacher_profile_{t.id}")])

    await callback.message.answer("📜 **اختر المدرس لعرض ملفه أو تعديل بياناته:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("teacher_profile_"))
async def teacher_profile_view(callback: types.CallbackQuery):
    t_id = int(callback.data.split("_")[2])
    details = await get_teacher_details(t_id)
    if not details:
        await callback.answer("المدرس غير موجود.", show_alert=True)
        return

    u = details["user"]
    subs_str = ", ".join(details["subjects"]) if details["subjects"] else "لا توجد مواد مسندة"
    
    approved_name = html.escape(str(u.approved_name)) if u.approved_name else 'غير محدد'
    full_name = html.escape(str(u.full_name)) if u.full_name else 'لا يوجد'
    username = html.escape(str(u.username)) if u.username else 'لا يوجد'
    bio = html.escape(str(u.bio)) if u.bio else 'لا يوجد'
    admin_notes = html.escape(str(u.admin_notes)) if u.admin_notes else 'لا يوجد'
    channel_link = html.escape(str(u.channel_link)) if u.channel_link else 'غير محدد'
    subs_escaped = html.escape(subs_str)

    msg = (
        f"👤 <b>ملف المدرس:</b>\n\n"
        f"• <b>الاسم المعتمد:</b> <code>{approved_name}</code>\n"
        f"• <b>اسم التليجرام:</b> {full_name}\n"
        f"• <b>المعرف (Username):</b> @{username}\n"
        f"• <b>ID التليجرام:</b> <code>{u.id}</code>\n"
        f"• <b>المواد التي يدرسها:</b> {subs_escaped}\n"
        f"• <b>رابط القناة:</b> {channel_link}\n"
        f"• <b>نبذة مختصرة:</b> {bio}\n"
        f"• <b>ملاحظات المدير:</b> {admin_notes}"
    )

    builder = [
        [InlineKeyboardButton(text="✏ تعديل الاسم المعتمد", callback_data=f"edit_t_name_{u.id}")],
        [InlineKeyboardButton(text="📝 تعديل النبذة", callback_data=f"edit_t_bio_{u.id}"), InlineKeyboardButton(text="🔗 تعديل رابط القناة", callback_data=f"edit_t_chan_{u.id}")],
        [InlineKeyboardButton(text="📌 تعديل ملاحظات الأدمن", callback_data=f"edit_t_notes_{u.id}")],
        [InlineKeyboardButton(text="🔙 العودة للقائمة", callback_data="view_teachers_list")]
    ]
    await callback.message.answer(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_t_name_"))
async def start_edit_t_name(callback: types.CallbackQuery, state: FSMContext):
    t_id = int(callback.data.split("_")[3])
    await state.update_data(target_t_id=t_id)
    await callback.message.answer("✏️ **أرسل الآن الاسم المعتمد/الحقيقي الجديد للمدرس:**", reply_markup=get_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_teacher_edit_name)
    await callback.answer()

@dp.message(AdminStates.waiting_for_teacher_edit_name)
async def save_t_name(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await update_teacher_profile(data["target_t_id"], approved_name=message.text.strip())
    await message.answer("✅ تم تحديث الاسم المعتمد بنجاح!", reply_markup=get_main_keyboard(message.from_user.id))
    await state.clear()

@dp.callback_query(F.data.startswith("edit_t_bio_"))
async def start_edit_t_bio(callback: types.CallbackQuery, state: FSMContext):
    t_id = int(callback.data.split("_")[3])
    await state.update_data(target_t_id=t_id)
    await callback.message.answer("📝 **أرسل النبذة المختصرة الخاصة بالمدرس:**", reply_markup=get_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_teacher_edit_bio)
    await callback.answer()

@dp.message(AdminStates.waiting_for_teacher_edit_bio)
async def save_t_bio(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await update_teacher_profile(data["target_t_id"], bio=message.text.strip())
    await message.answer("✅ تم تحديث نبذة المدرس بنجاح!", reply_markup=get_main_keyboard(message.from_user.id))
    await state.clear()

@dp.callback_query(F.data.startswith("edit_t_chan_"))
async def start_edit_t_chan(callback: types.CallbackQuery, state: FSMContext):
    t_id = int(callback.data.split("_")[3])
    await state.update_data(target_t_id=t_id)
    await callback.message.answer("🔗 **أرسل رابط القناة الرسمية للمدرس:**", reply_markup=get_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_teacher_edit_channel)
    await callback.answer()

@dp.message(AdminStates.waiting_for_teacher_edit_channel)
async def save_t_chan(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await update_teacher_profile(data["target_t_id"], channel_link=message.text.strip())
    await message.answer("✅ تم تحديث رابط القناة بنجاح!", reply_markup=get_main_keyboard(message.from_user.id))
    await state.clear()

@dp.callback_query(F.data.startswith("edit_t_notes_"))
async def start_edit_t_notes(callback: types.CallbackQuery, state: FSMContext):
    t_id = int(callback.data.split("_")[3])
    await state.update_data(target_t_id=t_id)
    await callback.message.answer("📌 **أرسل الملاحظات الخاصة بالإدارة بخصوص هذا المدرس:**", reply_markup=get_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_teacher_edit_notes)
    await callback.answer()

@dp.message(AdminStates.waiting_for_teacher_edit_notes)
async def save_t_notes(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await update_teacher_profile(data["target_t_id"], notes=message.text.strip())
    await message.answer("✅ تم تحديث الملاحظات بنجاح!", reply_markup=get_main_keyboard(message.from_user.id))
    await state.clear()

# --- 2. قسم إدارة الطلاب والمحادثات المباشرة والحظر ---

@dp.callback_query(F.data == "super_students_mgr")
async def super_students_mgr_menu(callback: types.CallbackQuery):
    if str(callback.from_user.id) != str(ADMIN_ID): return

    buttons = [
        [InlineKeyboardButton(text="⭐ الطلاب المشتركون", callback_data="view_students_subbed")],
        [InlineKeyboardButton(text="🆓 الطلاب غير المشتركين (المجانيين)", callback_data="view_students_unsubbed")],
        [InlineKeyboardButton(text="🔎 البحث السريع عن طالب (ID / Username)", callback_data="search_student_start")]
    ]
    await callback.message.answer("👥 **إدارة الطلاب والمحادثات:**\nاختر الفئة المطلوبة:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.in_(["view_students_subbed", "view_students_unsubbed"]))
async def view_students_list(callback: types.CallbackQuery):
    subbed, unsubbed = await get_classified_students()
    students = subbed if callback.data == "view_students_subbed" else unsubbed
    title = "⭐ قائمة الطلاب المشتركين:" if callback.data == "view_students_subbed" else "🆓 قائمة الطلاب غير المشتركين:"

    if not students:
        await callback.message.answer("ℹ️ لا يوجد طلاب في هذه القائمة حالياً.")
        await callback.answer()
        return

    builder = []
    for s in students[:50]:
        st_name = s.full_name or f"طالب [{s.id}]"
        builder.append([InlineKeyboardButton(text=f"👤 {st_name}", callback_data=f"student_profile_{s.id}")])

    await callback.message.answer(f"📋 **{title}**\n(انقر على اسم الطالب لمراسلته أو عرض ملفه)", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "search_student_start")
async def search_student_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🔎 **أرسل الآن User ID أو Username أو اسم الطالب:**", reply_markup=get_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_search_user)
    await callback.answer()

@dp.message(AdminStates.waiting_for_search_user)
async def process_search_student(message: types.Message, state: FSMContext):
    users = await search_user_by_query(message.text)
    if not users:
        await message.answer("❌ لم يتم العثور على نتائج للبحث.", reply_markup=get_main_keyboard(message.from_user.id))
        await state.clear()
        return

    builder = []
    for u in users:
        name = u.full_name or f"مستخدم [{u.id}]"
        builder.append([InlineKeyboardButton(text=f"👤 {name} (@{u.username})", callback_data=f"student_profile_{u.id}")])

    await message.answer("🔍 **نتائج البحث:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder))
    await state.clear()

@dp.callback_query(F.data.startswith("student_profile_"))
async def view_student_profile(callback: types.CallbackQuery):
    s_id = int(callback.data.split("_")[2])
    profile = await get_student_profile(s_id)

    if not profile:
        await callback.answer("الطالب غير موجود.", show_alert=True)
        return

    u = profile["user"]
    subs_str = "\n".join([f"• {s['subject']} ({'شهري' if s['type'] == 'monthly' else 'كامل'})" for s in profile["subscriptions"]]) or "لا توجد اشتراكات"
    codes_str = "\n".join([f"• `{c['code']}` مادة: {c['subject']}" for c in profile["used_codes"]]) or "لا توجد أكواد مفعّلة"

    block_status = "🔴 محظور" if u.is_blocked else "🟢 نشط"
    free_lecture_status = "✅ استهلك المحاضرة المجانية" if u.has_used_free_lecture else "❌ لم يستعملها بعد"

    msg = (
        f"👤 **ملف الطالب التفصيلي:**\n\n"
        f"• **الاسم:** {u.full_name or 'غير محدد'}\n"
        f"• **المعرف:** @{u.username if u.username else 'لا يوجد'}\n"
        f"• **ID:** `{u.id}`\n"
        f"• **حالة الحساب:** {block_status}\n"
        f"• **تاريخ الانضمام:** `{u.created_at.strftime('%Y-%m-%d') if u.created_at else 'غير مسجل'}`\n"
        f"• **المحاضرة المجانية:** {free_lecture_status}\n\n"
        f"📚 **الاشتراكات الفعّالة:**\n{subs_str}\n\n"
        f"🔑 **الأكواد المستخدمة:**\n{codes_str}"
    )

    block_btn_text = "🟢 إلغاء الحظر" if u.is_blocked else "🔴 حظر الطالب"
    builder = [
        [InlineKeyboardButton(text="💬 إرسال رسالة مباشرة بالطالب", callback_data=f"direct_msg_{u.id}")],
        [InlineKeyboardButton(text=block_btn_text, callback_data=f"toggle_block_{u.id}")],
        [InlineKeyboardButton(text="🔙 العودة", callback_data="super_students_mgr")]
    ]
    await callback.message.answer(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("toggle_block_"))
async def toggle_block_action(callback: types.CallbackQuery):
    s_id = int(callback.data.split("_")[2])
    is_blocked = await toggle_block_user(s_id)
    status_text = "تم حظر الطالب بنجاح 🔴" if is_blocked else "تم إلغاء حظر الطالب بنجاح 🟢"
    await callback.answer(status_text, show_alert=True)
    await view_student_profile(callback)

@dp.callback_query(F.data.startswith("direct_msg_"))
async def start_direct_msg(callback: types.CallbackQuery, state: FSMContext):
    s_id = int(callback.data.split("_")[2])
    await state.update_data(target_student_id=s_id)
    await callback.message.answer(f"💬 **أرسل الرسالة التي تريد توجهها مباشرةً للطالب (`{s_id}`):**", reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
    await state.set_state(AdminStates.waiting_for_direct_message)
    await callback.answer()

@dp.message(AdminStates.waiting_for_direct_message)
async def send_direct_msg(message: types.Message, state: FSMContext):
    data = await state.get_data()
    s_id = data.get("target_student_id")

    try:
        await message.copy_to(chat_id=s_id)
        await message.answer("✅ **تم إرسال الرسالة إلى الطالب بنجاح!**", reply_markup=get_main_keyboard(message.from_user.id), parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"❌ **تعذر إرسال الرسالة للطالب.**\nالسبب: {e}", reply_markup=get_main_keyboard(message.from_user.id))

    await state.clear()

# --- 3. نظام الإذاعة الموجهة ---

@dp.callback_query(F.data == "super_targeted_broadcast")
async def start_targeted_broadcast(callback: types.CallbackQuery):
    if str(callback.from_user.id) != str(ADMIN_ID): return

    buttons = [
        [InlineKeyboardButton(text="📢 لكل الطلاب", callback_data="bc_target_all")],
        [InlineKeyboardButton(text="🆓 للطلاب غير المشتركين فقط", callback_data="bc_target_unsubscribed")],
        [InlineKeyboardButton(text="📘 للمشتركين بمادة محددة", callback_data="bc_target_subject")]
    ]
    await callback.message.answer("🎯 **تحديد فئة الإذاعة الموجهة:**\nاختر الشريحة المستهدفة بالرسالة:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("bc_target_"))
async def process_broadcast_target_type(callback: types.CallbackQuery, state: FSMContext):
    target_type = callback.data.replace("bc_target_", "")
    
    if target_type == "subject":
        async with AsyncSessionLocal() as session:
            subjects = (await session.execute(select(Subject).options(selectinload(Subject.grade)))).scalars().all()
        
        builder = [[InlineKeyboardButton(text=f"📘 {s.grade.name} ➔ {s.name}", callback_data=f"bc_sub_{s.id}")] for s in subjects]
        await callback.message.answer("📘 **اختر المادة المستهدفة لإذاعة التنبيه لمشتركيها:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
        await callback.answer()
        return

    await state.update_data(bc_target_type=target_type)
    await callback.message.answer("📢 **أرسل الآن الرسالة التي تريد إرسالها للفئة المحددة:**", reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
    await state.set_state(AdminStates.waiting_for_broadcast_message)
    await callback.answer()

@dp.callback_query(F.data.startswith("bc_sub_"))
async def set_bc_sub(callback: types.CallbackQuery, state: FSMContext):
    sub_id = int(callback.data.split("_")[2])
    await state.update_data(bc_target_type="subject", bc_subject_id=sub_id)
    await callback.message.answer("📢 **أرسل الآن الرسالة المراد إذاعتها لمشتركي هذه المادة:**", reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
    await state.set_state(AdminStates.waiting_for_broadcast_message)
    await callback.answer()

@dp.message(AdminStates.waiting_for_broadcast_message)
async def exec_targeted_broadcast(message: types.Message, state: FSMContext):
    data = await state.get_data()
    target_type = data.get("bc_target_type", "all")
    subject_id = data.get("bc_subject_id")

    user_ids = await get_broadcast_target_ids(target_type, subject_id)
    if not user_ids:
        await message.answer("⚠️️ لا يوجد مستخدمون ضمن هذه الفئة حالياً.", reply_markup=get_main_keyboard(message.from_user.id))
        await state.clear()
        return

    await message.answer(f"⏳ **جاري بدء الإذاعة لـ {len(user_ids)} مستخدم...**", parse_mode="Markdown")

    success, failed = 0, 0
    for u_id in user_ids:
        try:
            await message.copy_to(chat_id=u_id)
            success += 1
            await asyncio.sleep(0.04)
        except Exception:
            failed += 1

    await message.answer(
        f"✅ **اكتملت الإذاعة الموجهة بنجاح!**\n\n"
        f"🎯 **تم الإرسال بنجاح إلى:** `{success}` مستخدم\n"
        f"❌ **فشل الإرسال إلى:** `{failed}` مستخدم.",
        reply_markup=get_main_keyboard(message.from_user.id),
        parse_mode="Markdown"
    )
    await state.clear()

# --- 4. تصدير البيانات إلى Excel ---

def _generate_excel_sync(data):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        students_df = pd.DataFrame([{
            "ID": u.id,
            "الاسم الكامل": u.full_name,
            "المعرف": u.username,
            "رقم الهاتف": u.phone_number,
            "تاريخ الانضمام": u.created_at,
            "استهلك مجانية": u.has_used_free_lecture,
            "محظور": u.is_blocked
        } for u in data["students"]])
        students_df.to_excel(writer, sheet_name="الطلاب", index=False)

        teachers_df = pd.DataFrame([{
            "ID": u.id,
            "الاسم المعتمد": u.approved_name,
            "الاسم بالتليجرام": u.full_name,
            "المعرف": u.username,
            "رابط القناة": u.channel_link,
            "النبذة": u.bio,
            "الملاحظات": u.admin_notes
        } for u in data["teachers"]])
        teachers_df.to_excel(writer, sheet_name="المدرسون", index=False)

        codes_df = pd.DataFrame([{
            "الكود": c[0].code,
            "المادة": c[1].name,
            "نوع الاشتراك": c[0].sub_type,
            "مستخدم": c[0].is_used,
            "مستخدم بواسطة ID": c[0].used_by,
            "تاريخ الإنشاء": c[0].created_at
        } for c in data["codes"]])
        codes_df.to_excel(writer, sheet_name="الأكواد", index=False)

        logs_df = pd.DataFrame([{
            "المستخدم": l.user_id,
            "العملية": l.action,
            "التفاصيل": l.details,
            "التاريخ": l.timestamp
        } for l in data.get("logs", [])])
        logs_df.to_excel(writer, sheet_name="سجل الأمان", index=False)

    output.seek(0)
    return output

@dp.callback_query(F.data == "admin_export_excel")
async def export_data_excel(callback: types.CallbackQuery):
    if str(callback.from_user.id) != str(ADMIN_ID): return

    await callback.message.answer("⏳ **جاري إنشاء وتصدير ملف Excel الكامل...**")
    data = await export_all_data_for_excel()

    loop = asyncio.get_running_loop()
    output = await loop.run_in_executor(None, _generate_excel_sync, data)

    file_input = BufferedInputFile(output.read(), filename="Platform_Data_Report.xlsx")
    await callback.message.answer_document(file_input, caption="📊 **تقرير بيانات المنصة الشامل بصيغة Excel**", parse_mode="Markdown")
    await callback.answer()

# --- 5. لوحة الأدمن والأكواد ---

@dp.callback_query(F.data == "admin_stats")
async def show_admin_stats(callback: types.CallbackQuery):
    stats = await get_dashboard_stats()
    text = (
        "📊 **إحصائيات وسجل نشاط المنصة:**\n\n"
        f"👥 **إجمالي المستخدمين:** `{stats['users']}` مستخدم\n"
        f"🆕 **المشتركون الجدد اليوم:** `{stats['new_today']}` | **هذا الأسبوع:** `{stats['new_week']}`\n"
        f"🎁 **استهلاك المحاضرات المجانية:** `{stats['free_lectures']}` مرة\n"
        f"⭐ **عدد الاشتراكات الطلابية:** `{stats['subscriptions']}` اشتراك\n"
        f"🔑 **الأكواد المستخدمة:** `{stats['used_codes']}` | **الأكواد المتاحة:** `{stats['unused_codes']}`\n"
        f"🏫 **المراحل الدراسية:** `{stats['grades']}` | **المواد:** `{stats['subjects']}`\n"
        f"📝 **الدروس:** `{stats['lessons']}` | **المحتويات المرفوعة:** `{stats['files']}`\n"
        f"👁 **إجمالي المشاهدات والتنزيلات:** `{stats['total_views']}` مرة"
    )
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "super_create_code")
async def admin_start_create_code(callback: types.CallbackQuery, state: FSMContext):
    if str(callback.from_user.id) != str(ADMIN_ID): return

    async with AsyncSessionLocal() as session:
        subjects = (await session.execute(select(Subject).options(selectinload(Subject.grade)))).scalars().all()

    if not subjects:
        await callback.message.answer("⚠️ لا توجد مواد مضافة لتوليد أكواد لها!")
        await callback.answer()
        return

    builder = [[InlineKeyboardButton(text=f"📘 {s.grade.name} ➔ {s.name}", callback_data=f"gen_code_sub_{s.id}")] for s in subjects]
    await callback.message.answer("🔑 **اختر المادة المراد توليد كود اشتراك لها:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("gen_code_sub_"))
async def admin_select_sub_type(callback: types.CallbackQuery, state: FSMContext):
    subject_id = int(callback.data.split("_")[3])
    await state.update_data(code_subject_id=subject_id)

    builder = [
        [
            InlineKeyboardButton(text="📅 اشتراك شهري", callback_data="save_gen_code_monthly"),
            InlineKeyboardButton(text="📚 كتاب كامل", callback_data="save_gen_code_full")
        ]
    ]
    await callback.message.answer("📌 **اختر نوع الاشتراك الخاص بهذا الرمز:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("save_gen_code_"))
async def admin_generate_code_final(callback: types.CallbackQuery, state: FSMContext):
    sub_type = "monthly" if "monthly" in callback.data else "full"
    data = await state.get_data()
    subject_id = data.get("code_subject_id")

    code = await create_subscription_code(subject_id, sub_type)
    type_str = "شهري 📅" if sub_type == "monthly" else "كتاب كامل 📚"

    await callback.message.answer(
        f"✅ **تم توليد كود الاشتراك بنجاح!**\n\n"
        f"🔑 **الرمز (الكود):** `{code}`\n"
        f"📌 **نوع الاشتراك:** {type_str}\n\n"
        f"💡 قم بنسخ الكود وأرسله للطالب لاستخدامه أثناء الاشتراك.",
        parse_mode="Markdown"
    )
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "super_view_codes")
async def admin_view_unused_codes(callback: types.CallbackQuery):
    if str(callback.from_user.id) != str(ADMIN_ID): return

    codes = await get_unused_codes()
    if not codes:
        await callback.message.answer("ℹ️ لا توجد أكواد غير مستخدمة حالياً.")
        await callback.answer()
        return

    text = "📋 **قائمة الأكواد الفعّالة غير المستخدمة:**\n\n"
    for c in codes:
        text += f"• الرمز: `{c['code']}` | المادة: **{c['subject_name']}** | النوع: ({c['sub_type']})\n"

    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "super_assign_teacher")
async def start_assign_teacher(callback: types.CallbackQuery, state: FSMContext):
    if str(callback.from_user.id) != str(ADMIN_ID): return

    await callback.message.answer("👤 **أرسل الآن معرف ID التليجرام الخاص بالمدرس المراد تعيينه:**", reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
    await state.set_state(AdminStates.waiting_for_teacher_id)
    await callback.answer()

@dp.message(AdminStates.waiting_for_teacher_id)
async def process_assign_teacher_id(message: types.Message, state: FSMContext):
    try:
        teacher_id = int(message.text.strip())
        await state.update_data(target_teacher_id=teacher_id)

        async with AsyncSessionLocal() as session:
            subjects = (await session.execute(select(Subject).options(selectinload(Subject.grade)))).scalars().all()

        if not subjects:
            await message.answer("⚠️ لا توجد مواد مضافة لإسنادها للمدرس!", reply_markup=get_main_keyboard(message.from_user.id))
            await state.clear()
            return

        builder = [[InlineKeyboardButton(text=f"📘 {s.grade.name} ➔ {s.name}", callback_data=f"assign_t_sub_{s.id}")] for s in subjects]
        await message.answer(f"📘 **اختر المادة المراد إسنادها للمدرس (`{teacher_id}`):**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
    except ValueError:
        await message.answer("❌ يرجى إدخال رقم ID صحيح (أرقام فقط).")

@dp.callback_query(F.data.startswith("assign_t_sub_"))
async def process_assign_teacher_finish(callback: types.CallbackQuery, state: FSMContext):
    subject_id = int(callback.data.split("_")[3])
    data = await state.get_data()
    teacher_id = data.get("target_teacher_id")

    if not teacher_id:
        await callback.message.answer("❌ حدث خطأ، يرجى البدء من جديد.")
        await state.clear()
        return

    success = await assign_subject_to_teacher(teacher_id, subject_id)
    if success:
        await callback.message.answer(f"✅ **تم تعيين المدرس (`{teacher_id}`) وإسناد المادة بنجاح!**", reply_markup=get_main_keyboard(callback.from_user.id), parse_mode="Markdown")
    else:
        await callback.message.answer("⚠️ هذا المدرس مضاف مسبقاً لهذه المادة أو حدث خطأ.", reply_markup=get_main_keyboard(callback.from_user.id))

    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "super_revoke_teacher_menu")
async def super_revoke_teacher_menu(callback: types.CallbackQuery):
    if str(callback.from_user.id) != str(ADMIN_ID): return

    teachers_list = await get_all_teachers_with_subjects()
    if not teachers_list:
        await callback.message.answer("ℹ️ لا توجد صلاحيات تدريس مضافة حالياً لإزالتها.")
        await callback.answer()
        return

    builder = []
    for item in teachers_list:
        btn_text = f"❌ {item['teacher_name']} ➔ {item['subject_name']}"
        builder.append([InlineKeyboardButton(text=btn_text, callback_data=f"revoke_ts_{item['ts_id']}")])

    await callback.message.answer("🗑️ **اختر الصلاحية المراد سحبها وإلغاء إسناد المادة:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("revoke_ts_"))
async def process_revoke_teacher(callback: types.CallbackQuery):
    ts_id = int(callback.data.split("_")[2])
    success = await remove_teacher_permission(ts_id)
    if success:
        await callback.message.answer("✅ **تم إلغاء صلاحية المدرس بنجاح!**")
    else:
        await callback.message.answer("❌ تعذر إزالة الصلاحية.")
    await callback.answer()

# --- 6. إضافة وإدارة الهيكل التعليمي (مراحل، مواد، دروس، ملفات) ---

@dp.callback_query(F.data == "admin_add_grade")
async def add_grade_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("➕ **أدخل اسم المرحلة الدراسية الجديدة (مثال: السادس الإعدادي):**", reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
    await state.set_state(AdminStates.waiting_for_grade_name)
    await callback.answer()

@dp.message(AdminStates.waiting_for_grade_name)
async def process_add_grade(message: types.Message, state: FSMContext):
    grade_name = message.text.strip()
    async with AsyncSessionLocal() as session:
        new_grade = Grade(name=grade_name)
        session.add(new_grade)
        await session.commit()

    await message.answer(f"✅ **تمت إضافة المرحلة الدراسية بنجاح:** `{grade_name}`", reply_markup=get_main_keyboard(message.from_user.id), parse_mode="Markdown")
    await state.clear()

@dp.callback_query(F.data == "admin_add_subject")
async def add_subject_start(callback: types.CallbackQuery, state: FSMContext):
    async with AsyncSessionLocal() as session:
        grades = (await session.execute(select(Grade))).scalars().all()

    if not grades:
        await callback.message.answer("⚠️ يجب إضافة مرحلة دراسية واحدة على الأقل أولاً!")
        await callback.answer()
        return

    builder = [[InlineKeyboardButton(text=f"📚 {g.name}", callback_data=f"add_sub_grade_{g.id}")] for g in grades]
    await callback.message.answer("📚 **اختر المرحلة التي تتبع لها المادة الجديدة:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("add_sub_grade_"))
async def process_add_sub_grade_selected(callback: types.CallbackQuery, state: FSMContext):
    grade_id = int(callback.data.split("_")[3])
    await state.update_data(target_grade_id=grade_id)
    await callback.message.answer("📘 **أدخل اسم المادة الدراسية الجديدة (مثال: الرياضيات):**", reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
    await state.set_state(AdminStates.waiting_for_subject_name)
    await callback.answer()

@dp.message(AdminStates.waiting_for_subject_name)
async def process_add_subject_finish(message: types.Message, state: FSMContext):
    subject_name = message.text.strip()
    data = await state.get_data()
    grade_id = data.get("target_grade_id")

    async with AsyncSessionLocal() as session:
        new_sub = Subject(name=subject_name, grade_id=grade_id)
        session.add(new_sub)
        await session.commit()

    await message.answer(f"✅ **تمت إضافة المادة بنجاح:** `{subject_name}`", reply_markup=get_main_keyboard(message.from_user.id), parse_mode="Markdown")
    await state.clear()

@dp.callback_query(F.data == "admin_add_lesson")
async def add_lesson_start(callback: types.CallbackQuery, state: FSMContext):
    u_id = callback.from_user.id
    allowed_ids = await get_teacher_allowed_subjects(u_id)

    async with AsyncSessionLocal() as session:
        if str(u_id) == str(ADMIN_ID):
            subjects = (await session.execute(select(Subject).options(selectinload(Subject.grade)))).scalars().all()
        else:
            subjects = (await session.execute(select(Subject).options(selectinload(Subject.grade)).where(Subject.id.in_(allowed_ids)))).scalars().all()

    if not subjects:
        await callback.message.answer("⚠️ لا توجد مواد متاحة لك لإضافة دروس فيها.")
        await callback.answer()
        return

    builder = [[InlineKeyboardButton(text=f"📘 {s.grade.name} ➔ {s.name}", callback_data=f"add_les_sub_{s.id}")] for s in subjects]
    await callback.message.answer("📘 **اختر المادة المراد إضافة درس/محاضرة إليها:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("add_les_sub_"))
async def process_add_les_sub_selected(callback: types.CallbackQuery, state: FSMContext):
    subject_id = int(callback.data.split("_")[3])
    await state.update_data(target_subject_id=subject_id)
    await callback.message.answer("📝 **أدخل عنوان المحاضرة أو الدرس الجديد:**", reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
    await state.set_state(AdminStates.waiting_for_lesson_title)
    await callback.answer()

@dp.message(AdminStates.waiting_for_lesson_title)
async def process_add_lesson_finish(message: types.Message, state: FSMContext):
    lesson_title = message.text.strip()
    data = await state.get_data()
    subject_id = data.get("target_subject_id")

    async with AsyncSessionLocal() as session:
        new_lesson = Lesson(title=lesson_title, subject_id=subject_id)
        session.add(new_lesson)
        await session.commit()

    await message.answer(f"✅ **تمت إضافة الدرس بنجاح:** `{lesson_title}`", reply_markup=get_main_keyboard(message.from_user.id), parse_mode="Markdown")
    await state.clear()

@dp.callback_query(F.data == "admin_add_file")
async def add_file_start(callback: types.CallbackQuery, state: FSMContext):
    u_id = callback.from_user.id
    allowed_ids = await get_teacher_allowed_subjects(u_id)

    async with AsyncSessionLocal() as session:
        if str(u_id) == str(ADMIN_ID):
            lessons = (await session.execute(select(Lesson).options(selectinload(Lesson.subject)))).scalars().all()
        else:
            lessons = (await session.execute(select(Lesson).options(selectinload(Lesson.subject)).where(Lesson.subject_id.in_(allowed_ids)))).scalars().all()

    if not lessons:
        await callback.message.answer("⚠️ لا توجد محاضرات متاحة لك لنشر المحتوى داخلها.")
        await callback.answer()
        return

    builder = [[InlineKeyboardButton(text=f"📝 {l.subject.name} ➔ {l.title}", callback_data=f"add_file_les_{l.id}")] for l in lessons]
    await callback.message.answer("📜 **اختر المحاضرة المراد إضافة المحتوى/الملف إليها:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("add_file_les_"))
async def process_add_file_les_selected(callback: types.CallbackQuery, state: FSMContext):
    lesson_id = int(callback.data.split("_")[3])
    await state.update_data(target_lesson_id=lesson_id)
    await callback.message.answer("📤 **قم بإرسال الملف أو الصورة أو الفيديو أو الملخص (مع إضافة الشرح بـ Caption إن وجد):**", reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
    await state.set_state(AdminStates.waiting_for_file)
    await callback.answer()

@dp.message(AdminStates.waiting_for_file)
async def process_add_file_finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lesson_id = data.get("target_lesson_id")

    file_id, file_type, title = None, "text", message.caption or message.text or "محتوى تعليمي"

    if message.document:
        file_id, file_type = message.document.file_id, "document"
        title = message.caption or message.document.file_name or "ملف مستند"
    elif message.photo:
        file_id, file_type = message.photo[-1].file_id, "photo"
        title = message.caption or "صورة تعليمية"
    elif message.video:
        file_id, file_type = message.video.file_id, "video"
        title = message.caption or "فيديو شرح"
    elif message.voice:
        file_id, file_type = message.voice.file_id, "voice"
        title = message.caption or "تسجيل صوتي"
    elif message.audio:
        file_id, file_type = message.audio.file_id, "audio"
        title = message.caption or message.audio.title or "ملف صوتي"

    async with AsyncSessionLocal() as session:
        new_file = FileItem(title=title, file_id=file_id, file_type=file_type, lesson_id=lesson_id)
        session.add(new_file)
        await session.commit()

    await message.answer("✅ **تم رفع المحتوى ونشره داخل المحاضرة بنجاح!**", reply_markup=get_main_keyboard(message.from_user.id))
    await state.clear()

# --- 7. قسم التعديل والإعادة التسمية ---

@dp.callback_query(F.data == "admin_edit_menu")
async def edit_menu(callback: types.CallbackQuery):
    buttons = [
        [InlineKeyboardButton(text="✏️ تعديل اسم مادة", callback_data="edit_subject_start")],
        [InlineKeyboardButton(text="✏️ تعديل عنوان درس", callback_data="edit_lesson_start")]
    ]
    await callback.message.answer("✏️ **قائمة التعديل وإعادة التسمية:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "edit_subject_start")
async def edit_subject_start(callback: types.CallbackQuery, state: FSMContext):
    async with AsyncSessionLocal() as session:
        subjects = (await session.execute(select(Subject))).scalars().all()

    if not subjects:
        await callback.message.answer("ℹ️ لا توجد مواد لتعديلها.")
        await callback.answer()
        return

    builder = [[InlineKeyboardButton(text=f"📘 {s.name}", callback_data=f"rename_sub_{s.id}")] for s in subjects]
    await callback.message.answer("📘 **اختر المادة المراد تعديل اسمها:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("rename_sub_"))
async def prompt_new_sub_name(callback: types.CallbackQuery, state: FSMContext):
    sub_id = int(callback.data.split("_")[2])
    await state.update_data(edit_sub_id=sub_id)
    await callback.message.answer("✏️ **أرسل الاسم الجديد للمادة:**", reply_markup=get_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_new_subject_name)
    await callback.answer()

@dp.message(AdminStates.waiting_for_new_subject_name)
async def process_rename_sub(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await update_subject_name(data["edit_sub_id"], message.text.strip())
    await message.answer("✅ **تم تحديث اسم المادة بنجاح!**", reply_markup=get_main_keyboard(message.from_user.id))
    await state.clear()

@dp.callback_query(F.data == "edit_lesson_start")
async def edit_lesson_start(callback: types.CallbackQuery, state: FSMContext):
    async with AsyncSessionLocal() as session:
        lessons = (await session.execute(select(Lesson))).scalars().all()

    if not lessons:
        await callback.message.answer("ℹ️ لا توجد دروس لتعديلها.")
        await callback.answer()
        return

    builder = [[InlineKeyboardButton(text=f"📝 {l.title}", callback_data=f"rename_les_{l.id}")] for l in lessons]
    await callback.message.answer("📝 **اختر الدرس المراد تعديل عنوانه:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("rename_les_"))
async def prompt_new_les_name(callback: types.CallbackQuery, state: FSMContext):
    les_id = int(callback.data.split("_")[2])
    await state.update_data(edit_les_id=les_id)
    await callback.message.answer("✏️ **أرسل العنوان الجديد للدرس:**", reply_markup=get_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_new_lesson_title)
    await callback.answer()

@dp.message(AdminStates.waiting_for_new_lesson_title)
async def process_rename_les(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await update_lesson_name(data["edit_les_id"], message.text.strip())
    await message.answer("✅ **تم تحديث عنوان الدرس بنجاح!**", reply_markup=get_main_keyboard(message.from_user.id))
    await state.clear()

# --- 8. قسم الحذف الشامل ---

@dp.callback_query(F.data == "admin_delete_menu")
async def delete_menu(callback: types.CallbackQuery):
    buttons = [
        [InlineKeyboardButton(text="🗑️ حذف مرحلة دراسية بالكامل", callback_data="del_grade_start")],
        [InlineKeyboardButton(text="🗑️ حذف مادة دراسية", callback_data="del_subject_start")],
        [InlineKeyboardButton(text="🗑️ حذف درس / محاضرة", callback_data="del_lesson_start")],
        [InlineKeyboardButton(text="🗑️ حذف محتوى / ملف مرفوق", callback_data="del_file_start")]
    ]
    await callback.message.answer("🗑️ **قائمة إدارة الحذف (تحذير: الحذف نهائي):**", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "del_grade_start")
async def del_grade_start(callback: types.CallbackQuery):
    async with AsyncSessionLocal() as session:
        grades = (await session.execute(select(Grade))).scalars().all()

    if not grades:
        await callback.message.answer("ℹ️ لا توجد مراحل للحذف.")
        await callback.answer()
        return

    builder = [[InlineKeyboardButton(text=f"🗑️ {g.name}", callback_data=f"confirm_del_grade_{g.id}")] for g in grades]
    await callback.message.answer("⚠️ **اختر المرحلة المراد حذفها بكافة موادها ودروسها:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_del_grade_"))
async def process_del_grade(callback: types.CallbackQuery):
    g_id = int(callback.data.split("_")[3])
    if await delete_grade(g_id):
        await callback.message.answer("✅ **تم حذف المرحلة التعليمية وجميع ملحقاتها بنجاح.**")
    else:
        await callback.message.answer("❌ تعذر حذف المرحلة.")
    await callback.answer()

@dp.callback_query(F.data == "del_subject_start")
async def del_subject_start(callback: types.CallbackQuery):
    async with AsyncSessionLocal() as session:
        subjects = (await session.execute(select(Subject))).scalars().all()

    if not subjects:
        await callback.message.answer("ℹ️ لا توجد مواد للحذف.")
        await callback.answer()
        return

    builder = [[InlineKeyboardButton(text=f"🗑️ {s.name}", callback_data=f"confirm_del_sub_{s.id}")] for s in subjects]
    await callback.message.answer("⚠️ **اختر المادة المراد حذفها بكافة دروسها:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_del_sub_"))
async def process_del_subject(callback: types.CallbackQuery):
    s_id = int(callback.data.split("_")[3])
    if await delete_subject(s_id):
        await callback.message.answer("✅ **تم حذف المادة بنجاح.**")
    else:
        await callback.message.answer("❌ تعذر حذف المادة.")
    await callback.answer()

@dp.callback_query(F.data == "del_lesson_start")
async def del_lesson_start(callback: types.CallbackQuery):
    async with AsyncSessionLocal() as session:
        lessons = (await session.execute(select(Lesson))).scalars().all()

    if not lessons:
        await callback.message.answer("ℹ️ لا توجد دروس للحذف.")
        await callback.answer()
        return

    builder = [[InlineKeyboardButton(text=f"🗑️ {l.title}", callback_data=f"confirm_del_les_{l.id}")] for l in lessons]
    await callback.message.answer("⚠️ **اختر الدرس المراد حذفه:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_del_les_"))
async def process_del_lesson(callback: types.CallbackQuery):
    l_id = int(callback.data.split("_")[3])
    if await delete_lesson(l_id):
        await callback.message.answer("✅ **تم حذف الدرس ومحتوياته بنجاح.**")
    else:
        await callback.message.answer("❌ تعذر حذف الدرس.")
    await callback.answer()

@dp.callback_query(F.data == "del_file_start")
async def del_file_start(callback: types.CallbackQuery):
    async with AsyncSessionLocal() as session:
        files = (await session.execute(select(FileItem))).scalars().all()

    if not files:
        await callback.message.answer("ℹ️ لا توجد ملفات للحذف.")
        await callback.answer()
        return

    builder = [[InlineKeyboardButton(text=f"🗑️ {f.title[:30]}", callback_data=f"confirm_del_file_{f.id}")] for f in files[:40]]
    await callback.message.answer("⚠️️ **اختر المحتوى/الملف المراد حذفه:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_del_file_"))
async def process_del_file(callback: types.CallbackQuery):
    f_id = int(callback.data.split("_")[3])
    if await delete_file_item(f_id):
        await callback.message.answer("✅ **تم حذف الملف المرفوق بنجاح.**")
    else:
        await callback.message.answer("❌ تعذر حذف الملف.")
    await callback.answer()

# --- 9. أزرار المعرفة العامة والدعم الفني ---

@dp.message(F.text == "📞 الدعم والاتصال")
async def support_info(message: types.Message):
    text = (
        "📞 **مركز الدعم الفني والاستفسارات:**\n\n"
        "إذا واجهتك أي مشكلة في تفعيل الاشتراكات أو الأكواد أو الوصول للمحاضرات، يرجى التواصل مع إدارة المنصة مباشرة عبر:\n"
        f"📢 القناة الرسمية: {CHANNEL_USERNAME}\n"
        "💬 الدعم المباشر: عبر أزرار التواصل المتاحة بالقناة."
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "ℹ️ عن المنصة")
async def about_platform(message: types.Message):
    text = (
        "🎓 **منصة النخبة التعليمية (E E P):**\n\n"
        "منصة تعليمية متكاملة تهدف إلى تقديم أفضل الملازم، الدروس، والمحاضرات للطلاب بأحدث وسائل المتابعة الذكية.\n"
        "• إمكانية مشاهدة محاضرة تجريبية مجانية لكل طالب.\n"
        "• متابعة الحضور والغياب وتسليم الواجبات.\n"
        "• حماية كاملة للمحتويات التعليمية."
    )
    await message.answer(text, parse_mode="Markdown")

# ==================== الدالة الرئيسية للتشغيل ====================

async def main():
    await init_db()
    print("🚀 Bot starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())