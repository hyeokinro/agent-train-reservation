import json
import os
import sys
from datetime import datetime, timezone, timedelta

import requests

try:
    from SRT import SRT
    from SRT.passenger import Adult
    SRT_AVAILABLE = True
except ImportError:
    SRT_AVAILABLE = False

try:
    from korail2 import Korail, AdultPassenger, TrainType, ReserveOption
    KORAIL_AVAILABLE = True
except ImportError:
    KORAIL_AVAILABLE = False

DEBUG = os.environ.get("DEBUG", "") == "1"

KST = timezone(timedelta(hours=9))
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

SRT_PAY_URL = "https://etk.srail.kr"
KTX_PAY_URL = "https://www.letskorail.com"


def today_kst() -> str:
    return datetime.now(KST).strftime("%Y%m%d")


def format_date(date_str: str) -> str:
    """'20260430' → '2026.04.30 (수)'"""
    dt = datetime.strptime(date_str, "%Y%m%d")
    return f"{dt.year}.{dt.month:02d}.{dt.day:02d} ({WEEKDAYS[dt.weekday()]})"


def format_time(time_str: str) -> str:
    """'190800' → '19:08'"""
    return f"{time_str[:2]}:{time_str[2:4]}"


def notify(text: str) -> None:
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("CHAT_ID", "")
    if not token or not chat_id:
        print(f"[알림 미전송] {text}", file=sys.stderr)
        return
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
        resp.raise_for_status()
        print(f"[텔레그램] 알림 전송 완료")
    except Exception as e:
        print(f"[텔레그램 전송 실패] {e}", file=sys.stderr)


def format_success(target: dict, train_no_str: str, dep: str, arr: str,
                   dep_t: str, arr_t: str, seat_str: str,
                   pay_url: str, pay_label: str) -> str:
    return (
        f"🚄 <b>{target['type']} 좌석 예약 완료!</b>\n"
        f"📌 {target['label']}\n\n"
        f"열차: {train_no_str}\n"
        f"날짜: {format_date(target['date'])}\n"
        f"구간: {dep} {dep_t} → {arr} {arr_t}\n"
        f"인원: {target['passengers']}명\n"
        f"좌석: {seat_str}\n\n"
        f"⚠️ 미결제 시 자동 취소됩니다!\n"
        f'👉 <a href="{pay_url}">{pay_label}</a>'
    )


def format_fail(target: dict, train_no_str: str, dep: str, arr: str,
                dep_t: str, arr_t: str, error: str,
                pay_url: str, pay_label: str) -> str:
    err_line = f"\n오류: {error}" if error else ""
    return (
        f"🚄 <b>{target['type']} 좌석 발견! (예약 실패)</b>\n"
        f"📌 {target['label']}\n\n"
        f"열차: {train_no_str}\n"
        f"날짜: {format_date(target['date'])}\n"
        f"구간: {dep} {dep_t} → {arr} {arr_t}\n"
        f"인원: {target['passengers']}명{err_line}\n\n"
        f"⚡ 직접 예매를 시도해보세요!\n"
        f'👉 <a href="{pay_url}">{pay_label}</a>'
    )


def is_already_reserved_srt(existing: list, target: dict) -> bool:
    if not target["train_no"]:
        return False
    for r in existing:
        if r.dep_date == target["date"] and r.train_number == target["train_no"]:
            return True
    return False


def is_already_reserved_ktx(existing: list, target: dict) -> bool:
    if not target["train_no"]:
        return False
    for r in existing:
        if r.dep_date == target["date"] and r.train_no == target["train_no"]:
            return True
    return False


def process_srt_targets(targets: list) -> None:
    srt_id = os.environ.get("SRT_ID", "")
    srt_pw = os.environ.get("SRT_PASSWORD", "")

    if not srt_id or not srt_pw:
        notify("⚠️ SRT 환경변수(SRT_ID, SRT_PASSWORD)가 설정되지 않았습니다.")
        return

    try:
        print("[SRT] 로그인 중...")
        srt = SRT(srt_id, srt_pw)
        print("[SRT] 로그인 성공")
    except Exception as e:
        notify(f"⚠️ SRT 로그인 실패: {e}")
        return

    try:
        existing = srt.get_reservations()
        print(f"[SRT] 기존 예약 {len(existing)}건 확인")
    except Exception as e:
        print(f"[SRT] 예약 내역 조회 실패 (무시하고 진행): {e}")
        existing = []

    for t in targets:
        label = t["label"]
        try:
            if is_already_reserved_srt(existing, t):
                print(f"[SRT][skip] {label}: 이미 예약됨")
                continue

            print(f"[SRT] {label}: {t['dep']}→{t['arr']} {t['date']} {t['dep_time']} 조회 중...")
            trains = srt.search_train(t["dep"], t["arr"], t["date"], t["dep_time"])
            print(f"[SRT] {label}: 열차 {len(trains)}개 발견")

            if t["train_no"]:
                candidates = [x for x in trains if x.train_number == t["train_no"]]
            else:
                candidates = trains

            if not candidates:
                print(f"[SRT] {label}: 대상 열차 좌석 없음")
                continue

            first = candidates[0]

            if DEBUG:
                print(f"\n[DEBUG][SRT][{label}] 열차 객체:")
                print(f"  repr : {repr(first)}")
                print(f"  dir  : {dir(first)}")
                if existing:
                    print(f"\n[DEBUG][SRT] 예약 객체 (첫 번째 기존 예약):")
                    print(f"  repr : {repr(existing[0])}")
                    print(f"  dir  : {dir(existing[0])}")
                print(f"[DEBUG] 예약 건너뜀.")
                continue

            has_general = first.general_seat_available()
            has_special = first.special_seat_available()
            if has_general and has_special:
                seat_str = "✅ 일반석/특실 예약됨"
            elif has_special:
                seat_str = "✅ 특실 예약됨"
            else:
                seat_str = "✅ 일반석 예약됨"

            print(f"[SRT] {label}: 열차 {first.train_number} {first.dep_time} 예약 시도...")
            passengers = [Adult() for _ in range(t["passengers"])]

            try:
                srt.reserve(first, passengers=passengers)
                print(f"[SRT] {label}: 예약 성공!")
                msg = format_success(
                    t,
                    train_no_str=f"SRT {first.train_number}",
                    dep=first.dep_station_name,
                    arr=first.arr_station_name,
                    dep_t=format_time(first.dep_time),
                    arr_t=format_time(first.arr_time),
                    seat_str=seat_str,
                    pay_url=SRT_PAY_URL,
                    pay_label="SRT 결제 바로가기",
                )
                notify(msg)
            except Exception as e:
                print(f"[SRT] {label}: 예약 실패 - {e}")
                msg = format_fail(
                    t,
                    train_no_str=f"SRT {first.train_number}",
                    dep=first.dep_station_name,
                    arr=first.arr_station_name,
                    dep_t=format_time(first.dep_time),
                    arr_t=format_time(first.arr_time),
                    error=str(e),
                    pay_url=SRT_PAY_URL,
                    pay_label="SRT 예매 바로가기",
                )
                notify(msg)

        except Exception as e:
            print(f"[SRT] {label}: 처리 중 에러 - {e}")
            notify(f"⚠️ SRT [{label}] 처리 중 에러: {e}")


def process_ktx_targets(targets: list) -> None:
    ktx_id = os.environ.get("KTX_ID", "")
    ktx_pw = os.environ.get("KTX_PASSWORD", "")

    if not ktx_id or not ktx_pw:
        notify("⚠️ KTX 환경변수(KTX_ID, KTX_PASSWORD)가 설정되지 않았습니다.")
        return

    try:
        print("[KTX] 로그인 중...")
        korail = Korail(ktx_id, ktx_pw)
        print("[KTX] 로그인 성공")
    except Exception as e:
        notify(f"⚠️ KTX 로그인 실패: {e}")
        return

    try:
        existing = korail.reservations()
        print(f"[KTX] 기존 예약 {len(existing)}건 확인")
    except Exception as e:
        print(f"[KTX] 예약 내역 조회 실패 (무시하고 진행): {e}")
        existing = []

    for t in targets:
        label = t["label"]
        try:
            if is_already_reserved_ktx(existing, t):
                print(f"[KTX][skip] {label}: 이미 예약됨")
                continue

            print(f"[KTX] {label}: {t['dep']}→{t['arr']} {t['date']} {t['dep_time']} 조회 중...")
            passengers_obj = [AdultPassenger(t["passengers"])]
            trains = korail.search_train(
                t["dep"], t["arr"], t["date"], t["dep_time"],
                train_type=TrainType.KTX,
                passengers=passengers_obj,
            )
            print(f"[KTX] {label}: 열차 {len(trains)}개 발견")

            if t["train_no"]:
                candidates = [x for x in trains if x.train_no == t["train_no"]]
            else:
                candidates = trains

            if not candidates:
                print(f"[KTX] {label}: 대상 열차 좌석 없음")
                continue

            first = candidates[0]

            if DEBUG:
                print(f"\n[DEBUG][KTX][{label}] 열차 객체:")
                print(f"  train_type      : {getattr(first, 'train_type', 'N/A')!r}")
                print(f"  train_type_name : {getattr(first, 'train_type_name', 'N/A')!r}")
                print(f"  repr : {repr(first)}")
                print(f"  dir  : {dir(first)}")
                if existing:
                    print(f"\n[DEBUG][KTX] 예약 객체 (첫 번째 기존 예약):")
                    print(f"  repr : {repr(existing[0])}")
                    print(f"  dir  : {dir(existing[0])}")
                print(f"[DEBUG] 예약 건너뜀.")
                continue

            has_general = first.has_general_seat()
            has_special = first.has_special_seat()
            if has_general and has_special:
                seat_str = "✅ 일반석/특실 예약됨"
            elif has_special:
                seat_str = "✅ 특실 예약됨"
            else:
                seat_str = "✅ 일반석 예약됨"

            print(f"[KTX] {label}: 열차 {first.train_no} {first.dep_time} 예약 시도...")

            try:
                result = korail.reserve(first, passengers=passengers_obj)
                if result is None:
                    raise RuntimeError("예약 결과가 없습니다 (None 반환)")
                print(f"[KTX] {label}: 예약 성공!")
                msg = format_success(
                    t,
                    train_no_str=f"KTX {first.train_no}",
                    dep=first.dep_name,
                    arr=first.arr_name,
                    dep_t=format_time(first.dep_time),
                    arr_t=format_time(first.arr_time),
                    seat_str=seat_str,
                    pay_url=KTX_PAY_URL,
                    pay_label="코레일 결제 바로가기",
                )
                notify(msg)
            except Exception as e:
                print(f"[KTX] {label}: 예약 실패 - {e}")
                msg = format_fail(
                    t,
                    train_no_str=f"KTX {first.train_no}",
                    dep=first.dep_name,
                    arr=first.arr_name,
                    dep_t=format_time(first.dep_time),
                    arr_t=format_time(first.arr_time),
                    error=str(e),
                    pay_url=KTX_PAY_URL,
                    pay_label="코레일 예매 바로가기",
                )
                notify(msg)

        except Exception as e:
            print(f"[KTX] {label}: 처리 중 에러 - {e}")
            notify(f"⚠️ KTX [{label}] 처리 중 에러: {e}")


def main() -> None:
    if not os.environ.get("TELEGRAM_TOKEN") or not os.environ.get("CHAT_ID"):
        print(
            "⚠️  TELEGRAM_TOKEN 또는 CHAT_ID가 설정되지 않았습니다. 텔레그램 알림이 비활성화됩니다.",
            file=sys.stderr,
        )

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    all_targets = config.get("targets", [])

    if not all_targets:
        print("targets가 비어있습니다. 종료합니다.")
        return

    today = today_kst()
    valid_targets = []
    for t in all_targets:
        if t["date"] < today:
            print(f"[만료됨] {t['label']} ({t['date']})")
        else:
            valid_targets.append(t)

    if not valid_targets:
        print("유효한 감시 대상이 없습니다. 종료합니다.")
        return

    srt_targets = [t for t in valid_targets if t["type"].upper() == "SRT"]
    ktx_targets = [t for t in valid_targets if t["type"].upper() == "KTX"]

    if srt_targets:
        if not SRT_AVAILABLE:
            notify("⚠️ SRTrain 패키지가 설치되지 않았습니다. pip install SRTrain")
        else:
            process_srt_targets(srt_targets)

    if ktx_targets:
        if not KORAIL_AVAILABLE:
            notify("⚠️ korail2 패키지가 설치되지 않았습니다. pip install korail2 pycryptodome")
        else:
            process_ktx_targets(ktx_targets)


if __name__ == "__main__":
    main()
