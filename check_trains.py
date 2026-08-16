import json
import os
import sys
from datetime import datetime, timezone, timedelta

import requests

try:
    from SRT import SRT
    from SRT.passenger import Adult, Child, Passenger
    from SRT.seat_type import SeatType

    class Infant(Passenger):
        def __init__(self, count=1):
            super().__init__()
            super().__init_internal__("유아", "6", count)

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

SEAT_TYPE_MAP = {
    "general_first": SeatType.GENERAL_FIRST,
    "general_only": SeatType.GENERAL_ONLY,
    "special_first": SeatType.SPECIAL_FIRST,
    "special_only": SeatType.SPECIAL_ONLY,
} if SRT_AVAILABLE else {}

SEAT_TYPE_LABEL = {
    "general_first": "일반실 우선",
    "general_only": "일반실만",
    "special_first": "특실 우선",
    "special_only": "특실만",
}


def safe_err(e: BaseException) -> str:
    """일부 라이브러리(예: SRTNetFunnelError)는 __str__이 비정상적으로 동작해서
    f-string에 그대로 넣으면 TypeError가 또 발생함. 안전하게 문자열화."""
    try:
        s = str(e)
        if isinstance(s, str):
            return s
    except Exception:
        pass
    try:
        return f"{type(e).__name__}: {e!r}"
    except Exception:
        return f"{type(e).__name__}: <unprintable>"


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
        print(f"[텔레그램 전송 실패] {safe_err(e)}", file=sys.stderr)


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


def format_standby(target: dict, train_no_str: str, dep: str, arr: str,
                   dep_t: str, arr_t: str,
                   pay_url: str, pay_label: str) -> str:
    return (
        f"🚄 <b>{target['type']} 예약대기 신청 완료!</b>\n"
        f"📌 {target['label']}\n\n"
        f"열차: {train_no_str}\n"
        f"날짜: {format_date(target['date'])}\n"
        f"구간: {dep} {dep_t} → {arr} {arr_t}\n"
        f"인원: {target['passengers']}명\n\n"
        f"💡 자리 나면 SMS로 알려옵니다.\n"
        f"⚠️ 좌석 확보 후 일정 시간 내 결제해야 합니다.\n"
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
        notify(f"⚠️ SRT 로그인 실패: {safe_err(e)}")
        return

    try:
        existing = srt.get_reservations()
        print(f"[SRT] 기존 예약 {len(existing)}건 확인")
    except Exception as e:
        print(f"[SRT] 예약 내역 조회 실패 (무시하고 진행): {safe_err(e)}")
        existing = []

    for t in targets:
        label = t["label"]
        try:
            if is_already_reserved_srt(existing, t):
                print(f"[SRT][skip] {label}: 이미 예약/대기 중")
                continue

            print(f"[SRT] {label}: {t['dep']}→{t['arr']} {t['date']} {t['dep_time']} 조회 중...")
            trains = srt.search_train(
                t["dep"], t["arr"], t["date"], t["dep_time"],
                available_only=False,
            )
            print(f"[SRT] {label}: 전체 열차 {len(trains)}개 (매진 포함)")

            if t["train_no"]:
                candidates = [x for x in trains if x.train_number == t["train_no"]]
                if not candidates:
                    print(f"[SRT] {label}: SRT {t['train_no']} 운행편 없음")
                    continue
            else:
                candidates = trains
                if not candidates:
                    print(f"[SRT] {label}: 해당 시간 이후 운행 열차 없음")
                    continue

            if DEBUG:
                first_dbg = candidates[0]
                print(f"\n[DEBUG][SRT][{label}] 열차 객체:")
                print(f"  repr : {repr(first_dbg)}")
                print(f"  dir  : {dir(first_dbg)}")
                if existing:
                    print(f"\n[DEBUG][SRT] 예약 객체 (첫 번째 기존 예약):")
                    print(f"  repr : {repr(existing[0])}")
                    print(f"  dir  : {dir(existing[0])}")
                print(f"[DEBUG] 예약 건너뜀.")
                continue

            adults = t.get("adults", t["passengers"])
            children = t.get("children", 0)
            infants = t.get("infants", 0)
            passengers = [Adult() for _ in range(adults)] + [Child() for _ in range(children + infants)]
            seat_type_key = t.get("seat_type", "general_first")
            seat_type = SEAT_TYPE_MAP.get(seat_type_key, SeatType.GENERAL_FIRST)

            # 1) 좌석 있는 열차 우선 — 정상 예약
            seated = [x for x in candidates if x.seat_available()]
            if seated:
                first = seated[0]
                has_general = first.general_seat_available()
                has_special = first.special_seat_available()
                if has_general and has_special:
                    seat_str = "✅ 일반석/특실 예약됨"
                elif has_special:
                    seat_str = "✅ 특실 예약됨"
                else:
                    seat_str = "✅ 일반석 예약됨"

                print(f"[SRT] {label}: 열차 {first.train_number} 좌석 있음 → 예약 시도...")
                try:
                    srt.reserve(first, passengers=passengers, special_seat=seat_type)
                    print(f"[SRT] {label}: 예약 성공!")
                    notify(format_success(
                        t,
                        train_no_str=f"SRT {first.train_number}",
                        dep=first.dep_station_name,
                        arr=first.arr_station_name,
                        dep_t=format_time(first.dep_time),
                        arr_t=format_time(first.arr_time),
                        seat_str=seat_str,
                        pay_url=SRT_PAY_URL,
                        pay_label="SRT 결제 바로가기",
                    ))
                except Exception as e:
                    print(f"[SRT] {label}: 예약 실패 - {safe_err(e)}")
                    notify(format_fail(
                        t,
                        train_no_str=f"SRT {first.train_number}",
                        dep=first.dep_station_name,
                        arr=first.arr_station_name,
                        dep_t=format_time(first.dep_time),
                        arr_t=format_time(first.arr_time),
                        error=safe_err(e),
                        pay_url=SRT_PAY_URL,
                        pay_label="SRT 예매 바로가기",
                    ))
                continue

            # 2) 매진 → 예약대기 가능한 열차 찾기
            standby_capable = [x for x in candidates if x.reserve_standby_available()]
            if not standby_capable:
                print(f"[SRT] {label}: 전부 매진 + 예약대기 불가 — 다음 사이클 대기")
                continue

            first = standby_capable[0]
            print(f"[SRT] {label}: 열차 {first.train_number} 매진 → 예약대기 신청...")
            try:
                standby_rsv = srt.reserve_standby(first, passengers=passengers, special_seat=seat_type)
                # SMS 알림 + 좌석등급 변경 동의 설정 (실패해도 대기는 유지)
                try:
                    srt.reserve_standby_option_settings(standby_rsv, True, True)
                    print(f"[SRT] {label}: 대기 옵션 설정 완료 (SMS + 등급변경)")
                except Exception as opt_e:
                    print(f"[SRT] {label}: 대기 옵션 설정 실패 (무시): {safe_err(opt_e)}")
                print(f"[SRT] {label}: 예약대기 신청 성공!")
                notify(format_standby(
                    t,
                    train_no_str=f"SRT {first.train_number}",
                    dep=first.dep_station_name,
                    arr=first.arr_station_name,
                    dep_t=format_time(first.dep_time),
                    arr_t=format_time(first.arr_time),
                    pay_url=SRT_PAY_URL,
                    pay_label="SRT 예매 바로가기",
                ))
            except Exception as e:
                print(f"[SRT] {label}: 예약대기 실패 - {safe_err(e)}")
                notify(format_fail(
                    t,
                    train_no_str=f"SRT {first.train_number}",
                    dep=first.dep_station_name,
                    arr=first.arr_station_name,
                    dep_t=format_time(first.dep_time),
                    arr_t=format_time(first.arr_time),
                    error=f"예약대기 실패: {safe_err(e)}",
                    pay_url=SRT_PAY_URL,
                    pay_label="SRT 예매 바로가기",
                ))

        except Exception as e:
            print(f"[SRT] {label}: 처리 중 에러 - {safe_err(e)}")
            notify(f"⚠️ SRT [{label}] 처리 중 에러: {safe_err(e)}")


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
        notify(f"⚠️ KTX 로그인 실패: {safe_err(e)}")
        return

    try:
        existing = korail.reservations()
        print(f"[KTX] 기존 예약 {len(existing)}건 확인")
    except Exception as e:
        print(f"[KTX] 예약 내역 조회 실패 (무시하고 진행): {safe_err(e)}")
        existing = []

    for t in targets:
        label = t["label"]
        try:
            if is_already_reserved_ktx(existing, t):
                print(f"[KTX][skip] {label}: 이미 예약/대기 중")
                continue

            print(f"[KTX] {label}: {t['dep']}→{t['arr']} {t['date']} {t['dep_time']} 조회 중...")
            passengers_obj = [AdultPassenger(t["passengers"])]
            trains = korail.search_train(
                t["dep"], t["arr"], t["date"], t["dep_time"],
                train_type=TrainType.KTX,
                passengers=passengers_obj,
                include_no_seats=True,
            )
            print(f"[KTX] {label}: 전체 열차 {len(trains)}개 (매진 포함)")

            if t["train_no"]:
                candidates = [x for x in trains if x.train_no == t["train_no"]]
                if not candidates:
                    print(f"[KTX] {label}: KTX {t['train_no']} 운행편 없음")
                    continue
            else:
                candidates = trains
                if not candidates:
                    print(f"[KTX] {label}: 해당 시간 이후 운행 열차 없음")
                    continue

            if DEBUG:
                first_dbg = candidates[0]
                print(f"\n[DEBUG][KTX][{label}] 열차 객체:")
                print(f"  train_type      : {getattr(first_dbg, 'train_type', 'N/A')!r}")
                print(f"  train_type_name : {getattr(first_dbg, 'train_type_name', 'N/A')!r}")
                print(f"  repr : {repr(first_dbg)}")
                print(f"  dir  : {dir(first_dbg)}")
                if existing:
                    print(f"\n[DEBUG][KTX] 예약 객체 (첫 번째 기존 예약):")
                    print(f"  repr : {repr(existing[0])}")
                    print(f"  dir  : {dir(existing[0])}")
                print(f"[DEBUG] 예약 건너뜀.")
                continue

            # 1) 좌석 있는 열차 우선 — 정상 예약
            seated = [x for x in candidates if x.has_seat()]
            if seated:
                first = seated[0]
                has_general = first.has_general_seat()
                has_special = first.has_special_seat()
                if has_general and has_special:
                    seat_str = "✅ 일반석/특실 예약됨"
                elif has_special:
                    seat_str = "✅ 특실 예약됨"
                else:
                    seat_str = "✅ 일반석 예약됨"

                print(f"[KTX] {label}: 열차 {first.train_no} 좌석 있음 → 예약 시도...")
                try:
                    result = korail.reserve(first, passengers=passengers_obj)
                    if result is None:
                        raise RuntimeError("예약 결과가 없습니다 (None 반환)")
                    print(f"[KTX] {label}: 예약 성공!")
                    notify(format_success(
                        t,
                        train_no_str=f"KTX {first.train_no}",
                        dep=first.dep_name,
                        arr=first.arr_name,
                        dep_t=format_time(first.dep_time),
                        arr_t=format_time(first.arr_time),
                        seat_str=seat_str,
                        pay_url=KTX_PAY_URL,
                        pay_label="코레일 결제 바로가기",
                    ))
                except Exception as e:
                    print(f"[KTX] {label}: 예약 실패 - {safe_err(e)}")
                    notify(format_fail(
                        t,
                        train_no_str=f"KTX {first.train_no}",
                        dep=first.dep_name,
                        arr=first.arr_name,
                        dep_t=format_time(first.dep_time),
                        arr_t=format_time(first.arr_time),
                        error=safe_err(e),
                        pay_url=KTX_PAY_URL,
                        pay_label="코레일 예매 바로가기",
                    ))
                continue

            # 2) 매진 → 예약대기 시도 (try_waiting=True)
            first = candidates[0]
            print(f"[KTX] {label}: 열차 {first.train_no} 매진 → 예약대기 신청...")
            try:
                result = korail.reserve(
                    first, passengers=passengers_obj, try_waiting=True,
                )
                if result is None:
                    raise RuntimeError("예약대기 결과가 없습니다 (None 반환)")
                print(f"[KTX] {label}: 예약대기 신청 성공!")
                notify(format_standby(
                    t,
                    train_no_str=f"KTX {first.train_no}",
                    dep=first.dep_name,
                    arr=first.arr_name,
                    dep_t=format_time(first.dep_time),
                    arr_t=format_time(first.arr_time),
                    pay_url=KTX_PAY_URL,
                    pay_label="코레일 예매 바로가기",
                ))
            except Exception as e:
                print(f"[KTX] {label}: 예약대기 실패 - {safe_err(e)}")
                notify(format_fail(
                    t,
                    train_no_str=f"KTX {first.train_no}",
                    dep=first.dep_name,
                    arr=first.arr_name,
                    dep_t=format_time(first.dep_time),
                    arr_t=format_time(first.arr_time),
                    error=f"예약대기 실패: {safe_err(e)}",
                    pay_url=KTX_PAY_URL,
                    pay_label="코레일 예매 바로가기",
                ))

        except Exception as e:
            print(f"[KTX] {label}: 처리 중 에러 - {safe_err(e)}")
            notify(f"⚠️ KTX [{label}] 처리 중 에러: {safe_err(e)}")


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
