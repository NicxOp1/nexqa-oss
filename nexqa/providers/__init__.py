"""
Voice platform adapters.

    from nexqa.providers import get_provider
    provider = get_provider("vapi", {"mode": "chat"})

A spec picks its platform with top-level keys (both optional):

    provider: vapi            # default: retell
    provider_config:
      mode: chat
      max_turns: 12

Adapters are imported lazily, so a missing optional dependency (websockets,
livekit-agents) only matters when you use that platform.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type

from nexqa.providers.base import (
    Conversation,
    ProviderError,
    SuiteRun,
    TestSuite,
    ToolCall,
    Turn,
    VoiceProvider,
)

DEFAULT_PROVIDER = "retell"

# name -> "module:Class"
REGISTRY: Dict[str, str] = {
    "retell": "nexqa.providers.retell:RetellProvider",
    "vapi": "nexqa.providers.vapi:VapiProvider",
    "elevenlabs": "nexqa.providers.elevenlabs:ElevenLabsProvider",
    "bland": "nexqa.providers.bland:BlandProvider",
    "synthflow": "nexqa.providers.synthflow:SynthflowProvider",
    "ultravox": "nexqa.providers.ultravox:UltravoxProvider",
    "livekit": "nexqa.providers.livekit:LiveKitProvider",
    "pipecat": "nexqa.providers.pipecat:PipecatProvider",
    "custom": "nexqa.providers.local:CustomHarnessProvider",
}

ALIASES = {
    "retellai": "retell",
    "eleven": "elevenlabs",
    "11labs": "elevenlabs",
    "elevenlabs_agents": "elevenlabs",
    "bland_ai": "bland",
    "livekit_agents": "livekit",
}


def normalize_name(name: Optional[str]) -> str:
    key = (name or DEFAULT_PROVIDER).strip().lower().replace("-", "_").replace(" ", "_")
    key = ALIASES.get(key, key)
    if key not in REGISTRY:
        raise ProviderError(
            f"Unknown provider {name!r}. Available: {', '.join(sorted(REGISTRY))}"
        )
    return key


def provider_class(name: Optional[str]) -> Type[VoiceProvider]:
    module_name, cls_name = REGISTRY[normalize_name(name)].split(":")
    return getattr(importlib.import_module(module_name), cls_name)


def get_provider(name: Optional[str] = None, config: Optional[Dict[str, Any]] = None,
                 **kwargs: Any) -> VoiceProvider:
    return provider_class(name)(config or {}, **kwargs)


def list_providers() -> List[Dict[str, str]]:
    return [provider_class(n).describe() for n in REGISTRY]


def load_provider_settings(spec_path: Optional[Path]) -> Tuple[str, Dict[str, Any]]:
    """Read `provider` / `provider_config` straight from a YAML or JSON spec.

    Read deterministically (not through the Claude ingest step). A spec that
    has neither key, or a spec that is not YAML/JSON (.txt, .docx), uses Retell.
    """
    if spec_path is None:
        return DEFAULT_PROVIDER, {}
    path = Path(spec_path)
    if not path.exists() or path.suffix.lower() not in (".yaml", ".yml", ".json"):
        return DEFAULT_PROVIDER, {}
    text = path.read_text(encoding="utf-8")
    try:
        if path.suffix.lower() == ".json":
            data = json.loads(text)
        else:
            import yaml

            data = yaml.safe_load(text)
    except Exception:
        return DEFAULT_PROVIDER, {}
    if not isinstance(data, dict):
        return DEFAULT_PROVIDER, {}
    name = normalize_name(data.get("provider") or DEFAULT_PROVIDER)
    config = data.get("provider_config") or {}
    if not isinstance(config, dict):
        raise ProviderError("provider_config must be a mapping")
    return name, config


__all__ = [
    "Conversation",
    "DEFAULT_PROVIDER",
    "ProviderError",
    "REGISTRY",
    "SuiteRun",
    "TestSuite",
    "ToolCall",
    "Turn",
    "VoiceProvider",
    "get_provider",
    "list_providers",
    "load_provider_settings",
    "normalize_name",
    "provider_class",
]
