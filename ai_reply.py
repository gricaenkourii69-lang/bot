import google.generativeai as genai
import os
import json
from collections import Counter

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = "gemini-2.0-flash"

def init_gemini():
    genai.configure(api_key=GEMINI_API_KEY)

async def generate_reply(title: str, description: str, skills: str) -> str:
    try:
        init_gemini()
        model = genai.GenerativeModel(MODEL)
        prompt = (
            "Ти — дівчина-фрілансер, веб-розробник (HTML/CSS/JS/Python/Telegram-боти). "
            "Звати Катерина. Пишеш відклик українською.\n\n"
            f"Замовлення:\nНазва: {title}\nОпис: {description}\nНавички: {skills}\n\n"
            "Напиши короткий персоналізований відклик (3-5 речень). "
            "Покажи розуміння завдання. Від першої особи, жіночий рід. "
            "Без шаблонних фраз. Тільки текст відклику."
        )
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"⚠️ Помилка: {e}"

async def score_project(title: str, description: str, skills: str) -> dict:
    try:
        init_gemini()
        model = genai.GenerativeModel(MODEL)
        prompt = (
            "Оціни фріланс-замовлення для веб-розробника (HTML/CSS/JS/Python/Telegram).\n\n"
            f"Назва: {title}\nОпис: {description}\nНавички: {skills}\n\n"
            "Відповідь ТІЛЬКИ JSON без markdown:\n"
            '{"score": <1-10>, "pros": "<плюси>", "cons": "<мінуси>", "verdict": "<Відмінно/Добре/Нормально/Слабко/Пропустити>"}'
        )
        response = model.generate_content(prompt)
        text = response.text.strip().replace("```json","").replace("```","").strip()
        return json.loads(text)
    except Exception:
        return {"score": 5, "pros": "—", "cons": "—", "verdict": "Нормально"}

async def analyze_skills_trend(projects: list) -> str:
    try:
        init_gemini()
        model = genai.GenerativeModel(MODEL)
        skills_list = []
        for p in projects[:30]:
            for sk in (p.get("attributes") or {}).get("skills", []):
                name = sk.get("name", "")
                if name:
                    skills_list.append(name)
        if not skills_list:
            return "Недостатньо даних. Спробуй пізніше."
        counts = Counter(skills_list).most_common(10)
        skills_str = ", ".join(f"{k}({v})" for k, v in counts)
        prompt = (
            f"Статистика навичок на фрілансі: {skills_str}\n\n"
            "Дай короткий аналіз попиту та поради фрілансеру (3-4 речення, українською)."
        )
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"⚠️ Помилка аналізу: {e}"
