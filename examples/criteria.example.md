# Criteria — example (fictional solo automation consultant)

offer: Fixed-scope automation builds (inboxes to CRM, lead follow-up,
reporting) delivered in 2-6 weeks with a fixed price.

ideal_client: 5-50 person B2B services teams, EU/US business hours,
English or Russian, owner or sales lead as decision maker.

red_flags:
free work, "exposure", spam, vague scope, no budget given, agency
middlemen reselling, crypto projects.

tone:
Short, direct, one question at a time. "Got it. Two things before I
quote: which CRM, and what does done look like on a closed lead?"

## config
weights: {"fit": 40, "budget": 25, "urgency": 15, "clarity": 10, "source_trust": 10}
a_min: 75
b_min: 50
hard_red_flags: ["exposure", "free work", "no budget", "spam", "vague scope"]
