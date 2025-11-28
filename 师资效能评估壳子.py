import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(layout="wide", page_title="HKA 师资效能评估")

# 读取 HTML 文件
with open("dashboard.html", "r", encoding="utf-8") as f:
    html_content = f.read()

# 1. 从 Secrets 读取你在第一步设置的 Key
api_key = st.secrets["SILICONFLOW_API_KEY"]

# 2. 将 HTML 中的占位符替换为真实 Key
# 注意：这里我们约定 HTML 里的占位符是 "[[SILICONFLOW_KEY]]"
html_content = html_content.replace("[[SILICONFLOW_KEY]]", api_key)

# 渲染网页
components.html(html_content, height=1000, scrolling=True)
