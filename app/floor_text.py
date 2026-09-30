"""Words for the screens the floor reads.

Telugu is used only where an operator, a supervisor or a shift in-charge has to
act on what is written. Everything the management screens carry stays in
English: those are read by the MD and by Planning, and translating a KPI label
only makes it harder to match the screen against the sheets already in use.

Machine codes, specification codes and people's names are never translated —
they are the same characters on the loom, on the paper form and here.
"""

FLOOR_TITLE_EN = "SHIFT BOARD — LATEST WORKING DAY"
FLOOR_TITLE_TE = "షిఫ్ట్ బోర్డు — చివరి పని దినం"

K_PRODUCED_EN = "Produced"
K_PRODUCED_TE = "ఉత్పత్తి అయినది"
K_TARGET_EN = "Target"
K_TARGET_TE = "లక్ష్యం"
K_ACHIEVED_TE = "సాధించారు"
K_RUNNING_EN = "Looms that ran"
K_RUNNING_TE = "నడిచిన మెషీన్లు"
K_RUNNING_SUB_TE = "మొత్తం మెషీన్లలో"
K_REJECT_EN = "Rejected"
K_REJECT_TE = "తిరస్కరించినది"

SHIFT_BOARD_TE = "షిఫ్ట్ వారీగా ఉత్పత్తి"
SHIFT_BOARD_EN = "Production by shift on the latest working day"
NO_SHIFT_TE = "ఈ రోజుకు షిఫ్ట్ వారీ నమోదు లేదు."

COL_SHIFT_TE = "షిఫ్ట్"
COL_PRODUCED_TE = "ఉత్పత్తి (గజాలు)"
COL_TARGET_TE = "లక్ష్యం (గజాలు)"
COL_PCT_TE = "శాతం"
COL_MACHINE_TE = "మెషీన్"
COL_PEER_TE = "గ్రూప్"
COL_LINES_TE = "లైన్లు"
COL_OPERATOR_TE = "ఆపరేటర్"

STOPPED_TITLE_EN = "LOOMS THAT DID NOT RUN"
STOPPED_TITLE_TE = "నడవని మెషీన్లు — కారణం రాయండి"
ALL_RAN_TE = "అన్ని మెషీన్లు నడిచాయి."

RULES_TE = "నాలుగు నియమాలు"
RULES_EN = "The four rules for filling the production sheet"

# (Telugu, English) — the same four rules printed at the foot of form FM-ZD-01,
# so the screen and the paper never say different things.
RULES = [
    ("ప్రతి షిఫ్ట్ ముగింపులో రీడింగ్ రాయండి — ఒకే సమయంలో.",
     "Write the meter reading at the end of every shift, at the same time each day."),
    ("మెషీన్ ఆగితే — ఆగిన సమయం, తిరిగి ప్రారంభ సమయం, కారణ కోడ్ మూడూ రాయాలి.",
     "If the loom stops, write all three: stop time, restart time and the reason code."),
    ("ఎన్ని లైన్లు అమర్చారు, ఎన్ని నిజంగా నడుస్తున్నాయి — రెండూ వేరుగా రాయండి.",
     "Write lines fitted and lines actually running separately — they are not always the same."),
    ("ఆపరేటర్, సూపర్‌వైజర్ పేర్లు ప్రతి షీట్‌లో తప్పనిసరి.",
     "The operator's and supervisor's names are required on every sheet."),
]
