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


async def score_project(title: str, description: str, skills: str) -> dict:
    """Оцінити заказ по 10-бальній шкалі"""
    try:
        init_gemini()
        model = genai.GenerativeModel("gemini-1.5-flash")

        prompt = f"""Ти — досвідчений фрілансер. Оціни це замовлення для веб-розробника (HTML/CSS/JS/Python/Telegram-боти).

Замовлення:
Назва: {title}
Опис: {description}
Навички: {skills}

Дай відповідь ТІЛЬКИ у форматі JSON (без markdown):
{{
  "score": <число від 1 до 10>,
  "pros": "<1-2 плюси коротко>",
  "cons": "<1-2 мінуси коротко>",
  "verdict": "<одне слово: Відмінно/Добре/Нормально/Слабко/Пропустити>"
}}"""

        response = model.generate_content(prompt)
        text = response.text.strip()
        # Чистимо можливий markdown
        text = text.replace("```json", "").replace("```", "").strip()
        import json
        return json.loads(text)

    except Exception as e:
        return {"score": 5, "pros": "", "cons": "", "verdict": "Нормально"}


async def analyze_skills_trend(projects: list) -> str:
    """Аналізувати які навички найчастіше зустрічаються"""
    try:
        init_gemini()
        model = genai.GenerativeModel("gemini-1.5-flash")

        skills_text = []
        for p in projects[:30]:
            attrs = p.get("attributes", {})
            for sk in attrs.get("skills", []):
                skills_text.append(sk.get("name", ""))

        if not skills_text:
            return "Недостатньо даних для аналізу."

        from collections import Counter
        counts = Counter(skills_text).most_common(10)
        skills_str = ", ".join(f"{k}({v})" for k, v in counts)

        prompt = f"""Проаналізуй попит на навички на фрілансі. Дай короткі поради українською (3-4 речення).
Статистика навичок: {skills_str}"""

        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"⚠️ Помилка аналізу: {e}"
