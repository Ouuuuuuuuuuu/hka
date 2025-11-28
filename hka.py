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

# --- 新增：自动化登录模块 (多浏览器支持) ---
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.firefox.service import Service as FirefoxService

# 引入 webdriver_manager
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from webdriver_manager.firefox import GeckoDriverManager

# ==========================================
# 🚀 核心黑科技：配置国内镜像源 (解决网络报错)
# ==========================================
# 强制让 Chrome 驱动从淘宝镜像下载，解决 "Could not reach host" 问题
os.environ['WDM_BASE_URL'] = "https://npmmirror.com/mirrors/chromedriver"
os.environ['WDM_SSL_VERIFY'] = '0' 

# --- 页面配置 ---
st.set_page_config(
    page_title="WeChat Insight Pro",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 智能驱动查找器 (专门解决小白找不到路径的问题) ---
def find_driver_automatically(browser_name):
    """
    如果自动下载失败，这个函数会自动去电脑的 Downloads 文件夹
    或者系统路径里“捡”一个驱动回来用。
    """
    system_name = platform.system()
    driver_filename = ""
    
    if browser_name == "Chrome":
        driver_filename = "chromedriver"
    elif browser_name == "Edge":
        driver_filename = "msedgedriver"
    
    if system_name == "Windows":
        driver_filename += ".exe"

    # 1. 搜索当前目录
    if os.path.exists(driver_filename):
        return os.path.abspath(driver_filename)
    
    # 2. 搜索用户的 Downloads 文件夹 (这是小白最容易存放的地方)
    home = os.path.expanduser("~")
    downloads_path = os.path.join(home, "Downloads")
    
    # 在 Downloads 里找 (包括子文件夹，防止解压在里面)
    # 简单搜索 Downloads 根目录
    target = os.path.join(downloads_path, driver_filename)
    if os.path.exists(target):
        return target
        
    # 3. 尝试从 PATH 环境变量里找
    return shutil.which(driver_filename)

# --- 核心爬虫逻辑 (保持不变) ---
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
    df['publish_time'] = pd.to_datetime(df['create_time'], unit='s')
    df['date'] = df['publish_time'].dt.date
    df['is_original'] = df['copyright_type'].apply(lambda x: '原创' if x == 1 else '转载')
    
    if fetch_details and crawler:
        st.info("🐢 正在深度采集全文，速度较慢，请耐心等待...")
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
        df['ip_location'] = "-"

    return df

# --- 辅助函数：智能自动登录 ---
def auto_login_get_cookie(browser_type="Chrome"):
    driver = None
    status_placeholder = st.empty()
    
    try:
        status_placeholder.info(f"🚀 正在启动 {browser_type} 浏览器...")
        
        # 1. 尝试初始化浏览器
        if browser_type == "Chrome":
            options = webdriver.ChromeOptions()
            try:
                # 尝试 A: 使用国内镜像自动下载
                service = ChromeService(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=options)
            except Exception as e_net:
                # 尝试 B: 自动查找本地是否存在驱动 (Downloads文件夹等)
                local_path = find_driver_automatically("Chrome")
                if local_path:
                    st.toast(f"✅ 在本地发现了驱动：{local_path}", icon="📂")
                    service = ChromeService(executable_path=local_path)
                    driver = webdriver.Chrome(service=service, options=options)
                else:
                    raise e_net
            
        elif browser_type == "Edge":
            options = webdriver.EdgeOptions()
            try:
                # 尝试 A: 自动下载 (可能被墙)
                service = EdgeService(EdgeChromiumDriverManager().install())
                driver = webdriver.Edge(service=service, options=options)
            except Exception as e_net:
                # 尝试 B: 自动查找本地
                local_path = find_driver_automatically("Edge")
                if local_path:
                    st.toast(f"✅ 在本地发现了驱动：{local_path}", icon="📂")
                    service = EdgeService(executable_path=local_path)
                    driver = webdriver.Edge(service=service, options=options)
                else:
                    # 尝试 C: 不指定Service，让Selenium 4.x自己尝试寻找
                    try:
                        driver = webdriver.Edge(options=options)
                    except:
                        raise e_net
            
        elif browser_type == "Safari":
            # Safari 是 Mac 原生，最稳定，无须下载
            if platform.system() != 'Darwin':
                st.error("Safari 仅支持 Mac 系统")
                return None, None
            try:
                options = webdriver.SafariOptions()
                driver = webdriver.Safari(options=options)
            except Exception as e:
                st.error("启动 Safari 失败。请检查：屏幕左上角 Safari -> 偏好设置 -> 高级 -> 勾选'在菜单栏中显示开发菜单' -> 菜单栏'开发' -> 勾选'允许远程自动化'。")
                return None, None
            
        # 2. 打开微信
        driver.get("https://mp.weixin.qq.com/")
        status_placeholder.success("✅ 浏览器启动成功！请在弹出的窗口中扫码...")
        
        # 3. 循环检测登录
        max_wait = 180
        start_time
