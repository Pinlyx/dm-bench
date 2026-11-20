import pytest

from dm_bench.langdetect import detect

SAMPLES = [
    ("en", "Thanks for reaching out! We are open until 6 pm and you can book online."),
    ("tr", "Merhaba, bugün saat 18:00'e kadar açığız, online rezervasyon yapabilirsiniz."),
    ("es", "¡Hola! Estamos abiertos hasta las 18:00 y puedes reservar en la web."),
    ("pt", "Olá! Estamos abertos até às 18h e você pode reservar pelo site."),
    ("de", "Hallo! Wir haben heute bis 18 Uhr geöffnet und Sie können online buchen."),
    ("ru", "Здравствуйте! Мы работаем до 18:00, записаться можно на сайте."),
    ("ar", "مرحباً! نحن نعمل حتى الساعة السادسة مساءً ويمكنك الحجز عبر الموقع."),
]


@pytest.mark.parametrize("lang,text", SAMPLES)
def test_detects_each_language(lang, text):
    assert detect(text) == lang


def test_ignores_urls_and_marker():
    assert detect("Merhaba, ekibimiz size hemen dönecek. https://example.com/the-and-you [HANDOFF]") == "tr"


def test_no_signal_returns_none():
    assert detect("") is None
    assert detect("12345 !!!") is None
