# Criteria — fill this with the owner

The prose sections (offer / ideal client / tone) are read by the agent when it
assigns sub-scores and writes drafts. The machine-readable `## config` block
at the bottom feeds `scripts/score.py` — keep its values as single-line JSON.

offer:
# <one paragraph: what you actually sell/deliver>

ideal_client:
# <niche, company size, geography>

red_flags:
# free work, "exposure", spam, vague scope, no budget given...

tone:
# <short examples of the owner's real replies — the drafts copy this voice>

## config
weights: {"fit": 40, "budget": 25, "urgency": 15, "clarity": 10, "source_trust": 10}
a_min: 75
b_min: 50
hard_red_flags: ["exposure", "free work", "no budget", "spam", "vague scope"]
