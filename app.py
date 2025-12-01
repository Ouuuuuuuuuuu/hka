import streamlit as st
import streamlit.components.v1 as components
import os

# 1. 设置页面基本配置
st.set_page_config(layout="wide", page_title="HKA 综合工具箱")

# 2. 自定义 CSS (保持不变)
st.markdown("""
    <style>
    .main-title {
        font-size: 3.5rem !important;
        font-weight: 700 !important;
        color: #1e293b;
        text-align: center;
        margin-top: 2rem;
        margin-bottom: 0.5rem;
        font-family: "Microsoft YaHei", sans-serif;
    }
    .sub-title {
        font-size: 1.2rem !important;
        color: #64748b;
        text-align: center;
        margin-bottom: 4rem;
    }
    .footer {
        position: fixed;
        left: 0;
        bottom: 0;
        width: 100%;
        background-color: white;
        color: #94a3b8;
        text-align: center;
        padding: 10px;
        font-size: 0.8rem;
        border-top: 1px solid #e2e8f0;
        z-index: 999;
    }
    .fixed-height-box {
        min-height: 120px;
        display: flex;
        flex-direction: column;
        justify-content: flex-start;
    }
    div.stButton > button {
        width: 100%;
        height: 3rem;
        font-weight: bold;
        border-radius: 10px;
    }
    </style>
""", unsafe_allow_html=True)

# 3. 状态管理
if 'current_page' not in st.session_state:
    st.session_state.current_page = "🏠 首页"
if 'pending_page' not in st.session_state:
    st.session_state.pending_page = None

# 定义页面列表 (更新了最后一个栏目)
PAGES = {
    "home": "🏠 首页",
    "eval": "📊 师资效能评估",
    "article": "📝 校长文章库生成器",
    "hotspot": "🔥 公众号热点分析",
    "whimsy": "💡 奇思妙想"  # <--- 新增栏目
}

# 解决状态冲突
if st.session_state.pending_page:
    st.session_state.current_page = st.session_state.pending_page
    st.session_state.pending_page = None

# 4. 侧边栏导航
st.sidebar.title("漢開工具箱")
selection = st.sidebar.radio(
    "功能导航:",
    list(PAGES.values()),
    key="current_page"
)

# 5. 页面路由逻辑

# --- 🏠 首页 ---
if selection == PAGES["home"]:
    st.markdown('<div class="main-title">漢開教育 校办工具箱</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">HKA Administrative Toolkit</div>', unsafe_allow_html=True)

    def switch_page(page_name):
        st.session_state.pending_page = page_name

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown('<div class="fixed-height-box">', unsafe_allow_html=True)
        st.info("📊 **师资效能评估**\n\nDeepSeek—R1 驱动的师资结构诊断。")
        st.markdown('</div>', unsafe_allow_html=True)
        st.button("进入评估系统", use_container_width=True, on_click=switch_page, args=(PAGES["eval"],))

    with col2:
        st.markdown('<div class="fixed-height-box">', unsafe_allow_html=True)
        st.success("📝 **文章库生成器**\n\nWord 批量转网页工具，纯前端处理。")
        st.markdown('</div>', unsafe_allow_html=True)
        st.button("打开生成工具", use_container_width=True, on_click=switch_page, args=(PAGES["article"],))

    with col3:
        st.markdown('<div class="fixed-height-box">', unsafe_allow_html=True)
        st.warning("🔥 **热点分析**\n\n公众号数据可视化与词云分析。")
        st.markdown('</div>', unsafe_allow_html=True)
        st.button("开始热点分析", use_container_width=True, on_click=switch_page, args=(PAGES["hotspot"],))

    with col4:
        st.markdown('<div class="fixed-height-box">', unsafe_allow_html=True)
        st.error("💡 **奇思妙想**\n\nMAS 研报与 AI 易学预测实验室。")
        st.markdown('</div>', unsafe_allow_html=True)
        st.button("进入实验室", use_container_width=True, on_click=switch_page, args=(PAGES["whimsy"],))

    st.markdown("---")
    st.caption("请从上方选择模块或使用左侧侧边栏进行导航。")

# --- 模块 1: 师资效能评估 ---
elif selection == PAGES["eval"]:
    script_file = "师资效能评估壳子.py"
    if os.path.exists(script_file):
        try:
            with open(script_file, "r", encoding="utf-8") as f:
                code = f.read()
                exec(code, globals())
        except Exception as e:
            st.error(f"❌ 运行错误: {e}")
    else:
        st.warning(f"⚠️ 找不到 {script_file}")

# --- 模块 2: 文章库生成器 ---
elif selection == PAGES["article"]:
    st.title("📄 Word 转网页生成工具")
    try:
        with open("demo.html", "r", encoding="utf-8") as f:
            html_content = f.read()
        components.html(html_content, height=900, scrolling=True)
    except FileNotFoundError:
        st.error("❌ 找不到 demo.html")

# --- 模块 3: 公众号热点分析 ---
elif selection == PAGES["hotspot"]:
    hka_file = "hka.py"
    if os.path.exists(hka_file):
        try:
            with open(hka_file, "r", encoding="utf-8") as f:
                code = f.read()
                exec(code, globals())
        except Exception as e:
            st.error(f"❌ 运行错误: {e}")
    else:
        st.warning("⚠️ 找不到 hka.py")

# --- 模块 4: 奇思妙想 (新增) ---
elif selection == PAGES["whimsy"]:
    st.title("💡 奇思妙想实验室")
    st.caption("这里汇聚了 HKA 最前沿的 AI 实验项目，请点击下方标签切换应用。")
    
    # 使用 Tabs 标签页来区分两个应用
    tab1, tab2 = st.tabs(["📈 MAS 联合研报终端", "🔮 AI 智能易学预测"])

    with tab1:
        st.info("正在加载 MAS 联合研报终端...")
        # 嵌入 MAS Finance
        components.iframe("https://masfinance.streamlit.app/?embed=true", height=1000, scrolling=True)

    with tab2:
        st.info("正在加载 AI 智能易学预测系统...")
        # 嵌入 Fortune Tell
        components.iframe("https://fortunetell.streamlit.app/?embed=true", height=1000, scrolling=True)

# 6. 底部 Footer
st.markdown('<div class="footer">by Ouuuuuuuuuuu</div>', unsafe_allow_html=True)
