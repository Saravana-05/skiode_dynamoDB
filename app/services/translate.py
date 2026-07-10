"""
Pluggable machine-translation service.
Default provider: MyMemory (free, no API key, ~5000 words/day on anon usage).
Swap `translate_text`'s implementation to Google/Azure/DeepL later —
call sites (`build_translations`) never need to change.
"""
import httpx

SUPPORTED_LANGS = ["en", "ta", "ar"]   # add more language codes here later, nothing else changes

_LANG_PAIRS = {
    "ta": "en|ta",
    "ar": "en|ar",
}


async def translate_text(text: str, target_lang: str) -> str:
    """Translate `text` (assumed English) into target_lang. Returns text unchanged on failure."""
    if not text or target_lang == "en":
        return text
    pair = _LANG_PAIRS.get(target_lang)
    if not pair:
        return text
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://api.mymemory.translated.net/get",
                params={"q": text, "langpair": pair},
            )
            resp.raise_for_status()
            data = resp.json()
            translated = data.get("responseData", {}).get("translatedText")
            return translated or text
    except Exception as e:
        print(f"[translate] WARNING: could not translate '{text}' -> {target_lang}: {e}")
        return text


async def build_translations(label: str, existing: dict | None = None) -> dict:
    """
    Returns a translations dict {en, ta, ar, ...} for a label.
    Reuses any languages already present in `existing` when the English
    label hasn't changed, so we never re-translate (and never re-call
    the external API) for an unchanged label.
    """
    existing = existing or {}
    result = {"en": label}
    for lang in SUPPORTED_LANGS:
        if lang == "en":
            continue
        if existing.get(lang) and existing.get("en") == label:
            result[lang] = existing[lang]
        else:
            result[lang] = await translate_text(label, lang)
    return result