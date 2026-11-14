"""Pre-generate AI insights for every course that has none yet.

Run on the server (inside the venv, in the app folder):   python generate_insights.py

Why: saved insights open instantly for reviewers and cost no free-tier quota. This script
respects the app's daily AI limit, pauses between requests, and stops at the first error
(for example "quota used up") so it never burns attempts. Run it again later to continue.
"""
import argparse
import time

import ai_insights
import app as A


def main(pause=4.0):
    todo = A.query("SELECT c.course_id, c.course_code, c.course_name FROM courses c "
                   "LEFT JOIN course_insights i ON i.course_id = c.course_id "
                   "WHERE i.course_id IS NULL ORDER BY c.course_code")
    if not todo:
        print("All courses already have insights.")
        return 0
    done = 0
    for c in todo:
        if A.ai_attempts(24) >= A.AI_DAILY_LIMIT:
            print(f"Daily AI limit ({A.AI_DAILY_LIMIT}) reached. Run this again tomorrow to continue.")
            break
        try:
            r = ai_insights.generate_insight(c["course_name"])
            A.store_insight(c["course_id"], r)
            A.audit("AI_INSIGHT", "course", c["course_id"], {"model": r["model"], "web_search": r["grounded"]})
            print(f"OK    {c['course_code']}  {c['course_name']}  (web search: {'yes' if r['grounded'] else 'no'})")
            done += 1
        except ai_insights.AIError as e:
            A.audit("AI_FAILED", "course", c["course_id"], {"reason": str(e)})
            print(f"STOP  {c['course_code']}: {e}")
            break
        time.sleep(pause)
    print(f"Generated {done} of {len(todo)} missing insights.")
    return done


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pause", type=float, default=4.0, help="seconds to wait between requests")
    main(ap.parse_args().pause)
