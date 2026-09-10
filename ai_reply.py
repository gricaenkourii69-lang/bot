import google.generativeai as genai
import os

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def init_gemini():
    genai.configure(api_key=GEMINI_API_KEY)

async def generate_reply(title: str, description: str, skills: str) -> str:
    """Генерировать отклик на заказ от имени фрилансера-девушки"""
    try:
        init_gemini()
        model = genai.GenerativeModel("gemini-1.5-flash")

        prompt = f"""Ти — дівчина-фрілансер, веб-розробник з досвідом у HTML/CSS, JavaScript, Python та Telegram-ботах.
Тебе звати Катерина. Ти пишеш відклик на фріланс-замовлення українською мовою.

Замовлення:
Назва: {title}
Опис: {description}
Навички: {skills}

Напиши короткий, професійний та персоналізований відклик (3-5 речень).
Покажи що ти розумієш завдання. Зроби акцент на своєму досвіді саме під це завдання.
Не пиши шаблонні фрази типу "Готова виконати проект". 
Відповідай від першої особи, у жіночому роді.
Лише текст відклику, без зайвих пояснень."""

        response = model.generate_content(prompt)
        return response.text.strip()

    except Exception as e:
        return f"⚠️ Не вдалося згенерувати відклик: {e}"
