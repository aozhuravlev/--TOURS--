"""
Memes configuration for Instagram Stories generation.

Cultural codes and nostalgia triggers for 80-90s generation (target audience: 30-40 year olds with kids).
LLM selects the most relevant meme based on the topic context.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class MemeConfig:
    """Single meme configuration."""
    id: str              # Unique identifier
    name: str            # Display name for prompt
    trigger: str         # Emotional trigger
    example: str         # Example usage


# 27 memes organized by category
MEMES: list[MemeConfig] = [
    # === Ностальгия (детство 80-90-х) ===
    MemeConfig(
        id="childhood",
        name="Как в детстве",
        trigger="ностальгия, беззаботность",
        example="Мороженое у моря — как в детстве, только лучше",
    ),
    MemeConfig(
        id="dacha",
        name="Дача у бабушки",
        trigger="лето, свобода, фрукты с дерева",
        example="Инжир прямо с дерева — как на даче у бабушки",
    ),
    MemeConfig(
        id="sea_reward",
        name="Море как награда",
        trigger="особое событие, долгожданное",
        example="Помните, как ждали лета целый год? Вот оно",
    ),
    MemeConfig(
        id="yard_freedom",
        name="Двор и свобода",
        trigger="гуляли до темноты, сами по себе",
        example="Дети носятся по пляжу — как мы когда-то во дворе",
    ),
    MemeConfig(
        id="soviet_cinema",
        name="Советское кино",
        trigger="культовые фильмы, цитаты",
        example="Шашлык такой, что Шурик бы одобрил",
    ),
    MemeConfig(
        id="pioneer_camp",
        name="Пионерлагерь",
        trigger="лето, коллектив, костёр",
        example="Вечер у костра — как в лагере, только вино можно",
    ),

    # === Аутентичность ===
    MemeConfig(
        id="real_thing",
        name="Настоящее",
        trigger="натуральное, не из пакета, фермерское",
        example="Сыр настоящий — не тот, что в вакууме",
    ),
    MemeConfig(
        id="grandma_food",
        name="Бабушкина еда",
        trigger="домашнее, с любовью, руками",
        example="Хинкали лепят как бабушка — руками и с душой",
    ),
    MemeConfig(
        id="homemade_wine",
        name="Домашнее вино",
        trigger="не магазинное, своё",
        example="Вино домашнее — дядя Гиви делает сам",
    ),
    MemeConfig(
        id="bazaar",
        name="Рынок/базар",
        trigger="колорит, торг, свежее, общение",
        example="На базаре — это не покупки, это спектакль",
    ),
    MemeConfig(
        id="authentic",
        name="Не для туристов",
        trigger="как у местных, настоящее",
        example="Место, куда ходят сами батумцы",
    ),
    MemeConfig(
        id="simple",
        name="По-простому",
        trigger="без понтов, честно",
        example="Пластиковые стулья, но шашлык — лучший в городе",
    ),

    # === Побег от реальности ===
    MemeConfig(
        id="escape",
        name="Побег от суеты",
        trigger="другой мир, без пробок, перезагрузка",
        example="Здесь нет пробок — только море и горы",
    ),
    MemeConfig(
        id="digital_detox",
        name="Убрать телефон",
        trigger="смотреть, а не снимать",
        example="Закат такой, что телефон убрали — просто смотрим",
    ),
    MemeConfig(
        id="mountains_freedom",
        name="Горы = свобода",
        trigger="высота, масштаб, всё мелочи",
        example="Смотришь с горы — и все проблемы кажутся мелкими",
    ),
    MemeConfig(
        id="fresh_air",
        name="Свежий воздух",
        trigger="не кондиционер, природа, здоровье",
        example="Воздух такой, что дышишь и не надышишься",
    ),

    # === Социальные связи ===
    MemeConfig(
        id="hospitality",
        name="Кавказское гостеприимство",
        trigger="накормят, не отпустят",
        example="Хозяин не отпустит, пока не поешь трижды",
    ),
    MemeConfig(
        id="feast",
        name="Застолье",
        trigger="большой стол, тосты, долгие разговоры",
        example="Обед на 3 часа — это не обед, это событие",
    ),
    MemeConfig(
        id="soulful",
        name="Душевно",
        trigger="не сервис, а тепло, искренность",
        example="Официант уже как друг — советует от души",
    ),
    MemeConfig(
        id="traditions",
        name="Традиции",
        trigger="от прабабушки, не меняли",
        example="Рецепт 100 лет — и менять не собираются",
    ),

    # === Ценности миллениалов ===
    MemeConfig(
        id="discovery",
        name="Открытия",
        trigger="не по туристическим тропам, своё",
        example="Нашли место — в путеводителях такого нет",
    ),
    MemeConfig(
        id="history",
        name="История",
        trigger="связь времён, глубина",
        example="Этой крепости 500 лет — представляете?",
    ),
    MemeConfig(
        id="fair_price",
        name="Справедливая цена",
        trigger="честно, за эти деньги",
        example="За эти деньги в Москве — бизнес-ланч. Здесь — пир",
    ),
    MemeConfig(
        id="human_way",
        name="По-человечески",
        trigger="не all-inclusive, живое общение",
        example="Не отель-браслет, а живые люди и истории",
    ),

    # === Семья ===
    MemeConfig(
        id="kids_happy",
        name="Дети в восторге",
        trigger="детские эмоции, радость",
        example="Ребёнок увидел дельфинов — это бесценно",
    ),
    MemeConfig(
        id="family_memories",
        name="Семейные воспоминания",
        trigger="фото на холодильник, вспоминать",
        example="Это фото — на холодильник, будем вспоминать",
    ),
    MemeConfig(
        id="safety",
        name="Безопасность",
        trigger="дети бегают спокойно, расслабленность",
        example="Дети носятся — и никто не дёргается",
    ),
]


def get_all_memes() -> list[MemeConfig]:
    """Get all memes."""
    return MEMES


def get_meme_by_id(meme_id: str) -> Optional[MemeConfig]:
    """Get meme by ID."""
    for meme in MEMES:
        if meme.id == meme_id:
            return meme
    return None


def format_memes_for_prompt() -> str:
    """
    Format all memes as a string for LLM prompt.

    Returns:
        Formatted string with all memes for prompt insertion.
    """
    lines = []
    for meme in MEMES:
        lines.append(f"- {meme.id}: \"{meme.name}\" — {meme.trigger}")
        lines.append(f"  Пример: {meme.example}")
    return "\n".join(lines)


def get_total_memes() -> int:
    """Get total number of memes."""
    return len(MEMES)
