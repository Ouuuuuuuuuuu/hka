import streamlit as st
import pandas as pd
import requests
import time
import random
import os
import sys
import subprocess
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright

# --- 页面基础配置 ---
st.set_page_config(
    page_title="公众号批量采集 & 分析神器",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# 核心工具类：负责搞定数据和HTML清洗
# ==========================================

def clean_wechat_html(html_content):
    """
    清洗微信HTML，破解图片防盗链，适配网页显示
    """
    if not html_content:
        return "<div style='padding:20px; text-align:center; color:#999'>📭 正文内容为空</div>"
    
    soup = BeautifulSoup(html_content, "html.parser")
    
    # 1. 破解图片防盗链 & 修复懒加载
    for img in soup.find_all("img"):
        if "data-src" in img.attrs:
            img["src"] = img["data-src"]
        
        # 强制样式：自适应宽度
        img["style"] = "max-width: 100% !important; height: auto !important; display: block; margin: 10px auto; border-radius: 4px;"
        img["referrerpolicy"] = "no-referrer"

    # 2. 移除视频 iframe
    for iframe in soup.find_all("iframe"):
        iframe["style"] = "width: 100%; height: 300px; border: 1px solid #eee; background: #f9f9f9;"

    wrapper = f"""
    <div style="
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        line-height: 1.8;
        color: #333;
        font-size: 16px;
        padding: 10px;
        background-color: #fff;
    ">
        {str(soup)}
    </div>
    """
    return wrapper

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

    def check_auth(self):
        """简单验证 Token 是否有效"""
        url = "https://mp.weixin.qq.com/cgi-bin/searchbiz"
        params = {
            "action": "search_biz", "token": self.token, "lang": "zh_CN",
            "f": "json", "ajax": "1", "query": "test", "begin": "0", "count": "1"
        }
        try:
            res = self.session.get(url, params=params)
            data = res.json()
            if "base_resp" in data and data["base_resp"]["ret"] != 0:
                return False, f"验证失败: {data['base_resp']}"
            return True, "验证通过"
        except:
            return False, "网络连接异常"

    def search_account(self, query):
        """搜索公众号"""
        search_url = "https://mp.weixin.qq.com/cgi-bin/searchbiz"
        params = {
            "action": "search_biz", "token": self.token, "lang": "zh_CN",
            "f": "json", "ajax": "1", "query": query, "begin": "0", "count": "5",
        }
        try:
            res = self.session.get(search_url, params=params, timeout=10)
            data = res.json()
            return data.get("list", [])
        except Exception as e:
            st.error(f"❌ 搜索失败: {e}")
            return []

    def fetch_article_list(self, fakeid, pages=1):
        """获取文章列表"""
        all_articles = []
        
        # 这里的进度条由外部控制，这里只负责抓取
        for page in range(pages):
            params = {
                "token": self.token, "lang": "zh_CN", "f": "json", "ajax": "1",
                "action": "list_ex", "fakeid": fakeid, "query": "",
                "begin": str(page * 5), "count": "5", "type": "9",
            }
            try:
                res = self.session.get(self.base_url, params=params, timeout=10)
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
                            "copyright_type": item.get("copyright_type", 0)
                        })
                else:
                    break 
                time.sleep(random.uniform(1.5, 3.0)) # 稍微调大延时，批量抓取更安全
            except:
                break
        return all_articles

    def fetch_content(self, url):
        """采集正文 HTML"""
        try:
            res = self.session.get(url, timeout=15)
            soup = BeautifulSoup(res.text, "html.parser")
            content_div = soup.find("div", {"id": "js_content"})
            
            if content_div:
                final_html = clean_wechat_html(str(content_div))
            else:
                final_html = "<p>无法解析正文结构</p>"
            
            author_tag = soup.find("strong", {"class": "profile_nickname"})
            author = author_tag.get_text().strip() if author_tag else "未知"
            
            return final_html, author
        except Exception:
            return "", "获取失败"

# ==========================================
# 自动化工具类
# ==========================================

def force_install_chromium():
    try:
        cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except Exception as e:
        return False

def auto_login_browser():
    status_box = st.empty()
    token = None
    cookie_str = None

    status_box.info("🚀 正在启动自动化引擎，请稍候...")

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=False)
            except Exception as e:
                if "Executable doesn't exist" in str(e):
                    status_box.warning("⚙️ 首次运行，正在自动安装浏览器内核...")
                    if force_install_chromium():
                         status_box.success("✅ 安装成功！")
                         browser = p.chromium.launch(headless=False)
                    else:
                         return None, None
                else:
                    raise e

            context = browser.new_context()
            page = context.new_page()

            status_box.info("🔗 正在打开微信公众平台...")
            page.goto("https://mp.weixin.qq.com/")

            status_box.warning("📱 请看浏览器窗口 -> 用微信扫码登录")
            
            max_wait = 120
            for i in range(max_wait):
                try:
                    if page.is_closed(): return None, None
                    current_url = page.url
                except: return None, None

                if "token=" in current_url:
                    status_box.success(f"✅ 登录成功！正在提取密钥... ({i}s)")
                    parsed = urlparse(current_url)
                    token = parse_qs(parsed.query).get("token", [""])[0]
                    cookies = context.cookies()
                    cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
                    time.sleep(1)
                    break
                else:
                    time.sleep(1)
            
            browser.close()
            
    except Exception as e:
        status_box.error(f"❌ 启动失败: {e}")
        return None, None

    return token, cookie_str

# ==========================================
# Streamlit 主界面
# ==========================================

if 'wx_token' not in st.session_state: st.session_state['wx_token'] = ''
if 'wx_cookie' not in st.session_state: st.session_state['wx_cookie'] = ''
if 'all_data' not in st.session_state: st.session_state['all_data'] = None

with st.sidebar:
    st.title("📊 批量采集分析")
    st.caption("支持多账号 · 聚合分析 · 图文还原")
    st.markdown("---")
    
    st.markdown("### 1. 获取权限")
    if st.button("📢 唤起浏览器扫码", type="primary", use_container_width=True):
        token, cookie = auto_login_browser()
        if token and cookie:
            st.session_state['wx_token'] = token
            st.session_state['wx_cookie'] = cookie
            st.balloons()
            st.success("🎉 获取成功！凭证已填入。")
            time.sleep(1)
            st.rerun()

    with st.expander("🔑 凭证管理", expanded=True):
        token_input = st.text_input("Token", value=st.session_state['wx_token'])
        cookie_input = st.text_area("Cookie", value=st.session_state['wx_cookie'], height=100)
        
        if token_input != st.session_state['wx_token']: st.session_state['wx_token'] = token_input
        if cookie_input != st.session_state['wx_cookie']: st.session_state['wx_cookie'] = cookie_input

    st.markdown("---")
    st.markdown("### 2. 批量设置")
    
    # 批量输入框
    targets_input = st.text_area(
        "输入公众号名称 (一行一个，最多20个)", 
        placeholder="36氪\n虎嗅APP\n晚点LatePost",
        height=150
    )
    
    page_count = st.slider("每个号抓取页数 (每页5篇)", 1, 5, 2, help="抓取太多页可能会触发微信风控")
    need_detail = st.checkbox("深度采集正文", value=True)
    
    run_btn = st.button("🚀 开始批量采集", use_container_width=True)

# --- 主逻辑区 ---

if run_btn:
    if not token_input or not cookie_input:
        st.error("❌ 请先扫码获取权限！")
        st.stop()
    if not targets_input.strip():
        st.error("❌ 请输入至少一个公众号名称！")
        st.stop()
        
    target_list = [line.strip() for line in targets_input.split('\n') if line.strip()]
    if len(target_list) > 20:
        st.warning(f"⚠️ 输入了 {len(target_list)} 个账号，自动截取前 20 个。")
        target_list = target_list[:20]
        
    crawler = WechatCrawler(token_input, cookie_input)
    
    all_results = []
    
    # 全局容器
    status_container = st.status("正在初始化采集任务...", expanded=True)
    progress_bar = st.progress(0)
    
    with status_container:
        # 1. 验证权限
        st.write("🔐 验证身份权限...")
        is_valid, msg = crawler.check_auth()
        if not is_valid:
            status_container.update(label="身份验证失败", state="error")
            st.error(msg)
            st.stop()
            
        st.write(f"📋 任务队列: 共 {len(target_list)} 个公众号")
        
        # 2. 循环抓取
        for i, target_name in enumerate(target_list):
            st.write(f"🔄 [{i+1}/{len(target_list)}] 正在处理: **{target_name}** ...")
            
            # 搜索账号
            accounts = crawler.search_account(target_name)
            if not accounts:
                st.warning(f"⚠️ 未找到公众号: {target_name}，跳过。")
                continue
                
            # 默认取第一个匹配项
            target_account = accounts[0]
            fakeid = target_account['fakeid']
            real_nickname = target_account['nickname']
            
            # 抓取列表
            articles = crawler.fetch_article_list(fakeid, pages=page_count)
            st.write(f"   - 获取到 {len(articles)} 篇文章摘要")
            
            # 深度采集
            if need_detail and articles:
                st.write(f"   - 正在下载正文 ({len(articles)}篇)...")
                # 简单的内部进度
                for art in articles:
                    html_content, author = crawler.fetch_content(art['link'])
                    art['content_html'] = html_content
                    art['author'] = author
                    time.sleep(0.5) # 避免由于请求过快导致IP被封
            
            # 补充元数据
            for art in articles:
                art['account_name'] = real_nickname
                art['keyword'] = target_name
                
            all_results.extend(articles)
            
            # 更新总进度
            progress_bar.progress((i + 1) / len(target_list))
            
            # 账号间延时，防风控
            time.sleep(random.uniform(2.0, 4.0))
            
        status_container.update(label="✅ 所有任务执行完毕！", state="complete")
    
    # 处理数据
    if all_results:
        df = pd.DataFrame(all_results)
        df['发布时间'] = pd.to_datetime(df['create_time'], unit='s')
        df['发布日期'] = df['发布时间'].dt.date
        df['类型'] = df['copyright_type'].apply(lambda x: '原创' if x == 1 else '转载')
        st.session_state['all_data'] = df
    else:
        st.warning("未采集到任何有效数据。")

# --- 分析展示区 ---

if st.session_state['all_data'] is not None:
    df = st.session_state['all_data']
    
    st.divider()
    st.title("📈 全网数据分析看板")
    
    # 概览指标
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("公众号数量", df['account_name'].nunique())
    c2.metric("文章总数", len(df))
    c3.metric("原创文章", len(df[df['类型']=='原创']))
    c4.metric("最早发布", str(df['发布日期'].min()))
    
    tab_analysis, tab_data, tab_read = st.tabs(["📊 图表分析", "📋 数据明细", "👓 阅读文章"])
    
    with tab_analysis:
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("各公众号发文量对比")
            count_data = df['account_name'].value_counts()
            st.bar_chart(count_data)
            
        with col2:
            st.subheader("原创 vs 转载 比例")
            type_counts = df['类型'].value_counts()
            st.bar_chart(type_counts, horizontal=True, color="#ffaa00")
            
        st.subheader("发布时间分布 (按日期)")
        time_chart = df.groupby('发布日期').size()
        st.line_chart(time_chart)
        
    with tab_data:
        # 数据表
        display_cols = ['account_name', 'title', '发布时间', '类型', 'digest', 'link']
        if 'author' in df.columns: display_cols.insert(2, 'author')
        
        st.dataframe(
            df[display_cols],
            column_config={
                "link": st.column_config.LinkColumn("链接"),
                "account_name": "公众号",
                "title": "标题"
            },
            use_container_width=True
        )
        
        # 下载
        csv = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            "📥 下载所有数据 (CSV)",
            data=csv,
            file_name='wechat_batch_data.csv',
            mime='text/csv',
            type="primary"
        )
        
    with tab_read:
        if 'content_html' in df.columns:
            # 级联选择器
            sel_account = st.selectbox("选择公众号", df['account_name'].unique())
            sub_df = df[df['account_name'] == sel_account]
            
            sel_article_idx = st.selectbox(
                "选择文章", 
                sub_df.index, 
                format_func=lambda x: f"{sub_df.loc[x, '发布时间']} | {sub_df.loc[x, 'title']}"
            )
            
            if sel_article_idx is not None:
                article = df.loc[sel_article_idx]
                with st.container(border=True):
                    st.markdown(f"## {article['title']}")
                    st.caption(f"📅 {article['发布时间']} | 👤 {article.get('author','')} | 🏷️ {article['类型']}")
                    st.divider()
                    st.components.v1.html(article['content_html'], height=600, scrolling=True)
        else:
            st.info("未采集正文数据")
else:
    st.info("👋 请在左侧输入公众号并开始采集，数据将在此处展示。")
