import fitz
from deep_translator import GoogleTranslator


def extract_pdf_text(pdf_path):

    doc = fitz.open(pdf_path)

    text = ""

    for page in doc:
        text += page.get_text()

    return text


def translate_text(text, target_language):

    translated = GoogleTranslator(
        source="auto",
        target=target_language
    ).translate(text)

    return translated