from pydantic import BaseModel, ConfigDict, Field, model_validator


class Source(BaseModel):
    id: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str
    image: str | None = None


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    explanation: str
    steps: list[str]
    limitations: list[str]
    source_ids: list[str] = Field(min_length=1)


class QuizOption(BaseModel):
    label: str
    text: str


class Quiz(BaseModel):
    question: str
    options: list[QuizOption]
    correct_option: str | None
    explanation: str

    @model_validator(mode="after")
    def check_answer(self):
        if self.correct_option is not None and self.correct_option not in {
            option.label for option in self.options
        }:
            raise ValueError("Ответ должен совпадать с меткой существующего варианта")
        return self


class VideoSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(description="Type of the observed content, named by the model")
    title: str
    items: list[str]
    source_ids: list[str] = Field(min_length=1)
    visual_evidence: str = ""
    quiz: Quiz | None = None


class Chapter(VideoSection):
    start: float = Field(ge=0)
    end: float = Field(ge=0)


class Notes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notes: list[Note]
    sections: list[VideoSection] = Field(default_factory=list)
    context_summary: str = Field(default="", description="Russian summary of this block, at most 20 words")
    lecture_plan: list[str] = Field(default_factory=list, description="Explicit lecture agenda visible in current sources, or []")
