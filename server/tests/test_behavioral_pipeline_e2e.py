"""End-to-end behavioral pipeline validation on REAL text (#68, CI gate).

This is the always-on companion to the live-LLM suite in
``tests/e2e_real_llm/`` (which needs ANTHROPIC_API_KEY and runs on demand).
Here we drive the SAME production pipeline — the real SDK feature extractor
(``metalins_drift.behavioral.compute_behavioral_features``) feeding the real
κ-engine V2 core (``app.kappa.build_distributions`` /
``compare_distributions``) — over corpora of real, human-written text:

  • a CONCISE corpus: short, plain-text, one-sentence answers, and
  • a VERBOSE+CODE corpus: long multi-paragraph answers with fenced code
    blocks, bulleted lists and markdown headings.

The text is real content run through the real extractor and real engine;
only its *source* is a fixture rather than a freshly-billed LLM call. That
keeps the wiring (#62 + #63) under continuous test without a paid key,
while the live suite proves the same path against an actual model.

Asserts the contract from board #68:
  - a behavioral shift (concise → verbose+code) is detected (verified=False,
    drift_score high) with a plausible dominant feature + attribution, and
  - the same corpus against itself does NOT trip a false drift.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# The SDK feature extractor lives in sdk-python; make it importable from the
# server test process (server `app` is already on path).
_SDK_DIR = Path(__file__).resolve().parents[2] / "sdk-python"
if str(_SDK_DIR) not in sys.path:
    sys.path.insert(0, str(_SDK_DIR))

_TMP_DB_PATH = f"/tmp/_metalins_pipeline_e2e_{os.getpid()}.db"
os.environ.setdefault("METALINS_DB_URL", f"sqlite:///{_TMP_DB_PATH}")
os.environ.setdefault("METALINS_DISABLE_INPROC_SCHEDULER", "1")

from metalins_drift.behavioral import compute_behavioral_features  # noqa: E402
from app.kappa import build_distributions, compare_distributions  # noqa: E402


ALERT_THRESHOLD = 0.6
DRIFT_THRESHOLD = 0.5


# --------------------------------------------------------------------------- #
# Real text corpora                                                           #
# --------------------------------------------------------------------------- #

CONCISE_ANSWERS = [
    "Staying organized usually comes down to writing tasks down and reviewing them each morning.",
    "The sky looks blue because air scatters short blue wavelengths of sunlight more than red.",
    "Boil salted water, cook the pasta until tender, then toss it with a little oil and cheese.",
    "Regular exercise improves your heart, mood, sleep, and long-term health.",
    "A bicycle works by turning pedal force into wheel rotation through a chain and gears.",
    "Before adopting a pet, consider your time, space, budget, and the animal's needs.",
    "Compound interest grows savings because you earn returns on past returns over time.",
    "Practice a new language a little every day and speak it as early as you can.",
    "Sleep matters because it lets the body repair and the brain consolidate memory.",
    "Plants make food from sunlight, water, and carbon dioxide through photosynthesis.",
    "Good coffee needs fresh beans, the right grind, clean water, and careful timing.",
    "The internet works by routing small packets of data between networked computers.",
    "Reduce stress by sleeping well, moving your body, and taking short breaks often.",
    "The water cycle moves water through evaporation, condensation, and precipitation.",
    "Start a garden with a sunny spot, good soil, and a few easy vegetables.",
    "A productive morning starts with a consistent wake time and a short plan.",
    "We have seasons because Earth's tilt changes how directly sunlight hits us.",
    "A refrigerator stays cold by pumping heat out using an evaporating refrigerant.",
    "A balanced diet mixes vegetables, fruit, protein, whole grains, and healthy fats.",
    "Improve handwriting by slowing down and practicing consistent letter shapes.",
    "Rainbows form when sunlight bends and splits inside falling water droplets.",
    "Save money by budgeting, automating savings, and cutting unused subscriptions.",
    "A battery stores energy chemically and releases it as current when connected.",
    "Leaves change color in autumn as green chlorophyll fades and other pigments show.",
]

VERBOSE_CODE_ANSWERS = [
    (
        "## Staying organized\n\n"
        "Getting organized is less about willpower and more about building a system you "
        "can trust. The goal is to get tasks out of your head and into a place you review "
        "regularly, so nothing slips and you always know the next action.\n\n"
        "Here are the core habits that tend to work:\n\n"
        "- Capture every task immediately, before you forget it\n"
        "- Review your list each morning and pick three priorities\n"
        "- Break big projects into small, concrete steps\n\n"
        "A tiny script can even nudge you each day:\n\n"
        "```python\n"
        "tasks = load_tasks()\n"
        "top = sorted(tasks, key=lambda t: t.priority)[:3]\n"
        "for t in top:\n"
        "    print('Focus:', t.title)\n"
        "```\n\n"
        "Start small, keep the system simple, and let it grow with you over time."
    ),
    (
        "## Why the sky is blue\n\n"
        "Sunlight contains every color, but the atmosphere does not treat them equally. "
        "Air molecules scatter shorter wavelengths far more strongly than longer ones, an "
        "effect named after the physicist Rayleigh.\n\n"
        "The key points:\n\n"
        "- Blue light has a short wavelength and scatters the most\n"
        "- That scattered blue reaches your eyes from all directions\n"
        "- At sunset the light travels farther, so reds dominate instead\n\n"
        "Roughly, scattering scales like this:\n\n"
        "```python\n"
        "def scatter(wavelength):\n"
        "    return 1.0 / (wavelength ** 4)\n"
        "```\n\n"
        "So the sky is blue by day and red at dusk for the very same reason."
    ),
    (
        "## Making a simple pasta\n\n"
        "A good basic pasta needs only a few ingredients and some attention to timing. "
        "The trick is salting the water well and saving a little starchy water for the "
        "sauce.\n\n"
        "Steps:\n\n"
        "- Bring a large pot of salted water to a rolling boil\n"
        "- Cook the pasta until just tender, then reserve a cup of water\n"
        "- Toss with oil, cheese, and a splash of the pasta water\n\n"
        "A rough timer helps:\n\n"
        "```python\n"
        "minutes = 9\n"
        "while minutes > 0:\n"
        "    minutes -= 1\n"
        "print('Drain now!')\n"
        "```\n\n"
        "Serve straight away while it is hot and the sauce still clings."
    ),
    (
        "## Benefits of exercise\n\n"
        "Moving regularly changes nearly every system in the body for the better, from "
        "your heart to your mood. You do not need a gym; consistency matters more than "
        "intensity.\n\n"
        "What you gain:\n\n"
        "- A stronger heart and better circulation\n"
        "- Improved sleep and steadier energy\n"
        "- Lower stress and a brighter mood\n\n"
        "Even a simple counter keeps you honest:\n\n"
        "```python\n"
        "steps = 0\n"
        "for _ in range(walks_today):\n"
        "    steps += 2000\n"
        "print(steps, 'steps')\n"
        "```\n\n"
        "Pick something you enjoy so the habit actually sticks for the long run."
    ),
    (
        "## How a bicycle works\n\n"
        "A bicycle is a beautifully efficient machine that turns the push of your legs "
        "into forward motion with very little waste. The drivetrain is the heart of it.\n\n"
        "The essentials:\n\n"
        "- Pedals turn the crank and front chainring\n"
        "- The chain carries that motion to the rear wheel\n"
        "- Gears trade speed for climbing power\n\n"
        "Gear ratio in one line:\n\n"
        "```python\n"
        "ratio = front_teeth / rear_teeth\n"
        "print('Higher ratio = faster, harder to pedal')\n"
        "```\n\n"
        "Balance comes from steering and momentum working together as you ride."
    ),
    (
        "## Adopting a pet\n\n"
        "Bringing an animal home is a long commitment, so it pays to think it through "
        "before you fall for a face at the shelter. Match the pet to your real life, not "
        "your ideal one.\n\n"
        "Things to weigh:\n\n"
        "- The daily time the animal needs from you\n"
        "- Your space, budget, and travel habits\n"
        "- The breed or species' temperament and lifespan\n\n"
        "A quick readiness check:\n\n"
        "```python\n"
        "ready = hours_free >= 2 and budget_ok and space_ok\n"
        "print('Adopt!' if ready else 'Wait a bit')\n"
        "```\n\n"
        "When the fit is right, the bond you build is more than worth the effort."
    ),
    (
        "## How compound interest grows\n\n"
        "Compound interest is often called the eighth wonder of the world because your "
        "money earns money, and then that money earns money too. Time is the real engine.\n\n"
        "Why it works:\n\n"
        "- Each period you earn return on your whole balance\n"
        "- Past returns are added back to the principal\n"
        "- Growth accelerates the longer you leave it alone\n\n"
        "The classic formula:\n\n"
        "```python\n"
        "def future_value(p, r, n):\n"
        "    return p * (1 + r) ** n\n"
        "```\n\n"
        "Start early, stay patient, and let the curve do the heavy lifting."
    ),
    (
        "## Learning a new language\n\n"
        "Languages reward steady daily contact far more than occasional long sessions. "
        "Build a routine you can keep even on a busy day.\n\n"
        "A workable plan:\n\n"
        "- Study a small amount every single day\n"
        "- Speak out loud from the very first week\n"
        "- Review old material on a spaced schedule\n\n"
        "Track your streak simply:\n\n"
        "```python\n"
        "streak = 0\n"
        "if studied_today:\n"
        "    streak += 1\n"
        "print('Day', streak)\n"
        "```\n\n"
        "Consistency, not talent, is what carries most learners to fluency."
    ),
    (
        "## Why sleep matters\n\n"
        "Sleep is not downtime; it is when the body does its most important maintenance. "
        "Skimp on it and nearly everything else suffers.\n\n"
        "During good sleep:\n\n"
        "- Tissues repair and the immune system resets\n"
        "- The brain consolidates the day's memories\n"
        "- Hormones that govern hunger and mood rebalance\n\n"
        "A simple sleep-debt tally:\n\n"
        "```python\n"
        "debt = max(0, 8 - hours_slept)\n"
        "print('Hours short:', debt)\n"
        "```\n\n"
        "Protect your sleep window and the rest of your health gets easier."
    ),
    (
        "## How plants make food\n\n"
        "Plants are quietly running one of the planet's most important chemical reactions "
        "in every green leaf. They build their own food from light.\n\n"
        "Photosynthesis in brief:\n\n"
        "- Leaves absorb sunlight with chlorophyll\n"
        "- Water and carbon dioxide are the raw inputs\n"
        "- Sugar is produced and oxygen is released\n\n"
        "The reaction, sketched in code:\n\n"
        "```python\n"
        "def photosynthesis(co2, water, light):\n"
        "    return 'sugar + oxygen'\n"
        "```\n\n"
        "That sugar feeds the plant and, eventually, almost everything else."
    ),
    (
        "## Brewing good coffee\n\n"
        "Great coffee is mostly about controlling a few variables well rather than buying "
        "fancy gear. Freshness is the one thing you cannot fake.\n\n"
        "Focus on:\n\n"
        "- Freshly roasted beans ground just before brewing\n"
        "- Clean, filtered water at the right temperature\n"
        "- A consistent ratio of coffee to water\n\n"
        "A simple ratio helper:\n\n"
        "```python\n"
        "grams = water_ml / 16\n"
        "print('Use', round(grams), 'g of coffee')\n"
        "```\n\n"
        "Dial in one variable at a time and your cup will steadily improve."
    ),
    (
        "## How the internet works\n\n"
        "The internet can feel like magic, but underneath it is a remarkably simple idea: "
        "break messages into packets and pass them along until they arrive.\n\n"
        "The moving parts:\n\n"
        "- Data is split into small numbered packets\n"
        "- Routers forward each packet toward its destination\n"
        "- The receiver reassembles them in order\n\n"
        "A toy of the idea:\n\n"
        "```python\n"
        "packets = split(message)\n"
        "for p in packets:\n"
        "    route(p, destination)\n"
        "```\n\n"
        "Countless networks cooperating on this scheme make the whole web feel seamless."
    ),
    (
        "## Reducing daily stress\n\n"
        "Stress builds quietly, so the best defenses are small habits you repeat rather "
        "than one big fix. Aim for steady relief, not perfection.\n\n"
        "Reliable levers:\n\n"
        "- Protect your sleep and wake times\n"
        "- Move your body, even briefly, every day\n"
        "- Take short breaks before you feel drained\n\n"
        "A nudge to pause:\n\n"
        "```python\n"
        "if minutes_working > 50:\n"
        "    print('Take a five minute break')\n"
        "```\n\n"
        "Stacked over weeks, these small resets keep stress from piling up."
    ),
    (
        "## The water cycle\n\n"
        "Water is in constant motion around the planet, changing form as it goes. The "
        "same molecules cycle endlessly between sky, land, and sea.\n\n"
        "The main stages:\n\n"
        "- Evaporation lifts water into the air as vapor\n"
        "- Condensation forms clouds as it cools\n"
        "- Precipitation returns it as rain or snow\n\n"
        "A loop, in code:\n\n"
        "```python\n"
        "while True:\n"
        "    vapor = evaporate(ocean)\n"
        "    rain = condense(vapor)\n"
        "```\n\n"
        "Driven by the sun, this cycle keeps fresh water moving everywhere on Earth."
    ),
]


def _features_for(texts: list[str], *, prompt: str = "Answer the question.") -> list[dict]:
    """Run real text through the real SDK extractor."""
    return [
        compute_behavioral_features(prompt, t, error_class="none", lsh_salt="e2e")
        for t in texts
    ]


def _cycle(pool: list[str], n: int, offset: int = 0) -> list[str]:
    return [pool[(offset + i) % len(pool)] for i in range(n)]


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #


def test_real_extractor_produces_schema_features():
    """Sanity: the SDK extractor yields the #63 schema over real text."""
    feats = _features_for([CONCISE_ANSWERS[0], VERBOSE_CODE_ANSWERS[0]])
    for f in feats:
        for key in ("output_length_chars", "had_code_block", "had_list",
                    "had_markdown", "token_bag_lsh", "sentence_count_output"):
            assert key in f
    # The verbose+code answer is structurally distinct from the concise one.
    assert feats[1]["had_code_block"] is True
    assert feats[1]["output_length_chars"] > feats[0]["output_length_chars"] * 3


def test_persona_shift_detected_end_to_end():
    """concise baseline → verbose+code window must be flagged as drift."""
    baseline = build_distributions(_features_for(_cycle(CONCISE_ANSWERS, 80)))
    window = _features_for(_cycle(VERBOSE_CODE_ANSWERS, 14))
    verdict = compare_distributions(baseline, window)

    assert verdict["verified"] is False, verdict
    assert verdict["drift_score"] > ALERT_THRESHOLD, verdict
    assert verdict["dominant_feature"] is not None
    assert verdict["attribution"]["feature_name"] == verdict["dominant_feature"]


def test_stable_behavior_no_false_drift():
    """concise baseline vs a concise window → no false positive."""
    baseline = build_distributions(_features_for(_cycle(CONCISE_ANSWERS, 80)))
    window = _features_for(_cycle(CONCISE_ANSWERS, 14, offset=5))
    verdict = compare_distributions(baseline, window)

    assert verdict["drift_score"] < ALERT_THRESHOLD, verdict
    assert verdict["verified"] is True, verdict


def test_attribution_has_usable_before_after():
    """The drift verdict carries a concrete before/after for the dominant
    feature — what the alerts pipeline (#64) surfaces to the customer."""
    baseline = build_distributions(_features_for(_cycle(CONCISE_ANSWERS, 80)))
    window = _features_for(_cycle(VERBOSE_CODE_ANSWERS, 14))
    verdict = compare_distributions(baseline, window)

    detail = verdict["attribution"]["detail"]
    # Whatever the dominant feature, its detail exposes a before/after the
    # alert layer can render (continuous mean, categorical dist, or hamming).
    assert (
        ("baseline_mean" in detail and "current_mean" in detail)
        or ("baseline_dist" in detail and "current_dist" in detail)
        or ("mean_min_hamming" in detail)
    ), detail


def test_format_marker_drift_is_categorical():
    """A pure formatting flip (no code/lists → all code/lists) registers on
    the categorical format-marker features."""
    plain = build_distributions(_features_for(_cycle(CONCISE_ANSWERS, 60)))
    window = _features_for(_cycle(VERBOSE_CODE_ANSWERS, 14))
    verdict = compare_distributions(plain, window)
    # had_code_block / had_list / had_markdown should all show strong drift.
    scores = verdict["scores"]
    assert any(
        scores.get(f, 0) > 0.8
        for f in ("had_code_block", "had_list", "had_markdown")
    ), scores
