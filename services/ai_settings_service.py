from storage.ai_settings_store import AISettingsStore
from storage.prompt_store import PromptStore


class AISettingsService:
    def __init__(self, settings: AISettingsStore, prompts: PromptStore):
        self.settings = settings
        self.prompts = prompts

    def get(self) -> dict:
        return {
            "settings": self.settings.get(),
            "system_prompt": self.prompts.get(),
            "default_system_prompt": self.prompts.default,
        }

    def save(self, settings: dict[str, bool], system_prompt: str) -> dict:
        self.settings.save(settings)
        self.prompts.save(system_prompt)
        return self.get()

    def get_prompt(self) -> str:
        return self.prompts.get()

    def save_prompt(self, prompt: str) -> None:
        self.prompts.save(prompt)
