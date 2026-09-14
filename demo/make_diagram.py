"""Render ShiftSnap architecture diagram -> architecture.png"""
from PIL import Image, ImageDraw, ImageFont

W, H = 1600, 1000
TEAL, DARK, LIGHT, GRAY, WHITE = (31, 78, 95), (30, 30, 30), (217, 232, 236), (120, 120, 120), (255, 255, 255)
ACCENT = (0, 150, 136)

img = Image.new("RGB", (W, H), WHITE)
d = ImageDraw.Draw(img)
try:
    f_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 44)
    f_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
    f_med = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    f_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
except OSError:
    f_title = f_big = f_med = f_small = ImageFont.load_default()


def box(xy, fill, outline=None, r=18):
    d.rounded_rectangle(xy, radius=r, fill=fill, outline=outline or fill, width=3)


def center_text(cx, y, text, font, fill=DARK):
    bb = d.textbbox((0, 0), text, font=font)
    d.text((cx - (bb[2] - bb[0]) / 2, y), text, font=font, fill=fill)


def arrow(x1, y1, x2, y2, w=4):
    d.line([x1, y1, x2, y2], fill=TEAL, width=w)
    s = 14
    if y2 > y1:
        d.polygon([(x2 - s // 2, y2 - s), (x2 + s // 2, y2 - s), (x2, y2)], fill=TEAL)
    else:
        d.polygon([(x2 - s // 2, y2 + s), (x2 + s // 2, y2 + s), (x2, y2)], fill=TEAL)


center_text(W // 2, 30, "ShiftSnap — Architecture", f_title, TEAL)

# Worker
box((120, 130, 420, 250), LIGHT)
center_text(270, 155, "Worker", f_big)
center_text(270, 200, '"Sep 3, 9 AM to 5:30 PM"', f_small, GRAY)

# Arrow to agent
d.line([430, 190, 560, 190], fill=TEAL, width=4)
d.polygon([(546, 183), (546, 197), (562, 190)], fill=TEAL)
d.text((440, 150), "plain English", font=f_small, fill=TEAL)

# Agent box
box((570, 110, 1480, 420), WHITE, TEAL)
d.text((610, 130), "Strands Agent  (src/agent.py)", font=f_big, fill=TEAL)
box((610, 190, 1440, 260), (240, 248, 250), ACCENT)
center_text(1025, 205, "Model provider (pluggable):  demo  ·  bedrock  ·  openai  ·  anthropic", f_med)
box((610, 285, 1440, 390), (240, 248, 250), ACCENT)
center_text(1025, 300, "Agent loop:  reason  →  call tool  →  observe result  →  reply", f_med)
center_text(1025, 340, "only surfaces when there is a decision, a confirmation, or the finished timesheet", f_small, GRAY)

# Tool boxes
tools = [
    ("log_shift", "natural time parsing\n+ unpaid breaks"),
    ("list_shifts", "review logged\nshifts"),
    ("pay_period_summary", "totals · approved 8h\n· extra · missing days"),
    ("generate_timesheet", "formatted Excel\n+ estimated pay"),
]
tx = [660, 900, 1140, 1380]
for x, (name, desc) in zip(tx, tools):
    box((x - 115, 500, x + 115, 670), LIGHT)
    center_text(x, 520, name, f_small, TEAL)
    for i, line in enumerate(desc.split("\n")):
        center_text(x, 560 + i * 30, line, f_small, GRAY)
    arrow(x, 420, x, 495)

# Bottom: store + excel
box((540, 740, 1000, 860), WHITE, TEAL)
center_text(770, 765, "ShiftStore  (JSON shift log)", f_med, TEAL)
center_text(770, 805, "~/.shiftsnap/shifts.json", f_small, GRAY)
box((1080, 740, 1480, 860), WHITE, TEAL)
center_text(1280, 765, "Timesheet .xlsx", f_med, TEAL)
center_text(1280, 805, "per-day rows · totals · est. pay", f_small, GRAY)
arrow(660, 665, 700, 735)
arrow(900, 665, 830, 735)
arrow(1140, 665, 1210, 735)
arrow(1380, 665, 1340, 735)

d.text((40, H - 50), "Built with the Strands Agents SDK · Agents for Humans Hackathon", font=f_small, fill=GRAY)
img.save("/home/hatch/workspace/shiftsnap/architecture.png")
print("saved architecture.png", img.size)
