# mekorot-shiur – מילוי מראי מקומות בסיכומי שיעורים

תוסף (plugin) ל-Claude (Cowork ו-Claude Code) שממלא הערות שוליים ריקות (או מסומנות `???`) במראי מקומות בקובץ docx של סיכום שיעור של הרב יצחק גינזבורג – במעקב שינויים, עם סימון מקורות לא ודאיים ב-comment.

## מה בתוך התוסף
- **skill `milui-mekorot`** – ההוראות המלאות לקלוד: איך לזהות את ההערות, איפה לחפש, איך לצטט, איך למסור.
- **`references/arachim.md`** – קובץ "ערכים ומראי מקומות" בפורמט markdown (ערך = שורה אחת; ניתן לחיפוש מהיר). זהו מקור החיפוש העיקרי.
- **`references/conventions.md`** – מוסכמות ציטוט וקיצורים.
- **`scripts/footnotes_tool.py`** – כלי בשלוש פקודות: `list` (ההערות הריקות עם ההקשר שלהן בגוף המסמך), `apply` (החלת המילויים במעקב שינויים + comments), `verify` (בדיקת קובץ הפלט). python3 בלבד, בלי התקנות.
- **`examples/fills.example.json`** – דוגמה לקובץ מילויים.

## התקנה

**ב-Cowork:** Customize → Plugins → **Add marketplace** → `MZweingort/mekorot-plugins` → **Install** על mekorot-shiur.
(לחלופין: לגרור קובץ `.plugin` לשיחה וללחוץ "התקן".)

**ב-Claude Code:** שתי פקודות בתוך סשן:
```
/plugin marketplace add MZweingort/mekorot-plugins
/plugin install mekorot-shiur@mekorot-plugins
```
אם ההודעה בסיום ההתקנה אומרת `Run /reload-plugins to activate` – להריץ `/reload-plugins`. לעדכון גרסה: `/plugin marketplace update mekorot-plugins`.

## שימוש

**ב-Cowork:** שיחה חדשה → לצרף את קובץ ה-docx → לכתוב **"מלא מקורות בהערות הריקות"** → הקובץ `... - עם מקורות.docx` חוזר בשיחה.

**ב-Claude Code:** להריץ `claude` בתיקייה שבה נמצא השיעור, ולכתוב "מלא מקורות בהערות הריקות ב-shiur.docx". הקובץ החדש נכתב לצד המקור באותה תיקייה.

בשני המקרים: לפתוח ב-Word עם "מעקב שינויים", לעבור על ההוספות (מחבר: Claude) ועל ה-comments ("מקור לא ודאי").

טיפים:
- כמה שיעורים בשיחה אחת חוסך זמן (ההכנה נעשית פעם אחת).
- הערה שרוצים שקלוד יבדוק – לכתוב בה `???`.
- קובץ ערכים מעודכן: להעלות אותו לשיחה ולבקש "השתמש בקובץ הערכים הזה במקום המובנה" (ה-skill יודע להמיר אותו).

## דרישות
`python3` בלבד (ספריות תקן). `pandoc` נדרש רק להמרת קובץ ערכים חדש, ו-`soffice` (LibreOffice) רק לבדיקה חזותית אופציונלית – בלעדיהם הכל עובד, כולל האימות (`verify`).

## ארכיון השיעורים (אופציונלי)
ה-skill יודע להיעזר גם בקונקטור (MCP) של ארכיון שיעורי הרב (גל עיני) – חיפוש בטקסט המלא של אלפי שיעורים וספרים, שימושי למציאת מקורות ששיעור אחר כבר ציטט ולהפניות מסוג "ראה שיעור ...". הקונקטור מוגדר בתוסף (`.mcp.json`, כתובת: https://galeinai-v3.vercel.app/mcp/) – בהתקנה Cowork מציע לחבר אותו; אם הוא לא הוצע, אפשר להוסיף אותו ידנית ב-Settings → Connectors → Add custom connector עם הכתובת הזו. בלעדיו ה-skill עובד רק עם קובץ הערכים והידע הכללי.

## עדכון קובץ הערכים בתוך התוסף
```
pandoc -t gfm --wrap=none "ערכים ומראי מקומות.docx" | sed -E 's#<span dir="rtl">##g; s#</span>##g; s#\\([*"\x27\[\]_])#\1#g' > skills/milui-mekorot/references/arachim.md
```
ואז לארוז מחדש: `zip -r mekorot-shiur.plugin .` מתוך תיקיית התוסף.
