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

# --- 核心：Playwright 自动登录逻辑 ---
def auto_login_playwright():
    """
    使用 Playwright 启动浏览器并监听登录状态
    """
    status_placeholder = st.empty()
    token = None
    cookie_string = None
    
    try:
        status_placeholder.info("🚀 正在启动 Chromium 浏览器...")
        
        with sync_playwright() as p:
            # 1. 启动浏览器 (headless=False 以便看到界面扫码)
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()

            status_placeholder.info("🔗 正在打开微信登录页...")
            page.goto("https://mp.weixin.qq.com/")
            
            status_placeholder.warning("📱 请拿起手机微信扫码登录 (请勿关闭浏览器)...")

            # 2. 循环检测 URL Token
            max_retries = 120  # 等待 120 秒
            for i in range(max_retries):
                # 检查浏览器是否被手动关闭
                if page.is_closed():
                    status_placeholder.error("浏览器已关闭，操作取消。")
                    return None, None
                    
                current_url = page.url
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
        status_placeholder.error(f"Playwright 启动失败: {str(e)}")
        st.markdown("💡 **提示**: 第一次使用请确保已运行命令安装浏览器内核:\n`playwright install`")
        return None, None
        
    return token, cookie_string

# --- 主程序 UI 逻辑 ---

# 初始化 session state
if 'wx_token' not in st.session_state:
    st.session_state['wx_token'] = ''
if 'wx_cookie' not in st.session_state:
    st.session_state['wx_cookie'] = ''

with st.sidebar:
    st.title("🤖 自动获取助手")
    st.caption("基于 Playwright (Chromium)")

    # 自动获取按钮
    if st.button("📢 唤起浏览器扫码", type="primary"):
        token, cookie = auto_login_playwright()
        if token and cookie:
            st.session_state['wx_token'] = token
            st.session_state['wx_cookie'] = cookie
            st.balloons()
            st.success("凭证已自动填入！")
            
            # 自动备份到桌面 (可选)
            try:
                home = os.path.expanduser("~")
                save_dir = os.path.join(home, "Desktop", "finance")
                if not os.path.exists(save_dir):
                    os.makedirs(save_dir)
                with open(os.path.join(save_dir, "weixin_config_backup.txt"), "w") as f:
                    f.write(f"Token:\n{token}\n\nCookie:\n{cookie}")
            except:
                pass 
                
            time.sleep(1)
            st.rerun()
    
    st.divider()
    
    with st.expander("🔑 凭证配置", expanded=True):
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
            status.update(label="未找到账号，可能是Cookie已失效，请重新扫码", state="error")
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
    st.info("👈 点击左侧 **'唤起浏览器扫码'** 开始。")
