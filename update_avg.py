import sys

def update():
    with open('daily_usage_system.py', 'r', encoding='utf-8') as f:
        content = f.read()

    is_crlf = '\r\n' in content
    c_norm = content.replace('\r\n', '\n')

    old_stats = """        total_gb = total_bytes / (1024 ** 3)
        peak_gb = peak_bytes / (1024 ** 3)
        avg_gb = total_gb / days if days > 0 else 0.0

        # بررسی کافی بودن تاریخچه و فرمت شمسی تاریخ شروع
        has_sufficient_history = True
        history_note = ""

        if not first_date:
            has_sufficient_history = False
            history_note = "ثبت آمار این سرویس به تازگی آغاز شده است." if lang == "fa" else "Stats collection just started for this service."
        else:
            first_dt = datetime.strptime(first_date, "%Y-%m-%d").date()
            recorded_span_days = (today - first_dt).days + 1
            if recorded_span_days < days or total_historical_days < days:
                has_sufficient_history = False
                shamsi_start = format_date_persian(first_date) if lang == "fa" else first_date
                history_note = (
                    f"آمار مربوط به {to_persian_digits(total_historical_days)} روز ثبت‌شده است (شروع ثبت: {shamsi_start})."
                    if lang == "fa" else
                    f"Showing {total_historical_days} recorded days (started: {first_date})."
                )

        return {
            "days_data": days_data,
            "total_bytes": total_bytes,
            "peak_bytes": peak_bytes,
            "total_gb": total_gb,
            "avg_gb": avg_gb,"""

    new_stats = """        total_gb = total_bytes / (1024 ** 3)
        peak_gb = peak_bytes / (1024 ** 3)

        # بررسی کافی بودن تاریخچه و محاسبه دقیق تعداد روزهای مؤثر برای میانگین
        has_sufficient_history = True
        history_note = ""
        effective_days = days

        if not first_date:
            has_sufficient_history = False
            effective_days = 1
            history_note = "ثبت آمار این سرویس به تازگی آغاز شده است." if lang == "fa" else "Stats collection just started for this service."
        else:
            first_dt = datetime.strptime(first_date, "%Y-%m-%d").date()
            recorded_span_days = max(1, (today - first_dt).days + 1)
            # در صورتی که عمر سرویس کمتر از ۷ روز باشد، میانگین بر تعداد روزهای واقعی سپری‌شده تقسیم می‌شود نه عدد ۷
            effective_days = min(days, max(1, recorded_span_days))

            if recorded_span_days < days or total_historical_days < days:
                has_sufficient_history = False
                shamsi_start = format_date_persian(first_date) if lang == "fa" else first_date
                history_note = (
                    f"آمار مربوط به {to_persian_digits(total_historical_days)} روز ثبت‌شده است (شروع ثبت: {shamsi_start})."
                    if lang == "fa" else
                    f"Showing {total_historical_days} recorded days (started: {first_date})."
                )

        avg_gb = total_gb / effective_days if effective_days > 0 else 0.0
        avg_bytes = int(round(total_bytes / effective_days)) if effective_days > 0 else 0

        return {
            "days_data": days_data,
            "total_bytes": total_bytes,
            "peak_bytes": peak_bytes,
            "avg_bytes": avg_bytes,
            "effective_days": effective_days,
            "total_gb": total_gb,
            "avg_gb": avg_gb,"""

    old_caption_avg = """    total_bytes = stats.get("total_bytes", 0)
    peak_bytes = stats.get("peak_bytes", 0)
    avg_bytes = total_bytes // 7 if total_bytes > 0 else 0"""

    new_caption_avg = """    total_bytes = stats.get("total_bytes", 0)
    peak_bytes = stats.get("peak_bytes", 0)
    avg_bytes = stats.get("avg_bytes", total_bytes)"""

    if old_stats in c_norm and old_caption_avg in c_norm:
        c_norm = c_norm.replace(old_stats, new_stats, 1)
        c_norm = c_norm.replace(old_caption_avg, new_caption_avg, 1)
        if is_crlf:
            c_norm = c_norm.replace('\n', '\r\n')
        with open('daily_usage_system.py', 'w', encoding='utf-8') as f:
            f.write(c_norm)
        print("Successfully updated daily average calculation!")
        return 0
    else:
        print("Failed to find target in daily_usage_system.py")
        return 1

if __name__ == '__main__':
    sys.exit(update())

