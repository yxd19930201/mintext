from typing import Literal

from pydantic import BaseModel, model_validator


GenerationMode = Literal["economy", "strict", "free"]


class GenerationModeOptions(BaseModel):
    """Common mode snapshot attached to every AI job.

    The optional explicit name is used by current desktop clients.  The two
    booleans remain for compatibility with previously released installers.
    """

    generation_mode: GenerationMode | None = None
    economy_mode: bool = False
    free_mode: bool = False
    free_provider: Literal["deepseek", "chatgpt"] = "deepseek"

    @model_validator(mode="after")
    def synchronize_legacy_flags(self):
        if self.generation_mode == "free":
            self.free_mode = True
            self.economy_mode = True
        elif self.generation_mode == "strict":
            self.free_mode = False
            self.economy_mode = False
        elif self.generation_mode == "economy":
            self.free_mode = False
            self.economy_mode = True
        return self
