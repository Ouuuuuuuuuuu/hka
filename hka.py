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
import platform
import os
import shutil
import glob

# --- Selenium 相关库 ---
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.firefox.service import Service as FirefoxService

# 引入 webdriver_manager
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from webdriver_manager.firefox import GeckoDriverManager

# ==========================================
# 🚀 配置国内镜像源
# ==========================================
os.environ['WDM_BASE_URL'] = "https://npmmirror.com/mirrors/chromedriver"
os.environ['WDM_SSL_VERIFY'] = '0' 

# --- 页面配置 ---
st.set_page_config(
    page_title="WeChat Insight Pro",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 辅助函数：智能查找本地驱动 ---
def find_local_driver(browser_name):
    """
    全盘扫描：在 Downloads 文件夹和系统路径中查找驱动文件
    """
    system_name = platform.system()
    driver_filename = "chromedriver" if browser_name == "Chrome" else "msedgedriver"
    if system_name == "Windows":
        driver_filename += ".exe"

    # 1. 检查当前目录
    if os.path.exists(driver_filename):
        return os.path.abspath(driver_filename)
    
    # 2. 检查 Downloads 目录
    home = os.path.expanduser("~")
    downloads_path = os.path.join(home, "Downloads")
    target = os.path.join(downloads_path, driver_filename)
    if os.path.exists(target):
        return target
        
    # 3. 检查系统 PATH
    return shutil.which(driver_filename)

# --- 核心逻辑：初始化浏览器驱动 ---
# 将此逻辑独立出来，避免主函数出现 SyntaxError
def init_driver_engine(browser_type):
    driver = None
    err_msg = ""
    
    try:
        # === Safari 策略 (Mac专用) ===
        if browser_type == "Safari":
            if platform.system() != 'Darwin':
                return None, "Safari 仅支持 macOS 系统。"
            try:
                options = webdriver.SafariOptions()
                driver = webdriver.Safari(options=options)
                return driver, ""
            except Exception as e:
                return None, f"Safari 启动失败: {str(e)}。请确保在 Safari 菜单栏 -> 开发 -> 勾选 '允许远程自动化'。"

        # === Chrome 策略 ===
        elif browser_type == "Chrome":
            options = webdriver.ChromeOptions()
            # 策略A: 自动下载 (国内镜像)
            try:
                service = ChromeService(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=options)
                return driver, ""
            except Exception:
                # 策略B: 查找本地
                local_path = find_local_driver("Chrome")
                if local_path:
                    st.toast(f"已调用本地驱动: {local_path}", icon="📂")
                    service = ChromeService(executable_path=local_path)
                    driver = webdriver.Chrome(service=service, options=options)
                    return driver, ""
                else:
                    return None, "Chrome 驱动下载失败且未找到本地文件。"

        # === Edge 策略 ===
        elif browser_type == "Edge":
            options = webdriver.EdgeOptions()
            # 策略A: 查找本地 (优先)
            local_path = find_local_driver("Edge")
            if local_path:
                st.toast(f"已调用本地驱动: {local_path}", icon="📂")
                try:
                    service = EdgeService(executable_path=local_path)
                    driver = webdriver.Edge(service=service, options=options)
                    return driver, ""
                except Exception as e:
                    # 如果本地驱动版本不匹配，尝试自动下载
                    pass 

            # 策略B: 自动下载
            try:
                service = EdgeService(EdgeChromiumDriverManager().install())
                driver = webdriver.Edge(service=service, options=options)
                return driver, ""
            except Exception as e:
                return None, f"Edge 驱动启动失败: {str(e)}。请手动下载驱动放入 Downloads 文件夹。"

    except Exception as e:
        return None, f"未知错误: {str(e)}"
    
    return None, "不支持的浏览器类型"

# --- 核心爬虫逻辑类 ---
class WechatCrawler:
    def __init__(self, token, cookie):
        self.base_url = "https://mp.weixin.qq.com/cgi-bin/appmsg"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Cookie": cookie
        }
        self.token = token
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def search_account(self, query):
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
            return []

    def fetch_article_list(self, fakeid, pages=3):
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
                time.sleep(random.uniform(1.0, 2.0))
            except:
                break
        
        progress_bar.empty()
        status_text.empty()
        return all_articles

    def fetch_article_content(self, url):
        try:
            res = self.session.get(url, timeout=10)
            soup = BeautifulSoup(res.text, "lxml")
            
            content_div = soup.find("div", {"id": "js_content"})
            if content_div:
                for p in content_div.find_all('p'):
                    p.insert_after('\n')
                content_text = content_div.get_text().strip()
            else:
                content_text = ""
            
            author_tag = soup.find("strong", {"class": "profile_nickname"})
            if not author_tag:
                author_tag = soup.find("a", {"id": "js_name"})
            author = author_tag.get_text().strip() if author_tag else "未知"
            
            return content_text, author, "IP未知"
        except Exception:
            return "", "获取失败", "获取失败"

# --- 数据处理工具 ---
def process_data(articles, crawler=None, fetch_details=False):
    if not articles:
        return pd.DataFrame()
    df = pd.DataFrame(articles)
    df['publish_time'] = pd.to_datetime(df['create_time'], unit='s')
    df['date'] = df['publish_time'].dt.date
    df['is_original'] = df['copyright_type'].apply(lambda x: '原创' if x == 1 else '转载')
    
    if fetch_details and crawler:
        st.info("🐢 正在深度采集全文...")
        details = []
        bar = st.progress(0)
        for idx, row in df.iterrows():
            content, author, ip = crawler.fetch_article_content(row['link'])
            details.append({'content': content, 'author': author, 'ip_location': ip})
            bar.progress((idx + 1) / len(df))
            time.sleep(0.5)
        detail_df = pd.DataFrame(details)
        df = pd.concat([df, detail_df], axis=1)
        bar.empty()
    else:
        df['content'] = ""
        df['author'] = "未采集"
    return df

# --- 主交互函数：扫码获取凭证 ---
def auto_login_get_cookie(browser_type):
    status_placeholder = st.empty()
    status_placeholder.info(f"🚀 正在启动 {browser_type}，请稍候...")
    
    # 1. 启动浏览器
    driver, error = init_driver_engine(browser_type)
    
    if not driver:
        status_placeholder.error(error)
        return None, None
    
    try:
        # 2. 打开微信
        driver.get("https://mp.weixin.qq.com/")
        status_placeholder.success("✅ 浏览器已就绪！请在弹出的窗口中扫码登录...")
        
        # 3. 循环检测登录
        max_wait = 180
        start_time = time.time()
        
        while True:
            # 检查超时
            if time.time() - start_time > max_wait:
                status_placeholder.error("⏰ 登录超时，请重试")
                break
                
            # 检查浏览器是否被用户关闭
            try:
                current_url = driver.current_url
            except:
                status_placeholder.warning("⚠️ 浏览器已关闭")
                return None, None

            # 检查是否包含 token (登录成功标志)
            if "token=" in current_url:
                status_placeholder.success("🎉 扫码成功！正在提取凭证...")
                try:
                    token = current_url.split("token=")[1].split("&")[0]
                except:
                    token = ""
                
                selenium_cookies = driver.get_cookies()
                cookie_items = [f"{c['name']}={c['value']}" for c in selenium_cookies]
                cookies_str = "; ".join(cookie_items)
                
                driver.quit()
                return token, cookies_str
            
            time.sleep(1)
            
    except Exception as e:
        status_placeholder.error(f"运行时发生错误: {str(e)}")
        if driver:
            try: driver.quit() 
            except: pass
        return None, None
        
    return None, None

# --- 主程序 UI 逻辑 ---

if 'wx_token' not in st.session_state:
    st.session_state['wx_token'] = ''
if 'wx_cookie' not in st.session_state:
    st.session_state['wx_cookie'] = ''

with st.sidebar:
    st.title("🤖 自动获取助手")
    
    # 智能默认选择
    default_idx = 0 if platform.system() == 'Darwin' else 2 # Mac默认Safari, Win默认Edge
    browser_choice = st.selectbox("选择浏览器", ["Safari", "Chrome", "Edge"], index=default_idx)
    
    if browser_choice == "Safari":
        st.caption("🍎 **Mac首选**：无需下载驱动。若失败请检查Safari菜单栏 `开发` -> `允许远程自动化`。")
    elif browser_choice == "Edge":
        st.caption("⚡️ **自动搜索**：将下载好的驱动放在 Downloads 文件夹，我会自动找到它。")

    if st.button("📢 一键唤起扫码", type="primary"):
        token, cookie = auto_login_get_cookie(browser_choice)
        if token and cookie:
            st.session_state['wx_token'] = token
            st.session_state['wx_cookie'] = cookie
            st.balloons()
            st.success("凭证已自动填入！")
            time.sleep(1)
            st.rerun()
    
    st.divider()
    
    with st.expander("🔑 凭证配置 (手动)", expanded=True):
        wx_token = st.text_input("Token", value=st.session_state['wx_token'])
        wx_cookie = st.text_area("Cookie", value=st.session_state['wx_cookie'], height=150)
    
    st.divider()
    target_query = st.text_input("🔍 目标公众号", placeholder="输入名称")
    scrape_pages = st.number_input("抓取页数", 1, 10, 2)
    enable_details = st.checkbox("采集正文 (阅读模式必选)", value=True)
    
    start_btn = st.button("🚀 开始分析数据", use_container_width=True)

# --- 主界面 ---
if start_btn and wx_token and wx_cookie and target_query:
    crawler = WechatCrawler(wx_token, wx_cookie)
    
    with st.status("正在建立数据连接...", expanded=True) as status:
        status.write("🔍 定位目标账号...")
        accounts = crawler.search_account(target_query)
        if not accounts:
            status.update(label="未找到账号，可能是Cookie已失效", state="error")
            st.stop()
        
        target = accounts[0]
        status.write(f"✅ 锁定: {target['nickname']}")
        
        status.write("📃 拉取文章列表...")
        raw_list = crawler.fetch_article_list(target['fakeid'], pages=scrape_pages)
        
        if not raw_list:
             status.update(label="未获取到文章列表，请检查凭证", state="error")
             st.stop()

        status.write("🧹 深度采集正文内容...")
        df_res = process_data(raw_list, crawler, fetch_details=enable_details)
        
        status.update(label="数据准备就绪!", state="complete")
        st.session_state['data'] = df_res
        st.session_state['account'] = target['nickname']

if 'data' in st.session_state:
    df = st.session_state['data']
    nickname = st.session_state['account']
    st.header(f"📰 {nickname} · 深度阅读看板")
    
    tab_read, tab_list = st.tabs(["👓 阅读模式", "📋 文章列表"])
    
    with tab_read:
        if 'content' in df.columns and not df['content'].isna().all():
            df['select_label'] = df['date'].astype(str) + " | " + df['title']
            selected_article_label = st.selectbox("选择文章:", df['select_label'].tolist())
            article = df[df['select_label'] == selected_article_label].iloc[0]
            
            with st.container():
                st.markdown(f"## {article['title']}")
                st.caption(f"作者: {article['author']} | 发布时间: {article['publish_time']} | {article['is_original']}")
                st.divider()
                if article['content']:
                    st.markdown(article['content'].replace("\n", "\n\n"))
                else:
                    st.warning("正文内容为空")
                    st.markdown(f"[点击跳转原文链接]({article['link']})")
        else:
            st.info("暂无正文数据，请确保勾选了【采集正文】并重新抓取。")
            
    with tab_list:
        st.dataframe(
            df[['title', 'date', 'author', 'is_original', 'link']],
            use_container_width=True,
            column_config={"link": st.column_config.LinkColumn("原文链接")}
        )
else:
    st.info("👈 请在左侧选择浏览器并点击 **'一键唤起扫码'**。")
