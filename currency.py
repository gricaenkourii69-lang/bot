import aiohttp

async def get_usd_rate() -> float:
    """Получить курс USD/UAH с НБУ"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?valcode=USD&json",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                data = await resp.json()
                return float(data[0]["rate"])
    except Exception:
        return 41.0  # fallback

async def format_budget(amount, currency="UAH") -> str:
    if not amount or amount == 0:
        return "Договірна"
    if currency == "UAH":
        rate = await get_usd_rate()
        usd = round(amount / rate)
        return f"{amount} UAH (~${usd})"
    elif currency == "USD":
        rate = await get_usd_rate()
        uah = round(amount * rate)
        return f"${amount} (~{uah} UAH)"
    return f"{amount} {currency}"
