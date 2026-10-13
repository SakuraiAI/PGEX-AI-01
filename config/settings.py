from dataclasses import dataclass
from pathlib import Path

from config.env import get_env_bool, get_env_int, get_env_str


APP_NAME = get_env_str("LUNA_APP_NAME", "PGEX")
APP_HOST = get_env_str("LUNA_APP_HOST", "127.0.0.1")
APP_PORT = get_env_int("LUNA_APP_PORT", 8000)
MODEL_TYPE = get_env_str("LUNA_MODEL_TYPE", "nvidia")
MEMORY_PATH = get_env_str("LUNA_MEMORY_PATH", "data/chats/chat_history.json")
LONG_MEMORY_PATH = get_env_str("LUNA_LONG_MEMORY_PATH", "data/chats/long_memory.json")
USER_SETTINGS_PATH = get_env_str("LUNA_USER_SETTINGS_PATH", "data/settings/user_settings.json")
PROJECTS_PATH = get_env_str("LUNA_PROJECTS_PATH", "data/projects/projects.json")
LIBRARY_PATH = get_env_str("LUNA_LIBRARY_PATH", "data/library/library.json")
DEFAULT_WORKFLOW = get_env_str("LUNA_DEFAULT_WORKFLOW", "auto")
DEFAULT_REASONING_BOX = get_env_str("LUNA_DEFAULT_REASONING_BOX", "black_box")
MEMORY_REVIEW_INTERVAL = get_env_int("LUNA_MEMORY_REVIEW_INTERVAL", 6)

LM_STUDIO_BASE_URL = get_env_str("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/api/v1/chat")
LM_STUDIO_MODEL = get_env_str("LM_STUDIO_MODEL", "google/gemma-3-4b")
LM_STUDIO_API_TOKEN = get_env_str("LM_STUDIO_API_TOKEN", "")
LM_STUDIO_TIMEOUT_SECONDS = get_env_int("LM_STUDIO_TIMEOUT_SECONDS", 180)

NVIDIA_API_KEY = get_env_str("NVIDIA_API_KEY", "")

LUNA_NVIDIA_BASE_URL = get_env_str("LUNA_NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
LUNA_NVIDIA_MODEL = get_env_str("LUNA_NVIDIA_MODEL", "openai/gpt-oss-120b")
LUNA_NVIDIA_API_TOKEN = get_env_str("LUNA_NVIDIA_API_TOKEN", NVIDIA_API_KEY)
LUNA_NVIDIA_TIMEOUT_SECONDS = get_env_int("LUNA_NVIDIA_TIMEOUT_SECONDS", 180)

NVIDIA_BASE_URL = get_env_str("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_MODEL = get_env_str("NVIDIA_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning")
NVIDIA_API_TOKEN = get_env_str("NVIDIA_API_TOKEN", NVIDIA_API_KEY)
NVIDIA_TIMEOUT_SECONDS = get_env_int("NVIDIA_TIMEOUT_SECONDS", 180)
NVIDIA_REASONING_BUDGET = get_env_int("NVIDIA_REASONING_BUDGET", 16384)
NVIDIA_ENABLE_THINKING = get_env_bool("NVIDIA_ENABLE_THINKING", True)

VISION_NVIDIA_BASE_URL = get_env_str("VISION_NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
VISION_NVIDIA_MODEL = get_env_str("VISION_NVIDIA_MODEL", "nvidia/nemotron-nano-12b-v2-vl")
VISION_NVIDIA_API_TOKEN = get_env_str("VISION_NVIDIA_API_TOKEN", NVIDIA_API_TOKEN)
VISION_NVIDIA_TIMEOUT_SECONDS = get_env_int("VISION_NVIDIA_TIMEOUT_SECONDS", 180)

SPEECH_NVIDIA_BASE_URL = get_env_str("SPEECH_NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
SPEECH_NVIDIA_MODEL = get_env_str("SPEECH_NVIDIA_MODEL", "nvidia/parakeet-1.1b-rnnt-multilingual-asr")
SPEECH_NVIDIA_API_TOKEN = get_env_str("SPEECH_NVIDIA_API_TOKEN", NVIDIA_API_TOKEN)
SPEECH_NVIDIA_SERVER = get_env_str("SPEECH_NVIDIA_SERVER", "grpc.nvcf.nvidia.com:443")
SPEECH_NVIDIA_FUNCTION_ID = get_env_str("SPEECH_NVIDIA_FUNCTION_ID", "71203149-d3b7-4460-8231-1be2543a1fca")
SPEECH_NVIDIA_USE_SSL = get_env_bool("SPEECH_NVIDIA_USE_SSL", True)
SPEECH_NVIDIA_TIMEOUT_SECONDS = get_env_int("SPEECH_NVIDIA_TIMEOUT_SECONDS", 180)
SPEECH_NVIDIA_LANGUAGE = get_env_str("SPEECH_NVIDIA_LANGUAGE", "cs-CZ")

TTS_NVIDIA_MODEL = get_env_str("TTS_NVIDIA_MODEL", "nvidia/magpie-tts-multilingual")
TTS_NVIDIA_API_TOKEN = get_env_str("TTS_NVIDIA_API_TOKEN", NVIDIA_API_TOKEN)
TTS_NVIDIA_SERVER = get_env_str("TTS_NVIDIA_SERVER", "grpc.nvcf.nvidia.com:443")
TTS_NVIDIA_FUNCTION_ID = get_env_str("TTS_NVIDIA_FUNCTION_ID", "877104f7-e885-42b9-8de8-f6e4c6303969")
TTS_NVIDIA_USE_SSL = get_env_bool("TTS_NVIDIA_USE_SSL", True)
TTS_NVIDIA_TIMEOUT_SECONDS = get_env_int("TTS_NVIDIA_TIMEOUT_SECONDS", 180)
TTS_NVIDIA_LANGUAGE = get_env_str("TTS_NVIDIA_LANGUAGE", "en-US")
TTS_NVIDIA_VOICE = get_env_str("TTS_NVIDIA_VOICE", "Magpie-Multilingual.EN-US.Aria")
TTS_NVIDIA_SAMPLE_RATE = get_env_int("TTS_NVIDIA_SAMPLE_RATE", 22050)
TTS_OUTPUT_DIR = get_env_str("TTS_OUTPUT_DIR", "data/audio/tts")

INTERNET_ENABLED = get_env_bool("LUNA_INTERNET_ENABLED", True)
INTERNET_MODE = get_env_str("LUNA_INTERNET_MODE", "auto")


@dataclass(slots=True)
class AppSettings:
    app_name: str = APP_NAME
    host: str = APP_HOST
    port: int = APP_PORT
    model_type: str = MODEL_TYPE
    memory_path: str = MEMORY_PATH
    long_memory_path: str = LONG_MEMORY_PATH
    user_settings_path: str = USER_SETTINGS_PATH
    projects_path: str = PROJECTS_PATH
    library_path: str = LIBRARY_PATH
    default_workflow: str = DEFAULT_WORKFLOW
    default_reasoning_box: str = DEFAULT_REASONING_BOX
    memory_review_interval: int = MEMORY_REVIEW_INTERVAL
    lm_studio_base_url: str = LM_STUDIO_BASE_URL
    lm_studio_model: str = LM_STUDIO_MODEL
    lm_studio_api_token: str = LM_STUDIO_API_TOKEN
    lm_studio_timeout_seconds: int = LM_STUDIO_TIMEOUT_SECONDS
    luna_nvidia_base_url: str = LUNA_NVIDIA_BASE_URL
    luna_nvidia_model: str = LUNA_NVIDIA_MODEL
    luna_nvidia_api_token: str = LUNA_NVIDIA_API_TOKEN
    luna_nvidia_timeout_seconds: int = LUNA_NVIDIA_TIMEOUT_SECONDS
    nvidia_base_url: str = NVIDIA_BASE_URL
    nvidia_model: str = NVIDIA_MODEL
    nvidia_api_token: str = NVIDIA_API_TOKEN
    nvidia_timeout_seconds: int = NVIDIA_TIMEOUT_SECONDS
    nvidia_reasoning_budget: int = NVIDIA_REASONING_BUDGET
    nvidia_enable_thinking: bool = NVIDIA_ENABLE_THINKING
    vision_nvidia_base_url: str = VISION_NVIDIA_BASE_URL
    vision_nvidia_model: str = VISION_NVIDIA_MODEL
    vision_nvidia_api_token: str = VISION_NVIDIA_API_TOKEN
    vision_nvidia_timeout_seconds: int = VISION_NVIDIA_TIMEOUT_SECONDS
    speech_nvidia_base_url: str = SPEECH_NVIDIA_BASE_URL
    speech_nvidia_model: str = SPEECH_NVIDIA_MODEL
    speech_nvidia_api_token: str = SPEECH_NVIDIA_API_TOKEN
    speech_nvidia_server: str = SPEECH_NVIDIA_SERVER
    speech_nvidia_function_id: str = SPEECH_NVIDIA_FUNCTION_ID
    speech_nvidia_use_ssl: bool = SPEECH_NVIDIA_USE_SSL
    speech_nvidia_timeout_seconds: int = SPEECH_NVIDIA_TIMEOUT_SECONDS
    speech_nvidia_language: str = SPEECH_NVIDIA_LANGUAGE
    tts_nvidia_model: str = TTS_NVIDIA_MODEL
    tts_nvidia_api_token: str = TTS_NVIDIA_API_TOKEN
    tts_nvidia_server: str = TTS_NVIDIA_SERVER
    tts_nvidia_function_id: str = TTS_NVIDIA_FUNCTION_ID
    tts_nvidia_use_ssl: bool = TTS_NVIDIA_USE_SSL
    tts_nvidia_timeout_seconds: int = TTS_NVIDIA_TIMEOUT_SECONDS
    tts_nvidia_language: str = TTS_NVIDIA_LANGUAGE
    tts_nvidia_voice: str = TTS_NVIDIA_VOICE
    tts_nvidia_sample_rate: int = TTS_NVIDIA_SAMPLE_RATE
    tts_output_dir: str = TTS_OUTPUT_DIR
    internet_enabled: bool = INTERNET_ENABLED
    internet_mode: str = INTERNET_MODE

    def ensure_directories(self) -> None:
        Path(self.memory_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.long_memory_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.user_settings_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.projects_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.library_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.tts_output_dir).mkdir(parents=True, exist_ok=True)


__all__ = [
    "AppSettings",
    "APP_NAME",
    "APP_HOST",
    "APP_PORT",
    "MODEL_TYPE",
    "MEMORY_PATH",
    "LONG_MEMORY_PATH",
    "USER_SETTINGS_PATH",
    "PROJECTS_PATH",
    "LIBRARY_PATH",
    "DEFAULT_WORKFLOW",
    "DEFAULT_REASONING_BOX",
    "MEMORY_REVIEW_INTERVAL",
    "LM_STUDIO_BASE_URL",
    "LM_STUDIO_MODEL",
    "LM_STUDIO_API_TOKEN",
    "LM_STUDIO_TIMEOUT_SECONDS",
    "LUNA_NVIDIA_BASE_URL",
    "LUNA_NVIDIA_MODEL",
    "LUNA_NVIDIA_API_TOKEN",
    "LUNA_NVIDIA_TIMEOUT_SECONDS",
    "NVIDIA_API_KEY",
    "NVIDIA_BASE_URL",
    "NVIDIA_MODEL",
    "NVIDIA_API_TOKEN",
    "NVIDIA_TIMEOUT_SECONDS",
    "NVIDIA_REASONING_BUDGET",
    "NVIDIA_ENABLE_THINKING",
    "VISION_NVIDIA_BASE_URL",
    "VISION_NVIDIA_MODEL",
    "VISION_NVIDIA_API_TOKEN",
    "VISION_NVIDIA_TIMEOUT_SECONDS",
    "SPEECH_NVIDIA_BASE_URL",
    "SPEECH_NVIDIA_MODEL",
    "SPEECH_NVIDIA_API_TOKEN",
    "SPEECH_NVIDIA_SERVER",
    "SPEECH_NVIDIA_FUNCTION_ID",
    "SPEECH_NVIDIA_USE_SSL",
    "SPEECH_NVIDIA_TIMEOUT_SECONDS",
    "SPEECH_NVIDIA_LANGUAGE",
    "TTS_NVIDIA_MODEL",
    "TTS_NVIDIA_API_TOKEN",
    "TTS_NVIDIA_SERVER",
    "TTS_NVIDIA_FUNCTION_ID",
    "TTS_NVIDIA_USE_SSL",
    "TTS_NVIDIA_TIMEOUT_SECONDS",
    "TTS_NVIDIA_LANGUAGE",
    "TTS_NVIDIA_VOICE",
    "TTS_NVIDIA_SAMPLE_RATE",
    "TTS_OUTPUT_DIR",
    "INTERNET_ENABLED",
    "INTERNET_MODE",
]
