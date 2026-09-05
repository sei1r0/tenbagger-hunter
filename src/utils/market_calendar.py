import datetime
import sys
import jpholiday
import holidays

def get_jst_now() -> datetime.datetime:
    """JST基準の現在日時を取得"""
    jst = datetime.timezone(datetime.timedelta(hours=9))
    return datetime.datetime.now(jst)

def is_tokyo_market_open(target_date: datetime.date = None) -> bool:
    """
    東証（東京証券取引所）の開場日判定
    - 土日
    - 国民の祝日・振替休日
    - 年末年始特別休場（12/31〜1/3）
    """
    if target_date is None:
        target_date = get_jst_now().date()

    if target_date.weekday() >= 5:
        return False

    if jpholiday.is_holiday(target_date):
        return False

    month, day = target_date.month, target_date.day
    if (month == 12 and day == 31) or (month == 1 and day in (1, 2, 3)):
        return False

    return True

def is_us_market_open_prev_day(target_date: datetime.date = None) -> bool:
    """
    日本時間の判定時点で、前夜の米国市場（NYSE/NASDAQ）が開場していたかを判定
    """
    if target_date is None:
        # 日本時間の朝7時時点では、米国の日付は前日
        target_date = (get_jst_now() - datetime.timedelta(days=1)).date()

    if target_date.weekday() >= 5:
        return False

    us_holidays = holidays.US(years=target_date.year)
    if target_date in us_holidays:
        return False

    return True

def guard_tokyo_market():
    """東証が休場日の場合はログを出力して Exit 0 (正常終了) する"""
    today = get_jst_now().date()
    if not is_tokyo_market_open(today):
        h_name = jpholiday.is_holiday_name(today)
        reason = h_name if h_name else "週末または年末年始休場"
        print(f"[{today}] 本日は東京市場の休場日です ({reason})。処理をスキップします。")
        sys.exit(0)