"""NewsPulse 一键入口（demo 版）：新闻→情绪→决策→撮合→报告。"""
import sys
import datetime as dt

import fetch_news
import filter_news
import decision
import sim_account
import daily_report
import select_stock


def main():
    date_str = dt.date.today().isoformat()
    print(f"=== NewsPulse demo {date_str} ===")
    select_stock.main(date_str)
    fetch_news.main(date_str)
    filter_news.main(date_str)
    decision.main(date_str)
    sim_account.main(date_str)
    daily_report.main(date_str)
    print("=== done ===")


if __name__ == "__main__":
    sys.path.insert(0, __file__.rsplit("\\", 1)[0])
    main()