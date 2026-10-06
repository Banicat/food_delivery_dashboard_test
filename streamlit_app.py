import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="사용자 행동 탐색 대시보드", layout="wide")
st.title("사용자 행동 탐색 대시보드")
st.caption("주별 세션 퍼널 | 플랫폼 · 유입 경로별 | 2025.07 ~ 2026.06")

# ------------------------------------------------------------
# 0. 필요한 데이터만 추출 — 쓸 테이블과 컬럼만 메모리 DB에 올리고, 정제 테이블 events를 처음 한 번만 만듦
# ------------------------------------------------------------
DATA_DIR = "data"                         # 원본 CSV를 넣어 둔 폴더
NEEDED = {                                 # 이번 대시보드에 필요한 테이블과 컬럼
    "app_events": ["event_id", "event_datetime", "customer_id", "session_id",
                   "event_name", "platform", "traffic_source"],
}

@st.cache_resource
def get_db():                             # 필요한 컬럼만 메모리 DB에 올리고, 정제 테이블 events를 만듦 (처음 한 번만)
    con = sqlite3.connect(":memory:", check_same_thread=False)
    for name, cols in NEEDED.items():
        pd.read_csv(f"{DATA_DIR}/{name}.csv", usecols=cols).to_sql(name, con, index=False)
    # 5주차 제외 규칙: QA 계정 제외 · 중복 이벤트 제거
    con.execute("""
        CREATE TABLE events AS
        SELECT event_id, event_datetime, customer_id, session_id, event_name, platform, traffic_source
          FROM (SELECT *,
                       ROW_NUMBER() OVER (PARTITION BY session_id, event_datetime, event_name
                                          ORDER BY event_id) AS dup
                  FROM app_events
                 WHERE customer_id NOT LIKE 'QA%')
         WHERE dup = 1
    """)
    return con

# ------------------------------------------------------------
# 1. 데이터 준비 — 정제된 events 테이블을 SQL로 집계
# ------------------------------------------------------------
@st.cache_data
def query(sql):                           # SQL을 실행해 표로 돌려줌
    return pd.read_sql(sql, get_db())

# 주 × 플랫폼 × 유입 경로별 세션 퍼널
SQL_WEEKLY_FUNNEL = """
WITH s AS (                                 -- 세션의 첫 이벤트로 플랫폼 · 유입 경로 · 주 정하기
    SELECT session_id, platform, traffic_source,
           DATE(MIN(event_datetime), 'weekday 0', '-6 days') AS 주시작일
      FROM events
     GROUP BY session_id
)
SELECT s.주시작일,
       s.platform       AS 플랫폼,
       s.traffic_source AS 유입경로,
       COUNT(DISTINCT e.session_id)                                                              AS 세션수,
       COUNT(DISTINCT CASE WHEN e.event_name = 'view_restaurant' THEN e.session_id END)   AS 조회세션,
       COUNT(DISTINCT CASE WHEN e.event_name = 'add_to_cart'      THEN e.session_id END)   AS 장바구니세션,
       COUNT(DISTINCT CASE WHEN e.event_name = 'begin_checkout'   THEN e.session_id END)   AS 결제시작세션,
       COUNT(DISTINCT CASE WHEN e.event_name = 'order_complete'   THEN e.session_id END)   AS 주문세션,
       SUM(CASE WHEN e.event_name = 'payment_fail' THEN 1 ELSE 0 END)                     AS 결제실패
  FROM events e
  JOIN s ON e.session_id = s.session_id
 WHERE s.주시작일 < '2026-06-29'             -- 이틀치뿐인 마지막 주 제외
 GROUP BY 1, 2, 3
 ORDER BY 1, 2, 3
"""

@st.cache_data
def load_data():
    data = query(SQL_WEEKLY_FUNNEL)
    data["주시작일"] = pd.to_datetime(data["주시작일"]).dt.date
    return data

df = load_data()                           # 주 × 플랫폼 × 유입 경로별 세션 퍼널

AI_NOTES = {
    "전체": "전체 28,840개 세션 중 주문 전환율은 14.5%이며, 조회에서 장바구니로 이어지는 단계의 전환율이 41.4%로 가장 낮았다. 다른 집단들의 기준이 되는 전체 평균 흐름을 보여준다. 초기 유입 단계에서의 이탈 원인 파악이 필요하다.",
    "Android": "16,053개 세션으로 주문 전환율은 14.3%이며, 최저 단계는 41.8%의 장바구니 전환율을 기록했다. 2026-04-13 주부터 2026-06-01 주까지 결제 전환율이 크게 낮아지고 결제실패 이벤트가 급증했다. 해당 기간 동안 결제 프로세스에 기술적 문제가 있었던 것으로 보인다.",
    "iOS": "12,787개 세션으로 주문 전환율은 14.8%이며, 장바구니 전환율이 40.8%로 가장 낮았다. 전체 평균과 유사한 주문 전환율을 보였으나 결제 전환율은 85.5%로 안드로이드 대비 다소 높았다. 플랫폼별 결제 환경의 차이가 영향을 미쳤을 것으로 보인다.",
    "organic": "22,489개 세션으로 전체의 다수를 차지하며 주문 전환율은 16.0%로 전체 평균 대비 높았다. 장바구니 전환율은 41.4%로 가장 낮았으며, 결제 전환율은 80.4%를 기록했다. 자연 유입 사용자의 서비스 이용 의도가 비교적 높았던 것으로 보인다.",
    "paid_ad": "1,595개 세션으로 주문 전환율은 26.3%, 결제 전환율은 90.3%를 기록해 다른 유입경로 대비 성과가 가장 우수했다. 가장 낮은 단계인 장바구니 전환율도 53.7%로 전체 평균을 상회했다. 광고를 통해 유입된 사용자의 구매 전환 성향이 뚜렷했던 것으로 보인다.",
    "push": "4,635개 세션으로 주문 전환율은 3.2%, 결제 전환율은 63.8%로 다른 경로에 비해 낮았다. 세션에서 조회로 이어지는 단계의 전환율이 28.4%로 전 구간 중 가장 낮았다. 푸시 메시지를 통해 유입된 사용자의 콘텐츠 관심도가 상대적으로 낮았던 것으로 보인다.",
    "referral": "세션 수가 121개로 500개 미만이며 주문 전환율과 결제 전환율 모두 0.0%를 기록했다. 결제시작에서 주문으로 이어지는 단계의 전환율이 0.0%로 가장 낮았다. 표본 크기가 매우 작아 해당 경로의 성과를 단정하기 어렵다.",
}
AI_SOURCE = "🤖 Gemini가 미리 만든 해설 · 전체 기간 기준"

# ------------------------------------------------------------
# 사이드바 필터
# ------------------------------------------------------------
st.sidebar.header("필터")

# 주시작일 목록 정렬
date_options = sorted(df["주시작일"].unique())

# 기간 선택 (select_slider)
selected_dates = st.sidebar.select_slider(
    "기간",
    options=date_options,
    value=(date_options[0], date_options[-1])
)

# 플랫폼 선택 (multiselect)
platform_options = sorted(df["플랫폼"].unique())
selected_platforms = st.sidebar.multiselect(
    "플랫폼",
    options=platform_options,
    default=platform_options
)

# 유입 경로 선택 (multiselect)
traffic_options = sorted(df["유입경로"].unique())
selected_traffic = st.sidebar.multiselect(
    "유입 경로",
    options=traffic_options,
    default=traffic_options
)

# 평소 범위 기준 기간 (select_slider)
default_baseline_end_idx = min(25, len(date_options) - 1)
baseline_dates = st.sidebar.select_slider(
    "평소 범위 기준 기간",
    options=date_options,
    value=(date_options[0], date_options[default_baseline_end_idx]),
    help="문제가 없던 기간을 고르세요. 이 기간의 주별 값 범위를 '평소 범위'로 씁니다."
)

# 집단 조건(플랫폼·유입경로)만 적용한 데이터 g 생성
g = df[
    (df["플랫폼"].isin(selected_platforms)) &
    (df["유입경로"].isin(selected_traffic))
]

# 기존 f는 g에 기간 조건을 더해 만듦
f = g[
    (g["주시작일"] >= selected_dates[0]) &
    (g["주시작일"] <= selected_dates[1])
]

# f가 비어 있는 경우 처리
if f.empty:
    st.warning("선택한 조건에 해당하는 데이터가 없습니다. 필터를 바꿔 주세요.")
    st.stop()

# ------------------------------------------------------------
# 2. KPI 카드
# ------------------------------------------------------------
def rate(a, b):
    return a / b * 100 if b else 0

t = f[["세션수", "결제시작세션", "주문세션"]].sum()
c1, c2, c3 = st.columns(3)
c1.metric("세션 수", f"{t['세션수']:,}개")
c2.metric("주문 전환율 (방문 → 주문)", f"{rate(t['주문세션'], t['세션수']):.1f}%")
c3.metric("결제 전환율 (결제 시작 → 주문)", f"{rate(t['주문세션'], t['결제시작세션']):.1f}%")

# ------------------------------------------------------------
# 규칙 기반 설명 문장 (st.info)
# ------------------------------------------------------------
def generate_explanation(metric_type):
    # 선택 기간의 주 목록 정렬
    selected_weeks = sorted(f["주시작일"].unique())
    if len(selected_weeks) < 4:
        return "비교하려면 선택 기간을 4주 이상 골라 주세요"
    
    # 마지막 4주 기간
    last_4_weeks = selected_weeks[-4:]
    start_week_str = last_4_weeks[0].strftime("%Y-%m-%d")
    
    # g 데이터를 이용해 기준 기간(baseline_dates) 내 주별 전환율 계산 (분모 0 제외)
    g_base = g[(g["주시작일"] >= baseline_dates[0]) & (g["주시작일"] <= baseline_dates[1])]
    
    # 주별 집계
    weekly_base = g_base.groupby("주시작일")[["세션수", "결제시작세션", "주문세션"]].sum().reset_index()
    
    base_rates = []
    for _, row in weekly_base.iterrows():
        if metric_type == "payment":
            den = row["결제시작세션"]
            num = row["주문세션"]
        else:
            den = row["세션수"]
            num = row["주문세션"]
        if den > 0:
            base_rates.append(num / den * 100)
            
    if len(base_rates) < 4:
        return "기준 기간을 이 집단의 데이터가 있는 시기로 옮겨 주세요"
        
    min_rate = min(base_rates)
    max_rate = max(base_rates)
    
    # 이번 값: f의 마지막 4주 합계로 계산
    f_last_4 = f[f["주시작일"].isin(last_4_weeks)][["세션수", "결제시작세션", "주문세션"]].sum()
    if metric_type == "payment":
        current_val = rate(f_last_4["주문세션"], f_last_4["결제시작세션"])
        name_str = "결제 전환율"
    else:
        current_val = rate(f_last_4["주문세션"], f_last_4["세션수"])
        name_str = "주문 전환율"
        
    if current_val < min_rate:
        diff = min_rate - current_val
        status = f"평소 범위({min_rate:.1f}% ~ {max_rate:.1f}%)보다 {diff:.1f}%p 낮습니다."
    elif current_val > max_rate:
        diff = current_val - max_rate
        status = f"평소 범위({min_rate:.1f}% ~ {max_rate:.1f}%)보다 {diff:.1f}%p 높습니다."
    else:
        status = f"평소 범위({min_rate:.1f}% ~ {max_rate:.1f}%) 안에 있습니다."
        
    return f"{start_week_str} 주부터 4주간 {name_str}은 {current_val:.1f}%로, {status}"

st.info(generate_explanation("payment"))
st.info(generate_explanation("order"))
st.caption(f"📏 자동 계산 · 평소 범위 기준 기간 {baseline_dates[0]} ~ {baseline_dates[1]} (주별 값)")

with st.expander("🤖 AI 해설 · 전체", expanded=False):
    st.write(AI_NOTES.get("전체", "이 집단의 해설은 아직 없습니다."))
st.caption(AI_SOURCE)

st.divider()

# ------------------------------------------------------------
# 3. 차트
# ------------------------------------------------------------
left, right = st.columns(2)

# 3-1. 주별 결제 전환율 (플랫폼별)
wp = f.groupby(["주시작일", "플랫폼"])[["결제시작세션", "주문세션"]].sum().reset_index()
wp["결제전환율"] = (wp["주문세션"] / wp["결제시작세션"] * 100).round(1)
fig1 = px.line(wp, x="주시작일", y="결제전환율", color="플랫폼", markers=True,
               title="주별 결제 전환율 (플랫폼별)")
fig1.update_layout(yaxis_title="결제 전환율 (%)", xaxis_title="")
left.plotly_chart(fig1, width="stretch")

# 3-2. 세션 퍼널
steps = {"1.방문": "세션수", "2.식당조회": "조회세션", "3.장바구니": "장바구니세션",
         "4.결제시작": "결제시작세션", "5.주문완료": "주문세션"}
fun = pd.DataFrame({"단계": list(steps), "세션수": [f[c].sum() for c in steps.values()]})
fig2 = px.funnel(fun, x="세션수", y="단계", title="세션 퍼널")
right.plotly_chart(fig2, width="stretch")

# 3-3. 유입 경로별 주문 전환율
ws = f.groupby("유입경로")[["세션수", "주문세션"]].sum().reset_index()
ws["주문전환율"] = (ws["주문세션"] / ws["세션수"] * 100).round(1)
ws = ws.sort_values("주문전환율")
fig3 = px.bar(ws, x="주문전환율", y="유입경로", orientation="h", text_auto=".1f",
              hover_data=["세션수"], title="유입 경로별 주문 전환율")
if not ws.empty and ws["주문전환율"].max() > 0:
    fig3.update_xaxes(range=[0, ws["주문전환율"].max() * 1.2])
fig3.update_layout(xaxis_title="주문 전환율 (%)", yaxis_title="")
st.plotly_chart(fig3, width="stretch")

st.divider()

# ------------------------------------------------------------
# 4. 집단 비교
# ------------------------------------------------------------
st.subheader("집단 비교")
comp_by = st.radio("비교 기준", ["플랫폼", "유입경로"], horizontal=True)
comp_dim = "플랫폼" if comp_by == "플랫폼" else "유입경로"

# 집단별 5단계 집계
comp_df = f.groupby(comp_dim)[["세션수", "조회세션", "장바구니세션", "결제시작세션", "주문세션"]].sum().reset_index()

# 세션 수 500개 미만 집단 체크
low_session_groups = comp_df[comp_df["세션수"] < 500][comp_dim].tolist()
if low_session_groups:
    st.caption(f"주의: {', '.join(low_session_groups)} 집단은 세션 수가 500개 미만으로 값이 크게 흔들릴 수 있습니다.")

c_left, c_right = st.columns(2)

# 4-1. 왼쪽: 누적 전환율 퍼널
steps_map = {
    "1.방문": "세션수",
    "2.식당조회": "조회세션",
    "3.장바구니": "장바구니세션",
    "4.결제시작": "결제시작세션",
    "5.주문완료": "주문세션"
}

funnel_rows = []
for _, row in comp_df.iterrows():
    group_val = row[comp_dim]
    base = row["세션수"]
    for step_name, col_name in steps_map.items():
        val = row[col_name]
        rate_val = (val / base * 100) if base > 0 else 0
        funnel_rows.append({
            comp_dim: group_val,
            "단계": step_name,
            "누적전환율": round(rate_val, 1),
            "세션수": val
        })

funnel_plot_df = pd.DataFrame(funnel_rows)
fig_comp1 = px.funnel(
    funnel_plot_df,
    x="누적전환율",
    y="단계",
    color=comp_dim,
    hover_data=["세션수"],
    title="누적 전환율 퍼널 (첫 단계 대비 %)"
)
fig_comp1.update_layout(xaxis_title="누적 전환율 (%)", yaxis_title="")
c_left.plotly_chart(fig_comp1, width="stretch")

# 4-2. 오른쪽: 단계 전환율 막대 (직전 단계 대비)
bar_rows = []
for _, row in comp_df.iterrows():
    group_val = row[comp_dim]
    s1, s2, s3, s4, s5 = row["세션수"], row["조회세션"], row["장바구니세션"], row["결제시작세션"], row["주문세션"]
    
    r2 = (s2 / s1 * 100) if s1 > 0 else 0
    bar_rows.append({comp_dim: group_val, "단계": "2.식당조회", "전환율": round(r2, 1), "직전세션수": s1})
    
    r3 = (s3 / s2 * 100) if s2 > 0 else 0
    bar_rows.append({comp_dim: group_val, "단계": "3.장바구니", "전환율": round(r3, 1), "직전세션수": s2})
    
    r4 = (s4 / s3 * 100) if s3 > 0 else 0
    bar_rows.append({comp_dim: group_val, "단계": "4.결제시작", "전환율": round(r4, 1), "직전세션수": s3})
    
    r5 = (s5 / s4 * 100) if s4 > 0 else 0
    bar_rows.append({comp_dim: group_val, "단계": "5.주문완료", "전환율": round(r5, 1), "직전세션수": s4})

bar_plot_df = pd.DataFrame(bar_rows)
fig_comp2 = px.bar(
    bar_plot_df,
    x="단계",
    y="전환율",
    color=comp_dim,
    barmode="group",
    text_auto=".1f",
    hover_data=["직전세션수"],
    title="단계별 전환율 (직전 단계 대비 %)"
)
fig_comp2.update_layout(yaxis_title="전환율 (%)", xaxis_title="")
c_right.plotly_chart(fig_comp2, width="stretch")

st.divider()

# ------------------------------------------------------------
# 5. 드릴다운: 언제부터, 무엇 때문일까
# ------------------------------------------------------------
st.subheader("드릴다운: 언제부터, 무엇 때문일까")

# f에 존재하는 해당 축의 값들 추출
available_groups = sorted(f[comp_dim].unique())
step_options = [
    "방문 → 식당조회",
    "식당조회 → 장바구니",
    "장바구니 → 결제시작",
    "결제시작 → 주문"
]

d_col1, d_col2 = st.columns(2)
selected_group = d_col1.selectbox("자세히 볼 집단", options=available_groups)
selected_step = d_col2.selectbox("단계", options=step_options)

other_dim = "유입경로" if comp_dim == "플랫폼" else "플랫폼"

# 차트 ① 데이터 준비
sub_f = f[f[comp_dim] == selected_group]
weekly_sub = sub_f.groupby(["주시작일", other_dim])[["세션수", "조회세션", "장바구니세션", "결제시작세션", "주문세션", "결제실패"]].sum().reset_index()

if selected_step == "방문 → 식당조회":
    num_col, den_col = "조회세션", "세션수"
elif selected_step == "식당조회 → 장바구니":
    num_col, den_col = "장바구니세션", "조회세션"
elif selected_step == "장바구니 → 결제시작":
    num_col, den_col = "결제시작세션", "장바구니세션"
else: # 결제시작 → 주문
    num_col, den_col = "주문세션", "결제시작세션"

weekly_sub["전환율"] = weekly_sub.apply(
    lambda r: (r[num_col] / r[den_col] * 100) if r[den_col] > 0 else None,
    axis=1
)

fig_drill1 = px.line(
    weekly_sub,
    x="주시작일",
    y="전환율",
    color=other_dim,
    markers=True,
    title=f"① {selected_group}의 주별 {selected_step} 전환율 — {other_dim}별로 쪼개 보기"
)
fig_drill1.update_layout(yaxis_title="전환율 (%)", xaxis_title="")
st.plotly_chart(fig_drill1, width="stretch")
st.caption("모든 갈래가 같은 시점에 함께 움직였다면, 그 축은 원인이 아닙니다.")

# 차트 ② 데이터 준비
# 고른 집단 결제실패 주별 합계
g_fail = sub_f.groupby("주시작일")["결제실패"].sum().reset_index()
g_fail[comp_dim] = selected_group

# 그 외 집단 합치기
other_f = f[f[comp_dim] != selected_group]
o_fail = other_f.groupby("주시작일")["결제실패"].sum().reset_index()
o_fail[comp_dim] = "그 외"

fail_plot_df = pd.concat([g_fail, o_fail], ignore_index=True)

fig_drill2 = px.bar(
    fail_plot_df,
    x="주시작일",
    y="결제실패",
    color=comp_dim,
    barmode="group",
    color_discrete_map={selected_group: "darkred", "그 외": "lightgray"},
    title=f"주별 결제실패 건수: {selected_group} vs 그 외"
)
fig_drill2.update_layout(yaxis_title="결제실패 건수", xaxis_title="")
st.plotly_chart(fig_drill2, width="stretch")
st.caption("문제가 생긴 시점과 함께 움직였다면 원인 후보입니다. 함께 움직였다고 원인이 확정되지는 않습니다.")

target = selected_group
with st.expander(f"🤖 AI 해설 · {target}", expanded=False):
    st.write(AI_NOTES.get(target, "이 집단의 해설은 아직 없습니다."))
st.caption(AI_SOURCE)
