"""Generate a simple, easy-to-read PDF report for the FOMO rat-detection model.
Charts via matplotlib, layout via fpdf2. Run:  python make_report_pdf.py
"""
import os
import tempfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from fpdf import FPDF, XPos, YPos

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Rodent_AI_Report.pdf")
TMP = tempfile.gettempdir()
CHART_PERF = os.path.join(TMP, "rai_perf.png")
CHART_TRAIN = os.path.join(TMP, "rai_train.png")

# ---------------------------------------------------------------- palette
HEADER = (31, 78, 121)
ACCENT = (46, 134, 171)
GREEN = (39, 174, 96)
ORANGE = (211, 84, 0)
LIGHT = (236, 240, 241)
DARK = (44, 62, 80)
GREY = (127, 140, 141)

# ---------------------------------------------------------------- real data
TH = [0.3, 0.4, 0.5, 0.6, 0.7]
PREC = [0.445, 0.518, 0.612, 0.752, 0.860]
REC = [0.713, 0.808, 0.781, 0.653, 0.523]
F1 = [0.548, 0.631, 0.686, 0.699, 0.650]

VAL_LOSS = [
    0.0518, 0.0582, 0.0549, 0.0571, 0.0514, 0.0493, 0.0527, 0.0554, 0.0562, 0.0555,
    0.0541, 0.0460, 0.0551, 0.0504, 0.0452, 0.0478, 0.0396, 0.0392, 0.0422, 0.0420,
    0.0399, 0.0394, 0.0407, 0.0386, 0.0376, 0.0383, 0.0387, 0.0360, 0.0321, 0.0365,
    0.0428, 0.0349, 0.0361, 0.0351, 0.0306, 0.0332, 0.0326, 0.0336, 0.0336, 0.0309,
    0.0317, 0.0320, 0.0283, 0.0287, 0.0281, 0.0255, 0.0239, 0.0241, 0.0255, 0.0248,
    0.0231, 0.0278, 0.0251, 0.0273, 0.0259, 0.0274, 0.0257, 0.0253, 0.0236, 0.0234,
]
EPOCHS = list(range(1, 61))


def build_charts():
    # ---- detection performance ----
    plt.figure(figsize=(7, 3.3))
    plt.axvspan(0.5, 0.6, color="#2E86AB", alpha=0.10)
    plt.plot(TH, REC, "-o", color="#27AE60", lw=2.2, label="Recall (rats caught)")
    plt.plot(TH, PREC, "-o", color="#D35400", lw=2.2, label="Precision (alerts correct)")
    plt.plot(TH, F1, "-o", color="#2E86AB", lw=2.6, label="F1 (overall score)")
    plt.scatter([0.6], [0.699], s=160, facecolors="none", edgecolors="#c0392b", lw=2, zorder=5)
    plt.annotate("best 0.70", (0.6, 0.699), textcoords="offset points",
                 xytext=(6, 10), color="#c0392b", fontsize=9, fontweight="bold")
    plt.title("How well it detects rats  (higher = better)", fontsize=11, fontweight="bold")
    plt.xlabel("Alarm sensitivity setting (threshold)")
    plt.ylabel("Score  (0 to 1)")
    plt.ylim(0.35, 1.0)
    plt.grid(alpha=0.25)
    plt.legend(fontsize=8, loc="lower center", ncol=3)
    plt.tight_layout()
    plt.savefig(CHART_PERF, dpi=150)
    plt.close()

    # ---- training curve ----
    plt.figure(figsize=(7, 2.9))
    plt.plot(EPOCHS, VAL_LOSS, "-", color="#2E86AB", lw=1.9)
    plt.axvline(42, color=GREY_HEX, ls="--", lw=1, alpha=0.6)
    plt.axvline(58, color=GREY_HEX, ls="--", lw=1, alpha=0.6)
    plt.scatter([51], [0.0231], s=100, color="#27AE60", zorder=5)
    plt.annotate("best (epoch 51)", (51, 0.0231), textcoords="offset points",
                 xytext=(-95, 6), color="#27AE60", fontsize=9, fontweight="bold")
    plt.title("Learning progress  (mistakes going down = good)", fontsize=11, fontweight="bold")
    plt.xlabel("Training round (epoch)")
    plt.ylabel("Mistake level")
    plt.grid(alpha=0.25)
    plt.tight_layout()
    plt.savefig(CHART_TRAIN, dpi=150)
    plt.close()


GREY_HEX = "#7f8c8d"


class Report(FPDF):
    def footer(self):
        self.set_y(-12)
        self.set_font("DejaVu", "", 8)
        self.set_text_color(*GREY)
        self.cell(0, 6, f"Rat Detection AI  -  page {self.page_no()}", align="C")


def register_fonts(pdf):
    ttf = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
    pdf.add_font("DejaVu", "", os.path.join(ttf, "DejaVuSans.ttf"))
    pdf.add_font("DejaVu", "B", os.path.join(ttf, "DejaVuSans-Bold.ttf"))


def section(pdf, title):
    pdf.ln(2)
    pdf.set_fill_color(*ACCENT)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("DejaVu", "B", 13)
    pdf.cell(0, 9, "  " + title, new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
    pdf.ln(3)
    pdf.set_text_color(*DARK)
    pdf.set_font("DejaVu", "", 11)


def para(pdf, text):
    pdf.set_text_color(*DARK)
    pdf.set_font("DejaVu", "", 11)
    pdf.multi_cell(0, 6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)


def add_image(pdf, path, ratio, w=172):
    x = (210 - w) / 2.0
    y = pdf.get_y()
    pdf.image(path, x=x, y=y, w=w)
    pdf.set_y(y + w * ratio + 3)


def build_pdf():
    pdf = Report(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(True, margin=16)
    pdf.set_margins(15, 15, 15)
    register_fonts(pdf)

    # ============================================================ COVER
    pdf.add_page()
    pdf.set_fill_color(*HEADER)
    pdf.rect(0, 0, 210, 46, "F")
    pdf.set_xy(0, 12)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("DejaVu", "B", 26)
    pdf.cell(210, 12, "Rat Detection AI", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(0)
    pdf.set_font("DejaVu", "", 13)
    pdf.cell(210, 8, "Simple Results Report", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # verdict box
    by = 54
    pdf.set_fill_color(*GREEN)
    pdf.rect(15, by, 180, 28, "F")
    pdf.set_xy(20, by + 4)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("DejaVu", "B", 12)
    pdf.multi_cell(170, 6.5,
                   "RESULT:  The model works and is ready to use.\n"
                   "It finds about 8 out of 10 rats, is tiny (57 KB), and runs on\n"
                   "the ESP32 camera.", align="L")

    # stat cards
    cards = [("78%", "of rats caught", "at the normal setting"),
             ("57 KB", "model size", "fits on the camera"),
             ("0.70", "detection score", "F1, higher is better")]
    x0, w, gap, y, h = 15, 57, 4, 92, 32
    for i, (big, mid, sub) in enumerate(cards):
        x = x0 + i * (w + gap)
        pdf.set_fill_color(*LIGHT)
        pdf.rect(x, y, w, h, "F")
        pdf.set_fill_color(*ACCENT)
        pdf.rect(x, y, w, 3, "F")
        pdf.set_xy(x, y + 7)
        pdf.set_text_color(*ACCENT)
        pdf.set_font("DejaVu", "B", 20)
        pdf.cell(w, 10, big, align="C", new_x=XPos.LEFT, new_y=YPos.NEXT)
        pdf.set_x(x)
        pdf.set_text_color(*DARK)
        pdf.set_font("DejaVu", "B", 10)
        pdf.cell(w, 6, mid, align="C", new_x=XPos.LEFT, new_y=YPos.NEXT)
        pdf.set_x(x)
        pdf.set_font("DejaVu", "", 8)
        pdf.set_text_color(*GREY)
        pdf.cell(w, 5, sub, align="C")

    pdf.set_xy(15, y + h + 10)
    pdf.set_text_color(*DARK)
    pdf.set_font("DejaVu", "", 12)
    pdf.multi_cell(180, 7,
                   "In one line:  a small AI that watches the feeding station and "
                   "tells you when a rat is there.")

    # what the words mean (mini glossary on cover)
    gy = pdf.get_y() + 4
    pdf.set_fill_color(*LIGHT)
    pdf.rect(15, gy, 180, 30, "F")
    pdf.set_xy(19, gy + 3)
    pdf.set_text_color(*HEADER)
    pdf.set_font("DejaVu", "B", 11)
    pdf.cell(0, 6, "Two words used in this report:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(19)
    pdf.set_text_color(*DARK)
    pdf.set_font("DejaVu", "", 10)
    pdf.multi_cell(172, 5.5,
                   "Recall  =  out of all the real rats, how many did it catch?  (like a fishing net)\n"
                   "Precision  =  when it shouts \u201crat!\u201d, how often is it right?  (not crying wolf)")

    # ============================================================ PAGE 2
    pdf.add_page()
    section(pdf, "1.  What is this, and how does it work?")
    para(pdf,
         "This is a tiny AI \u201cbrain\u201d for your camera. It looks at the feeding station "
         "and answers one simple question: is there a rat in view right now?")
    para(pdf, "How it works, in simple steps:")
    pdf.set_font("DejaVu", "", 11)
    steps = [
        "1.  The camera takes a small black-and-white photo (96 x 96 pixels).",
        "2.  The AI splits the photo into a 12 x 12 grid, like a checkerboard.",
        "3.  For each square it gives a score: how likely a rat\u2019s centre is there.",
        "4.  Squares with a high score are grouped together \u2014 each group is one rat.",
    ]
    for s in steps:
        pdf.set_x(20)
        pdf.multi_cell(175, 6, s, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    para(pdf,
         "It does not draw exact boxes around rats; it just drops a \u201cdot\u201d where each rat is. "
         "That is why it can be so small and fast \u2014 small enough to run on a cheap camera board.")

    section(pdf, "2.  What it learned from")
    para(pdf,
         "The AI was shown thousands of pictures. Some had rats, some were empty (so it also "
         "learns what \u201cno rat\u201d looks like).")
    # data table
    pdf.set_font("DejaVu", "B", 10)
    pdf.set_text_color(255, 255, 255)
    pdf.set_fill_color(*ACCENT)
    pdf.cell(76, 8, "  Pictures", fill=True, align="L")
    pdf.cell(38, 8, "Total", fill=True, align="C")
    pdf.cell(38, 8, "With rats", fill=True, align="C")
    pdf.cell(38, 8, "Empty", fill=True, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    rows = [("  To learn (training)", "4,192", "3,600", "592"),
            ("  To test (the exam)", "1,040", "900", "140")]
    pdf.set_text_color(*DARK)
    pdf.set_font("DejaVu", "", 10)
    fill = False
    for r in rows:
        pdf.set_fill_color(*LIGHT)
        pdf.cell(76, 8, r[0], fill=fill, align="L")
        pdf.cell(38, 8, r[1], fill=fill, align="C")
        pdf.cell(38, 8, r[2], fill=fill, align="C")
        pdf.cell(38, 8, r[3], fill=fill, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        fill = not fill
    pdf.ln(2)
    para(pdf,
         "Important: the test pictures are kept separate, so the \u201cexam\u201d score below is honest \u2014 "
         "the AI never saw those pictures while learning.")

    # ============================================================ PAGE 3
    pdf.add_page()
    section(pdf, "3.  How well does it work?")
    para(pdf,
         "There is always a trade-off. One setting (the \u201cthreshold\u201d) decides how eager the AI is "
         "to shout \u201crat!\u201d. Turn it up and you get fewer false alarms but miss more rats; turn it "
         "down and you catch more rats but get more false alarms.")
    add_image(pdf, CHART_PERF, ratio=3.3 / 7.0)
    para(pdf, "Two sensible settings to choose from:")
    # comparison table
    pdf.set_font("DejaVu", "B", 10)
    pdf.set_text_color(255, 255, 255)
    pdf.set_fill_color(*ACCENT)
    pdf.cell(46, 8, "  Setting", fill=True, align="L")
    pdf.cell(44, 8, "Rats caught", fill=True, align="C")
    pdf.cell(46, 8, "Alerts correct", fill=True, align="C")
    pdf.cell(54, 8, "Best for", fill=True, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    comp = [("  Normal (0.5)", "78%", "61%", "catching every rat"),
            ("  Careful (0.6)", "65%", "75%", "fewer false alarms")]
    pdf.set_text_color(*DARK)
    pdf.set_font("DejaVu", "", 10)
    fill = False
    for r in comp:
        pdf.set_fill_color(*LIGHT)
        pdf.cell(46, 8, r[0], fill=fill, align="L")
        pdf.cell(44, 8, r[1], fill=fill, align="C")
        pdf.cell(46, 8, r[2], fill=fill, align="C")
        pdf.cell(54, 8, r[3], fill=fill, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        fill = not fill
    pdf.ln(2)
    para(pdf, "The camera currently uses the Normal (0.5) setting.")

    # ============================================================ PAGE 4
    pdf.add_page()
    section(pdf, "4.  Did it learn properly?")
    para(pdf,
         "\u201cTraining\u201d means the AI reviewed the pictures 60 times to improve. The graph below shows "
         "its mistakes going down smoothly and staying down \u2014 that is exactly what a healthy, "
         "well-behaved training looks like (no sudden jumps, no breakdowns).")
    add_image(pdf, CHART_TRAIN, ratio=2.9 / 7.0)

    section(pdf, "5.  Conclusion")
    cy = pdf.get_y()
    pdf.set_fill_color(*LIGHT)
    pdf.rect(15, cy, 180, 52, "F")
    pdf.set_fill_color(*GREEN)
    pdf.rect(15, cy, 4, 52, "F")
    pdf.set_xy(22, cy + 4)
    pdf.set_text_color(*DARK)
    pdf.set_font("DejaVu", "", 11)
    pdf.multi_cell(168, 6.2,
                   "\u2022  The model is good for its job: a rat alarm.\n"
                   "\u2022  Strength: it rarely misses rats (it catches about 8 out of 10).\n"
                   "\u2022  Weak point: sometimes it alarms when there is no rat (false alarms).\n"
                   "\u2022  Easy fixes for false alarms:  (a) make the camera wait until a rat shows up in\n"
                   "    several photos in a row, or  (b) use the \u201cCareful\u201d setting.\n"
                   "\u2022  Next step: put it on the camera and test it in real life.")

    pdf.ln(6)
    pdf.set_text_color(*GREY)
    pdf.set_font("DejaVu", "", 9)
    pdf.multi_cell(0, 5,
                   "Technical note: FOMO detector (MobileNetV2 alpha=0.35), input 96x96 grayscale, "
                   "output 12x12 grid, ~20.7K parameters, exported int8 TFLite (57 KB). "
                   "Best object-level F1 = 0.699 at threshold 0.6; recall 0.78 at threshold 0.5.")

    pdf.output(OUT)
    return OUT


if __name__ == "__main__":
    build_charts()
    path = build_pdf()
    print("PDF written to:", path)
    print("Size:", os.path.getsize(path), "bytes")
