import streamlit as st
import streamlit.components.v1 as components
import os

# 设置页面基本配置
st.set_page_config(layout="wide", page_title="HKA 综合工具箱")

# 侧边栏：应用选择器
st.sidebar.title("HKA 工具箱")
st.sidebar.info(f"当前工作目录: {os.getcwd()}") # 调试用，方便查看文件位置

app_mode = st.sidebar.radio(
    "请选择功能模块:",
    [
        "📊 师资效能评估", 
        "📝 校长文章库生成器",
        "🔥 公众号热点分析 (hka.py)"
    ]
)

# --- 模块 1: 师资效能评估 (Python) ---
if app_mode == "📊 师资效能评估":
    # 这里改为运行 "师资效能评估壳子.py"
    # 请确保该文件已上传，且如果在其中使用 HTML 组件，可直接使用 st.secrets 读取 Key
    
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
elif app_mode == "📝 校长文章库生成器":
    st.title("📄 Word 转网页生成工具")
    st.caption("纯前端工具，保护数据隐私。")
    
    try:
        with open("demo.html", "r", encoding="utf-8") as f:
            html_content = f.read()
        components.html(html_content, height=900, scrolling=True)
        
    except FileNotFoundError:
        st.error("❌ 找不到 demo.html。请确保文件已上传。")

# --- 模块 3: 公众号热点分析 (Python) ---
elif app_mode == "🔥 公众号热点分析 (hka.py)":
    # 这里直接运行 hka.py 的代码
    
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

# 侧边栏底部信息
st.sidebar.markdown("---")
st.sidebar.caption("HKA Internal Tools v3.0")
