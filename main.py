import streamlit as st
import json
import hashlib
from datetime import datetime, timezone
import pytz
import os
import re
import html
import requests
import unicodedata

#  PAGE CONFIG 
st.set_page_config(
    page_title="C++ Lab By Group 2",
    page_icon="C++",
    layout="wide",
    initial_sidebar_state="collapsed",
)

#  DEADLINE 
# Friday 11:59 PM of the current week (local timezone: Asia/Phnom_Penh)
TZ = pytz.timezone("Asia/Phnom_Penh")


def get_deadline():
    now = datetime.now(TZ)
    # Days until Friday (weekday 4). If today is Sat/Sun, target next Friday.
    days_ahead = (4 - now.weekday()) % 7
    if days_ahead == 0 and now.hour >= 23 and now.minute >= 59:
        days_ahead = 7
    deadline_date = now.replace(hour=23, minute=59, second=0, microsecond=0)
    from datetime import timedelta
    deadline_date += timedelta(days=days_ahead)
    return deadline_date


def is_past_deadline():
    return datetime.now(TZ) > get_deadline()


def time_remaining():
    deadline = get_deadline()
    now = datetime.now(TZ)
    delta = deadline - now
    if delta.total_seconds() <= 0:
        return None
    days = delta.days
    hours, rem = divmod(delta.seconds, 3600)
    minutes = rem // 60
    return days, hours, minutes


#  DATABASE 
SUPABASE_TABLE = "submissions"


def get_secret(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value:
        return value.strip()
    try:
        value = st.secrets.get(name, default)
    except Exception:
        value = default
    return str(value).strip() if value else default


def supabase_configured() -> bool:
    return bool(get_secret("SUPABASE_URL") and get_secret("SUPABASE_KEY"))


def supabase_headers(prefer: str | None = None) -> dict:
    key = get_secret("SUPABASE_KEY")
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def supabase_endpoint() -> str:
    return f"{get_secret('SUPABASE_URL').rstrip('/')}/rest/v1/{SUPABASE_TABLE}"


def external_request(method: str, url: str, **kwargs) -> requests.Response:
    with requests.Session() as session:
        session.trust_env = False
        return session.request(method, url, **kwargs)


def sanitize_filename(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", normalized.strip().lower()).strip("_")
    return f"{cleaned or 'student'}.txt"


def init_db():
    if not supabase_configured():
        st.error("Supabase is not configured. Please set SUPABASE_URL and SUPABASE_KEY.")
        st.stop()


def save_submission(data: dict):
    payload = {
        "student_name": data["student_name"],
        "student_group": data["student_group"],
        "submitted_at": data["submitted_at"],
        "deadline": data["deadline"],
        "on_time": data["on_time"],
        "qcm_score": data["qcm_score"],
        "qcm_total": data["qcm_total"],
        "lab_score": data["lab_score"],
        "lab_total": data["lab_total"],
        "total_score": data["total_score"],
        "max_score": data["max_score"],
        "percentage": data["percentage"],
        "grade": data["grade"],
        "qcm_answers": data["qcm_answers"],
        "lab_answers": data["lab_answers"],
        "lab_code_answers": data["lab_code_answers"],
    }
    response = external_request(
        "POST",
        supabase_endpoint(),
        headers=supabase_headers("return=minimal"),
        json=payload,
        timeout=15,
    )
    if not response.ok:
        detail = response.text.strip()
        message = f"{response.status_code} {response.reason}"
        if detail:
            message = f"{message}: {detail}"
        raise requests.HTTPError(message, response=response)


def get_all_results():
    response = external_request(
        "GET",
        supabase_endpoint(),
        headers=supabase_headers(),
        params={"select": "*", "order": "submitted_at.desc"},
        timeout=15,
    )
    response.raise_for_status()
    rows = []
    for item in response.json():
        rows.append((
            item.get("id"),
            item.get("student_name", ""),
            item.get("submitted_at", ""),
            item.get("deadline", ""),
            int(bool(item.get("on_time"))),
            item.get("qcm_score", 0),
            item.get("qcm_total", 0),
            item.get("lab_score", 0),
            item.get("lab_total", 0),
            item.get("total_score", 0),
            item.get("max_score", 0),
            item.get("percentage", 0),
            item.get("grade", ""),
            json.dumps(item.get("qcm_answers", {})),
            json.dumps(item.get("lab_answers", {})),
            item.get("student_group", ""),
        ))
    return rows


def qcm_choice_text(question_idx: int, answer_idx) -> str:
    if isinstance(answer_idx, int) and 0 <= answer_idx < len(QCM[question_idx]["opts"]):
        return QCM[question_idx]["opts"][answer_idx]
    return "No answer"


def build_submission_txt(data: dict) -> str:
    lines = [
        f"Student: {data['student_name']}",
        f"Group: {data['student_group']}",
        f"Submitted At: {data['submitted_at']}",
        f"Deadline: {data['deadline']}",
        f"On Time: {'Yes' if data['on_time'] else 'No'}",
        f"Score: {data['total_score']}/{data['max_score']} ({data['percentage']:.1f}%)",
        f"Grade: {data['grade']}",
        "==============",
        "QCM Answers",
    ]

    qcm_answers = data.get("qcm_answers", {})
    for i, q in enumerate(QCM):
        answer_idx = qcm_answers.get(f"q{i}", -1)
        lines.extend([
            f"Q{i + 1}: {q['q']}",
            f"Chosen: {qcm_choice_text(i, answer_idx)}",
            f"Correct: {q['opts'][q['ans']]}",
            "",
        ])

    lab_code_answers = data.get("lab_code_answers", {})
    for i, lab in enumerate(LABS):
        code = lab_code_answers.get(str(i), "")
        lines.extend([
            "==============",
            f"Lab {i + 1}: {lab['title']}",
            code.strip() or "No code submitted",
        ])
    lines.append("==============")
    return "\n".join(lines)


def send_telegram_submission(data: dict) -> bool:
    bot_token = get_secret("TELEGRAM_BOT_TOKEN")
    chat_id = get_secret("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        return False

    filename = sanitize_filename(data["student_name"])
    api_url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    caption = (
        f"New C++ lab submission: {data['student_name']} | "
        f"Group {data['student_group']} | "
        f"{data['total_score']}/{data['max_score']} | Grade {data['grade']}"
    )
    payload = {
        "chat_id": chat_id,
        "caption": caption,
    }
    files = {
        "document": (filename, build_submission_txt(data).encode("utf-8"), "text/plain; charset=utf-8")
    }
    response = external_request("POST", api_url, data=payload, files=files, timeout=15)
    response.raise_for_status()
    return True


init_db()

#  QCM QUESTIONS 
QCM = [
    {
        "q": "What is printed^2 `int a = 7; int b = 2; cout << a / b << ' ' << a % b;`",
        "opts": ["3 1", "3.5 1", "4 1", "3 0"],
        "ans": 0,
        "explain": "With two integers, `/` performs integer division, and `%` gives the remainder.",
    },
    {
        "q": "What is the value of `avg`^2 `int total = 9, count = 2; float avg = total / count;`",
        "opts": ["4.0", "4.5", "5.0", "Compilation error"],
        "ans": 0,
        "explain": "`total / count` is calculated as integer division first, so 9 / 2 becomes 4.",
    },
    {
        "q": "Which declarations use valid C++ literals for the shown data types^2",
        "opts": [
            "int n = 12.5; char c = \"A\";",
            "float price = 4.99; char grade = 'B';",
            "bool ready = \"true\"; int count = '5';",
            "char letter = 'AB'; bool done = yes;",
        ],
        "ans": 1,
        "explain": "A float can store a decimal literal, and a char literal uses single quotes.",
    },
    {
        "q": "What is printed^2 `bool flag = false; cout << flag;`",
        "opts": ["false", "0", "1", "Nothing"],
        "ans": 1,
        "explain": "By default, `cout` prints bool values as 0 for false and 1 for true.",
    },
    {
        "q": "Which line causes a compilation error^2",
        "opts": [
            "const int MAX = 100;",
            "float rate = 0.25;",
            "const char section = 'A';",
            "MAX = 50;",
        ],
        "ans": 3,
        "explain": "A const variable cannot be assigned a new value after it is initialized.",
    },
    {
        "q": "What is printed^2 `cout << 5 + 12 / 4 * 2 - 1;`",
        "opts": ["10", "9", "16", "7"],
        "ans": 0,
        "explain": "Division and multiplication happen left to right: 12 / 4 = 3, 3 * 2 = 6, then 5 + 6 - 1 = 10.",
    },
    {
        "q": "Given `int id; char grade; float score; cin >> id >> grade >> score;`, which input matches the variables correctly^2",
        "opts": ["101 A 87.5", "A 101 87.5", "101 87.5 A", "101, A, 87.5"],
        "ans": 0,
        "explain": "`cin` reads values in order: integer first, then character, then floating-point number.",
    },
    {
        "q": "What is the final value of `x`^2 `int x = 8; x = x + 3 * 2;`",
        "opts": ["22", "14", "11", "48"],
        "ans": 1,
        "explain": "Multiplication happens before addition, so x becomes 8 + 6 = 14.",
    },
    {
        "q": "Which statement prints `Name: Dara, Age: 18` if `name` is `Dara` and `age` is `18`^2",
        "opts": [
            "cout << \"Name: \" << name << \", Age: \" << age;",
            "cin >> \"Name: \" >> name >> \", Age: \" >> age;",
            "cout >> \"Name: \" >> name >> \", Age: \" >> age;",
            "cout << Name: << name << Age: << age;",
        ],
        "ans": 0,
        "explain": "`cout` uses `<<`, string literals need double quotes, and variables are inserted without quotes.",
    },
    {
        "q": "Which expression gives `2.5` when `a = 5` and `b = 2`, where both variables are `int`?",
        "opts": ["a / b", "(float)a / b", "a % b", "float(a / b)"],
        "ans": 1,
        "explain": "Casting one operand before division forces floating-point division. `float(a / b)` casts too late.",
    },
]

LABS = [
    {
        "title": "Lab 1 - Declare & Display",
        "icon": "",
        "desc": """Declare the following variables and print each one:
- `name` = `your name (string)`
- `age` = your age (int)  
- `gpa` = your GPA (float)
- `initial` = your first letter (char)

Print them with labels like `Name: Alice`""",
        "hint": "Declare variable like this => string name = Hengly . Use cout << to print.",
        "starter": """#include <iostream>
#include <string>
using namespace std;

int main() {
    // TODO: Declare your variables here

    // TODO: Print each variable with a label

    return 0;
}""",
        "check_keywords": ["string", "int", "float", "char", "cout"],
        "check_patterns": [
            (r"string\s+\w+\s*=", "Declared a string variable"),
            (r"int\s+\w+\s*=\s*\d+", "Declared an int variable"),
            (r"float\s+\w+\s*=\s*[\d.]+", "Declared a float variable"),
            (r"char\s+\w+\s*=\s*'.", "Declared a char variable"),
            (r'cout\s*<<', "Used cout to print"),
        ],
        "max_pts": 10,
    },
    {
        "title": "Lab 2 - Calculator",
        "icon": "",
        "desc": """Write a program that:
1. Declares two integers `a = 20` and `b = 6`
2. Computes and prints ALL 5 operations:
   - Addition, Subtraction, Multiplication
   - Integer division, Modulo
3. **Bonus**: Also print float division (cast first)""",
        "hint": "For float division: (float)a / b  or  float fa = a;",
        "starter": """#include <iostream>
using namespace std;

int main() {
    int a = 20;
    int b = 6;

    // TODO: Print all 5 arithmetic results
    // Add labels like: cout << "a + b = " << (a + b) << endl;

    return 0;
}""",
        "check_keywords": ["a + b", "a - b", "a * b", "a / b", "a % b"],
        "check_patterns": [
            (r"a\s*\+\s*b", "Addition computed"),
            (r"a\s*-\s*b", "Subtraction computed"),
            (r"a\s*\*\s*b", "Multiplication computed"),
            (r"a\s*/\s*b", "Division computed"),
            (r"a\s*%\s*b", "Modulo computed"),
        ],
        "max_pts": 10,
    },
    {
        "title": "Lab 3 - Constants Challenge",
        "icon": "",
        "desc": """Write a program that uses constants to compute:
1. Declare `const float PI = 3.14159`
2. Declare `float radius = 7.5`
3. Compute and print:
   - Area of circle = PI * r * r
   - Circumference = 2 * PI * r
4. Use `const int DAYS_WEEK = 7` and print how many hours are in a week""",
        "hint": "Use r*r for radius squared. Hours in a week = DAYS_WEEK * 24",
        "starter": """#include <iostream>
using namespace std;

int main() {
    const float PI = 3.14159;
    float radius = 7.5;

    // TODO: Compute area and circumference

    const int DAYS_WEEK = 7;
    // TODO: Print hours in a week

    return 0;
}""",
        "check_keywords": ["const", "PI", "radius", "cout"],
        "check_patterns": [
            (r"const\s+float\s+PI", "Declared const PI"),
            (r"PI\s*\*\s*radius\s*\*\s*radius|PI\s*\*\s*\(radius\s*\*\s*radius\)", "Computed area correctly"),
            (r"2\s*\*\s*PI\s*\*\s*radius|2\.0\s*\*\s*PI\s*\*\s*radius", "Computed circumference"),
            (r"const\s+int\s+DAYS_WEEK", "Declared DAYS_WEEK constant"),
            (r"DAYS_WEEK\s*\*\s*24|24\s*\*\s*DAYS_WEEK", "Computed hours in a week"),
        ],
        "max_pts": 10,
    },
]


#  GRADING 
def grade_qcm(answers: dict) -> tuple[int, dict]:
    """Returns (score, feedback_dict)"""
    score = 0
    feedback = {}
    for i, q in enumerate(QCM):
        key = f"q{i}"
        chosen = answers.get(key, -1)
        correct = q["ans"]
        if chosen == correct:
            score += 1
            feedback[key] = {"correct": True, "explain": q["explain"]}
        else:
            feedback[key] = {
                "correct": False,
                "chosen": chosen,
                "correct_ans": correct,
                "explain": q["explain"],
            }
    return score, feedback


def grade_lab(lab_idx: int, code: str) -> tuple[int, list[str]]:
    """Returns (score, list_of_feedback_messages)"""
    lab = LABS[lab_idx]
    if not code or code.strip() == lab["starter"].strip():
        return 0, ["No code submitted (starter code unchanged)"]

    messages = []
    passed = 0
    total_checks = len(lab["check_patterns"])

    for pattern, label in lab["check_patterns"]:
        if re.search(pattern, code, re.IGNORECASE):
            passed += 1
            messages.append(f"[OK] {label}")
        else:
            messages.append(f"[Missing] {label}")

    # Basic syntax checks
    has_main = "int main()" in code or "int main (" in code
    has_return = "return 0" in code
    has_include = "#include" in code

    if has_main:
        messages.append("[OK] Has main() function")
    else:
        messages.append("[Warning] Missing main() function")
    if has_return:
        messages.append("[OK] Has return 0")
    if has_include:
        messages.append("[OK] Has #include")

    # Score: proportional to patterns matched
    score = round((passed / total_checks) * lab["max_pts"])
    return score, messages


def calculate_grade(pct: float) -> str:
    if pct >= 90: return "A+"
    if pct >= 80: return "A"
    if pct >= 70: return "B"
    if pct >= 60: return "C"
    if pct >= 50: return "D"
    return "F"


#  CUSTOM CSS 
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2^2family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');

:root {
    --navy: #0F172A;
    --blue: #2563EB;
    --blue2: #38BDF8;
    --green: #059669;
    --orange: #D97706;
    --red: #DC2626;
    --purple: #7C3AED;
    --bg: #F8FAFC;
    --card: #FFFFFF;
    --text: #0F172A;
    --muted: #475569;
    --border: #E2E8F0;
}

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif !important;
}

.stApp {
    background: #F8FAFC;
    min-height: 100vh;
}

/* Hero Banner */
.hero-banner {
    background: linear-gradient(135deg, #0F172A 0%, #1E3A8A 100%);
    border-radius: 8px;
    padding: 1.6rem 2rem;
    color: white;
    text-align: left;
    margin-bottom: 1.5rem;
    box-shadow: 0 12px 32px rgba(15,23,42,0.18);
    position: relative;
    overflow: hidden;
}
.hero-banner::before,
.hero-banner::after { display: none; }
.hero-title {
    font-family: 'Inter', sans-serif !important;
    font-size: clamp(1.5rem, 3vw, 2.35rem);
    font-weight: 800;
    margin: 0 0 0.5rem 0;
    color: #FFFFFF;
}
.hero-sub {
    font-size: 0.98rem;
    color: #CBD5E1;
    margin: 0;
}
.home-hero {
    background:
        linear-gradient(135deg, rgba(15,23,42,0.96), rgba(30,58,138,0.94)),
        linear-gradient(90deg, #0F172A, #1E3A8A);
    border: 1px solid rgba(148,163,184,0.25);
    border-radius: 10px;
    padding: 2rem;
    margin-bottom: 1.2rem;
    box-shadow: 0 18px 42px rgba(15,23,42,0.18);
}
.home-hero-grid {
    display: grid;
    grid-template-columns: minmax(0, 1.6fr) minmax(260px, 0.8fr);
    gap: 1.5rem;
    align-items: end;
}
.hero-kicker {
    display: inline-block;
    color: #BFDBFE;
    background: rgba(37,99,235,0.22);
    border: 1px solid rgba(191,219,254,0.28);
    border-radius: 6px;
    padding: 0.28rem 0.55rem;
    font-size: 0.72rem;
    font-weight: 800;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    margin-bottom: 0.9rem;
}
.home-title {
    color: #FFFFFF;
    font-size: clamp(2rem, 5vw, 3.8rem);
    line-height: 1.02;
    font-weight: 800;
    margin: 0 0 0.9rem;
}
.home-copy {
    color: #CBD5E1;
    font-size: 1rem;
    max-width: 680px;
    line-height: 1.7;
    margin: 0;
}
.home-hero-panel {
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(226,232,240,0.16);
    border-radius: 8px;
    padding: 1rem;
}
.home-panel-row {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.7rem 0;
    border-bottom: 1px solid rgba(226,232,240,0.16);
}
.home-panel-row:last-child { border-bottom: 0; }
.home-panel-label {
    color: #94A3B8;
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    font-weight: 700;
}
.home-panel-value {
    color: #FFFFFF;
    font-weight: 800;
    text-align: right;
}
.Assignment-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.8rem;
}
.Assignment-card {
    background: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 1rem;
}
.Assignment-index {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.85rem;
    color: #2563EB;
    font-weight: 700;
    margin-bottom: 0.65rem;
}
.Assignment-title {
    color: #0F172A;
    font-weight: 800;
    margin-bottom: 0.25rem;
}
.Assignment-desc {
    color: #64748B;
    font-size: 0.86rem;
    min-height: 2.4rem;
}
.Assignment-points {
    display: inline-block;
    margin-top: 0.8rem;
    border-radius: 6px;
    background: #0F172A;
    color: #FFFFFF;
    padding: 0.25rem 0.55rem;
    font-size: 0.78rem;
    font-weight: 800;
}

/* Timer badge */
.timer-card {
    background: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-left: 4px solid #2563EB;
    border-radius: 8px;
    padding: 1rem 1.5rem;
    color: #0F172A;
    text-align: left;
    margin-bottom: 1.2rem;
    box-shadow: 0 6px 18px rgba(15,23,42,0.06);
}
.timer-expired {
    border-left-color: #DC2626;
    box-shadow: 0 6px 18px rgba(220,38,38,0.12);
}
.timer-label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 1.4px; color: #64748B; font-weight: 700; }
.timer-val { font-family: 'JetBrains Mono', monospace !important; font-size: 1.6rem; font-weight: 600; }

/* Cards */
.section-card {
    background: white;
    color: #0F172A;
    border-radius: 8px;
    padding: 1.5rem;
    margin-bottom: 1rem;
    box-shadow: 0 4px 16px rgba(15,23,42,0.05);
    border: 1px solid #E2E8F0;
}
.section-card,
.section-card p,
.section-card li,
.section-card span,
.section-card div {
    color: #0F172A;
}
.section-card .section-sub,
.section-card .Assignment-desc,
.section-card [style*="#64748B"] {
    color: #64748B !important;
}
.home-hero,
.home-hero p,
.home-hero span,
.home-hero div,
.home-hero h1 {
    color: inherit;
}
.home-title,
.home-panel-value {
    color: #FFFFFF !important;
}
.home-copy,
.home-panel-label {
    color: #CBD5E1 !important;
}
.Assignment-points,
.lb-score,
.grade-badge {
    color: #FFFFFF !important;
}
.section-header {
    font-family: 'Inter', sans-serif !important;
    font-size: 1.08rem;
    font-weight: 700;
    color: #0F172A;
    margin-bottom: 0.35rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
.section-sub { color: #64748B; font-size: 0.9rem; margin-bottom: 1rem; }

/* QCM Question */
.qcm-card {
    background: #FFFFFF;
    color: #0F172A;
    border: 1px solid #CBD5E1;
    border-left: 4px solid #2563EB;
    border-radius: 8px;
    padding: 1.2rem 1.4rem;
    margin-bottom: 0.7rem;
    transition: border-color 0.2s, box-shadow 0.2s;
}
.qcm-card,
.qcm-card div,
.qcm-card span {
    color: #0F172A;
}
.qcm-card:hover {
    border-color: #2563EB;
    box-shadow: 0 8px 22px rgba(37,99,235,0.08);
}
.qcm-num {
    display: inline-block;
    background: #E0E7FF;
    color: #1E3A8A;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.75rem;
    font-weight: 700;
    padding: 2px 10px;
    border-radius: 6px;
    margin-bottom: 0.6rem;
}
.qcm-q {
    font-size: 1rem;
    font-weight: 600;
    color: #1E293B;
    line-height: 1.5;
}
.qcm-selected {
    display: inline-block;
    margin: 0.2rem 0 0.8rem;
    padding: 0.35rem 0.75rem;
    border-radius: 6px;
    background: #ECFDF5;
    color: #047857;
    font-size: 0.86rem;
    font-weight: 800;
}
.qcm-waiting {
    display: inline-block;
    margin: 0.2rem 0 0.8rem;
    padding: 0.35rem 0.75rem;
    border-radius: 6px;
    background: #F8FAFC;
    color: #475569;
    font-size: 0.86rem;
    font-weight: 800;
}

/* Code area */
.lab-challenge-card {
    background:
        linear-gradient(180deg, #FFFFFF 0%, #F8FAFC 100%);
    color: #0F172A !important;
    border: 1px solid #CBD5E1;
    border-left: 5px solid #2563EB;
    border-radius: 10px;
    padding: 1.1rem 1.25rem;
    margin: 1rem 0 0.8rem;
    box-shadow: 0 12px 28px rgba(15,23,42,0.08);
}
.lab-challenge-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.8rem;
    margin-bottom: 0.85rem;
}
.lab-challenge-title {
    color: #0F172A !important;
    font-size: 1.08rem;
    font-weight: 800;
}
.lab-challenge-tag {
    background: #DBEAFE;
    color: #1D4ED8 !important;
    border: 1px solid #BFDBFE;
    border-radius: 999px;
    padding: 0.22rem 0.6rem;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.78rem;
    font-weight: 700;
    white-space: nowrap;
}
.lab-desc-box {
    background: #FFFFFF;
    color: #0F172A !important;
    border: 1px solid #D7E3F8;
    border-radius: 8px;
    padding: 0.9rem 1rem;
    line-height: 1.75;
}
.lab-desc-box,
.lab-desc-box div,
.lab-desc-box li,
.lab-desc-box span,
.lab-desc-box p {
    color: #0F172A !important;
}
.lab-desc-box ul,
.lab-desc-box ol {
    margin: 0.45rem 0 0.45rem 1.25rem;
    padding: 0;
}
.lab-desc-box li {
    margin: 0.25rem 0;
}
.lab-desc-code {
    display: inline-block;
    background: #E0E7FF;
    color: #1E3A8A !important;
    border: 1px solid #C7D2FE;
    border-radius: 5px;
    padding: 0.05rem 0.35rem;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.86em;
    font-weight: 700;
}
.code-hint {
    background: #0F172A;
    color: #BFDBFE;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.85rem;
    padding: 0.8rem 1rem;
    border-radius: 10px;
    margin: 0.6rem 0;
    border-left: 3px solid #2563EB;
}

/* Score result */
.result-card {
    border-radius: 8px;
    padding: 2rem;
    text-align: center;
    color: white;
    margin: 1rem 0;
    box-shadow: 0 20px 50px rgba(0,0,0,0.2);
}
.grade-A { background: linear-gradient(135deg, #047857, #059669); }
.grade-B { background: linear-gradient(135deg, #1D4ED8, #2563EB); }
.grade-C { background: linear-gradient(135deg, #D97706, #F59E0B); }
.grade-D { background: linear-gradient(135deg, #EA580C, #F97316); }
.grade-F { background: linear-gradient(135deg, #DC2626, #EF4444); }
.score-big {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 3.5rem;
    font-weight: 700;
    line-height: 1;
}
.grade-badge {
    font-family: 'Inter', sans-serif !important;
    font-size: 1.8rem;
    font-weight: 700;
    background: rgba(255,255,255,0.2);
    display: inline-block;
    padding: 0.2rem 1rem;
    border-radius: 6px;
    margin: 0.5rem 0;
}

/* Feedback pill */
.fb-correct {
    background: #D1FAE5; color: #065F46;
    padding: 4px 12px; border-radius: 20px;
    font-size: 0.8rem; font-weight: 600;
    display: inline-block; margin: 2px;
}
.fb-wrong {
    background: #FEE2E2; color: #991B1B;
    padding: 4px 12px; border-radius: 20px;
    font-size: 0.8rem; font-weight: 600;
    display: inline-block; margin: 2px;
}
.quick-check-msg {
    background: #BBF7D0;
    color: #111827;
    border: 1px solid #000000;
    border-radius: 6px;
    padding: 0.75rem 1rem;
    margin: 0.45rem 0;
    font-size: 0.92rem;
    font-weight: 700;
}
.quick-check-missing {
    background: #FEE2E2;
}

/* Progress */
.progress-bar-wrap {
    background: #E2E8F0;
    border-radius: 6px;
    height: 13px;
    overflow: hidden;
    margin: 0.5rem 0;
}
.progress-bar-fill {
    height: 100%;
    border-radius: 6px;
    background: linear-gradient(90deg, #2563EB, #38BDF8);
    transition: width 0.5s ease;
}

/* Leaderboard */
.lb-row {
    display: flex;
    align-items: center;
    padding: 0.7rem 1rem;
    border-radius: 8px;
    margin-bottom: 0.5rem;
    background: #F8FAFC;
    border: 1px solid #2563EB;
    gap: 0.8rem;
}
.lb-rank { font-family: 'JetBrains Mono', monospace !important; font-weight: 700; width: 30px; color: black !important; }
.lb-name { flex: 1; font-weight: 600; color: black !important;}
.lb-score {
    font-family: 'JetBrains Mono', monospace !important;
    background: #0F172A; color: #BFDBFE;
    padding: 3px 12px; border-radius: 6px;
    font-size: 0.85rem; font-weight: 600;
}

/* Name input section */
.name-card {
    background: #0F172A;
    border-radius: 8px;
    padding: 2rem;
    color: white;
    text-align: center;
    margin: 2rem auto;
    max-width: 480px;
    box-shadow: 0 14px 36px rgba(15,23,42,0.22);
}

/* Responsive tweaks */
@media (max-width: 768px) {
    .hero-banner { padding: 1.2rem; }
    .home-hero { padding: 1.25rem; }
    .home-hero-grid { grid-template-columns: 1fr; align-items: start; }
    .Assignment-grid { grid-template-columns: 1fr; }
    .section-card { padding: 1rem; border-radius: 8px; }
    .qcm-card { padding: 1rem; }
    .qcm-num { font-size: 0.7rem; }
    .qcm-q { font-size: 0.96rem; }
    .score-big { font-size: 2.5rem; }
    .timer-val { font-size: 1.25rem; }
}

/* Streamlit overrides */
div[data-testid="stTextInput"] input {
    border-radius: 8px !important;
    border: 1px solid #CBD5E1 !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 1rem !important;
    padding: 0.6rem 1rem !important;
    transition: border-color 0.2s !important;
}
div[data-testid="stTextInput"] input:focus {
    border-color: #2563EB !important;
    box-shadow: 0 0 0 3px rgba(37,99,235,0.14) !important;
}
div[data-testid="stTextArea"] textarea {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.85rem !important;
    border-radius: 8px !important;
    border: 1px solid #CBD5E1 !important;
    background: #0F172A !important;
    color: #BAE6FD !important;
    padding: 1rem !important;
    line-height: 1.7 !important;
}
div[data-testid="stTextArea"] textarea:focus {
    border-color: #2563EB !important;
    box-shadow: 0 0 0 3px rgba(37,99,235,0.14) !important;
}
div[data-testid="stRadio"] label {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.95rem !important;
    color: #0F172A !important;
    background: #FFFFFF !important;
    border: 1px solid #CBD5E1 !important;
    border-radius: 8px !important;
    padding: 0.55rem 0.75rem !important;
    margin-bottom: 0.35rem !important;
    width: 100% !important;
    min-height: 2.6rem !important;
    display: flex !important;
    align-items: center !important;
}
div[data-testid="stRadio"] label,
div[data-testid="stRadio"] label *,
div[data-testid="stRadio"] span,
div[data-testid="stRadio"] p {
    color: #0F172A !important;
    opacity: 1 !important;
    visibility: visible !important;
}
div[data-testid="stRadio"] [role="radiogroup"] {
    gap: 0.35rem;
    width: 100%;
}
div[data-testid="stRadio"] [data-testid="stMarkdownContainer"] p {
    margin: 0 !important;
    color: #0F172A !important;
    font-weight: 600 !important;
    line-height: 1.35 !important;
    white-space: normal !important;
    overflow: visible !important;
    opacity: 1 !important;
}
.stButton > button {
    border-radius: 8px !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 700 !important;
    font-size: 1rem !important;
    padding: 0.6rem 2rem !important;
    transition: all 0.2s !important;
}
.stButton > button:hover {
    box-shadow: 0 6px 16px rgba(15,23,42,0.12) !important;
}
div[data-testid="stTabs"] [role="tab"] {
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.95rem !important;
}

/* Tab text color */
button[data-baseweb="tab"] {
    color: #000000 !important;
}

button[data-baseweb="tab"] p {
    color: #000000 !important;
}

/* Active tab */
button[data-baseweb="tab"][aria-selected="true"] {
    color: #000000 !important;
}

button[data-baseweb="tab"][aria-selected="true"] p {
    color: #000000 !important;
}

.qcm-instruction-box {
    background: #FFFFFF !important;
    color: #0F172A !important;
    border: 1px solid #CBD5E1 !important; /*  */
    border-radius: 8px !important;
    padding: 0.8rem 1rem !important;
    margin-bottom: 1rem !important;
}

.qcm-instruction-box b {
    color: #000000 !important;
}

.support-note-box {
    background: #FEF2F2 !important;
    color: #991B1B !important;
    border: 1px solid #FECACA !important;
    border-radius: 8px !important;
    padding: 1rem !important;
    margin-top: 1.5rem !important;
    font-size: 0.95rem !important;
    line-height: 1.6 !important;
}

.support-note-box b {
    color: #991B1B !important;
}
</style>
""", unsafe_allow_html=True)


#  SESSION STATE 
def init_state():
    defaults = {
        "page": "home",  # home | quiz | result | leaderboard
        "student_name": "",
        "student_group": "",
        "qcm_answers": {},
        "lab_answers": {0: "", 1: "", 2: ""},
        "submitted": False,
        "result": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()


#  HELPERS 
def progress_html(val, total, color="#2563EB"):
    pct = int(val / total * 100) if total else 0
    return f"""
    <div style="display:flex;align-items:center;gap:0.7rem;">
        <div class="progress-bar-wrap" style="flex:1">
            <div class="progress-bar-fill" style="width:{pct}%;background:linear-gradient(90deg,{color},{color}aa)"></div>
        </div>
        <span style="font-family:'JetBrains Mono';font-size:0.85rem;font-weight:600;color:#1E293B">{val}/{total}</span>
    </div>"""


def set_qcm_answer(question_idx: int):
    selected = st.session_state.get(f"radio_q{question_idx}")
    if selected in QCM[question_idx]["opts"]:
        st.session_state.qcm_answers[f"q{question_idx}"] = QCM[question_idx]["opts"].index(selected)


def inline_code_html(text: str) -> str:
    parts = re.split(r"(`[^`]+`)", text)
    formatted = []
    for part in parts:
        if part.startswith("`") and part.endswith("`"):
            formatted.append(f'<span class="lab-desc-code">{html.escape(part[1:-1])}</span>')
        else:
            formatted.append(html.escape(part))
    return "".join(formatted)


def lab_description_html(desc: str) -> str:
    lines = desc.strip().splitlines()
    output = []
    list_stack = []

    def close_lists(target_depth=0):
        while len(list_stack) > target_depth:
            output.append(f"</{list_stack.pop()}>")

    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))

        if not stripped:
            close_lists()
            output.append("<div style='height:0.45rem'></div>")
            continue

        bullet_match = re.match(r"^-\s+(.*)", stripped)
        number_match = re.match(r"^\d+\.\s+(.*)", stripped)

        if bullet_match:
            target_depth = 2 if indent >= 3 else 1
            if len(list_stack) < target_depth:
                while len(list_stack) < target_depth:
                    output.append("<ul>")
                    list_stack.append("ul")
            else:
                close_lists(target_depth)
            output.append(f"<li>{inline_code_html(bullet_match.group(1))}</li>")
        elif number_match:
            if list_stack != ["ol"]:
                close_lists()
                output.append("<ol>")
                list_stack.append("ol")
            output.append(f"<li>{inline_code_html(number_match.group(1))}</li>")
        else:
            close_lists()
            output.append(f"<p>{inline_code_html(stripped)}</p>")

    close_lists()
    return "\n".join(output)


def render_timer():
    deadline = get_deadline()
    remaining = time_remaining()
    deadline_str = deadline.strftime("%A, %B %d at 11:59 PM")

    if remaining is None:
        st.markdown(f"""
        <div class="timer-card timer-expired">
            <div class="timer-label">Deadline Passed</div>
            <div class="timer-val">Submissions Closed</div>
            <div style="font-size:0.8rem;opacity:0.8;margin-top:4px">Was due: {deadline_str}</div>
        </div>""", unsafe_allow_html=True)
    else:
        d, h, m = remaining
        parts = []
        if d: parts.append(f"{d}d")
        parts.append(f"{h:02d}h {m:02d}m")
        color_class = "timer-expired" if d == 0 and h < 3 else ""
        st.markdown(f"""
        <div class="timer-card {color_class}">
            <div class="timer-label">Time Remaining Until Deadline</div>
            <div class="timer-val">{'  '.join(parts)}</div>
            <div style="font-size:0.8rem;opacity:0.8;margin-top:4px">Due: {deadline_str}</div>
        </div>""", unsafe_allow_html=True)


#  PAGE: HOME 
def page_home():
    # Hero
    st.markdown("""
    <div class="home-hero">
        <div class="home-hero-grid">
            <div>
                <div class="hero-kicker">C++ Unit 1 Assignment By Group 2 🔥</div>
                <h1 class="home-title">Programming Lab Portal</h1>
                <p class="home-copy">
                    Complete the QCM section and coding labs in one focused workspace.
                    Your progress, deadline, and score are tracked automatically.
                </p>
            </div>
            <div class="home-hero-panel">
                <div class="home-panel-row">
                    <span class="home-panel-label">Format</span>
                    <span class="home-panel-value">10 QCM + 3 Labs</span>
                </div>
                <div class="home-panel-row">
                    <span class="home-panel-label">Total Score</span>
                    <span class="home-panel-value">100 pts</span>
                </div>
                <div class="home-panel-row">
                    <span class="home-panel-label">Grading</span>
                    <span class="home-panel-value">Auto Checked</span>
                </div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns([2, 1])

    with col1:
        render_timer()

        st.markdown("""
        <div class="section-card">
            <div class="section-header">About This Lab</div>
            <div class="section-sub">Complete all sections to get your auto-graded score</div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="Assignment-grid">
            <div class="Assignment-card">
                <div class="Assignment-index">01</div>
                <div class="Assignment-title">QCM</div>
                <div class="Assignment-desc">Ten multiple-choice questions covering C++ fundamentals.</div>
                <span class="Assignment-points">50 pts</span>
            </div>
            <div class="Assignment-card">
                <div class="Assignment-index">02</div>
                <div class="Assignment-title">Coding Labs</div>
                <div class="Assignment-desc">Three short C++ exercises checked for required patterns.</div>
                <span class="Assignment-points">50 pts</span>
            </div>
            <div class="Assignment-card">
                <div class="Assignment-index">03</div>
                <div class="Assignment-title">Final Score</div>
                <div class="Assignment-desc">Results are calculated and saved after submission.</div>
                <span class="Assignment-points">100 pts</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # 🗂️Instructions
        st.markdown("""
        <div class="section-card">
            <div class="section-header">🗂️Instructions</div>
            <ul style="color:#1E293B;line-height:2;margin:0;padding-left:1.2rem;">
                <li>Enter your <b>full name</b> and <b>group</b> to begin</li>
                <li>Answer all <b>10 multiple choice questions</b></li>
                <li>Complete all <b>3 coding lab challenges</b></li>
                <li>Click <b>Submit All</b> when done - scores are auto-calculated</li>
                <li>Your submission time and score are saved automatically</li>
                <li>You can only submit <b>once</b> per session</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        # Student entry
        st.markdown("""
        <div class="section-card" style="border:1px solid #2563EB;">
            <div class="section-header">Student Access</div>
        """, unsafe_allow_html=True)

        name = st.text_input(
            "Full Name",
            value=st.session_state.student_name,
            placeholder="Enter your name here . e.g. Trean Hengly",
            label_visibility="collapsed",
        )
        st.session_state.student_name = name.strip()

        group = st.text_input(
            "Group",
            value=st.session_state.student_group,
            placeholder="Enter your group here . e.g. Group 2",
            label_visibility="collapsed",
        )
        st.session_state.student_group = group.strip()

        if is_past_deadline():
            st.error("The deadline has passed. Submissions are closed.")
        elif st.session_state.submitted:
            st.success("Already submitted!")
            if st.button("View My Result", use_container_width=True):
                st.session_state.page = "result"
                st.rerun()
        else:
            if st.session_state.student_name and st.session_state.student_group:
                if st.button("Start Assignment", use_container_width=True, type="primary"):
                    st.session_state.page = "quiz"
                    st.rerun()
            else:
                st.button("Enter your name and group first", disabled=True, use_container_width=True)

        st.markdown("</div>", unsafe_allow_html=True)

        # Leaderboard preview
        st.markdown("""
        <div class="section-card">
            <div class="section-header">Leaderboard</div>
        """, unsafe_allow_html=True)
        try:
            rows = get_all_results()
        except requests.RequestException as exc:
            rows = []
            st.warning(f"Could not load leaderboard from Supabase: {exc}")
        if rows:
            top = sorted(rows, key=lambda r: r[9], reverse=True)[:5]
            medals = ["1", "2", "3", "4", "5"]
            for i, row in enumerate(top):
                st.markdown(f"""
                <div class="lb-row">
                    <span class="lb-rank">{medals[i]}</span>
                    <span class="lb-name">{row[1][:20]}</span>
                    <span class="lb-score">{row[11]:.0f}%</span>
                </div>""", unsafe_allow_html=True)
        else:
            st.markdown(
                "<div style='color:#64748B;text-align:center;padding:1rem'>No submissions yet.</div>",
                unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        if st.button("Full Leaderboard", use_container_width=True):
            st.session_state.page = "leaderboard"
            st.rerun()


#  PAGE: QUIZ 
def page_quiz():
    if is_past_deadline():
        st.error("Deadline has passed.")
        if st.button("Back"):
            st.session_state.page = "home";
            st.rerun()
        return

    # Header
    st.markdown(f"""
    <div class="hero-banner" style="padding:1.2rem 2rem;">
        <div class="hero-title" style="font-size:1.6rem">Lab Assignment</div>
        <p class="hero-sub">Student: <b style="color:#BFDBFE">{st.session_state.student_name}</b> &nbsp;|&nbsp; Group: <b style="color:#BFDBFE">{st.session_state.student_group}</b> &nbsp;|&nbsp; Answer all questions then submit</p>
    </div>
    """, unsafe_allow_html=True)

    col_main, col_side = st.columns([3, 1])

    with col_side:
        render_timer()

        # Progress tracker
        st.markdown("""<div class="section-card"><div class="section-header" style="font-size:1rem"> Progress</div>""",
                    unsafe_allow_html=True)
        qcm_done = sum(1 for i in range(len(QCM)) if f"q{i}" in st.session_state.qcm_answers)
        lab_done = sum(1 for i in range(len(LABS)) if
                       st.session_state.lab_answers.get(i, "").strip() not in ["", LABS[i]["starter"].strip()])
        st.markdown(f"<div style='font-size:0.85rem;color:#64748B;margin-bottom:4px'>QCM: {qcm_done}/10</div>",
                    unsafe_allow_html=True)
        st.markdown(progress_html(qcm_done, 10), unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:0.85rem;color:#64748B;margin:8px 0 4px'>Labs: {lab_done}/3</div>",
                    unsafe_allow_html=True)
        st.markdown(progress_html(lab_done, 3, "#059669"), unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # Submit button
        can_submit = qcm_done == len(QCM) and lab_done == len(LABS)
        if can_submit:
            st.success("All sections complete!")
        else:
            st.info(f"Complete {10 - qcm_done} QCM + {3 - lab_done} lab(s) remaining")

        if st.button("Submit Assignment", type="primary", use_container_width=True):
            submit_all()

        if st.button("Back to Home", use_container_width=True):
            st.session_state.page = "home";
            st.rerun()

    with col_main:
        tab_qcm, tab_lab = st.tabs(["Part 1 - QCM (50 pts)", "Part 2 - Coding Labs (50 pts)"])

        #  QCM TAB 
        with tab_qcm:
            st.markdown("""
            <div class="qcm-instruction-box">
                <b>📝 Instructions:</b> Choose the best answer for each question. The QCM section is worth 50 points total.
            </div>""", unsafe_allow_html=True)

            st.markdown("""
            <div class="support-note-box" style="margin-top: -0.5rem; margin-bottom: 1.5rem;">
                🚀 <b>Note:</b> If you think there's an error with your points, you can chat with our team and we will solve it for you. 
                We already store your score in our database and capture answers which u choose and write send to our Telegram bot too. Don't worry about it ❤️
            </div>""", unsafe_allow_html=True)

            for i, q in enumerate(QCM):
                current = st.session_state.qcm_answers.get(f"q{i}", None)
                answered_class = "qcm-selected" if current is not None else "qcm-waiting"
                answered_text = f"Selected: {q['opts'][current]}" if current is not None else "Choose one answer"
                radio_key = f"radio_q{i}"
                if st.session_state.get(radio_key) not in [None, *q["opts"]]:
                    st.session_state.pop(radio_key, None)

                st.markdown(f"""
                <div class="qcm-card">
                    <span class="qcm-num">Q{i + 1} / 10</span>
                    <div class="qcm-q">{q['q']}</div>
                </div>""", unsafe_allow_html=True)

                st.markdown(f'<div class="{answered_class}">{answered_text}</div>', unsafe_allow_html=True)

                st.radio(
                    f"q{i}_radio",
                    q["opts"],
                    index=current,
                    key=radio_key,
                    label_visibility="collapsed",
                    on_change=set_qcm_answer,
                    args=(i,),
                    width="stretch",
                )

                st.markdown("<hr style='border:none;border-top:1px solid #F1F5F9;margin:0.3rem 0'>",
                            unsafe_allow_html=True)

        #  LAB TAB 
        with tab_lab:
            st.markdown("""
            <div class="qcm-instruction-box">
                <b>📝 Instructions:</b> Write C++ code for each challenge. You do not need to run it - we check for correct patterns. The lab section is worth 50 points total.
            </div>""", unsafe_allow_html=True)

            st.markdown("""
            <div class="support-note-box" style="margin-top: -0.5rem; margin-bottom: 1.5rem;">
                🚀 <b>Note:</b> If you think there's an error with your points, you can chat with our team and we will solve it for you. 
                We already store your score in our database and capture answers which u choose and write send to our Telegram bot too. Don't worry about it ❤️
            </div>""", unsafe_allow_html=True)

            for i, lab in enumerate(LABS):
                border_color = "#2563EB" if i == 0 else "#059669" if i == 1 else "#7C3AED"
                st.markdown(f"""
                <div class="lab-challenge-card" style="border-left-color:{border_color}">
                    <div class="lab-challenge-head">
                        <div class="lab-challenge-title">{lab['icon']} {html.escape(lab['title'])}</div>
                        <div class="lab-challenge-tag">{lab['max_pts']} raw pts</div>
                    </div>
                    <div class="lab-desc-box">
                        {lab_description_html(lab["desc"])}
                    </div>
                </div>
                """, unsafe_allow_html=True)

                # Hint
                st.markdown(f'<div class="code-hint">Hint: {lab["hint"]}</div>', unsafe_allow_html=True)

                # Code editor
                current_code = st.session_state.lab_answers.get(i, lab["starter"])
                if not current_code:
                    current_code = lab["starter"]

                new_code = st.text_area(
                    f"Write your C++ code here",
                    value=current_code,
                    height=280,
                    key=f"lab_code_{i}",
                )
                st.session_state.lab_answers[i] = new_code

                # Live check button
                if st.button(f"Quick Check Lab {i + 1}", key=f"check_{i}"):
                    score, msgs = grade_lab(i, new_code)
                    pct = score / lab["max_pts"] * 100
                    st.markdown(f"**Estimated score: {score}/{lab['max_pts']} ({pct:.0f}%)**")
                    for m in msgs:
                        msg_class = "quick-check-msg quick-check-missing" if m.startswith("[Missing]") else "quick-check-msg"
                        st.markdown(
                            f'<div class="{msg_class}">{html.escape(m)}</div>',
                            unsafe_allow_html=True,
                        )

                st.markdown("")

def submit_all():
    """Grade everything, save to DB, go to result page."""
    name = st.session_state.student_name
    group = st.session_state.student_group
    if not name:
        st.error("Please enter your name!")
        return
    if not group:
        st.error("Please enter your group!")
        return

    # Grade QCM
    qcm_score, qcm_feedback = grade_qcm(st.session_state.qcm_answers)
    qcm_total = 50
    lab_total = 50
    qcm_pts = round((qcm_score / len(QCM)) * qcm_total)

    # Grade Labs
    lab_scores = {}
    lab_feedback = {}
    for i in range(len(LABS)):
        code = st.session_state.lab_answers.get(i, "")
        s, msgs = grade_lab(i, code)
        lab_scores[i] = s
        lab_feedback[i] = msgs
    raw_lab_pts = sum(lab_scores.values())
    raw_lab_total = sum(l["max_pts"] for l in LABS)
    lab_pts = round((raw_lab_pts / raw_lab_total) * lab_total) if raw_lab_total else 0

    total = qcm_pts + lab_pts
    max_score = qcm_total + lab_total
    pct = total / max_score * 100
    grade = calculate_grade(pct)

    now = datetime.now(TZ)
    deadline = get_deadline()
    on_time = now <= deadline

    result = {
        "student_name": name,
        "student_group": group,
        "submitted_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "deadline": deadline.strftime("%Y-%m-%d %H:%M:%S"),
        "on_time": on_time,
        "qcm_score": qcm_pts,
        "qcm_total": qcm_total,
        "lab_score": lab_pts,
        "lab_total": lab_total,
        "total_score": total,
        "max_score": max_score,
        "percentage": pct,
        "grade": grade,
        "qcm_answers": st.session_state.qcm_answers,
        "lab_answers": {str(k): v for k, v in lab_scores.items()},
        "lab_code_answers": {str(k): st.session_state.lab_answers.get(k, "") for k in range(len(LABS))},
        "qcm_feedback": qcm_feedback,
        "lab_feedback": lab_feedback,
    }

    try:
        save_submission(result)
    except requests.RequestException as exc:
        st.error(f"Could not save submission to database: {exc}")
        return

    try:
        result["telegram_sent"] = send_telegram_submission(result)
    except requests.RequestException as exc:
        result["telegram_sent"] = False
        result["telegram_error"] = str(exc)

    st.session_state.result = result
    st.session_state.submitted = True
    st.session_state.page = "result"
    st.rerun()


#  PAGE: RESULT 
def page_result():
    result = st.session_state.result
    if not result:
        st.warning("No result found.")
        if st.button(" Home"):
            st.session_state.page = "home";
            st.rerun()
        return

    grade = result["grade"]
    pct = result["percentage"]
    grade_class = (
        "grade-A" if grade in ("A+", "A") else
        "grade-B" if grade == "B" else
        "grade-C" if grade == "C" else
        "grade-D" if grade == "D" else
        "grade-F"
    )
    timing_badge = "On Time" if result["on_time"] else "Late"

    st.markdown(f"""
    <div class="result-card {grade_class}">
        <div style="font-size:1.2rem;font-weight:600;opacity:0.9">{result['student_name']}</div>
        <div style="font-size:0.95rem;font-weight:600;opacity:0.75">Group: {result['student_group']}</div>
        <div class="score-big">{result['total_score']}<span style="font-size:1.5rem;opacity:0.7">/{result['max_score']}</span></div>
        <div class="grade-badge">Grade {grade}</div>
        <div style="font-size:1rem;opacity:0.85">{pct:.1f}% &nbsp;|&nbsp; {timing_badge}</div>
        <div style="font-size:0.8rem;opacity:0.7;margin-top:6px">
            Submitted: {result['submitted_at']} &nbsp;|&nbsp; Deadline: {result['deadline']}
        </div>
    </div>""", unsafe_allow_html=True)

    if get_secret("TELEGRAM_BOT_TOKEN") and get_secret("TELEGRAM_CHAT_ID") and not result.get("telegram_sent"):
        st.warning("Result was saved, but Telegram delivery failed. Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""<div class="section-card"><div class="section-header">QCM Results</div>""",
                    unsafe_allow_html=True)
        st.markdown(progress_html(result["qcm_score"], result["qcm_total"]), unsafe_allow_html=True)
        st.markdown(
            f"<div style='color:#64748B;font-size:0.85rem;margin:0.5rem 0'>Score: {result['qcm_score']}/{result['qcm_total']}</div>",
            unsafe_allow_html=True)

        fb = result.get("qcm_feedback", {})
        for i, q in enumerate(QCM):
            key = f"q{i}"
            info = fb.get(key, {})
            correct = info.get("correct", False)
            status = "Correct" if correct else "Incorrect"
            color = "#ECFDF5" if correct else "#FEF2F2"
            text_color = "#047857" if correct else "#B91C1C"
            st.markdown(f"""
            <div style="background:{color};border-radius:8px;padding:0.6rem 0.8rem;margin-bottom:0.4rem;border:1px solid {'#BBF7D0' if correct else '#FECACA'};">
                <div style="font-weight:600;color:{text_color};font-size:0.9rem">{status} - Q{i + 1}: {q['q'][:60]}...</div>
                <div style="color:{text_color};font-size:0.8rem;opacity:0.85;margin-top:3px">{info.get('explain', '')}</div>
            </div>""", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown("""<div class="section-card"><div class="section-header">Lab Results</div>""",
                    unsafe_allow_html=True)
        st.markdown(progress_html(result["lab_score"], result["lab_total"], "#059669"), unsafe_allow_html=True)
        st.markdown(
            f"<div style='color:#64748B;font-size:0.85rem;margin:0.5rem 0'>Score: {result['lab_score']}/{result['lab_total']}</div>",
            unsafe_allow_html=True)

        lab_fb = result.get("lab_feedback", {})
        lab_sc = result.get("lab_answers", {})
        colors = ["#2563EB", "#059669", "#7C3AED"]
        for i, lab in enumerate(LABS):
            sc = lab_sc.get(str(i), lab_sc.get(i, 0))
            msgs = lab_fb.get(i, [])
            st.markdown(f"""
            <div style="background:#F8FAFC;border-radius:8px;padding:0.8rem;margin-bottom:0.6rem;border:1px solid #E2E8F0;border-left:4px solid {colors[i]}">
                <div style="font-weight:700;color:#0F172A">{lab['title']}</div>
                <div style="font-family:'JetBrains Mono';font-size:0.85rem;color:{colors[i]};margin:4px 0">{sc}/{lab['max_pts']} pts</div>
            """, unsafe_allow_html=True)
            for m in msgs[:5]:
                pill_class = "fb-correct" if m.startswith("[OK]") else "fb-wrong" if m.startswith("[Missing]") else "fb-correct"
                st.markdown(f'<span class="{pill_class}">{m}</span>', unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("View Leaderboard", use_container_width=True):
            st.session_state.page = "leaderboard";
            st.rerun()
    with col_b:
        if st.button("Back to Home", use_container_width=True):
            st.session_state.page = "home";
            st.rerun()

    st.markdown("""
    <div class="support-note-box">
        🚀 <b>Note:</b> If you think there's an error with your points, you can chat with our team and we will solve it for you. 
        We already store your score in our database and capture answers which u choose and write send to our Telegram bot too. Don't worry about it ❤️
    </div>""", unsafe_allow_html=True)


#  PAGE: LEADERBOARD 
def page_leaderboard():
    st.markdown("""
    <div class="hero-banner">
        <div class="hero-title">Leaderboard</div>
        <p class="hero-sub">Top scores from all submissions</p>
    </div>""", unsafe_allow_html=True)

    try:
        rows = get_all_results()
    except requests.RequestException as exc:
        rows = []
        st.warning(f"Could not load leaderboard from Supabase: {exc}")
    if not rows:
        st.info("No submissions yet. Be the first!")
        if st.button("Back"):
            st.session_state.page = "home";
            st.rerun()
        return

    sorted_rows = sorted(rows, key=lambda r: (r[9], r[2]), reverse=True)
    rank_labels = ["1", "2", "3"] + [str(i) for i in range(4, 104)]

    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown("""<div class="section-card"><div class="section-header">Rankings</div>""",
                    unsafe_allow_html=True)

        # Header row
        st.markdown("""
        <div style="display:grid;grid-template-columns:50px 1fr 80px 80px 80px 80px;gap:0.5rem;
             padding:0.5rem 0.8rem;background:#0F172A;color:white;border-radius:8px;
             font-size:0.8rem;font-weight:700;text-align:center;margin-bottom:0.5rem">
            <span>#</span><span style="text-align:left">Name</span>
            <span>Total</span><span>QCM</span><span>Lab</span><span>Grade</span>
        </div>""", unsafe_allow_html=True)

        for rank, row in enumerate(sorted_rows):
            _, name, submitted, _, on_time, qcm_s, qcm_t, lab_s, lab_t, total_s, max_s, pct, grade, _, _, group = row
            g_color = "#059669" if grade in ("A+",
                                             "A") else "#2563EB" if grade == "B" else "#D97706" if grade == "C" else "#DC2626"
            on_time_badge = "On time" if on_time else "Late"
            bg = "#F8FAFC" if rank % 2 == 0 else "white"
            border = "1px solid #E2E8F0"
            st.markdown(f"""
            <div style="display:grid;grid-template-columns:50px 1fr 80px 80px 80px 80px;gap:0.5rem;
                  padding:0.6rem 0.8rem;background:{bg};border:{border};border-radius:8px;
                  margin-bottom:0.3rem;align-items:center;font-size:0.9rem">
                <span style="font-family:'JetBrains Mono';font-weight:700;text-align:center">{rank_labels[rank]}</span>
                <span style="font-weight:600;color:#1E293B">{name[:22]} <span style="color:#64748B;font-size:0.75rem">({group[:12]} - {on_time_badge})</span></span>
                <span style="text-align:center;font-family:'JetBrains Mono';font-weight:700;color:#1E293B">{total_s}/{max_s}</span>
                <span style="text-align:center;color:#2563EB;font-family:'JetBrains Mono'">{qcm_s}</span>
                <span style="text-align:center;color:#059669;font-family:'JetBrains Mono'">{lab_s}</span>
                <span style="text-align:center;background:{g_color};color:white;border-radius:6px;padding:2px 8px;font-weight:700;font-size:0.8rem">{grade}</span>
            </div>""", unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        # Stats
        pcts = [r[11] for r in rows]
        st.markdown(f"""
        <div class="section-card">
            <div class="section-header">Stats</div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.8rem;margin-top:0.5rem">
                <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:0.8rem;text-align:center">
                    <div style="font-size:0.7rem;color:#64748B;text-transform:uppercase;letter-spacing:1px">Students</div>
                    <div style="font-family:'JetBrains Mono';font-size:1.8rem;font-weight:700;color:#0F172A">{len(rows)}</div>
                </div>
                <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:0.8rem;text-align:center">
                    <div style="font-size:0.7rem;color:#64748B;text-transform:uppercase;letter-spacing:1px">Avg Score</div>
                    <div style="font-family:'JetBrains Mono';font-size:1.8rem;font-weight:700;color:#059669">{sum(pcts) / len(pcts):.0f}%</div>
                </div>
                <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:0.8rem;text-align:center">
                    <div style="font-size:0.7rem;color:#64748B;text-transform:uppercase;letter-spacing:1px">Highest</div>
                    <div style="font-family:'JetBrains Mono';font-size:1.8rem;font-weight:700;color:#D97706">{max(pcts):.0f}%</div>
                </div>
                <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:0.8rem;text-align:center">
                    <div style="font-size:0.7rem;color:#64748B;text-transform:uppercase;letter-spacing:1px">Pass Rate</div>
                    <div style="font-family:'JetBrains Mono';font-size:1.8rem;font-weight:700;color:#DC2626">{sum(1 for p in pcts if p >= 50) / len(pcts) * 100:.0f}%</div>
                </div>
            </div>
        </div>""", unsafe_allow_html=True)

        # Grade distribution
        grade_counts = {}
        for r in rows:
            g = r[12]
            grade_counts[g] = grade_counts.get(g, 0) + 1

        st.markdown("""<div class="section-card"><div class="section-header">Grades</div>""", unsafe_allow_html=True)
        for g, color in [("A+", "#047857"), ("A", "#059669"), ("B", "#2563EB"), ("C", "#D97706"), ("D", "#EA580C"),
                         ("F", "#DC2626")]:
            count = grade_counts.get(g, 0)
            if count or True:
                bar = int(count / len(rows) * 100) if rows else 0
                st.markdown(f"""
                <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.4rem">
                    <span style="font-weight:700;color:{color};width:22px;font-size:0.9rem">{g}</span>
                    <div style="flex:1;background:#E2E8F0;border-radius:6px;height:10px;overflow:hidden">
                        <div style="width:{bar}%;height:100%;background:{color};border-radius:6px"></div>
                    </div>
                    <span style="font-family:'JetBrains Mono';font-size:0.8rem;color:#64748B;width:20px">{count}</span>
                </div>""", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    if st.button("Back to Home", use_container_width=True):
        st.session_state.page = "home";
        st.rerun()


#  ROUTER 
page = st.session_state.page
if page == "home":
    page_home()
elif page == "quiz":
    page_quiz()
elif page == "result":
    page_result()
elif page == "leaderboard":
    page_leaderboard()
