import streamlit as st
import pandas as pd
import requests
import time
import random
import os
import sys
import subprocess
import jieba
import matplotlib.pyplot as plt
import collections
from wordcloud import WordCloud
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright
from io import BytesIO
import base64

# --- 页面基础配置 ---
st.set_page_config(
    page_title="高校公众号舆情分析系统",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 解决 Matplotlib 中文乱码 (尽可能尝试多种字体)
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'PingFang SC', 'Heiti TC', 'Microsoft YaHei', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

# ==========================================
# 核心工具类
# ==========================================

def get_chinese_font_path():
    """
    尝试获取系统中的中文字体路径，用于 WordCloud
    """
    system = sys.platform
    font_paths = []
    
    if system == "darwin": # MacOS
        font_paths = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
        ]
    elif system == "win32": # Windows
        font_paths = [
            "C:\\Windows\\Fonts\\simhei.ttf",
            "C:\\Windows\\Fonts\\msyh.ttc",
            "C:\\Windows\\Fonts\\simsun.ttc"
        ]
    else: # Linux (Streamlit Cloud)
        font_paths = [
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
        ]
        
    for path in font_paths:
        if os.path.exists(path):
            return path
            
    return None # 如果没找到，词云可能会显示方框，但不会报错

def clean_wechat_html(html_content):
    """
    [Bug修复] 深度清洗微信HTML，确保图片显示和排版正常
    """
    if not html_content:
        return "<div style='padding:20px; text-align:center; color:#999'>📭 正文内容为空</div>"
    
    soup = BeautifulSoup(html_content, "html.parser")
    
    # 1. 移除 script 标签，防止执行恶意代码
    for script in soup(["script", "style"]):
        script.decompose()

    # 2. 破解图片防盗链 & 修复懒加载 (关键步骤)
    for img in soup.find_all("img"):
        # 微信图片通常放在 data-src 中
        if "data-src" in img.attrs:
            img["src"] = img["data-src"]
        
        # 必须添加 no-referrer，否则微信服务器会返回 403 Forbidden (裂图)
        img["referrerpolicy"] = "no-referrer"
        
        # 强制样式：自适应宽度，居中
        img["style"] = "max-width: 100% !important; height: auto !important; display: block; margin: 15px auto; border-radius: 6px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);"

    # 3. 优化排版容器
    # 注入一个基础样式，模拟微信阅读体验
    wrapper = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif;
                line-height: 1.8;
                color: #333;
                background-color: #fff;
                margin: 0;
                padding: 10px;
                font-size: 16px;
                text-align: justify;
            }}
            p {{ margin-bottom: 20px; }}
            strong {{ color: #000; font-weight: 700; }}
            blockquote {{
                border-left: 4px solid #07c160;
                background-color: #f8f8f8;
                margin: 20px 0;
                padding: 15px;
                color: #666;
            }}
        </style>
    </head>
    <body>
        <div id="js_content">
            {str(soup)}
        </div>
    </body>
    </html>
    """
    return wrapper

def generate_wordcloud_img(text_data):
    """
    生成词云图片对象
    """
    if not text_data:
        return None, []
        
    font_path = get_chinese_font_path()
    
    # 使用 jieba 分词
    words = jieba.cut(text_data)
    # 过滤停用词 (这里简单过滤单字和常见虚词)
    filtered_words = [w for w in words if len(w) > 1 and w not in ['的', '了', '和', '是', '就', '都', '而', '及', '与', '在', '为', '对', '等', '篇', '微', '信', '号', '月', '日', '年', '有', '我', '他', '她', '它', '这', '那']]
    space_split_text = " ".join(filtered_words)
    
    if not space_split_text.strip():
        return None, []

    try:
        wc = WordCloud(
            font_path=font_path,
            width=800,
            height=400,
            background_color='white',
            max_words=100,
            colormap='viridis',
            prefer_horizontal=0.9
        ).generate(space_split_text)
        
        return wc, filtered_words
    except Exception as e:
        print(f"词云生成失败: {e}")
        return None, []

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
        url = "https://mp.weixin.qq.com/cgi-bin/searchbiz"
        params = {
            "action": "search_biz", "token": self.token, "lang": "zh_CN",
            "f": "json", "ajax": "1", "query": "test", "begin": "0", "count": "1"
        }
        try:
            res = self.session.get(url, params=params)
            data = res.json()
            if "base_resp" in data and data["base_resp"]["ret"] != 0:
                return False, f"Token 失效或 Cookie 过期: {data['base_resp']}"
            return True, "验证通过"
        except:
            return False, "网络连接异常"

    def search_account(self, query):
        search_url = "https://mp.weixin.qq.com/cgi-bin/searchbiz"
        params = {
            "action": "search_biz", "token": self.token, "lang": "zh_CN",
            "f": "json", "ajax": "1", "query": query, "begin": "0", "count": "5",
        }
        try:
            res = self.session.get(search_url, params=params, timeout=10)
            data = res.json()
            return data.get("list", [])
        except:
            return []

    def fetch_article_list(self, fakeid, pages=1):
        all_articles = []
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
                time.sleep(random.uniform(1.0, 2.0))
            except:
                break
        return all_articles

    def fetch_content(self, url):
        try:
            res = self.session.get(url, timeout=15)
            # 使用 html.parser 兼容性更好
            soup = BeautifulSoup(res.text, "html.parser")
            
            # 尝试获取正文容器，微信通常是 js_content
            content_div = soup.find("div", {"id": "js_content"}) or soup.find("div", {"class": "rich_media_content"})
            
            if content_div:
                final_html = clean_wechat_html(str(content_div))
                
                # 提取纯文本用于词云分析
                plain_text = content_div.get_text(strip=True)
            else:
                final_html = "<div>解析失败，可能文章已删除或需要特殊权限</div>"
                plain_text = ""
            
            author_tag = soup.find("strong", {"class": "profile_nickname"}) or soup.find("a", {"id": "js_name"})
            author = author_tag.get_text().strip() if author_tag else "未知"
            
            return final_html, author, plain_text
        except Exception:
            return "", "获取失败", ""

# ==========================================
# 自动化登录模块 (确保无头模式)
# ==========================================

def force_install_chromium():
    try:
        cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except:
        return False

def auto_login_browser():
    status_box = st.empty()
    qr_box = st.empty()
    token = None
    cookie_str = None

    status_box.info("🚀 正在启动自动化引擎 (高清云端模式)...")

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as e:
                if "Executable doesn't exist" in str(e):
                    status_box.warning("⚙️ 正在安装浏览器内核...")
                    if force_install_chromium():
                         status_box.success("✅ 安装成功！重试中...")
                         browser = p.chromium.launch(headless=True)
                    else:
                         return None, None
                else:
                    raise e

            context = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = context.new_page()

            status_box.info("🔗 正在加载微信登录页...")
            page.goto("https://mp.weixin.qq.com/")
            
            try:
                page.wait_for_selector(".login__type__container__scan", timeout=15000)
            except:
                pass 

            status_box.warning("📱 请使用手机微信扫码 (二维码已放大):")
            
            max_wait = 120
            for i in range(max_wait):
                try:
                    if page.is_closed(): return None, None
                    current_url = page.url
                except: return None, None

                if i % 1.5 == 0 and "token=" not in current_url:
                    try:
                        qr_elem = page.locator(".login__type__container__scan")
                        if qr_elem.count() > 0:
                            screenshot_bytes = qr_elem.screenshot()
                            qr_box.image(screenshot_bytes, caption="📸 请扫码 (实时画面)", width=400)
                        else:
                            screenshot_bytes = page.screenshot()
                            qr_box.image(screenshot_bytes, caption="📸 请扫码 (全屏备用)", width=600)
                    except:
                        pass

                if "token=" in current_url:
                    qr_box.empty()
                    status_box.success(f"✅ 登录成功！")
                    
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
        status_box.error(f"❌ 运行错误: {e}")
        return None, None

    return token, cookie_str

# ==========================================
# Streamlit 主界面
# ==========================================

if 'wx_token' not in st.session_state: st.session_state['wx_token'] = ''
if 'wx_cookie' not in st.session_state: st.session_state['wx_cookie'] = ''
if 'all_data' not in st.session_state: st.session_state['all_data'] = None

with st.sidebar:
    st.title("🎓 高校舆情分析 Pro")
    st.caption("Playwright 驱动 · Jieba 分词 · 可视化")
    st.markdown("---")
    
    # 登录区
    if st.button("📢 1. 扫码获取权限", type="primary", use_container_width=True):
        token, cookie = auto_login_browser()
        if token and cookie:
            st.session_state['wx_token'] = token
            st.session_state['wx_cookie'] = cookie
            st.success("权限获取成功！")
            time.sleep(1)
            st.rerun()

    with st.expander("🔑 凭证管理", expanded=True):
        token_input = st.text_input("Token", value=st.session_state['wx_token'])
        cookie_input = st.text_area("Cookie", value=st.session_state['wx_cookie'], height=100)
        
        if token_input != st.session_state['wx_token']: st.session_state['wx_token'] = token_input
        if cookie_input != st.session_state['wx_cookie']: st.session_state['wx_cookie'] = cookie_input

    st.markdown("---")
    # 设置区
    targets_input = st.text_area(
        "2. 输入高校公众号 (一行一个)", 
        placeholder="清华大学\n北京大学\n复旦大学",
        height=150
    )
    
    page_count = st.slider("抓取页数 (每页5篇)", 1, 10, 2)
    run_btn = st.button("🚀 3. 开始抓取与分析", use_container_width=True)

# --- 主逻辑区 ---

if run_btn:
    if not token_input or not cookie_input:
        st.error("请先获取 Token 和 Cookie！")
        st.stop()
    if not targets_input.strip():
        st.error("请输入至少一个公众号！")
        st.stop()
        
    target_list = [line.strip() for line in targets_input.split('\n') if line.strip()]
    crawler = WechatCrawler(token_input, cookie_input)
    
    all_results = []
    
    # 采集进度
    status_container = st.status("正在进行多校数据采集...", expanded=True)
    progress_bar = st.progress(0)
    
    with status_container:
        # 验证
        if not crawler.check_auth()[0]:
            st.error("权限验证失败，请重新扫码！")
            st.stop()
            
        total_targets = len(target_list)
        for i, target_name in enumerate(target_list):
            st.write(f"🔄 [{i+1}/{total_targets}] 分析: **{target_name}** ...")
            
            # 搜索
            accounts = crawler.search_account(target_name)
            if not accounts:
                st.warning(f"⚠️ 未找到: {target_name}，跳过")
                continue
            
            target_account = accounts[0]
            fakeid = target_account['fakeid']
            real_nickname = target_account['nickname']
            
            # 列表
            articles = crawler.fetch_article_list(fakeid, pages=page_count)
            
            # 正文详情 (用于词云)
            if articles:
                st.write(f"   - 抓取正文 ({len(articles)}篇)...")
                for art in articles:
                    html_content, author, plain_text = crawler.fetch_content(art['link'])
                    art['content_html'] = html_content # 用于显示
                    art['plain_text'] = plain_text # 用于分词
                    art['author'] = author
                    # 补充元数据
                    art['account_name'] = real_nickname
                    time.sleep(0.5)

            all_results.extend(articles)
            progress_bar.progress((i + 1) / total_targets)
            time.sleep(random.uniform(1.5, 3.0))
            
        status_container.update(label="✅ 采集与分析完成！", state="complete")
    
    # 存入 Session
    if all_results:
        df = pd.DataFrame(all_results)
        df['发布时间'] = pd.to_datetime(df['create_time'], unit='s')
        df['发布日期'] = df['发布时间'].dt.date
        df['类型'] = df['copyright_type'].apply(lambda x: '原创' if x == 1 else '转载')
        st.session_state['all_data'] = df
    else:
        st.warning("未采集到数据。")

# --- 分析看板 ---

if st.session_state['all_data'] is not None:
    df = st.session_state['all_data']
    
    st.divider()
    st.title("📊 高校新媒体大数据看板")
    
    # ----------------------------------------------------
    # 1. 宏观数据分析 (所有学校)
    # ----------------------------------------------------
    st.header("1. 全网综合舆情 (All Schools)")
    
    tab_global_1, tab_global_2, tab_global_3 = st.tabs(["☁️ 综合词云", "🏆 影响力排行", "📈 发文趋势"])
    
    with tab_global_1:
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            st.subheader("全网·标题词云")
            all_titles = " ".join(df['title'].tolist())
            wc_title, _ = generate_wordcloud_img(all_titles)
            if wc_title:
                st.image(wc_title.to_array(), use_container_width=True)
            else:
                st.info("数据不足生成词云")
                
        with col_g2:
            st.subheader("全网·内容词云")
            all_contents = " ".join(df['plain_text'].fillna("").tolist())
            wc_content, words_list = generate_wordcloud_img(all_contents)
            if wc_content:
                st.image(wc_content.to_array(), use_container_width=True)
                
            # 全网 TOP 10 关键词
            if words_list:
                st.caption("🔥 全网 TOP 10 热词:")
                counts = collections.Counter(words_list)
                top10 = counts.most_common(10)
                st.write(" | ".join([f"**{w}**({c})" for w, c in top10]))

    with tab_global_2:
        st.subheader("高校活跃度排行榜 (按发文量)")
        st.caption("注：微信PC接口无法获取竞品文章的阅读量/点赞数，故此处展示【发文活跃度】排行。")
        
        # 本周/本月计算
        now = pd.Timestamp.now()
        one_week_ago = now - pd.Timedelta(days=7)
        one_month_ago = now - pd.Timedelta(days=30)
        
        df['dt'] = pd.to_datetime(df['create_time'], unit='s')
        
        col_r1, col_r2 = st.columns(2)
        with col_r1:
            st.markdown("#### 📅 本周发文榜")
            week_df = df[df['dt'] > one_week_ago]
            if not week_df.empty:
                week_rank = week_df['account_name'].value_counts().reset_index()
                week_rank.columns = ['高校名称', '发文数']
                st.dataframe(week_rank, use_container_width=True, hide_index=True)
            else:
                st.info("本周无发文")
                
        with col_r2:
            st.markdown("#### 🗓️ 本月发文榜")
            month_df = df[df['dt'] > one_month_ago]
            if not month_df.empty:
                month_rank = month_df['account_name'].value_counts().reset_index()
                month_rank.columns = ['高校名称', '发文数']
                st.dataframe(month_rank, use_container_width=True, hide_index=True)
            else:
                st.info("本月无发文")

    with tab_global_3:
        st.subheader("全网发布时间分布")
        # 按日期统计
        date_counts = df.groupby('发布日期').size()
        st.line_chart(date_counts)

    st.markdown("---")

    # ----------------------------------------------------
    # 2. 个体画像分析 (每个学校)
    # ----------------------------------------------------
    st.header("2. 单校深度画像 (Single School)")
    
    school_list = df['account_name'].unique()
    selected_school = st.selectbox("👉 选择一所高校查看详情:", school_list)
    
    if selected_school:
        sub_df = df[df['account_name'] == selected_school]
        
        # 2.1 统计指标
        c1, c2, c3 = st.columns(3)
        c1.metric("总发文数", len(sub_df))
        c2.metric("原创比例", f"{len(sub_df[sub_df['类型']=='原创']) / len(sub_df) * 100:.1f}%" if len(sub_df)>0 else "0%")
        c3.metric("最新发布", str(sub_df['发布日期'].max()))
        
        # 2.2 词云与TOP10
        tab_s1, tab_s2, tab_s3 = st.tabs(["☁️ 专属词云", "📊 文章列表", "👓 阅读正文"])
        
        with tab_s1:
            sc1, sc2 = st.columns(2)
            with sc1:
                st.markdown("**标题词云**")
                s_titles = " ".join(sub_df['title'].tolist())
                s_wc_t, _ = generate_wordcloud_img(s_titles)
                if s_wc_t: st.image(s_wc_t.to_array(), use_container_width=True)
                
            with sc2:
                st.markdown("**内容词云**")
                s_content = " ".join(sub_df['plain_text'].fillna("").tolist())
                s_wc_c, s_words = generate_wordcloud_img(s_content)
                if s_wc_c: 
                    st.image(s_wc_c.to_array(), use_container_width=True)
                    st.markdown("---")
                    # TOP 10
                    s_counts = collections.Counter(s_words)
                    s_top10 = s_counts.most_common(10)
                    st.write("🔥 **校内TOP10热词:**")
                    st.json(dict(s_top10))
        
        with tab_s2:
            st.dataframe(
                sub_df[['title', '发布时间', '类型', 'digest']], 
                use_container_width=True
            )
            
        with tab_s3:
            # 阅读器
            if 'content_html' in sub_df.columns:
                read_idx = st.selectbox("选择文章阅读:", sub_df.index, format_func=lambda x: sub_df.loc[x, 'title'])
                read_art = sub_df.loc[read_idx]
                
                with st.container(border=True):
                    st.markdown(f"### {read_art['title']}")
                    st.caption(f"作者: {read_art['author']} | 时间: {read_art['发布时间']}")
                    st.components.v1.html(read_art['content_html'], height=800, scrolling=True)
            else:
                st.warning("无正文数据")
else:
    st.info("👈 请在左侧侧边栏进行操作：扫码 -> 输入高校名称 -> 开始分析")
