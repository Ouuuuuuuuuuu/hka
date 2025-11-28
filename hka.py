import streamlit as st
import pandas as pd
import requests
import time
import random
import plotly.express as px
import datetime
from bs4 import BeautifulSoup
from collections import Counter
import jieba.analyse

# --- 新增：自动化登录模块 ---
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# --- 页面配置 ---
st.set_page_config(
    page_title="WeChat Insight Pro",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 核心爬虫逻辑 ---
class WechatCrawler:
    def __init__(self, token, cookie):
        self.base_url = "https://mp.weixin.qq.com/cgi-bin/appmsg"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
            "Cookie": cookie
        }
        self.token = token
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def search_account(self, query):
        """搜索公众号获取fakeid"""
        search_url = "https://mp.weixin.qq.com/cgi-bin/searchbiz"
        params = {
            "action": "search_biz", "token": self.token, "lang": "zh_CN",
            "f": "json", "ajax": "1", "query": query, "begin": "0", "count": "5",
        }
        try:
            res = self.session.get(search_url, params=params)
            data = res.json()
            return data.get("list", [])
        except Exception as e:
            st.error(f"搜索请求异常: {e}")
            return []

    def fetch_article_list(self, fakeid, pages=3):
        """获取文章列表元数据"""
        all_articles = []
        progress_bar = st.progress(0)
        status_text = st.empty()

        for page in range(pages):
            status_text.text(f"📡 正在扫描列表第 {page + 1}/{pages} 页...")
            params = {
                "token": self.token, "lang": "zh_CN", "f": "json", "ajax": "1",
                "action": "list_ex", "fakeid": fakeid, "query": "",
                "begin": str(page * 5), "count": "5", "type": "9",
            }
            try:
                res = self.session.get(self.base_url, params=params)
                data = res.json()
                if "app_msg_list" in data:
                    for item in data["app_msg_list"]:
                        all_articles.append({
                            "aid": item.get("aid"),
                            "title": item.get("title"),
                            "digest": item.get("digest"),
                            "link": item.get("link"),
                            "create_time": item.get("create_time"),
                            "cover": item.get("cover"),
                            "item_idx": item.get("item_idx", 1),
                            "copyright_type": item.get("copyright_type", 0)
                        })
                else:
                    break
                progress_bar.progress((page + 1) / pages)
                # 随机延时，避免触发反爬机制
                time.sleep(random.uniform(1.0, 2.0))
            except:
                break
        
        progress_bar.empty()
        status_text.empty()
        return all_articles

    def fetch_article_content(self, url):
        """深度采集：访问详情页获取正文、作者等信息"""
        try:
            res = self.session.get(url, timeout=10)
            soup = BeautifulSoup(res.text, "lxml")
            
            # 提取正文文本 (去除HTML标签，保留段落结构)
            content_div = soup.find("div", {"id": "js_content"})
            if content_div:
                # 简单处理：将p标签换行，增强阅读体验
                for p in content_div.find_all('p'):
                    p.insert_after('\n')
                content_text = content_div.get_text().strip()
            else:
                content_text = ""
            
            # 提取作者
            author_tag = soup.find("strong", {"class": "profile_nickname"})
            if not author_tag:
                author_tag = soup.find("a", {"id": "js_name"})
            author = author_tag.get_text().strip() if author_tag else "未知"
            
            # 尝试提取IP属地 (微信IP属地通常在Script变量中)
            scripts = soup.find_all("script")
            ip_location = "IP未知"
            for script in scripts:
                if script.string and "ip_wording" in script.string:
                    import re
                    match = re.search(r'ip_wording\s*=\s*\{\s*type\s*:\s*2\s*,\s*name\s*:\s*"(.*?)"', script.string)
                    if match:
                        ip_location = match.group(1)
                        break
            
            return content_text, author, ip_location
        except Exception:
            return "", "获取失败", "获取失败"

# --- 数据处理工具 ---
def process_data(articles, crawler=None, fetch_details=False):
    if not articles:
        return pd.DataFrame()
    
    df = pd.DataFrame(articles)
    
    # 时间格式化
    df['publish_time'] = pd.to_datetime(df['create_time'], unit='s')
    df['date'] = df['publish_time'].dt.date
    df['is_original'] = df['copyright_type'].apply(lambda x: '原创' if x == 1 else '转载')
    
    # 深度采集逻辑
    if fetch_details and crawler:
        st.info("🐢 正在深度采集全文，速度较慢，请耐心等待...")
        details = []
        bar = st.progress(0)
        for idx, row in df.iterrows():
            content, author, ip = crawler.fetch_article_content(row['link'])
            details.append({
                'content': content,
                'author': author,
                'ip_location': ip
            })
            bar.progress((idx + 1) / len(df))
            time.sleep(0.5) # 必须延时，否则容易封IP
        
        detail_df = pd.DataFrame(details)
        df = pd.concat([df, detail_df], axis=1)
        bar.empty()
    else:
        df['content'] = ""
        df['author'] = "未采集"
        df['ip_location'] = "-"

    return df

# --- 辅助函数：自动登录获取Cookie ---
def auto_login_get_cookie():
    try:
        # 初始化 Chrome 驱动
        options = webdriver.ChromeOptions()
        # 注意：扫码登录不能使用无头模式(headless)，必须显示浏览器窗口
        
        status_placeholder = st.empty()
        status_placeholder.info("🚀 正在启动浏览器，请在弹出的窗口中扫码登录...")
        
        # 自动下载并启动匹配版本的 ChromeDriver
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        
        # 打开微信公众平台
        driver.get("https://mp.weixin.qq.com/")
        
        # 循环检测是否登录成功 (检测URL中是否包含 token)
        max_wait = 180 # 3分钟超时
        start_time = time.time()
        
        token = ""
        cookies_str = ""
        
        while True:
            current_url = driver.current_url
            if "token=" in current_url:
                status_placeholder.success("✅ 扫码成功！正在提取凭证...")
                # 提取 Token
                try:
                    token = current_url.split("token=")[1].split("&")[0]
                except:
                    pass
                
                # 提取 Cookie
                selenium_cookies = driver.get_cookies()
                # 将 Cookie 列表转换为字符串格式
                cookie_items = [f"{c['name']}={c['value']}" for c in selenium_cookies]
                cookies_str = "; ".join(cookie_items)
                
                break
            
            if time.time() - start_time > max_wait:
                status_placeholder.error("⏰ 登录超时，请重试")
                break
            
            time.sleep(1)
        
        driver.quit()
        status_placeholder.empty()
        return token, cookies_str
        
    except Exception as e:
        st.error(f"启动浏览器失败，请确保安装了 Chrome 浏览器: {str(e)}")
        return None, None

# --- 主程序逻辑 ---

# 初始化 Session State 用于存储 Token 和 Cookie
if 'wx_token' not in st.session_state:
    st.session_state['wx_token'] = ''
if 'wx_cookie' not in st.session_state:
    st.session_state['wx_cookie'] = ''

with st.sidebar:
    st.title("🤖 自动获取助手")
    
    # 自动获取按钮
    if st.button("📢 点击唤起浏览器扫码", type="primary"):
        token, cookie = auto_login_get_cookie()
        if token and cookie:
            st.session_state['wx_token'] = token
            st.session_state['wx_cookie'] = cookie
            st.success("凭证已自动填入！")
            time.sleep(1)
            st.rerun() # 刷新页面以显示填入的数据
    
    st.divider()
    
    with st.expander("🔑 凭证配置", expanded=True):
        # 使用 session_state 自动填充
        wx_token = st.text_input("Token", value=st.session_state['wx_token'], help="URL中的token参数")
        wx_cookie = st.text_area("Cookie", value=st.session_state['wx_cookie'], height=150, help="完整的Cookie字符串")
    
    st.divider()
    target_query = st.text_input("🔍 目标公众号", placeholder="输入名称，如：清华大学")
    scrape_pages = st.number_input("抓取页数", 1, 10, 2)
    enable_details = st.checkbox("采集正文 (阅读模式必选)", value=True)
    
    start_btn = st.button("🚀 开始分析数据", use_container_width=True)

# --- 主界面 ---

if start_btn and wx_token and wx_cookie and target_query:
    crawler = WechatCrawler(wx_token, wx_cookie)
    
    with st.status("正在建立数据连接...", expanded=True) as status:
        # 1. 搜索
        status.write("🔍 定位目标账号...")
        accounts = crawler.search_account(target_query)
        if not accounts:
            status.update(label="未找到账号，可能是Cookie已失效，请重新扫码", state="error")
            st.stop()
        
        target = accounts[0]
        status.write(f"✅ 锁定: {target['nickname']}")
        
        # 2. 列表抓取
        status.write("📃 拉取文章列表...")
        raw_list = crawler.fetch_article_list(target['fakeid'], pages=scrape_pages)
        
        if not raw_list:
             status.update(label="未获取到文章列表，请检查凭证", state="error")
             st.stop()

        # 3. 深度采集
        status.write("🧹 深度采集正文内容...")
        df_res = process_data(raw_list, crawler, fetch_details=enable_details)
        
        status.update(label="数据准备就绪!", state="complete")
        
        st.session_state['data'] = df_res
        st.session_state['account'] = target['nickname']

# --- 看板展示 ---
if 'data' in st.session_state:
    df = st.session_state['data']
    nickname = st.session_state['account']
    st.header(f"📰 {nickname} · 深度阅读看板")
    
    tab_read, tab_list = st.tabs(["👓 阅读模式", "📋 文章列表"])
    
    with tab_read:
        if 'content' in df.columns and not df['content'].isna().all():
            # 生成下拉框选项
            df['select_label'] = df['date'].astype(str) + " | " + df['title']
            selected_article_label = st.selectbox("选择文章:", df['select_label'].tolist())
            
            # 获取选中文章数据
            article = df[df['select_label'] == selected_article_label].iloc[0]
            
            # 文章展示容器
            with st.container():
                st.markdown(f"## {article['title']}")
                st.caption(f"作者: {article['author']} | 发布时间: {article['publish_time']} | {article['is_original']} | IP: {article['ip_location']}")
                st.divider()
                
                # 正文展示区
                if article['content']:
                    st.markdown(article['content'].replace("\n", "\n\n")) # 优化排版
                else:
                    st.warning("正文内容为空或未采集")
                    st.markdown(f"[点击跳转原文链接]({article['link']})")
        else:
            st.info("暂无正文数据，请确保勾选了【采集正文】并重新抓取。")
            
    with tab_list:
        st.dataframe(
            df[['title', 'date', 'author', 'is_original', 'link']],
            use_container_width=True,
            column_config={
                "link": st.column_config.LinkColumn("原文链接")
            }
        )
else:
    st.info("👈 请在左侧点击 **'唤起浏览器扫码'** 获取凭证，然后输入公众号名称开始抓取。")
