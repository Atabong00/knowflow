from typing import TypeVar, Optional, List
from pydantic import BaseModel, Field, ValidationError, field_validator
from fastapi import Request, HTTPException, status

T = TypeVar("T", bound=BaseModel)


def form_parser(model: type[T]):
    async def parser(request: Request) -> T:
        form_data = await request.form()
        try:
            return model(**dict(form_data))
        except ValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=e.errors()
            )
    return parser


class CategoryBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(CategoryBase):
    name: str | None = None
    description: str | None = None


class DocumentBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)
    category_id: int | None = Field(None, ge=0)
    status_str: str = Field("published")

    @field_validator("status_str")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ("draft", "published"):
            raise ValueError("Status must be 'draft' or 'published'")
        return v


class DocumentCreate(DocumentBase):
    pass


class DocumentUpdate(DocumentBase):
    title: str | None = None
    content: str | None = None
    category_id: int | None = None
    status_str: str | None = None

    @field_validator("status_str", mode="before")
    @classmethod
    def empty_str_to_default(cls, v: str | None) -> str | None:
        if v == "" or v is None:
            return None
        return v


# ---------------------------------------------------------------------------
# Training / Quiz / Assessment Schemas
# ---------------------------------------------------------------------------

class CourseBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    objectives: str | None = None
    category: str | None = None
    difficulty: str = Field("Beginner")
    duration: str | None = None
    passing_score: int = Field(70, ge=0, le=100)
    start_date: Optional[str] = None
    due_date: Optional[str] = None
    mandatory: bool = False
    requires_module_completion: bool = False
    published: bool = False

    @field_validator("difficulty")
    @classmethod
    def validate_difficulty(cls, v: str) -> str:
        if v not in ("Beginner", "Intermediate", "Advanced"):
            raise ValueError("Difficulty must be Beginner, Intermediate, or Advanced")
        return v


class CourseCreate(CourseBase):
    pass


class CourseUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    objectives: str | None = None
    category: str | None = None
    difficulty: str | None = None
    duration: str | None = None
    passing_score: int | None = Field(None, ge=0, le=100)
    start_date: Optional[str] = None
    due_date: Optional[str] = None
    mandatory: bool | None = None
    requires_module_completion: bool | None = None
    published: bool | None = None

    @field_validator("difficulty")
    @classmethod
    def validate_difficulty(cls, v: str | None) -> str | None:
        if v is not None and v not in ("Beginner", "Intermediate", "Advanced"):
            raise ValueError("Difficulty must be Beginner, Intermediate, or Advanced")
        return v


class ModuleBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str | None = None
    content_type: str = Field("markdown")
    order: int = Field(0, ge=0)

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, v: str) -> str:
        if v not in ("markdown", "document"):
            raise ValueError("content_type must be 'markdown' or 'document'")
        return v


class ModuleCreate(ModuleBase):
    course_id: int
    document_id: Optional[int] = None
    assessment_id: Optional[int] = None


class ModuleUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    content_type: str | None = None
    document_id: Optional[int] = None
    order: int | None = None
    assessment_id: Optional[int] = None

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, v: str | None) -> str | None:
        if v is not None and v not in ("markdown", "document"):
            raise ValueError("content_type must be 'markdown' or 'document'")
        return v


class QuestionBase(BaseModel):
    type: str = Field("multiple_choice")
    question_text: str = Field(..., min_length=1)
    options: str = Field(...)
    correct_answer: str = Field(...)
    points: int = Field(1, ge=1)
    explanation: str | None = None
    difficulty: str = Field("Medium")
    topic: str | None = None
    order: int = Field(0, ge=0)

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ("multiple_choice", "true_false", "multiple_select"):
            raise ValueError("type must be multiple_choice, true_false, or multiple_select")
        return v

    @field_validator("difficulty")
    @classmethod
    def validate_difficulty(cls, v: str) -> str:
        if v not in ("Easy", "Medium", "Hard"):
            raise ValueError("difficulty must be Easy, Medium, or Hard")
        return v


class QuestionCreate(QuestionBase):
    pass


class QuestionUpdate(BaseModel):
    type: str | None = None
    question_text: str | None = None
    options: str | None = None
    correct_answer: str | None = None
    points: int | None = Field(None, ge=1)
    explanation: str | None = None
    difficulty: str | None = None
    topic: str | None = None
    order: int | None = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str | None) -> str | None:
        if v is not None and v not in ("multiple_choice", "true_false", "multiple_select"):
            raise ValueError("type must be multiple_choice, true_false, or multiple_select")
        return v

    @field_validator("difficulty")
    @classmethod
    def validate_difficulty(cls, v: str | None) -> str | None:
        if v is not None and v not in ("Easy", "Medium", "Hard"):
            raise ValueError("difficulty must be Easy, Medium, or Hard")
        return v


class AssessmentBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    passing_score: int = Field(70, ge=0, le=100)
    max_attempts: int = Field(3, ge=0)
    retakes_allowed: bool = True
    time_limit: Optional[int] = None


class AssessmentCreate(AssessmentBase):
    course_id: int


class AssessmentUpdate(BaseModel):
    title: str | None = None
    passing_score: int | None = Field(None, ge=0, le=100)
    max_attempts: int | None = Field(None, ge=0)
    retakes_allowed: bool | None = None
    time_limit: Optional[int] = None
    published: bool | None = None


# ---------------------------------------------------------------------------
# Quiz / Attempt submission schemas
# ---------------------------------------------------------------------------

class QuizAnswer(BaseModel):
    question_id: int
    answer: str | list[str]


class QuizSubmission(BaseModel):
    answers: List[QuizAnswer]
