from core.audio.runtime_audio import get_legacy_audio_manager, get_runtime_audio_manager


def test_runtime_audio_singleton_alias():
    runtime_mgr = get_runtime_audio_manager()
    legacy_mgr = get_legacy_audio_manager()
    assert runtime_mgr is legacy_mgr
