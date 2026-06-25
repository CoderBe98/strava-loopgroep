from config import get_settings
from database import initialise
from report_service import run_report

if __name__ == "__main__":
    settings = get_settings()
    initialise(settings.database_path)
    report = run_report(settings)
    print(report.content)
