import streamlit as st
import pandas as pd
import requests
import time
import random
import datetime
from bs4 import BeautifulSoup
import os
from urllib.parse import urlparse, parse_qs
import shutil
import subprocess
import sys

# --- 新增：Playwright 库 ---
from playwright.sync_api import sync_playwright

# --- 页面配置 ---
st.set_page_config(
    page_title="WeChat Insight Pro",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 核心爬虫逻辑 (负责抓取数据) ---
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
        """搜索公众号获取fakeid"""
        search_url = "https://mp.weixin.qq.com/cgi-bin/searchbiz"
        params = {
            "action": "search_biz", "token": self.token, "lang": "zh_CN",
            "f": "json", "ajax": "1", "query": query, "begin": "0", "count": "5",
        }
        try:
            res = self.session.get(search_url, params=params)
            data = res.json()
            # 检查是否有权限错误
            if "base_resp" in data and data["base_resp"]["ret"] != 0:
                st.error(f"微信接口报错: {data['base_resp']}")
                return []
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
                time.sleep(random.uniform(1.0, 2.0))
            except:
                break
        
        progress_bar.empty()
        status_text.empty()
        return all_articles

    def fetch_article_content(self, url):
        """深度采集：访问详情页获取正文"""
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

# --- 辅助函数：强力安装浏览器内核及依赖 ---
def force_install_playwright(install_deps=False):
    """
    针对 Streamlit 环境的强制安装脚本
    install_deps=True 时会尝试安装系统级依赖 (需要 sudo 权限)
    """
    try:
        # 使用当前运行 Streamlit 的 Python 解释器去安装，确保环境一致
        if install_deps:
            # 安装系统依赖 (对应 sudo playwright install-deps)
            cmd = [sys.executable, "-m", "playwright", "install-deps"]
        else:
            # 安装浏览器内核 (对应 playwright install chromium)
            cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
            
        process = subprocess.run(cmd, capture_output=True, text=True)
        
        if process.returncode != 0:
            return False, process.stderr
        return True, "安装成功"
    except Exception as e:
        return False, str(e)

# --- 核心：Playwright 自动登录逻辑 ---
def auto_login_playwright():
    """
    使用 Playwright 启动浏览器并监听登录状态
    包含自动安装内核的容错逻辑
    """
    status_placeholder = st.empty()
    token = None
    cookie_string = None
    
    status_placeholder.info("🚀 正在启动浏览器引擎...")
    
    try:
        with sync_playwright() as p:
            # 1. 尝试启动浏览器
            try:
                browser = p.chromium.launch(headless=False)
            except Exception as e:
                # 捕获浏览器错误，进行自动修复
                error_msg = str(e)
                
                # 情况 A: 缺少浏览器内核 (Executable doesn't exist)
                if "Executable doesn't exist" in error_msg:
                    status_placeholder.warning("⚙️ 检测到浏览器内核缺失，正在自动下载 (约需 1-2 分钟)...")
                    success, msg = force_install_playwright(install_deps=False)
                    if success:
                        status_placeholder.success("✅ 内核安装完成！正在启动...")
                        browser = p.chromium.launch(headless=False)
                    else:
                        status_placeholder.error(f"❌ 自动安装失败: {msg}")
                        return None, None
                        
                # 情况 B: 缺少系统依赖 (Host system is missing dependencies)
                elif "Host system is missing dependencies" in error_msg:
                    status_placeholder.warning("⚙️ 检测到系统组件缺失，正在尝试自动修复...")
                    
                    # 尝试自动安装依赖
                    success, msg = force_install_playwright(install_deps=True)
                    
                    if success:
                        status_placeholder.success("✅ 系统组件修复完成！正在启动...")
                        browser = p.chromium.launch(headless=False)
                    else:
                        # 自动修复失败（通常因为需要输入密码），给用户提供最简单的复制命令
                        status_placeholder.error("❌ 自动修复失败（权限不足）。请复制下方命令到终端运行：")
                        st.code("sudo playwright install-deps", language="bash")
                        st.caption("提示：在终端粘贴并回车后，输入您的开机密码即可（输入时密码不显示）。")
                        return None, None
                else:
                    raise e

            context = browser.new_context()
            page = context.new_page()

            status_placeholder.info("🔗 正在打开微信登录页...")
            page.goto("https://mp.weixin.qq.com/")
            
            status_placeholder.warning("📱 请拿起手机微信扫码登录 (请勿关闭浏览器)...")

            # 2. 循环检测 URL Token
            max_retries = 120  # 等待 120 秒
            for i in range(max_retries):
                # 检查浏览器是否被手动关闭
                if not page.context.pages: # 简单的检查方式
                    status_placeholder.error("浏览器已关闭，操作取消。")
                    return None, None
                
                try:
                    if page.is_closed():
                         status_placeholder.error("浏览器已关闭，操作取消。")
                         return None, None
                    current_url = page.url
                except:
                    status_placeholder.error("浏览器连接断开。")
                    return None, None

                if "token=" in current_url:
                    status_placeholder.success(f"✅ 登录成功！正在提取凭证... ({i}s)")
                    
                    # A. 提取 Token
                    parsed_url = urlparse(current_url)
                    params = parse_qs(parsed_url.query)
                    token = params.get("token", [""])[0]
                    
                    # B. 提取 Cookies
                    cookies_list = context.cookies()
                    cookie_string = "; ".join([f"{cookie['name']}={cookie['value']}" for cookie in cookies_list])
                    
                    # 稍等片刻确保数据稳定
                    time.sleep(1)
                    break
                else:
                    time.sleep(1)
            
            if not token:
                status_placeholder.error("⏰ 登录超时，请重试。")
            
            browser.close()
            
    except Exception as e:
        status_placeholder.error(f"启动失败: {str(e)}")
        return None, None
        
    return token, cookie_string
