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
import re
import json
from wordcloud import WordCloud
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright
from io import BytesIO
import base64

# --- 页面基础配置 ---
st.set_page_config(
    page_title="公众号舆情分析系统",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# 字体管理 (解决中文乱码)
# ==========================================

def get_font_path():
    """
    获取中文字体路径。如果系统没有，尝试下载 SimHei。
    """
    local_font = "SimHei.ttf"
    if os.path.exists(local_font):
        return local_font
    
    system_fonts = [
        "/System/Library/Fonts/PingFang.ttc", # MacOS
        "/System/Library/Fonts/STHeiti Light.ttc",
        "C:\\Windows\\Fonts\\simhei.ttf", # Windows
        "C:\\Windows\\Fonts\\msyh.ttc", 
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", # Linux
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    ]
    for path in system_fonts:
        if os.path.exists(path):
            return path
            
    try:
        url = "https://github.com/StellarCN/scp_zh/raw/master/fonts/SimHei.ttf"
        res = requests.get(url, timeout=30)
        with open(local_font, "wb") as f:
            f.write(res.content)
        return local_font
    except:
        pass
        
    return None

font_path = get_font_path()
if font_path:
    import matplotlib.font_manager as fm
    fe = fm.FontEntry(fname=font_path, name='CustomFont')
    fm.fontManager.ttflist.insert(0, fe)
    plt.rcParams['font.sans-serif'] = ['CustomFont']
else:
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

# ==========================================
# 核心工具类
# ==========================================

def clean_wechat_html(html_content):
    if not html_content:
        return "<div style='padding:20px; text-align:center; color:#999'>📭 正文内容为空</div>"
    
    soup = BeautifulSoup(html_content, "html.parser")
    
    content_div = soup.find("div", id="js_content")
    if content_div:
        existing_style = content_div.get('style', '')
        content_div['style'] = existing_style + '; visibility: visible !important; opacity: 1 !important;'
    
    for tag in soup(["script", "style", "iframe"]):
        tag.decompose()

    for img in soup.find_all("img"):
        if "data-src" in img.attrs:
            img["src"] = img["data-src"]
        img["referrerpolicy"] = "no-referrer"
        img["style"] = "max-width: 100% !important; height: auto !important; display: block; margin: 10px auto; border-radius: 4px;"

    wrapper = f"""
    <div style="
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
        line-height: 1.8;
        color: #333;
        font-size: 16px;
        background-color: #fff;
        padding: 15px;
    ">
        {str(soup)}
    </div>
    """
    return wrapper

def get_name_tokens(name_list):
    """
    对公众号名称列表进行分词，生成需要屏蔽的词集合
    """
    stop_tokens = set()
    for name in name_list:
        # 1. 添加全名
        stop_tokens.add(name)
        # 2. 结巴分词 (例如 '重庆德普外国语学校' -> '重庆', '德普', '外国语', '学校')
        tokens = jieba.lcut(name)
        for t in tokens:
            if len(t) > 1: # 只添加两个字以上的词
                stop_tokens.add(t)
        # 3. 尝试简单的简称规则 (取前两个字，后两个字)
        if len(name) >= 4:
            stop_tokens.add(name[:2]) # 例如 '重庆'
            stop_tokens.add(name[-2:]) # 例如 '学校'
    return stop_tokens

def generate_wordcloud_img(text_data, exclude_words=None):
    """
    生成词云图片对象
    exclude_words: 需要额外屏蔽的词列表 (list or set)
    """
    if not text_data:
        return None, []
        
    f_path = get_font_path()
    words = jieba.lcut(text_data)
    
    # 基础停用词表 (精简版)
    stop_words = set([
        '的', '了', '和', '是', '就', '都', '而', '及', '与', '在', '为', '对', '等', '篇', 
        '微', '信', '号', '月', '日', '年', '有', '我', '他', '她', '它', '这', '那',
        '我们', '图片', '来源', '原标', '题', '公众', '点击', '阅读', '原文', '下方', '关注',
        '展开', '全文', '视频', '分享', '收藏', '点赞', '在看', '扫码', '识别', '二维码',
        '官方', '平台', '发布', '资讯', '服务', '查看', '更多', '回复', '关键字',
        '学校', '教育', '学院', '大学', '中学', '小学', '幼儿园', '国际', '外国语', '校区' # 行业通用词保留屏蔽
        # 已移除：'老师', '学生', '家长', '同学', '孩子', '课程', '活动'，让这些词可以显示
    ])
    
    # 合并传入的自定义屏蔽词
    if exclude_words:
        stop_words.update(exclude_words)
    
    filtered_words = [w for w in words if len(w) > 1 and w not in stop_words]
    space_split_text = " ".join(filtered_words)
    
    if not space_split_text.strip():
        return None, []

    try:
        wc = WordCloud(
            font_path=f_path,
            width=800,
            height=400,
            background_color='white',
            max_words=150,
            colormap='viridis',
            prefer_horizontal=0.9
        ).generate(space_split_text)
        return wc, filtered_words
    except Exception as e:
        print(f"词云生成失败: {e}")
        return None, []

# ==========================================
# AI 分析模块 (SiliconFlow)
# ==========================================

def call_ai_analysis(data_df):
    """
    调用 SiliconFlow API 进行 AI 分析
    """
    # 1. 准备 Key (优先从 Secret 获取，否则使用默认)
    api_key = st.secrets.get("SILICONFLOW_API_KEY", "sk-lezqyzzxlcnarawzhmyddltuclijckeufnzzktmkizfslcje")
    
    # 2. 数据汇总与精简 (不再发送全文，而是提取摘要统计)
    summary_data = []
    
    # 获取需要屏蔽的账号名词，用于提取热词时排除
    all_accounts = data_df['account_name'].unique()
    stop_tokens = get_name_tokens(all_accounts) 
    # 添加一些基础停用词用于提取热词
    base_stops = {'的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这', '那', '有', '等', '为', '之', '与', '及', '以', '微', '信', '公众', '号', '扫码', '二维码', '关注', '阅读', '原文', '点击', '查看', '更多', '来源', '图片', '视频', '展开', '全文'}
    stop_tokens.update(base_stops)

    for account_name in all_accounts:
        sub_df = data_df[data_df['account_name'] == account_name]
        
        # 提取高频词 (基于标题和摘要，比较节省资源且能反映主题)
        text_content = " ".join(sub_df['title'].tolist() + sub_df['digest'].fillna("").tolist())
        words = jieba.lcut(text_content)
        words = [w for w in words if len(w) > 1 and w not in stop_tokens]
        top_keywords = [w for w, c in collections.Counter(words).most_common(8)] # 取前8个热词
        
        summary_data.append({
            "公众号名": account_name,
            "统计周期内发文数": len(sub_df),
            "最新发布日期": str(sub_df['发布时间'].max()),
            "文章标题列表": sub_df['title'].tolist(),
            "核心议题(热词)": top_keywords
        })
    
    data_json = json.dumps(summary_data, ensure_ascii=False, indent=2)
    
    # 3. 构造请求
    url = "https://api.siliconflow.cn/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # 优化后的 Prompt
    system_prompt = """你是一位资深的教育行业新媒体数据分析专家。
用户将提供一份JSON格式的汇总数据，包含多个公众号在近期的发文统计、标题列表及提取的高频热词。
请基于这些信息，撰写一份【深度舆情对比分析报告】。

报告应包含以下核心维度：
1. **核心议题概览**：结合标题和热词，分析各公众号近期关注的重点话题（如：招生宣传、校园活动、学术讲座、节日热点等）。
2. **活跃度与策略对比**：对比各账号的发文频率，分析其运营活跃度差异。
3. **内容风格洞察**：通过标题关键词分析各账号的行文风格（例如：标题党、学术严谨、亲民活泼等）。
4. **总结与建议**：为运营者提供基于数据的优化建议。

请务必在回答开头展示你的【思考过程】(Reasoning)，然后再输出结构清晰的最终报告。"""
    
    payload = {
        "model": "moonshotai/Kimi-K2-Thinking", 
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"这是各公众号的数据汇总，请进行分析：\n{data_json}"}
        ],
        "stream": False,
        "temperature": 0.7
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        if response.status_code == 200:
            res_json = response.json()
            choice = res_json.get('choices', [{}])[0]
            message = choice.get('message', {})
            content = message.get('content', '')
            reasoning = message.get('reasoning_content', '') 
            return True, content, reasoning
        else:
            return False, f"API 请求失败: {response.status_code} - {response.text}", ""
    except Exception as e:
        return False, f"发生错误: {str(e)}", ""

# ==========================================
# 爬虫类
# ==========================================

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
                time.sleep(random.uniform(0.5, 1.5))
            except:
                break
        return all_articles

    def fetch_content(self, url):
        try:
            res = self.session.get(url, timeout=15)
            soup = BeautifulSoup(res.text, "html.parser")
            content_div = soup.find("div", id="js_content")
            
            if content_div:
                final_html = clean_wechat_html(str(soup))
                plain_text = content_div.get_text(strip=True)
            else:
                final_html = clean_wechat_html(res.text)
                plain_text = ""
            
            author_tag = soup.find("strong", {"class": "profile_nickname"}) or soup.find("a", {"id": "js_name"})
            author = author_tag.get_text().strip() if author_tag else "未知"
            
            return final_html, author, plain_text
        except Exception:
            return "<div>获取失败</div>", "获取失败", ""

# ==========================================
# 自动化登录
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
    st.title("🎓 公众号舆情分析 Pro")
    st.caption("Playwright · 词云 · AI 深度思考")
    st.markdown("---")
    
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
    targets_input = st.text_area(
        "2. 输入公众号名称", 
        placeholder="支持中文逗号、顿号、空格或换行分隔\n例如：\n清华大学、北京大学，复旦大学",
        height=150
    )
    
    page_count = st.slider("每个号抓取页数 (每页5篇)", 1, 5, 2)
    run_btn = st.button("🚀 3. 开始分析", use_container_width=True)

# --- 主逻辑区 ---

if run_btn:
    if not token_input or not cookie_input:
        st.error("请先获取 Token 和 Cookie！")
        st.stop()
    if not targets_input.strip():
        st.error("请输入至少一个公众号！")
        st.stop()
        
    target_list = re.split(r'[,\s\n，、]+', targets_input.strip())
    target_list = [t for t in target_list if t]
    
    crawler = WechatCrawler(token_input, cookie_input)
    
    all_results = []
    status_container = st.status("正在进行数据采集...", expanded=True)
    progress_bar = st.progress(0)
    
    with status_container:
        if not crawler.check_auth()[0]:
            st.error("权限验证失败，请重新扫码！")
            st.stop()
            
        total_targets = len(target_list)
        for i, target_name in enumerate(target_list):
            st.write(f"🔄 [{i+1}/{total_targets}] 分析: **{target_name}** ...")
            
            accounts = crawler.search_account(target_name)
            if not accounts:
                st.warning(f"⚠️ 未找到: {target_name}，跳过")
                continue
            
            target_account = accounts[0]
            fakeid = target_account['fakeid']
            real_nickname = target_account['nickname']
            
            articles = crawler.fetch_article_list(fakeid, pages=page_count)
            
            if articles:
                st.write(f"   - 抓取正文 ({len(articles)}篇)...")
                for art in articles:
                    html_content, author, plain_text = crawler.fetch_content(art['link'])
                    art['content_html'] = html_content
                    art['plain_text'] = plain_text
                    art['author'] = author
                    art['account_name'] = real_nickname
                    time.sleep(0.5)

            all_results.extend(articles)
            progress_bar.progress((i + 1) / total_targets)
            time.sleep(random.uniform(1.0, 2.0))
            
        status_container.update(label="✅ 采集与分析完成！", state="complete")
    
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
    st.title("📊 公众号新媒体大数据看板")
    
    # 4个 Tab，最后一个是 AI 分析
    tab_global_1, tab_global_2, tab_global_3, tab_ai = st.tabs(["☁️ 综合词云", "🏆 影响力排行", "📈 发文趋势", "🤖 AI 深度报告"])
    
    # 获取所有公众号名称并生成屏蔽词
    all_accounts = df['account_name'].unique()
    global_stop_words = get_name_tokens(all_accounts)
    
    with tab_global_1:
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            st.subheader("全网·标题词云")
            all_titles = " ".join(df['title'].tolist())
            wc_title, _ = generate_wordcloud_img(all_titles, exclude_words=global_stop_words)
            if wc_title:
                st.image(wc_title.to_array(), use_container_width=True)
            else:
                st.info("数据不足")
                
        with col_g2:
            st.subheader("全网·内容词云")
            all_contents = " ".join(df['plain_text'].fillna("").tolist())
            wc_content, words_list = generate_wordcloud_img(all_contents, exclude_words=global_stop_words)
            if wc_content:
                st.image(wc_content.to_array(), use_container_width=True)
            
            if words_list:
                st.markdown("**🔥 全网 TOP 10 热词:**")
                counts = collections.Counter(words_list)
                top10 = counts.most_common(10)
                top10_df = pd.DataFrame(top10, columns=['关键词', '频次'])
                st.dataframe(top10_df.T, use_container_width=True)

    with tab_global_2:
        st.caption("注：数据基于本次抓取的样本计算。")
        col_r1, col_r2 = st.columns(2)
        now = pd.Timestamp.now()
        
        with col_r1:
            st.markdown("#### 📅 本周发文榜")
            week_df = df[df['发布时间'] > (now - pd.Timedelta(days=7))]
            if not week_df.empty:
                week_rank = week_df['account_name'].value_counts().reset_index()
                week_rank.columns = ['公众号', '发文数']
                st.dataframe(week_rank, use_container_width=True, hide_index=True)
            else:
                st.info("本周无数据")
                
        with col_r2:
            st.markdown("#### 🗓️ 本月发文榜")
            month_df = df[df['发布时间'] > (now - pd.Timedelta(days=30))]
            if not month_df.empty:
                month_rank = month_df['account_name'].value_counts().reset_index()
                month_rank.columns = ['公众号', '发文数']
                st.dataframe(month_rank, use_container_width=True, hide_index=True)
            else:
                st.info("本月无数据")

    with tab_global_3:
        st.subheader("全网发布时间分布")
        date_counts = df.groupby('发布日期').size()
        st.line_chart(date_counts)

    # --- AI 分析 Tab ---
    with tab_ai:
        st.subheader("🤖 Kimi-K2-Thinking 深度舆情报告")
        st.info("将使用 SiliconFlow API 对采集到的所有数据进行深度推理分析。")
        
        if st.button("🧠 开始 AI 深度思考与分析", type="primary"):
            with st.spinner("AI 正在阅读数据并进行推理 (这可能需要 30-60 秒)..."):
                success, report, reasoning = call_ai_analysis(df)
            
            if success:
                # 1. 展示思考过程
                if reasoning:
                    with st.expander("💭 点击查看 AI 的思考过程 (Reasoning)", expanded=True):
                        st.markdown(reasoning)
                    st.divider()
                
                # 2. 展示最终报告
                st.markdown(report)
                st.success("分析完成！")
            else:
                st.error(report)

    st.markdown("---")

    # 2. 个体画像
    st.header("2. 单号深度画像 (Single Account)")
    
    account_list = df['account_name'].unique()
    selected_account = st.selectbox("👉 选择一个公众号查看详情:", account_list)
    
    if selected_account:
        sub_df = df[df['account_name'] == selected_account].copy()
        
        # 针对单个账号生成特定的屏蔽词
        account_stop_words = get_name_tokens([selected_account])
        
        c1, c2, c3 = st.columns(3)
        c1.metric("总发文数", len(sub_df))
        c2.metric("原创比例", f"{len(sub_df[sub_df['类型']=='原创']) / len(sub_df) * 100:.1f}%" if len(sub_df)>0 else "0%")
        c3.metric("最新发布", str(sub_df['发布日期'].max()))
        
        tab_s1, tab_s2 = st.tabs(["📊 数据分析", "📰 文章列表与阅读"])
        
        with tab_s1:
            sc1, sc2 = st.columns(2)
            with sc1:
                st.markdown("**标题词云**")
                s_titles = " ".join(sub_df['title'].tolist())
                s_wc_t, _ = generate_wordcloud_img(s_titles, exclude_words=account_stop_words)
                if s_wc_t: st.image(s_wc_t.to_array(), use_container_width=True)
                
            with sc2:
                st.markdown("**内容词云**")
                s_content = " ".join(sub_df['plain_text'].fillna("").tolist())
                s_wc_c, s_words = generate_wordcloud_img(s_content, exclude_words=account_stop_words)
                if s_wc_c: 
                    st.image(s_wc_c.to_array(), use_container_width=True)
                    if s_words:
                        st.markdown("**🔥 TOP 10 热词:**")
                        s_counts = collections.Counter(s_words)
                        st.json(dict(s_counts.most_common(10)))

        with tab_s2:
            col_list, col_read = st.columns([1, 2])
            
            with col_list:
                st.markdown("##### 文章列表")
                sub_df['label'] = sub_df.apply(lambda x: f"{x['发布日期']} | {x['title']}", axis=1)
                
                selected_article_label = st.radio(
                    "点击选择文章阅读:",
                    sub_df['label'].tolist(),
                    label_visibility="collapsed"
                )
            
            with col_read:
                if selected_article_label:
                    read_art = sub_df[sub_df['label'] == selected_article_label].iloc[0]
                    
                    st.markdown(f"#### {read_art['title']}")
                    st.caption(f"✍️ {read_art['author']}  |  🕒 {read_art['发布时间']}")
                    st.divider()
                    
                    if 'content_html' in read_art and read_art['content_html']:
                        st.components.v1.html(read_art['content_html'], height=800, scrolling=True)
                    else:
                        st.warning("正文内容为空")

else:
    st.info("👈 请在左侧侧边栏操作：扫码 -> 输入公众号 -> 开始分析")
