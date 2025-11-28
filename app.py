import streamlit as st
import streamlit.components.v1 as components
import os

# 1. 设置页面基本配置 (必须是第一个 Streamlit 命令)
st.set_page_config(layout="wide", page_title="HKA 综合工具箱")

# 2. 自定义 CSS 样式：美化标题、卡片和底部 Footer
st.markdown("""
    <style>
    /* 大标题样式 */
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
    /* 底部 Footer 样式 */
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
    /* 调整按钮样式使其更像卡片 (可选，Streamlit 原生按钮较难完全定制，这里主要靠布局) */
    div.stButton > button {
        width: 100%;
        height: 3rem;
        font-weight: bold;
        border-radius: 10px;
    }
    </style>
""", unsafe_allow_html=True)

# 3. 状态管理：确保 session_state 中有当前页面的记录
if 'current_page' not in st.session_state:
    st.session_state.current_page = "🏠 首页"

# 定义页面列表
PAGES = {
    "home": "🏠 首页",
    "eval": "📊 师资效能评估",
    "article": "📝 校长文章库生成器",
    "hotspot": "🔥 公众号热点分析"
}

# 4. 侧边栏导航
st.sidebar.title("HKA 工具箱")
# 使用 session_state 来同步选择状态
selection = st.sidebar.radio(
    "功能导航:",
    list(PAGES.values()),
    key="current_page"
)

# 5. 页面路由逻辑

# --- 🏠 首页 (Landing Page) ---
if selection == PAGES["home"]:
    # 居中大字标题
    st.markdown('<div class="main-title">汉开教育 校办工具箱</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">HKA Administrative Toolkit</div>', unsafe_allow_html=True)

    # 横排三个模块入口
    col1, col2, col3 = st.columns(3)

    # 定义跳转函数
    def switch_page(page_name):
        st.session_state.current_page = page_name
        st.rerun()

    with col1:
        st.info("📊 **师资效能评估**\n\nDeepSeek 驱动的师资结构诊断与模拟沙盘。")
        if st.button("进入评估系统", use_container_width=True):
            switch_page(PAGES["eval"])

    with col2:
        st.success("📝 **文章库生成器**\n\nWord 批量转网页工具，纯前端处理，安全高效。")
        if st.button("打开生成工具", use_container_width=True):
            switch_page(PAGES["article"])

    with col3:
        st.warning("🔥 **公众号热点分析**\n\n基于 Python 的公众号数据可视化与词云分析。")
        if st.button("开始热点分析", use_container_width=True):
            switch_page(PAGES["hotspot"])

    # 首页底部的额外装饰或说明
    st.markdown("---")
    st.caption("请从上方选择模块或使用左侧侧边栏进行导航。")

# --- 模块 1: 师资效能评估 (Python) ---
elif selection == PAGES["eval"]:
    script_file = "师资效能评估壳子.py"
    if os.path.exists(script_file):
        try:
            with open(script_file, "r", encoding="utf-8") as f:
                code = f.read()
                exec(code, globals())
        except Exception as e:
            st.error(f"❌ 运行 {script_file} 时发生错误:\n{e}")
    else:
        st.warning(f"⚠️ 找不到 {script_file}。请确保文件已上传到仓库。")

# --- 模块 2: 文章库生成器 (HTML) ---
elif selection == PAGES["article"]:
    st.title("📄 Word 转网页生成工具")
    st.caption("纯前端工具，保护数据隐私。")
    try:
        with open("demo.html", "r", encoding="utf-8") as f:
            html_content = f.read()
        components.html(html_content, height=900, scrolling=True)
    except FileNotFoundError:
        st.error("❌ 找不到 demo.html。请确保文件已上传。")

# --- 模块 3: 公众号热点分析 (Python) ---
elif selection == PAGES["hotspot"]:
    # 模拟 hka.py 环境
    hka_file = "hka.py"
    if os.path.exists(hka_file):
        try:
            with open(hka_file, "r", encoding="utf-8") as f:
                code = f.read()
                exec(code, globals())
        except Exception as e:
            st.error(f"❌ 运行 hka.py 时发生错误:\n{e}")
            st.info("提示：请检查 hka.py 是否包含与 app.py 冲突的配置（如重复的 set_page_config）。")
    else:
        st.warning("⚠️ 尚未检测到 hka.py 文件。")
        st.markdown(f"""
        ### 如何启用此功能？
        1. 请将你的 **`hka.py`** 文件上传到同一个 GitHub 仓库。
        2. 如果 `hka.py` 用到了特殊的库（如 `jieba`, `wordcloud`, `pandas` 等），请记得更新 **`requirements.txt`**。
        """)

# 6. 底部 Footer (全局显示)
st.markdown('<div class="footer">by Ouuuuuuuuuuu</div>', unsafe_allow_html=True)
