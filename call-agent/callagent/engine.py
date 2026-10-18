"""engine: free(무료, 내 PC에서만) / ai(Claude + ElevenLabs, 유료) 중 고르기."""


def is_free(cfg: dict) -> bool:
    return cfg.get("engine", "free") == "free"


def make_ears(cfg: dict):
    if is_free(cfg):
        from .local_stt import LocalEars
        return LocalEars(cfg)
    from .voice import Ears
    return Ears(cfg)


def make_brain(cfg: dict, playbook: str, customer: dict | None, clips):
    if is_free(cfg):
        from .rules import RuleBrain
        return RuleBrain(cfg, playbook, customer, clips=clips)
    from .brain import Brain
    return Brain(cfg, playbook, customer, clips=clips)


def voice_mode(cfg: dict) -> str:
    # 무료 모드에서는 합성 목소리가 없으므로 항상 내 녹음 그대로
    return "clips" if is_free(cfg) else cfg["voice"].get("mode", "clips")
