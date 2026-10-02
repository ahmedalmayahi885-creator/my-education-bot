import os
import string
import secrets
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import BigInteger, String, Boolean, ForeignKey, Text, DateTime, Integer, Float, func, select, update, delete
from config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

# ==================== الموديلات (Tables) ====================

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    full_name: Mapped[str] = mapped_column(String, nullable=True)
    username: Mapped[str] = mapped_column(String, nullable=True)
    approved_name: Mapped[str] = mapped_column(String, nullable=True)
    bio: Mapped[str] = mapped_column(Text, nullable=True)
    channel_link: Mapped[str] = mapped_column(String, nullable=True)
    admin_notes: Mapped[str] = mapped_column(Text, nullable=True)
    phone_number: Mapped[str] = mapped_column(String, nullable=True)
    
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_teacher: Mapped[bool] = mapped_column(Boolean, default=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    has_used_free_lecture: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at = mapped_column(DateTime, server_default=func.now())

class Grade(Base):
    __tablename__ = "grades"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    subjects = relationship("Subject", back_populates="grade", cascade="all, delete-orphan")

class Subject(Base):
    __tablename__ = "subjects"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    grade_id: Mapped[int] = mapped_column(ForeignKey("grades.id"))
    
    grade = relationship("Grade", back_populates="subjects")
    lessons = relationship("Lesson", back_populates="subject", cascade="all, delete-orphan")
    assignments = relationship("Assignment", back_populates="subject", cascade="all, delete-orphan")

class Lesson(Base):
    __tablename__ = "lessons"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    
    subject = relationship("Subject", back_populates="lessons")
    files = relationship("FileItem", back_populates="lesson", cascade="all, delete-orphan")

class FileItem(Base):
    __tablename__ = "file_items"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    file_id: Mapped[str] = mapped_column(String, nullable=True)
    file_type: Mapped[str] = mapped_column(String, default="document")
    views_count: Mapped[int] = mapped_column(Integer, default=0)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"))
    
    lesson = relationship("Lesson", back_populates="files")

class TeacherSubject(Base):
    __tablename__ = "teacher_subjects"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    teacher_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))

class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    sub_type: Mapped[str] = mapped_column(String, default="full")
    created_at = mapped_column(DateTime, server_default=func.now())

class SubscriptionCode(Base):
    __tablename__ = "subscription_codes"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    sub_type: Mapped[str] = mapped_column(String, nullable=False)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    used_by: Mapped[int] = mapped_column(BigInteger, nullable=True)
    created_at = mapped_column(DateTime, server_default=func.now())

class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    due_date = mapped_column(DateTime, nullable=True)
    max_score: Mapped[float] = mapped_column(Float, default=100.0)
    created_at = mapped_column(DateTime, server_default=func.now())

    subject = relationship("Subject", back_populates="assignments")
    submissions = relationship("Submission", back_populates="assignment", cascade="all, delete-orphan")

class Submission(Base):
    __tablename__ = "submissions"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"))
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    file_id: Mapped[str] = mapped_column(String, nullable=True)
    file_type: Mapped[str] = mapped_column(String, default="document")
    score: Mapped[float] = mapped_column(Float, nullable=True)
    feedback: Mapped[str] = mapped_column(Text, nullable=True)
    submitted_at = mapped_column(DateTime, server_default=func.now())

    assignment = relationship("Assignment", back_populates="submissions")

class Attendance(Base):
    __tablename__ = "attendances"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    status: Mapped[str] = mapped_column(String, default="حاضر")
    session_date = mapped_column(DateTime, server_default=func.now())

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=True)
    timestamp = mapped_column(DateTime, server_default=func.now())

# ==================== الدوال التنفيذية ====================

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def log_audit_action(user_id: int, action: str, details: str = None):
    async with AsyncSessionLocal() as session:
        try:
            log = AuditLog(user_id=user_id, action=action, details=details)
            session.add(log)
            await session.commit()
        except Exception:
            await session.rollback()

async def create_grade(name: str) -> Grade:
    async with AsyncSessionLocal() as session:
        try:
            grade = Grade(name=name)
            session.add(grade)
            await session.commit()
            await session.refresh(grade)
            return grade
        except Exception:
            await session.rollback()
            return None

async def create_subject(name: str, grade_id: int) -> Subject:
    async with AsyncSessionLocal() as session:
        try:
            subject = Subject(name=name, grade_id=grade_id)
            session.add(subject)
            await session.commit()
            await session.refresh(subject)
            return subject
        except Exception:
            await session.rollback()
            return None

async def create_lesson(title: str, subject_id: int) -> Lesson:
    async with AsyncSessionLocal() as session:
        try:
            lesson = Lesson(title=title, subject_id=subject_id)
            session.add(lesson)
            await session.commit()
            await session.refresh(lesson)
            return lesson
        except Exception:
            await session.rollback()
            return None

async def create_file_item(title: str, lesson_id: int, file_id: str = None, file_type: str = "document") -> FileItem:
    async with AsyncSessionLocal() as session:
        try:
            file_item = FileItem(title=title, lesson_id=lesson_id, file_id=file_id, file_type=file_type)
            session.add(file_item)
            await session.commit()
            await session.refresh(file_item)
            return file_item
        except Exception:
            await session.rollback()
            return None

async def assign_subject_to_teacher(teacher_id: int, subject_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(User).where(User.id == teacher_id))
            user = result.scalar_one_or_none()
            
            if not user:
                user = User(id=teacher_id, full_name=f"مدرس {teacher_id}", is_teacher=True)
                session.add(user)
            else:
                user.is_teacher = True

            perm_check = await session.execute(
                select(TeacherSubject).where(
                    TeacherSubject.teacher_id == teacher_id,
                    TeacherSubject.subject_id == subject_id
                )
            )
            if perm_check.scalar_one_or_none():
                return False

            new_permission = TeacherSubject(teacher_id=teacher_id, subject_id=subject_id)
            session.add(new_permission)
            await session.commit()
            await log_audit_action(teacher_id, "ASSIGN_TEACHER", f"Subject ID: {subject_id}")
            return True
        except Exception:
            await session.rollback()
            return False

async def update_teacher_profile(teacher_id: int, approved_name: str = None, bio: str = None, channel_link: str = None, notes: str = None):
    async with AsyncSessionLocal() as session:
        try:
            stmt = select(User).where(User.id == teacher_id)
            res = await session.execute(stmt)
            user = res.scalar_one_or_none()
            if user:
                if approved_name is not None: user.approved_name = approved_name
                if bio is not None: user.bio = bio
                if channel_link is not None: user.channel_link = channel_link
                if notes is not None: user.admin_notes = notes
                await session.commit()
        except Exception:
            await session.rollback()

async def get_all_teachers_list() -> list[User]:
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(User).where(User.is_teacher == True))
        return list(res.scalars().all())

async def get_teacher_details(teacher_id: int) -> dict:
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(User).where(User.id == teacher_id))
        user = res.scalar_one_or_none()
        if not user: return None
        
        subs_res = await session.execute(
            select(Subject.name)
            .join(TeacherSubject, TeacherSubject.subject_id == Subject.id)
            .where(TeacherSubject.teacher_id == teacher_id)
        )
        subjects = list(subs_res.scalars().all())
        
        return {
            "user": user,
            "display_name": user.approved_name or user.full_name or user.username or f"مدرس [{user.id}]",
            "subjects": subjects
        }

async def get_teacher_allowed_subjects(teacher_id: int) -> list[int]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(TeacherSubject.subject_id).where(TeacherSubject.teacher_id == teacher_id)
        )
        return list(result.scalars().all())

async def get_all_teachers_with_subjects() -> list[dict]:
    async with AsyncSessionLocal() as session:
        stmt = (
            select(TeacherSubject, User, Subject)
            .join(User, TeacherSubject.teacher_id == User.id)
            .join(Subject, TeacherSubject.subject_id == Subject.id)
        )
        result = await session.execute(stmt)
        teachers_list = []
        for ts, u, s in result.all():
            teachers_list.append({
                "ts_id": ts.id,
                "teacher_id": u.id,
                "teacher_name": u.approved_name or u.full_name or u.username or f"مستخدم [{u.id}]",
                "subject_id": s.id,
                "subject_name": s.name
            })
        return teachers_list

async def remove_teacher_permission(ts_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        try:
            res = await session.execute(select(TeacherSubject).where(TeacherSubject.id == ts_id))
            ts = res.scalar_one_or_none()
            if not ts: return False
            
            teacher_id = ts.teacher_id
            await session.delete(ts)
            await session.commit()

            remaining = await session.execute(
                select(TeacherSubject).where(TeacherSubject.teacher_id == teacher_id)
            )
            if not remaining.scalars().all():
                await session.execute(
                    update(User).where(User.id == teacher_id).values(is_teacher=False)
                )
                await session.commit()
            await log_audit_action(teacher_id, "REVOKE_TEACHER", f"Permission ID: {ts_id}")
            return True
        except Exception:
            await session.rollback()
            return False

async def get_classified_students() -> tuple[list[User], list[User]]:
    async with AsyncSessionLocal() as session:
        sub_users_stmt = select(User).where(User.id.in_(select(Subscription.user_id)))
        subscribed_students = list((await session.execute(sub_users_stmt)).scalars().all())
        
        unsub_users_stmt = select(User).where(
            User.is_admin == False,
            User.is_teacher == False,
            User.id.not_in(select(Subscription.user_id))
        )
        unsubscribed_students = list((await session.execute(unsub_users_stmt)).scalars().all())
        
        return subscribed_students, unsubscribed_students

async def get_student_profile(user_id: int) -> dict:
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(User).where(User.id == user_id))
        user = res.scalar_one_or_none()
        if not user: return None
        
        subs_res = await session.execute(
            select(Subject.name, Subscription.sub_type)
            .join(Subscription, Subscription.subject_id == Subject.id)
            .where(Subscription.user_id == user_id)
        )
        subs = [{"subject": row[0], "type": row[1]} for row in subs_res.all()]
        
        codes_res = await session.execute(
            select(SubscriptionCode.code, Subject.name)
            .join(Subject, SubscriptionCode.subject_id == Subject.id)
            .where(SubscriptionCode.used_by == user_id)
        )
        used_codes = [{"code": row[0], "subject": row[1]} for row in codes_res.all()]
        
        return {
            "user": user,
            "subscriptions": subs,
            "used_codes": used_codes
        }

async def toggle_block_user(user_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        try:
            res = await session.execute(select(User).where(User.id == user_id))
            u = res.scalar_one_or_none()
            if u:
                u.is_blocked = not u.is_blocked
                await session.commit()
                await log_audit_action(user_id, "TOGGLE_BLOCK", f"Blocked: {u.is_blocked}")
                return u.is_blocked
            return False
        except Exception:
            await session.rollback()
            return False

async def search_user_by_query(query: str) -> list[User]:
    async with AsyncSessionLocal() as session:
        clean_q = query.strip().replace("@", "")
        if clean_q.isdigit():
            stmt = select(User).where(User.id == int(clean_q))
        else:
            stmt = select(User).where(
                (User.username.ilike(f"%{clean_q}%")) | 
                (User.full_name.ilike(f"%{clean_q}%")) |
                (User.approved_name.ilike(f"%{clean_q}%"))
            )
        res = await session.execute(stmt)
        return list(res.scalars().all())

async def get_broadcast_target_ids(target_type: str, subject_id: int = None) -> list[int]:
    async with AsyncSessionLocal() as session:
        if target_type == "all":
            res = await session.execute(select(User.id).where(User.is_blocked == False))
            return list(res.scalars().all())
        elif target_type == "unsubscribed":
            res = await session.execute(
                select(User.id).where(
                    User.is_blocked == False,
                    User.is_admin == False,
                    User.is_teacher == False,
                    User.id.not_in(select(Subscription.user_id))
                )
            )
            return list(res.scalars().all())
        elif target_type == "subject" and subject_id:
            res = await session.execute(
                select(Subscription.user_id)
                .join(User, Subscription.user_id == User.id)
                .where(Subscription.subject_id == subject_id, User.is_blocked == False)
            )
            return list(res.scalars().all())
        return []

def generate_random_code(length: int = 6) -> str:
    chars = string.ascii_uppercase + string.digits
    return "SUB-" + ''.join(secrets.choice(chars) for _ in range(length))

async def create_subscription_code(subject_id: int, sub_type: str) -> str:
    async with AsyncSessionLocal() as session:
        try:
            while True:
                code = generate_random_code()
                res = await session.execute(select(SubscriptionCode).where(SubscriptionCode.code == code))
                if not res.scalar_one_or_none(): break

            new_code = SubscriptionCode(code=code, subject_id=subject_id, sub_type=sub_type)
            session.add(new_code)
            await session.commit()
            return code
        except Exception:
            await session.rollback()
            return ""

async def redeem_subscription_code(user_id: int, subject_id: int, input_code: str) -> tuple[bool, str]:
    async with AsyncSessionLocal() as session:
        try:
            stmt = select(SubscriptionCode).where(
                SubscriptionCode.code == input_code.strip(),
                SubscriptionCode.is_used == False
            )
            res = await session.execute(stmt)
            code_obj = res.scalar_one_or_none()

            if not code_obj:
                return False, "❌ الرمز غير صحيح أو تم استخدامه سابقاً!"
            if code_obj.subject_id != subject_id:
                return False, "⚠️ هذا الرمز غير مخصص لهذه المادة!"

            code_obj.is_used = True
            code_obj.used_by = user_id

            sub_check = await session.execute(
                select(Subscription).where(Subscription.user_id == user_id, Subscription.subject_id == subject_id)
            )
            existing_sub = sub_check.scalar_one_or_none()
            if not existing_sub:
                session.add(Subscription(user_id=user_id, subject_id=subject_id, sub_type=code_obj.sub_type))
            else:
                existing_sub.sub_type = code_obj.sub_type

            await session.commit()
            await log_audit_action(user_id, "REDEEM_CODE", f"Code: {input_code}, Subject: {subject_id}")
            type_str = "شهري" if code_obj.sub_type == "monthly" else "كتاب كامل"
            return True, f"🎉 تم تفعيل اشتراكك بنجاح! نوع الاشتراك: ({type_str})"
        except Exception as e:
            await session.rollback()
            return False, f"❌ حدث خطأ أثناء تفعيل الاشتراك: {str(e)}"

async def is_student_subscribed(user_id: int, subject_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        stmt = select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.subject_id == subject_id
        )
        res = await session.execute(stmt)
        return res.scalar_one_or_none() is not None

async def get_user_subscriptions(user_id: int) -> list[dict]:
    async with AsyncSessionLocal() as session:
        stmt = (
            select(Subscription, Subject)
            .join(Subject, Subscription.subject_id == Subject.id)
            .where(Subscription.user_id == user_id)
        )
        res = await session.execute(stmt)
        subscriptions = []
        for sub, subject in res.all():
            ts_res = await session.execute(
                select(User)
                .join(TeacherSubject, TeacherSubject.teacher_id == User.id)
                .where(TeacherSubject.subject_id == subject.id)
            )
            teacher = ts_res.scalar_one_or_none()
            teacher_name = (teacher.approved_name or teacher.full_name) if teacher else "غير محدد"
            sub_type_label = "شهري 📅" if sub.sub_type == "monthly" else "كتاب كامل 📚"
            subscriptions.append({
                "subject_id": subject.id,
                "subject_name": subject.name,
                "teacher_name": teacher_name,
                "sub_type": sub_type_label
            })
        return subscriptions

async def check_or_use_free_lecture(user_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        try:
            res = await session.execute(select(User).where(User.id == user_id))
            user = res.scalar_one_or_none()
            if not user: return False

            if not user.has_used_free_lecture:
                user.has_used_free_lecture = True
                await session.commit()
                return True
            return False
        except Exception:
            await session.rollback()
            return False

async def get_unused_codes() -> list[dict]:
    async with AsyncSessionLocal() as session:
        stmt = (
            select(SubscriptionCode, Subject)
            .join(Subject, SubscriptionCode.subject_id == Subject.id)
            .where(SubscriptionCode.is_used == False)
        )
        res = await session.execute(stmt)
        codes = []
        for c, s in res.all():
            st = "شهري" if c.sub_type == "monthly" else "كتاب كامل"
            codes.append({"code": c.code, "subject_name": s.name, "sub_type": st})
        return codes

async def increment_file_views(file_id: int):
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                update(FileItem).where(FileItem.id == file_id).values(views_count=FileItem.views_count + 1)
            )
            await session.commit()
        except Exception:
            await session.rollback()

async def update_subject_name(subject_id: int, new_name: str):
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(update(Subject).where(Subject.id == subject_id).values(name=new_name))
            await session.commit()
        except Exception:
            await session.rollback()

async def update_lesson_name(lesson_id: int, new_title: str):
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(update(Lesson).where(Lesson.id == lesson_id).values(title=new_title))
            await session.commit()
        except Exception:
            await session.rollback()

async def delete_grade(grade_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(delete(Grade).where(Grade.id == grade_id))
            await session.commit()
            return True
        except Exception: 
            await session.rollback()
            return False

async def delete_subject(subject_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(delete(Subject).where(Subject.id == subject_id))
            await session.commit()
            return True
        except Exception: 
            await session.rollback()
            return False

async def delete_lesson(lesson_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(delete(Lesson).where(Lesson.id == lesson_id))
            await session.commit()
            return True
        except Exception: 
            await session.rollback()
            return False

async def delete_file_item(file_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(delete(FileItem).where(FileItem.id == file_id))
            await session.commit()
            return True
        except Exception: 
            await session.rollback()
            return False

async def create_assignment(title: str, description: str, subject_id: int, due_date: datetime = None, max_score: float = 100.0) -> int:
    async with AsyncSessionLocal() as session:
        try:
            assign = Assignment(title=title, description=description, subject_id=subject_id, due_date=due_date, max_score=max_score)
            session.add(assign)
            await session.commit()
            return assign.id
        except Exception:
            await session.rollback()
            return 0

async def submit_assignment(assignment_id: int, student_id: int, file_id: str, file_type: str = "document") -> bool:
    async with AsyncSessionLocal() as session:
        try:
            sub = Submission(assignment_id=assignment_id, student_id=student_id, file_id=file_id, file_type=file_type)
            session.add(sub)
            await session.commit()
            return True
        except Exception:
            await session.rollback()
            return False

async def grade_submission(submission_id: int, score: float, feedback: str = None) -> bool:
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                update(Submission)
                .where(Submission.id == submission_id)
                .values(score=score, feedback=feedback)
            )
            await session.commit()
            return True
        except Exception:
            await session.rollback()
            return False

async def record_attendance(student_id: int, subject_id: int, status: str = "حاضر") -> bool:
    async with AsyncSessionLocal() as session:
        try:
            att = Attendance(student_id=student_id, subject_id=subject_id, status=status)
            session.add(att)
            await session.commit()
            return True
        except Exception:
            await session.rollback()
            return False

async def get_student_grades(student_id: int) -> list[dict]:
    async with AsyncSessionLocal() as session:
        stmt = (
            select(Submission, Assignment, Subject)
            .join(Assignment, Submission.assignment_id == Assignment.id)
            .join(Subject, Assignment.subject_id == Subject.id)
            .where(Submission.student_id == student_id)
        )
        res = await session.execute(stmt)
        grades = []
        for sub, assign, subject in res.all():
            grades.append({
                "subject": subject.name,
                "assignment": assign.title,
                "score": sub.score,
                "max_score": assign.max_score,
                "feedback": sub.feedback or "لا يوجد"
            })
        return grades

async def get_student_attendance(student_id: int) -> list[dict]:
    async with AsyncSessionLocal() as session:
        stmt = (
            select(Attendance, Subject)
            .join(Subject, Attendance.subject_id == Subject.id)
            .where(Attendance.student_id == student_id)
        )
        res = await session.execute(stmt)
        records = []
        for att, subject in res.all():
            records.append({
                "subject": subject.name,
                "status": att.status,
                "date": att.session_date.strftime("%Y-%m-%d %H:%M") if att.session_date else "غير محدد"
            })
        return records

async def get_dashboard_stats() -> dict:
    async with AsyncSessionLocal() as session:
        now = datetime.now()
        today_start = datetime(now.year, now.month, now.day)
        week_start = now - timedelta(days=7)

        users_cnt = (await session.execute(select(func.count(User.id)))).scalar_one_or_none() or 0
        new_today = (await session.execute(select(func.count(User.id)).where(User.created_at >= today_start))).scalar_one_or_none() or 0
        new_week = (await session.execute(select(func.count(User.id)).where(User.created_at >= week_start))).scalar_one_or_none() or 0
        
        grades_cnt = (await session.execute(select(func.count(Grade.id)))).scalar_one_or_none() or 0
        subjects_cnt = (await session.execute(select(func.count(Subject.id)))).scalar_one_or_none() or 0
        lessons_cnt = (await session.execute(select(func.count(Lesson.id)))).scalar_one_or_none() or 0
        files_cnt = (await session.execute(select(func.count(FileItem.id)))).scalar_one_or_none() or 0
        views_cnt = (await session.execute(select(func.sum(FileItem.views_count)))).scalar_one_or_none() or 0
        subs_cnt = (await session.execute(select(func.count(Subscription.id)))).scalar_one_or_none() or 0
        used_codes_cnt = (await session.execute(select(func.count(SubscriptionCode.id)).where(SubscriptionCode.is_used == True))).scalar_one_or_none() or 0
        unused_codes_cnt = (await session.execute(select(func.count(SubscriptionCode.id)).where(SubscriptionCode.is_used == False))).scalar_one_or_none() or 0
        free_lectures_cnt = (await session.execute(select(func.count(User.id)).where(User.has_used_free_lecture == True))).scalar_one_or_none() or 0

        return {
            "users": users_cnt,
            "new_today": new_today,
            "new_week": new_week,
            "grades": grades_cnt,
            "subjects": subjects_cnt,
            "lessons": lessons_cnt,
            "files": files_cnt,
            "total_views": views_cnt,
            "subscriptions": subs_cnt,
            "used_codes": used_codes_cnt,
            "unused_codes": unused_codes_cnt,
            "free_lectures": free_lectures_cnt
        }

async def get_top_viewed_files(limit: int = 5):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(FileItem).order_by(FileItem.views_count.desc()).limit(limit)
        )
        return list(result.scalars().all())

async def get_all_user_ids() -> list[int]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User.id).where(User.is_blocked == False))
        return list(result.scalars().all())

async def export_all_data_for_excel() -> dict:
    async with AsyncSessionLocal() as session:
        students_res = await session.execute(select(User).where(User.is_admin == False, User.is_teacher == False))
        students = list(students_res.scalars().all())
        
        teachers_res = await session.execute(select(User).where(User.is_teacher == True))
        teachers = list(teachers_res.scalars().all())
        
        codes_res = await session.execute(select(SubscriptionCode, Subject).join(Subject, SubscriptionCode.subject_id == Subject.id))
        codes = list(codes_res.all())

        logs_res = await session.execute(select(AuditLog))
        logs = list(logs_res.scalars().all())

        return {
            "students": students,
            "teachers": teachers,
            "codes": codes,
            "logs": logs
        }