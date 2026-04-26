from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger
from main import run
from config import SCHEDULE_DAY, SCHEDULE_HOUR

scheduler = BlockingScheduler(timezone="America/Argentina/Buenos_Aires")

scheduler.add_job(
    run,
    trigger="cron",
    day_of_week=SCHEDULE_DAY,
    hour=SCHEDULE_HOUR,
    minute=0,
    id="weekly_scrape",
    name="Weekly real estate scrape",
    misfire_grace_time=3600,
)

if __name__ == "__main__":
    logger.info(f"Scheduler started: runs every {SCHEDULE_DAY} at {SCHEDULE_HOUR}:00 ART")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")
