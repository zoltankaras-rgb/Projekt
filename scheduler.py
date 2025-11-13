# scheduler.py
from __future__ import annotations
import os, time
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone

import db_connector
from tasks import uloha_kontrola_skladu, vykonaj_db_ulohu

TZ = timezone(os.getenv("APP_TZ", "Europe/Bratislava"))

def _schedule_builtin_jobs(sched: BlockingScheduler):
    # Príklad: každý deň 14:00 kontrola skladu na definovaný email
    email_to = os.getenv("LOW_STOCK_EMAIL", "")  # alebo nechaj prázdne a sprav úlohu v DB
    if email_to:
        sched.add_job(lambda: uloha_kontrola_skladu(email_to), CronTrigger(hour=14, minute=0, timezone=TZ),
                      id="builtin_low_stock_14", replace_existing=True, misfire_grace_time=300)

def _load_db_tasks(sched: BlockingScheduler):
    rows = db_connector.execute_query("SELECT * FROM automatizovane_ulohy WHERE is_enabled=1", fetch="all") or []
    # odstráň staré joby
    for j in list(sched.get_jobs()):
        if j.id.startswith("dbtask_"):
            sched.remove_job(j.id)

    for t in rows:
        tid = int(t["id"])
        cron = (t.get("cron_retazec") or "").strip() or "0 14 * * *"
        try:
            trig = CronTrigger.from_crontab(cron, timezone=TZ)
        except Exception:
            continue
        sched.add_job(lambda i=tid: vykonaj_db_ulohu(i), trig,
                      id=f"dbtask_{tid}", replace_existing=True, misfire_grace_time=300)

def main():
    sched = BlockingScheduler(timezone=TZ)
    _schedule_builtin_jobs(sched)
    _load_db_tasks(sched)

    # pravidelne refreshni definície úloh (napr. každých 5 minút)
    sched.add_job(lambda: _load_db_tasks(sched), CronTrigger(minute="*/5", timezone=TZ),
                  id="refresh_db_tasks", replace_existing=True)
    print("[scheduler] Spustený. (Ctrl+C na ukončenie)")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        print("[scheduler] Stop.")

if __name__ == "__main__":
    main()
