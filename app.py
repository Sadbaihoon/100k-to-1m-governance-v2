"""Personal investment-governance web app.

Run locally with: streamlit run app.py
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st
import yfinance as yf

from storage import get_decisions, initialize_database, save_decision


st.set_page_config(
    page_title="100K → 1M Governance",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
        .block-container {max-width: 1280px; padding-top: 2.25rem; padding-bottom: 3rem;}
        [data-testid="stMetricValue"] {font-size: 1.55rem;}
        .hero {padding: 1.6rem 1.8rem; border-radius: 1rem;
               background: linear-gradient(120deg, #0f2e35, #176b5b); color: #ffffff;
               margin-bottom: 1.5rem;}
        .hero h1 {margin: 0 0 .35rem 0; color: #ffffff; font-size: 2rem;}
        .hero p {margin: 0; opacity: .92;}
        .step-label {color: #176b5b; font-weight: 700; letter-spacing: .04em;}
    </style>
    """,
    unsafe_allow_html=True,
)


def as_number(value: object) -> float | None:
    """Return a safe float for values returned by Yahoo Finance."""
    return float(value) if isinstance(value, (int, float)) else None


def money(value: float | None) -> str:
    return f"${value:,.2f}" if value is not None else "ไม่พบข้อมูล"


def multiple(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "ไม่พบข้อมูล"


@st.cache_data(ttl=300, show_spinner=False)
def fetch_stock_data(ticker: str) -> tuple[dict[str, float | None], pd.DataFrame, str | None]:
    """Fetch market data with enough history for long EMA periods."""
    try:
        stock = yf.Ticker(ticker)
        # Use all available history so EMA 200 on monthly data can be calculated
        # as accurately as Yahoo Finance's available history allows.
        history = stock.history(period="max", auto_adjust=False)
        if history.empty:
            return {}, history, "ไม่พบข้อมูลราคาย้อนหลังสำหรับ Ticker นี้"

        info = stock.info
        close_price = float(history["Close"].iloc[-1])
        live_price = as_number(info.get("currentPrice")) or as_number(info.get("regularMarketPrice"))
        snapshot = {
            "current_price": live_price or close_price,
            "trailing_pe": as_number(info.get("trailingPE")),
            "price_to_book": as_number(info.get("priceToBook")),
            "free_cash_flow": as_number(info.get("freeCashflow")),
        }
        return snapshot, history, None
    except Exception as exc:  # Yahoo can reject requests or lack coverage for a symbol.
        return {}, pd.DataFrame(), str(exc)


def prepare_ema_chart(history: pd.DataFrame, timeframe: str, periods: list[int]) -> pd.DataFrame:
    """Resample price data to the selected timeframe and calculate EMA lines."""
    if history.empty:
        return pd.DataFrame()

    close = history["Close"].dropna()

    if timeframe == "วัน (Daily)":
        series = close
        # Keep the daily chart readable while retaining enough history for EMA 200.
        display_series = series.last("2Y")
    elif timeframe == "สัปดาห์ (Weekly)":
        series = close.resample("W-FRI").last().dropna()
        display_series = series.last("5Y")
    else:
        series = close.resample("MS").last().dropna()
        display_series = series.last("20Y")

    chart = pd.DataFrame({"ราคา": display_series})
    for period in periods:
        ema = series.ewm(span=period, adjust=False, min_periods=period).mean()
        chart[f"EMA {period}"] = ema.reindex(display_series.index)

    return chart


def cooling_key(ticker: str, minutes: int) -> str:
    return f"cooling_started_{ticker}_{minutes}"


def cooling_status(ticker: str, minutes: int) -> tuple[bool, str]:
    """Return whether a self-imposed waiting period has elapsed."""
    started_at = st.session_state.get(cooling_key(ticker, minutes))
    if not started_at:
        return False, "ยังไม่ได้เริ่มช่วงพักใจ"

    finish_at = started_at + timedelta(minutes=minutes)
    remaining = finish_at - datetime.now(timezone.utc)
    if remaining.total_seconds() <= 0:
        return True, "ผ่านช่วงพักใจแล้ว"

    minutes_left, seconds_left = divmod(int(remaining.total_seconds()), 60)
    return False, f"เหลืออีก {minutes_left} นาที {seconds_left} วินาที"


def get_risk_reward(entry: float, stop: float, target: float) -> tuple[float, float, float]:
    risk = entry - stop
    reward = target - entry
    ratio = reward / risk if risk > 0 else 0.0
    return risk, reward, ratio


def show_hero() -> None:
    st.markdown(
        """
        <div class="hero">
            <h1>🏢 บริษัท 100K → 1M</h1>
            <p>Investment Governance สำหรับการตัดสินใจอย่างมีวินัย — Smarter Process · Better Decision · Bigger Future</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def show_analysis() -> None:
    show_hero()
    st.caption("ข้อมูลตลาดใช้ประกอบการวิเคราะห์เท่านั้น ไม่ใช่คำแนะนำการลงทุน")

    st.sidebar.header("การวิเคราะห์ครั้งนี้")
    ticker = st.sidebar.text_input("Ticker", value=st.session_state.get("ticker", "KHC"), key="ticker").upper().strip()
    news_headline = st.sidebar.text_area(
        "หัวข้อข่าวที่พบ",
        value="บริษัทประกาศจ่ายปันผลเพิ่มขึ้น",
        key="news_headline",
    )
    news_source = st.sidebar.text_input("แหล่งที่มาของข่าว", value="SEC Filing / Official IR", key="news_source")
    if st.sidebar.button("↻ ดึงข้อมูลตลาดใหม่", use_container_width=True):
        fetch_stock_data.clear()
        st.rerun()

    st.markdown('<p class="step-label">ขั้นที่ 1–2</p>', unsafe_allow_html=True)
    st.subheader("ตรวจข่าวและจังหวะตลาด")
    news_col, source_col, event_col = st.columns((1.5, 1.1, 0.9))
    with news_col:
        st.info(f"**หัวข้อข่าว**\n\n{news_headline or 'ยังไม่ได้ระบุ'}")
    with source_col:
        st.info(f"**แหล่งที่มา**\n\n{news_source or 'ยังไม่ได้ระบุ'}")
    with event_col:
        has_event = st.checkbox("มี Event สำคัญใกล้ ๆ", help="เช่น Fed, Earnings, CPI หรือข่าวที่อาจทำให้ราคาแกว่งแรง")
        if has_event:
            st.warning("รอให้ Event ผ่านก่อนเปิดสถานะ")

    st.markdown('<p class="step-label">ขั้นที่ 3</p>', unsafe_allow_html=True)
    st.subheader("ยืนยันหลักฐาน")
    is_verified = st.checkbox(
        "ฉันตรวจสอบข่าวจากต้นฉบับแล้ว (SEC filing / ข่าวประชาสัมพันธ์ของบริษัท)",
    )
    if not is_verified:
        st.error("ข่าวที่ยังไม่มีหลักฐาน ไม่ควรใช้เป็นเหตุผลในการลงทุน")

    st.markdown('<p class="step-label">ขั้นที่ 4</p>', unsafe_allow_html=True)
    st.subheader("ข้อมูลพื้นฐานและราคา")
    current_price: float | None = None
    if ticker:
        with st.spinner(f"กำลังตรวจข้อมูล {ticker}..."):
            snapshot, history, error = fetch_stock_data(ticker)
        if error:
            st.warning(f"ยังดึงข้อมูล {ticker} ไม่ได้: {error}")
        else:
            current_price = snapshot["current_price"]
            metric_1, metric_2, metric_3, metric_4 = st.columns(4)
            metric_1.metric("ราคาล่าสุด", money(current_price))
            metric_2.metric("P/E", multiple(snapshot["trailing_pe"]))
            metric_3.metric("P/B", multiple(snapshot["price_to_book"]))
            fcf = snapshot["free_cash_flow"]
            metric_4.metric("Free cash flow", f"${fcf:,.0f}" if fcf is not None else "ไม่พบข้อมูล")

            st.markdown("#### 📈 EMA — เลือกกรอบเวลาและเส้นที่ต้องการ")
            ema_col1, ema_col2 = st.columns((1, 2))
            with ema_col1:
                ema_timeframe = st.selectbox(
                    "กรอบเวลา EMA",
                    ["วัน (Daily)", "สัปดาห์ (Weekly)", "เดือน (Monthly)"],
                    index=0,
                    key=f"ema_timeframe_{ticker}",
                )
            with ema_col2:
                ema_periods = st.multiselect(
                    "เส้น EMA",
                    options=[20, 50, 100, 200],
                    default=[20, 50, 100, 200],
                    format_func=lambda value: f"EMA {value}",
                    key=f"ema_periods_{ticker}_{ema_timeframe}",
                )

            ema_chart = prepare_ema_chart(history, ema_timeframe, ema_periods)

            if ema_chart.empty:
                st.warning("ยังไม่มีข้อมูลเพียงพอสำหรับแสดงกราฟ EMA")
            else:
                st.line_chart(
                    ema_chart,
                    x_label="วันที่",
                    y_label="ราคา (USD)",
                    use_container_width=True,
                )

                latest = ema_chart.iloc[-1]
                status_parts = []
                for period in ema_periods:
                    ema_value = latest.get(f"EMA {period}")
                    if pd.notna(ema_value):
                        relation = "เหนือ" if current_price >= float(ema_value) else "ต่ำกว่า"
                        status_parts.append(f"EMA {period}: {relation} (${float(ema_value):,.2f})")

                if status_parts:
                    st.caption(
                        f"ราคาปัจจุบัน {money(current_price)} · " + " · ".join(status_parts)
                    )
    else:
        st.info("ระบุ Ticker เพื่อดึงข้อมูลราคาหุ้น")

    st.markdown('<p class="step-label">ขั้นที่ 5</p>', unsafe_allow_html=True)
    st.subheader("Cooling-off period — กัน FOMO")
    cooling_col, cooling_status_col = st.columns((1, 2))
    with cooling_col:
        cooling_minutes = st.selectbox("ระยะเวลาพักใจ", options=[30, 60], format_func=lambda value: f"{value} นาที")
        if st.button("เริ่มช่วงพักใจ", use_container_width=True):
            st.session_state[cooling_key(ticker, cooling_minutes)] = datetime.now(timezone.utc)
            st.rerun()
    with cooling_status_col:
        cooling_done, cooling_message = cooling_status(ticker, cooling_minutes)
        if cooling_done:
            st.success(f"✅ {cooling_message}")
        else:
            st.info(f"⏱️ {cooling_message}")
            st.caption("สถานะจะอัปเดตเมื่อมีการใช้งานหน้าเว็บครั้งถัดไป")

    st.markdown('<p class="step-label">ขั้นที่ 6</p>', unsafe_allow_html=True)
    st.subheader("วางแผนความเสี่ยง")
    price_default = current_price or 0.0
    risk_col, result_col = st.columns((1.2, 0.8))
    with risk_col:
        entry_price = st.number_input(
            "ราคาแผนเข้าซื้อ", min_value=0.0, value=price_default, step=0.01, key=f"entry_{ticker}"
        )
        stop_loss = st.number_input(
            "จุดตัดขาดทุน", min_value=0.0, value=round(entry_price * 0.95, 2), step=0.01, key=f"stop_{ticker}"
        )
        target_price = st.number_input(
            "เป้าหมายทำกำไร", min_value=0.0, value=round(entry_price * 1.15, 2), step=0.01, key=f"target_{ticker}"
        )
    risk, reward, rr_ratio = get_risk_reward(entry_price, stop_loss, target_price)
    with result_col:
        st.metric("Risk / Reward", f"1 : {rr_ratio:.2f}")
        st.write(f"ขาดทุนตามแผน: **${risk:,.2f}**")
        st.write(f"กำไรตามแผน: **${reward:,.2f}**")
        if risk <= 0 or reward <= 0:
            st.error("กำหนดให้ Stop Loss ต่ำกว่า Entry และ Target สูงกว่า Entry")
        elif rr_ratio >= 2:
            st.success("ผ่านเกณฑ์ Risk/Reward ขั้นต่ำ 1:2")
        else:
            st.error("Risk/Reward ยังต่ำกว่าเกณฑ์ 1:2")

    st.markdown('<p class="step-label">ขั้นที่ 7</p>', unsafe_allow_html=True)
    st.subheader("CEO decision")
    thesis_clear = st.checkbox("Thesis ชัดเจน และเหตุผลยังสอดคล้องกับข้อมูล")
    no_emotion = st.checkbox("ไม่ได้ตัดสินใจด้วยความกลัว ความโลภ หรือ FOMO")
    notes = st.text_area("บันทึกเหตุผล / สิ่งที่ต้องติดตาม", placeholder="เช่น รอผลประกอบการไตรมาสหน้า หรือเฝ้าดูแนวรับ...")

    ready_to_execute = all((
        not has_event,
        is_verified,
        cooling_done,
        risk > 0,
        reward > 0,
        rr_ratio >= 2,
        thesis_clear,
        no_emotion,
    ))
    decision = "EXECUTE" if ready_to_execute else "WAIT & WATCH"
    if ready_to_execute:
        st.success("👑 **อนุมัติเปิดสถานะตามแผน — EXECUTE**")
    else:
        st.warning("🚦 **WAIT & WATCH** — ยังมีอย่างน้อยหนึ่งเงื่อนไขที่ไม่ผ่าน")

    if st.button("บันทึกการตัดสินใจ", type="primary", use_container_width=True):
        decision_id = save_decision(
            ticker=ticker,
            news_headline=news_headline,
            news_source=news_source,
            has_event=has_event,
            is_verified=is_verified,
            current_price=current_price,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=target_price,
            risk_reward=rr_ratio,
            cooling_done=cooling_done,
            thesis_clear=thesis_clear,
            no_emotion=no_emotion,
            decision=decision,
            notes=notes,
        )
        st.success(f"บันทึกการวิเคราะห์ #{decision_id} เรียบร้อยแล้ว")


def show_journal() -> None:
    show_hero()
    st.subheader("📚 สมุดบันทึกการตัดสินใจ")
    st.caption("เก็บในเครื่องของคุณ เพื่อย้อนดูว่ากระบวนการตัดสินใจในอดีตมีคุณภาพแค่ไหน")
    decisions = get_decisions()
    if not decisions:
        st.info("ยังไม่มีรายการบันทึก เริ่มจากหน้า “วิเคราะห์หุ้น” ได้เลย")
        return

    journal = pd.DataFrame(decisions)
    display_columns = [
        "created_at", "ticker", "decision", "current_price", "entry_price", "stop_loss",
        "target_price", "risk_reward", "is_verified", "cooling_done", "notes",
    ]
    journal_view = journal[display_columns].rename(
        columns={
            "created_at": "บันทึกเมื่อ (UTC)", "ticker": "Ticker", "decision": "ผลตัดสินใจ",
            "current_price": "ราคาล่าสุด", "entry_price": "ราคาเข้า", "stop_loss": "Stop loss",
            "target_price": "Target", "risk_reward": "R/R", "is_verified": "ยืนยันข่าว",
            "cooling_done": "ผ่านพักใจ", "notes": "บันทึก",
        }
    )
    st.dataframe(journal_view, use_container_width=True, hide_index=True)
    st.download_button(
        "ดาวน์โหลดประวัติเป็น CSV",
        data=journal.to_csv(index=False).encode("utf-8-sig"),
        file_name="investment-governance-journal.csv",
        mime="text/csv",
    )


def show_about() -> None:
    show_hero()
    st.subheader("วิธีใช้ระบบ")
    st.markdown(
        """
1. กรอก Ticker และรายละเอียดข่าวจากแหล่งที่เชื่อถือได้
2. ตรวจ Event สำคัญ และยืนยันหลักฐานต้นฉบับ
3. เริ่มช่วงพักใจ 30 หรือ 60 นาที ก่อนทำแผนราคาเข้า จุดตัดขาดทุน และเป้าหมาย
4. บันทึกผล ไม่ว่าจะเป็น EXECUTE หรือ WAIT & WATCH เพื่อทบทวนกระบวนการในอนาคต

ข้อมูลจาก Yahoo Finance อาจล่าช้าหรือไม่ครบถ้วน ควรตรวจสอบกับแหล่งข้อมูลทางการอีกครั้งก่อนลงทุนจริง
        """
    )
    st.subheader("การต่อยอดในอนาคต")
    st.write("ข้อมูลถูกแยกไว้ในชั้นจัดเก็บข้อมูลแล้ว จึงเปลี่ยนจากบันทึกในเครื่องเป็นบัญชีผู้ใช้และฐานข้อมูลกลางได้ โดยไม่ต้องรื้อหน้าวิเคราะห์ใหม่")


initialize_database()
st.sidebar.title("100K → 1M")
page = st.sidebar.radio("เมนู", ["วิเคราะห์หุ้น", "สมุดบันทึก", "วิธีใช้"], label_visibility="collapsed")

if page == "วิเคราะห์หุ้น":
    show_analysis()
elif page == "สมุดบันทึก":
    show_journal()
else:
    show_about()
