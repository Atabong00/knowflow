from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Course(Base):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=True)
    description = Column(Text, nullable=True)
    objectives = Column(Text, nullable=True)
    category = Column(String, nullable=True, index=True)
    difficulty = Column(String, default="Beginner", nullable=False)
    duration = Column(String, nullable=True)
    published = Column(Boolean, default=False, nullable=False)
    mandatory = Column(Boolean, default=False, nullable=False)
    passing_score = Column(Integer, default=70, nullable=False)
    start_date = Column(DateTime, nullable=True)
    due_date = Column(DateTime, nullable=True)
    requires_module_completion = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    modules = relationship("Module", back_populates="course", cascade="all, delete-orphan", order_by="Module.order")
    assessments = relationship("Assessment", back_populates="course", cascade="all, delete-orphan")
    progress_records = relationship("Progress", back_populates="course", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Course title={self.title} category={self.category} difficulty={self.difficulty} published={self.published}>"


class Module(Base):
    __tablename__ = "modules"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=True)
    content_type = Column(String, default="markdown", nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    order = Column(Integer, default=0, nullable=False)
    assessment_id = Column(Integer, ForeignKey("assessments.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    course = relationship("Course", back_populates="modules")
    assessment = relationship("Assessment", back_populates="module", uselist=False)
    document = relationship("Document", backref="training_modules")

    def __repr__(self):
        return f"<Module title={self.title} course_id={self.course_id} order={self.order}>"


class Assessment(Base):
    __tablename__ = "assessments"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False)
    passing_score = Column(Integer, default=70, nullable=False)
    max_attempts = Column(Integer, default=3, nullable=False)
    retakes_allowed = Column(Boolean, default=True, nullable=False)
    time_limit = Column(Integer, nullable=True)
    published = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    course = relationship("Course", back_populates="assessments")
    module = relationship("Module", back_populates="assessment", uselist=False)
    questions = relationship("Question", back_populates="assessment", cascade="all, delete-orphan", order_by="Question.order")
    attempts = relationship("Attempt", back_populates="assessment", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Assessment title={self.title} passing_score={self.passing_score} max_attempts={self.max_attempts}>"


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    type = Column(String, default="multiple_choice", nullable=False)
    question = Column(Text, nullable=False)
    options = Column(Text, nullable=True)
    correct_answer = Column(Text, nullable=False)
    points = Column(Integer, default=1, nullable=False)
    explanation = Column(Text, nullable=True)
    difficulty = Column(String, default="Medium", nullable=False)
    topic = Column(String, nullable=True, index=True)
    order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    assessment = relationship("Assessment", back_populates="questions")

    def __repr__(self):
        return f"<Question type={self.type} assessment_id={self.assessment_id} points={self.points}>"


class Attempt(Base):
    __tablename__ = "attempts"

    id = Column(Integer, primary_key=True, index=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    user_keycloak_id = Column(String, ForeignKey("users.keycloak_id", ondelete="SET NULL"), nullable=True)
    attempt_number = Column(Integer, default=1, nullable=False)
    answers = Column(Text, nullable=False)
    score = Column(Integer, default=0, nullable=False)
    percentage = Column(Integer, default=0, nullable=False)
    passed = Column(Boolean, default=False, nullable=False)
    completed_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    assessment = relationship("Assessment", back_populates="attempts")
    user = relationship("User")

    def __repr__(self):
        return f"<Attempt assessment_id={self.assessment_id} user={self.user_keycloak_id} score={self.percentage}% passed={self.passed}>"


class Progress(Base):
    __tablename__ = "progress"

    id = Column(Integer, primary_key=True, index=True)
    user_keycloak_id = Column(String, ForeignKey("users.keycloak_id", ondelete="CASCADE"), nullable=False)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    completed_modules = Column(Text, nullable=True)
    progress_percentage = Column(Integer, default=0, nullable=False)
    status = Column(String, default="not_started", nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    course = relationship("Course", back_populates="progress_records")
    user = relationship("User")

    def __repr__(self):
        return f"<Progress user={self.user_keycloak_id} course_id={self.course_id} status={self.status} progress={self.progress_percentage}%>"
