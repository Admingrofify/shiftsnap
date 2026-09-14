"""Build the ShiftSnap demo video: PIL slides + TTS narration -> ffmpeg mp4.

Steps: render slides, synthesize narration, assemble clips, concat.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/home/hatch/workspace/shiftsnap")
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

ROOT = Path("/home/hatch/workspace/shiftsnap")
OUT = ROOT / "demo" / "video"
OUT.mkdir(parents=True, exist_ok=True)

W, H = 1920, 1080
TEAL, DARK, GRAY, WHITE, LIGHT = (31, 78, 95), (25, 25, 25), (110, 110, 110), (255, 255, 255), (232, 240, 243)
GREEN, BLUE, DIM = (0, 150, 136), (40, 90, 160), (150, 150, 150)
TERM_BG = (24, 28, 34)

def font(name, size):
    try:
        return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{name}.ttf", size)
    except OSError:
        return ImageFont.load_default()

F_TITLE = font("DejaVuSans-Bold", 72)
F_H2 = font("DejaVuSans-Bold", 54)
F_BODY = font("DejaVuSans", 38)
F_SMALL = font("DejaVuSans", 30)
F_MONO = font("DejaVuSansMono", 30)
F_MONO_B = font("DejaVuSansMono-Bold", 30)


def new_slide(bg=WHITE):
    return Image.new("RGB", (W, H), bg), ImageDraw.Draw(Image.new("RGB", (W, H), bg))


def make():
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    return img, d


def centered(d, cx, y, text, f, fill=DARK):
    bb = d.textbbox((0, 0), text, font=f)
    d.text((cx - (bb[2] - bb[0]) / 2, y), text, font=f, fill=fill)


def wrap(d, text, f, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) <= max_w:
            cur = t
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


# ---------- slide builders ----------
def slide_title():
    img, d = make()
    d.rectangle([0, 0, W, 26], fill=TEAL)
    centered(d, W // 2, 330, "⏱ ShiftSnap".replace("⏱ ", ""), F_TITLE, TEAL)
    centered(d, W // 2, 450, "Your timesheet agent", F_H2, DARK)
    centered(d, W // 2, 580, "Built with the Strands Agents SDK", F_BODY, GRAY)
    centered(d, W // 2, 650, "Agents for Humans Hackathon  ·  Professional Agents track", F_SMALL, GRAY)
    return img


def slide_bullets(title, bullets, accent=TEAL):
    img, d = make()
    d.rectangle([0, 0, W, 26], fill=TEAL)
    d.text((120, 110), title, font=F_H2, fill=accent)
    y = 260
    for b in bullets:
        for line in wrap(d, "•  " + b, F_BODY, W - 320):
            d.text((140, y), line, font=F_BODY, fill=DARK)
            y += 62
        y += 28
    return img


def slide_terminal(title, turns):
    """turns: list of (kind, text); kind in user/agent/tool."""
    img = Image.new("RGB", (W, H), TERM_BG)
    d = ImageDraw.Draw(img)
    d.text((70, 50), title, font=F_H2, fill=WHITE)
    y = 170
    for kind, text in turns:
        color, prefix = {"user": (120, 200, 255), "agent": (140, 230, 170),
                         "tool": (255, 200, 120)}[kind], {"user": "You › ", "agent": "Agent › ", "tool": "⚙ "}[kind]
        for line in wrap(d, prefix + text, F_MONO, W - 200):
            d.text((90, y), line, font=F_MONO, fill=color)
            y += 48
        y += 26
        if y > H - 120:
            break
    return img


def slide_table():
    img, d = make()
    d.rectangle([0, 0, W, 26], fill=TEAL)
    d.text((120, 80), "One sentence → a finished timesheet", font=F_H2, fill=TEAL)
    headers = ["Date", "In", "Out", "Break", "Total", "Appr.", "Extra"]
    rows = [
        ["2026-09-01", "06:58", "22:26", "02:58-10:26", "8:00", "8:00", "0:00"],
        ["2026-09-02", "07:05", "18:40", "—", "11:35", "8:00", "3:35"],
        ["TOTALS", "", "", "", "19:35", "16:00", "3:35"],
    ]
    x0, y0, cw, rh = 150, 240, 230, 78
    for j, htxt in enumerate(headers):
        d.rectangle([x0 + j * cw, y0, x0 + (j + 1) * cw, y0 + rh], fill=TEAL)
        centered(d, x0 + j * cw + cw // 2, y0 + 18, htxt, F_SMALL, WHITE)
    for i, row in enumerate(rows):
        fill = (217, 232, 236) if i == len(rows) - 1 else (WHITE if i % 2 == 0 else (245, 248, 250))
        for j, val in enumerate(row):
            d.rectangle([x0 + j * cw, y0 + (i + 1) * rh, x0 + (j + 1) * cw, y0 + (i + 2) * rh],
                        fill=fill, outline=(200, 200, 200), width=2)
            centered(d, x0 + j * cw + cw // 2, y0 + (i + 1) * rh + 20, val,
                     font("DejaVuSans-Bold", 30) if i == len(rows) - 1 else F_SMALL)
    d.text((150, y0 + 4 * rh + 60), "Estimated gross pay: $430.83  (19.58h × $22/h)",
           font=font("DejaVuSans-Bold", 36), fill=TEAL)
    return img


def slide_arch():
    img, d = make()
    d.rectangle([0, 0, W, 26], fill=TEAL)
    d.text((120, 80), "How it works", font=F_H2, fill=TEAL)
    arch = Image.open(ROOT / "architecture.png")
    arch = arch.resize((1500, 938))
    img.paste(arch, (210, 200))
    return img


def slide_closing():
    img, d = make()
    d.rectangle([0, 0, W, 26], fill=TEAL)
    centered(d, W // 2, 380, "Talk like a human.", F_TITLE, TEAL)
    centered(d, W // 2, 500, "Get paid like a professional.", F_TITLE, TEAL)
    centered(d, W // 2, 680, "github.com/Admingrofify/shiftsnap  ·  MIT open source", F_BODY, GRAY)
    return img


# ---------- narration ----------
SEGMENTS = [
    ("01_title", slide_title,
     "ShiftSnap. Your timesheet agent. Built with the Strands Agents SDK for the Agents for Humans hackathon, Professional Agents track."),
    ("02_problem", lambda: slide_bullets("The problem", [
        "Every pay period, millions of hourly workers do the same painful ritual.",
        "Timestamp photos pile up. Hours get added by hand. Unpaid breaks get forgotten.",
        "One small arithmetic slip, and that's real money missing from a paycheck.",
        "ShiftSnap replaces all of that with a simple conversation."], accent=(180, 60, 40)),
     "Every pay period, millions of hourly workers do the same painful ritual. Timestamp photos pile up. Hours get added by hand. Unpaid breaks get forgotten. One small arithmetic slip, and that is real money missing from a paycheck. ShiftSnap replaces all of that with a simple conversation."),
    ("03_who", lambda: slide_bullets("Who it's for", [
        "Anyone paid by the hour: warehouse crews, data-center technicians, home aides.",
        "People working long, irregular shifts who just want to get paid accurately.",
        "No spreadsheets. No mental math at midnight. Just talk, and it's logged."], accent=TEAL),
     "It is for anyone paid by the hour. Warehouse crews, data center technicians, home aides. People working long, irregular shifts who just want to get paid accurately. No spreadsheets. No mental math at midnight. Just talk, and it is logged."),
    ("04_demo_log", lambda: slide_terminal("Live demo — logging a shift", [
        ("user", "I worked Sep 1, in at 6:58 AM, out at 10:26 PM, with an unpaid break from 2:58 AM to 10:26 AM."),
        ("tool", "log_shift(date='2026-09-01', time_in='6:58 AM', time_out='10:26 PM', break 2:58 AM-10:26 AM)"),
        ("agent", "Logged 2026-09-01: 06:58 to 22:26 (break 02:58-10:26). Net hours: 8:00."),
        ("user", "Also Sep 2, 7:05 AM to 6:40 PM, no break."),
        ("tool", "log_shift(date='2026-09-02', time_in='7:05 AM', time_out='6:40 PM')"),
        ("agent", "Logged 2026-09-02: 07:05 to 18:40. Net hours: 11:35.")]),
     "Watch. I tell the agent about my shift in plain English, break included. The agent reasons, calls its log shift tool, and confirms my net hours back to me. Eight hours flat, break subtracted. A second shift, just as easy."),
    ("05_demo_summary", lambda: slide_terminal("Live demo — pay period summary", [
        ("user", "Show me my summary for Sep 1 to Sep 15."),
        ("tool", "pay_period_summary(start_date='2026-09-01', end_date='2026-09-15')"),
        ("agent", "2 days worked, total 19:35 (19.58h), approved 16:00, extra 3:35. Missing weekday entries: Sep 3, Sep 4, Sep 7...")]),
     "Now the pay period summary. Two days worked, nineteen hours thirty five total, sixteen approved, three thirty five extra. And notice, it proactively flags the weekdays I am missing, so nothing goes under-reported."),
    ("06_demo_excel", slide_table,
     "And the payoff. One sentence, and ShiftSnap builds a formatted Excel timesheet. Per-day rows, totals, approved and extra hours, even estimated gross pay. Ready to submit."),
    ("07_arch", slide_arch,
     "Under the hood, it is a Strands agent. A pluggable model provider, the classic agent loop of reason, act, and observe, and four tools over a simple shift store. Swap the offline demo provider for Bedrock, OpenAI, or Anthropic with one environment variable."),
    ("08_closing", slide_closing,
     "ShiftSnap. Talk like a human, get paid like a professional. The code is open source, link in the project description. Thanks for watching."),
]


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("FAILED:", " ".join(cmd[:4]), r.stderr[-800:])
        raise SystemExit(1)
    return r


def main():
    clips = []
    for slug, builder, narration in SEGMENTS:
        png = OUT / f"{slug}.png"
        mp3 = OUT / f"{slug}.mp3"
        mp4 = OUT / f"{slug}.mp4"
        builder().save(png)
        print("slide", png.name)
        if not mp3.exists():
            run(["tts", "speak", "--text", narration, "--output", str(mp3)])
            print("audio", mp3.name)
        run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(png),
             "-i", str(mp3), "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-shortest", str(mp4)])
        clips.append(mp4)
    lst = OUT / "concat.txt"
    lst.write_text("".join(f"file '{c}'\n" for c in clips))
    final = ROOT / "demo" / "shiftsnap_demo.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(lst), "-c", "copy", str(final)])
    print("VIDEO:", final, final.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
